from __future__ import annotations

import subprocess
import wave
from pathlib import Path
from typing import Any

from src.config import find_binary
from src.state import DurationIssue, SrtCue, TtsSegment


def get_audio_duration_ms(
    path: str | Path, config: dict[str, Any] | None = None
) -> int:
    audio_path = Path(path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file does not exist: {audio_path}")
    wave_duration = _duration_with_wave(audio_path)
    if wave_duration is not None:
        return wave_duration
    ffprobe_duration = _duration_with_ffprobe(audio_path, config)
    if ffprobe_duration is not None:
        return ffprobe_duration
    pydub_duration = _duration_with_pydub(audio_path)
    if pydub_duration is not None:
        return pydub_duration
    raise RuntimeError(f"Unable to detect audio duration: {audio_path}")


def detect_duration_issues(
    cues: list[SrtCue],
    segments: list[TtsSegment],
    max_overrun_ms: int,
    max_ratio: float,
) -> list[DurationIssue]:
    cue_by_index = {cue["index"]: cue for cue in cues}
    issues: list[DurationIssue] = []
    for segment in segments:
        if not segment.get("success"):
            continue
        cue = cue_by_index.get(segment["index"])
        if cue is None:
            continue
        subtitle_duration = cue["end_ms"] - cue["start_ms"]
        tts_duration = int(segment.get("duration_ms", 0))
        overrun = tts_duration - subtitle_duration
        ratio = tts_duration / subtitle_duration if subtitle_duration > 0 else 999.0
        if overrun > max_overrun_ms or ratio > max_ratio:
            issues.append(
                {
                    "index": cue["index"],
                    "start_ms": cue["start_ms"],
                    "end_ms": cue["end_ms"],
                    "subtitle_duration_ms": subtitle_duration,
                    "tts_duration_ms": tts_duration,
                    "overrun_ms": overrun,
                    "ratio": round(ratio, 3),
                    "text": cue["text"],
                }
            )
    return issues


def build_tts_duration_report(
    segments: list[TtsSegment], issues: list[DurationIssue]
) -> dict[str, object]:
    success_count = sum(1 for segment in segments if segment.get("success"))
    failed_count = len(segments) - success_count
    return {
        "total_segments": len(segments),
        "success_segments": success_count,
        "failed_segments": failed_count,
        "duration_issue_count": len(issues),
        "issues": issues,
    }


def _duration_with_wave(path: Path) -> int | None:
    try:
        with wave.open(str(path), "rb") as reader:
            frames = reader.getnframes()
            frame_rate = reader.getframerate()
            if frame_rate <= 0:
                return None
            return int(round(frames / frame_rate * 1000))
    except (wave.Error, EOFError):
        return None


def _duration_with_ffprobe(path: Path, config: dict[str, Any] | None = None) -> int | None:
    try:
        binary = find_binary(config or {}, "ffmpeg.ffprobe_path", "ffprobe")
    except FileNotFoundError:
        return None
    try:
        result = subprocess.run(
            [
                str(binary),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            check=True,
            text=True,
        )
        return int(round(float(result.stdout.strip()) * 1000))
    except (subprocess.CalledProcessError, ValueError):
        return None


def _duration_with_pydub(path: Path) -> int | None:
    try:
        from pydub import AudioSegment  # type: ignore

        return len(AudioSegment.from_file(path))
    except Exception:
        return None

