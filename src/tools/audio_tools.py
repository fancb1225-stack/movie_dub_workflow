from __future__ import annotations

import shutil
import subprocess
import wave
from array import array
from pathlib import Path
from typing import Any

from src.state import SrtCue, TtsSegment
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
    canvas_ms = _calculate_canvas_ms(cues, segments)
    canvas = array("h", [0]) * int(sample_rate * canvas_ms / 1000)
    warnings: list[str] = []
    for segment in segments:
        if not segment.get("success"):
            warnings.append(f"Skip failed TTS segment {segment.get('index')}")
            continue
        try:
            audio, segment_rate = _read_pcm_mono_16(segment["path"])
            if segment_rate != sample_rate:
                audio = _resample_nearest(audio, segment_rate, sample_rate)
            _mix_into_canvas(canvas, audio, int(segment.get("start_ms", 0)), sample_rate)
        except Exception as exc:
            warnings.append(f"Skip unreadable TTS segment {segment.get('index')}: {exc}")
    _write_wav(wav_path, canvas, sample_rate)
    mp3_created_with = _export_mp3_or_copy(wav_path, mp3_path)
    return {
        "narration_wav": str(wav_path),
        "narration_mp3": str(mp3_path),
        "sample_rate": sample_rate,
        "duration_ms": canvas_ms,
        "segment_count": len(segments),
        "mp3_created_with": mp3_created_with,
        "warnings": warnings,
    }


def _calculate_canvas_ms(cues: list[SrtCue], segments: list[TtsSegment]) -> int:
    max_cue_end = max((cue["end_ms"] for cue in cues), default=0)
    max_segment_end = max(
        (
            int(segment.get("start_ms", 0)) + int(segment.get("duration_ms", 0))
            for segment in segments
            if segment.get("success")
        ),
        default=0,
    )
    return max(max_cue_end, max_segment_end, 1000) + 500


def _read_pcm_mono_16(path: str | Path) -> tuple[array, int]:
    audio_path = Path(path)
    try:
        with wave.open(str(audio_path), "rb") as reader:
            channels = reader.getnchannels()
            sample_width = reader.getsampwidth()
            frame_rate = reader.getframerate()
            raw = reader.readframes(reader.getnframes())
    except (wave.Error, EOFError) as exc:
        return _read_with_pydub(audio_path, exc)
    if sample_width != 2:
        raise RuntimeError(f"Unsupported sample width {sample_width}: {audio_path}")
    samples = array("h")
    samples.frombytes(raw)
    if channels == 1:
        return samples, frame_rate
    return _downmix(samples, channels), frame_rate


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


def _export_mp3_or_copy(wav_path: Path, mp3_path: Path) -> str:
    if shutil.which("ffmpeg") is not None:
        try:
            subprocess.run(
                [
                    "ffmpeg",
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
            pass
    copy_file(wav_path, mp3_path)
    return "wav_copy_fallback"

