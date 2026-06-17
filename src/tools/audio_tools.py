from __future__ import annotations

import subprocess
import wave
from array import array
from pathlib import Path
from typing import Any

from src.config import find_binary
from src.state import AdjustedPosition, SrtCue, TtsSegment
from src.tools.file_tools import copy_file, ensure_parent


def align_and_merge_segments(
    cues: list[SrtCue],
    segments: list[TtsSegment],
    output_wav: str | Path,
    output_mp3: str | Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    wav_path = ensure_parent(output_wav)
    mp3_path = ensure_parent(output_mp3)
    sample_rate = int(config.get("tts", {}).get("sample_rate", 24000))
    alignment_config = config.get("alignment", {})
    enable_resolution = alignment_config.get("enable_overlap_resolution", True)
    adjusted_positions: list[AdjustedPosition] | None = None
    if enable_resolution:
        adjusted_positions = compute_adjusted_positions(
            segments,
            cues,
            max_shift_back_overlap_ms=int(alignment_config.get("max_shift_back_overlap_ms", 200)),
            shift_back_gap_ms=int(alignment_config.get("shift_back_gap_ms", 50)),
        )
    canvas_ms = _calculate_canvas_ms(cues, segments, adjusted_positions)
    canvas = array("h", [0]) * int(sample_rate * canvas_ms / 1000)
    start_by_index: dict[int, int] = {}
    if adjusted_positions:
        start_by_index = {pos["index"]: pos["adjusted_start_ms"] for pos in adjusted_positions}
    warnings: list[str] = []
    for segment in segments:
        if not segment.get("success"):
            warnings.append(f"Skip failed TTS segment {segment.get('index')}")
            continue
        seg_start_ms = start_by_index.get(segment["index"], int(segment.get("start_ms", 0)))
        try:
            audio, segment_rate = _read_pcm_mono_16(segment["path"], config, sample_rate)
            if segment_rate != sample_rate:
                audio = _resample_nearest(audio, segment_rate, sample_rate)
            _mix_into_canvas(canvas, audio, seg_start_ms, sample_rate)
        except Exception as exc:
            warnings.append(f"Skip unreadable TTS segment {segment.get('index')}: {exc}")
    _write_wav(wav_path, canvas, sample_rate)
    mp3_created_with = _export_mp3_or_copy(wav_path, mp3_path, config)
    report: dict[str, Any] = {
        "narration_wav": str(wav_path),
        "narration_mp3": str(mp3_path),
        "sample_rate": sample_rate,
        "duration_ms": canvas_ms,
        "segment_count": len(segments),
        "mp3_created_with": mp3_created_with,
        "warnings": warnings,
    }
    if adjusted_positions is not None:
        report["adjusted_positions"] = adjusted_positions
        report["alignment_summary"] = _build_alignment_summary(adjusted_positions)
    return report


def align_and_merge_segments_simple(
    cues: list[SrtCue],
    segments: list[TtsSegment],
    output_wav: str | Path,
    output_mp3: str | Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    """确定性普通对齐:无 LLM、无反思循环。

    规则:
    - 片段比 SRT 时间轴短 → 对齐到 cue 起点,尾部天然静音(画布预填 0)。
    - 片段与上一个片段重叠 → 向前移动到不重叠位置,移动不超过
      ``max_shift_forward_ms``(默认 1s);公式为
      ``start_ms = max(0, min(cue_start - max_shift, prev_end))``。
    - 前移后仍溢出 → 不截断,画布自动延长。
    """
    wav_path = ensure_parent(output_wav)
    mp3_path = ensure_parent(output_mp3)
    sample_rate = int(config.get("tts", {}).get("sample_rate", 24000))
    alignment_config = config.get("alignment", {})
    max_shift = int(alignment_config.get("max_shift_forward_ms", 1000))

    max_cue_end = max((cue["end_ms"] for cue in cues), default=0)
    canvas_ms = max(max_cue_end, 1000) + 500
    canvas = array("h", [0]) * int(sample_rate * canvas_ms / 1000)

    warnings: list[str] = []
    placements: list[dict[str, Any]] = []
    prev_end_ms = 0

    for segment in segments:
        if not segment.get("success"):
            warnings.append(f"Skip failed TTS segment {segment.get('index')}")
            continue
        cue_start = int(segment.get("start_ms", 0))
        duration = int(segment.get("duration_ms", 0))
        try:
            audio, segment_rate = _read_pcm_mono_16(segment["path"], config, sample_rate)
            if segment_rate != sample_rate:
                audio = _resample_nearest(audio, segment_rate, sample_rate)
        except Exception as exc:
            warnings.append(f"Skip unreadable TTS segment {segment.get('index')}: {exc}")
            continue

        if cue_start < prev_end_ms:
            # 与上一个片段重叠 → 向前移动:min(cue_start - max_shift, prev_end)
            start_ms = max(0, min(cue_start - max_shift, prev_end_ms))
        else:
            start_ms = cue_start

        _mix_into_canvas(canvas, audio, start_ms, sample_rate)
        prev_end_ms = start_ms + duration
        placements.append(
            {
                "index": segment.get("index"),
                "start_ms": start_ms,
                "original_start_ms": cue_start,
                "duration_ms": duration,
                "shifted": start_ms != cue_start,
            }
        )

    _write_wav(wav_path, canvas, sample_rate)
    mp3_created_with = _export_mp3_or_copy(wav_path, mp3_path, config)
    duration_ms = int(len(canvas) / sample_rate * 1000)
    return {
        "alignment_mode": "simple",
        "narration_wav": str(wav_path),
        "narration_mp3": str(mp3_path),
        "sample_rate": sample_rate,
        "duration_ms": duration_ms,
        "segment_count": len(segments),
        "mp3_created_with": mp3_created_with,
        "warnings": warnings,
        "placements": placements,
    }


def _build_alignment_summary(positions: list[AdjustedPosition]) -> dict[str, Any]:
    by_strategy: dict[str, int] = {}
    max_forward = 0
    max_backward = 0
    for pos in positions:
        strategy = pos["strategy"]
        by_strategy[strategy] = by_strategy.get(strategy, 0) + 1
        shift = pos["shift_ms"]
        if shift > max_forward:
            max_forward = shift
        if shift < max_backward:
            max_backward = shift
    return {
        "total_overlaps_detected": sum(1 for p in positions if p["overlap_with_previous_ms"] > 0),
        "resolved_by_delay": by_strategy.get("delay", 0),
        "resolved_by_shift_back": by_strategy.get("shift_back", 0),
        "fallback_overlap": by_strategy.get("fallback", 0),
        "no_overlap": by_strategy.get("none", 0),
        "max_forward_shift_ms": max_forward,
        "max_backward_shift_ms": max_backward,
    }


def _calculate_canvas_ms(
    cues: list[SrtCue],
    segments: list[TtsSegment],
    adjusted_positions: list[AdjustedPosition] | None = None,
) -> int:
    max_cue_end = max((cue["end_ms"] for cue in cues), default=0)
    if adjusted_positions:
        seg_by_index = {s["index"]: s for s in segments if s.get("success")}
        max_segment_end = max(
            (
                pos["adjusted_start_ms"] + int(seg_by_index.get(pos["index"], {}).get("duration_ms", 0))
                for pos in adjusted_positions
            ),
            default=0,
        )
    else:
        max_segment_end = max(
            (
                int(segment.get("start_ms", 0)) + int(segment.get("duration_ms", 0))
                for segment in segments
                if segment.get("success")
            ),
            default=0,
        )
    return max(max_cue_end, max_segment_end, 1000) + 500


def compute_adjusted_positions(
    segments: list[TtsSegment],
    cues: list[SrtCue],
    max_shift_back_overlap_ms: int = 200,
    shift_back_gap_ms: int = 50,
) -> list[AdjustedPosition]:
    """Compute adjusted start positions for TTS segments to resolve overlaps.

    Strategy priority per segment:
    1. **delay** (顺延): shift current segment forward to start right after
       the previous segment ends, if that would not overlap the next cue.
    2. **shift_back** (前移): if overlap ≤ *max_shift_back_overlap_ms* and the
       previous segment can move backward by (overlap + shift_back_gap_ms)
       without colliding with its predecessor, shift the previous segment back.
    3. **fallback**: neither works — keep original position (additive mixing).
    4. **none**: no overlap detected, keep original position.
    """
    successful = [s for s in segments if s.get("success") and int(s.get("duration_ms", 0)) > 0]
    if not successful:
        return []

    cues_by_index = {cue["index"]: cue for cue in cues}
    # Sorted list of cue start_ms for next-cue lookup
    sorted_cue_starts = sorted(cue["start_ms"] for cue in cues)

    positions: list[AdjustedPosition] = []

    for i, seg in enumerate(successful):
        original_start = int(seg.get("start_ms", 0))
        duration = int(seg.get("duration_ms", 0))
        overlap_with_prev = 0

        if i == 0:
            # First segment: no previous to overlap with
            adjusted_start = max(0, original_start)
            positions.append(
                _make_position(seg["index"], original_start, adjusted_start, "none", 0)
            )
            continue

        prev_pos = positions[i - 1]
        prev_seg = successful[i - 1]
        prev_effective_end = prev_pos["adjusted_start_ms"] + int(prev_seg.get("duration_ms", 0))
        overlap_with_prev = max(0, prev_effective_end - original_start)

        if overlap_with_prev <= 0:
            # No overlap
            positions.append(
                _make_position(seg["index"], original_start, original_start, "none", 0)
            )
            continue

        # --- Strategy 1: 顺延 (delay) ---
        delayed_start = prev_effective_end
        delayed_end = delayed_start + duration
        next_cue_start = _next_cue_start(cues_by_index, sorted_cue_starts, seg["index"])
        can_delay = next_cue_start is None or delayed_end <= next_cue_start

        if can_delay:
            positions.append(
                _make_position(seg["index"], original_start, delayed_start, "delay", overlap_with_prev)
            )
            continue

        # --- Strategy 2: 前移 (shift_back) ---
        if overlap_with_prev <= max_shift_back_overlap_ms:
            shift_back_amount = overlap_with_prev + shift_back_gap_ms
            new_prev_start = prev_pos["adjusted_start_ms"] - shift_back_amount

            # Check if previous segment can move backward
            if i - 1 == 0:
                # Previous is the first segment: must stay >= 0
                can_shift_back = new_prev_start >= 0
            else:
                prev_prev_pos = positions[i - 2]
                prev_prev_seg = successful[i - 2]
                prev_prev_end = prev_prev_pos["adjusted_start_ms"] + int(prev_prev_seg.get("duration_ms", 0))
                can_shift_back = new_prev_start >= prev_prev_end

            if can_shift_back:
                # Retroactively update previous position
                positions[i - 1] = _make_position(
                    prev_seg["index"],
                    prev_pos["original_start_ms"],
                    new_prev_start,
                    "shift_back",
                    prev_pos["overlap_with_previous_ms"],
                )
                # Current segment stays at natural position
                positions.append(
                    _make_position(seg["index"], original_start, original_start, "none", overlap_with_prev)
                )
                continue

        # --- Strategy 3: fallback ---
        positions.append(
            _make_position(seg["index"], original_start, original_start, "fallback", overlap_with_prev)
        )

    return positions


def _make_position(
    index: int, original_start: int, adjusted_start: int, strategy: str, overlap: int
) -> AdjustedPosition:
    return AdjustedPosition(
        index=index,
        original_start_ms=original_start,
        adjusted_start_ms=adjusted_start,
        shift_ms=adjusted_start - original_start,
        strategy=strategy,
        overlap_with_previous_ms=overlap,
    )


def _next_cue_start(
    cues_by_index: dict[int, SrtCue],
    sorted_cue_starts: list[int],
    current_index: int,
) -> int | None:
    """Return the start_ms of the cue immediately after *current_index*, or None."""
    current_cue = cues_by_index.get(current_index)
    if current_cue is None:
        return None
    # Find the smallest cue start_ms that is strictly greater than current cue start
    current_start = current_cue["start_ms"]
    for s in sorted_cue_starts:
        if s > current_start:
            return s
    return None


def _read_pcm_mono_16(
    path: str | Path,
    config: dict[str, Any],
    target_rate: int,
) -> tuple[array, int]:
    audio_path = Path(path)
    try:
        with wave.open(str(audio_path), "rb") as reader:
            channels = reader.getnchannels()
            sample_width = reader.getsampwidth()
            frame_rate = reader.getframerate()
            raw = reader.readframes(reader.getnframes())
    except (wave.Error, EOFError) as exc:
        try:
            return _read_with_ffmpeg(audio_path, config, target_rate)
        except Exception:
            return _read_with_pydub(audio_path, exc)
    if sample_width != 2:
        raise RuntimeError(f"Unsupported sample width {sample_width}: {audio_path}")
    samples = array("h")
    samples.frombytes(raw)
    if channels == 1:
        return samples, frame_rate
    return _downmix(samples, channels), frame_rate


def _read_with_ffmpeg(
    path: Path,
    config: dict[str, Any],
    target_rate: int,
) -> tuple[array, int]:
    ffmpeg = find_binary(config, "ffmpeg.ffmpeg_path", "ffmpeg")
    result = subprocess.run(
        [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            str(target_rate),
            "-",
        ],
        check=True,
        capture_output=True,
    )
    samples = array("h")
    samples.frombytes(result.stdout)
    return samples, target_rate


def _read_with_pydub(path: Path, original_error: Exception) -> tuple[array, int]:
    try:
        from pydub import AudioSegment  # type: ignore

        audio = AudioSegment.from_file(path).set_channels(1).set_sample_width(2)
        samples = array("h")
        samples.frombytes(audio.raw_data)
        return samples, int(audio.frame_rate)
    except Exception as exc:
        raise RuntimeError(f"Unable to read audio {path}: {original_error}") from exc


def _downmix(samples: array, channels: int) -> array:
    mixed = array("h")
    for pos in range(0, len(samples), channels):
        frame = samples[pos : pos + channels]
        mixed.append(int(sum(frame) / len(frame)))
    return mixed


def _resample_nearest(samples: array, source_rate: int, target_rate: int) -> array:
    if source_rate <= 0 or source_rate == target_rate:
        return samples
    ratio = target_rate / source_rate
    target_len = int(len(samples) * ratio)
    output = array("h")
    for idx in range(target_len):
        source_idx = min(len(samples) - 1, int(idx / ratio))
        output.append(samples[source_idx])
    return output


def _mix_into_canvas(
    canvas: array, audio: array, start_ms: int, sample_rate: int
) -> None:
    start_frame = int(sample_rate * start_ms / 1000)
    required = start_frame + len(audio)
    if required > len(canvas):
        canvas.extend([0] * (required - len(canvas)))
    for offset, sample in enumerate(audio):
        pos = start_frame + offset
        value = int(canvas[pos]) + int(sample)
        canvas[pos] = max(-32768, min(32767, value))


def _write_wav(path: Path, samples: array, sample_rate: int) -> None:
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(samples.tobytes())


def _export_mp3_or_copy(wav_path: Path, mp3_path: Path, config: dict[str, Any]) -> str:
    try:
        ffmpeg = find_binary(config, "ffmpeg.ffmpeg_path", "ffmpeg")
    except FileNotFoundError:
        copy_file(wav_path, mp3_path)
        return "wav_copy_fallback"
    try:
        subprocess.run(
            [
                str(ffmpeg),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(wav_path),
                str(mp3_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return "ffmpeg"
    except subprocess.CalledProcessError:
        copy_file(wav_path, mp3_path)
        return "wav_copy_fallback"

