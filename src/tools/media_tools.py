from __future__ import annotations

from pathlib import Path
from typing import Any

from src.tools.ffmpeg_tools import run_ffmpeg
from src.tools.file_tools import ensure_parent


def extract_audio(
    input_video: str | Path,
    output_wav: str | Path,
    sample_rate: int,
    config: dict[str, Any],
) -> str:
    output_path = ensure_parent(output_wav)
    run_ffmpeg(
        config,
        [
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            Path(input_video),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            output_path,
        ],
    )
    return str(output_path)


def has_audio_stream(probe: dict[str, Any]) -> bool:
    return any(stream.get("codec_type") == "audio" for stream in probe.get("streams", []))


def has_video_stream(probe: dict[str, Any]) -> bool:
    return any(stream.get("codec_type") == "video" for stream in probe.get("streams", []))


def media_duration_ms(probe: dict[str, Any]) -> int:
    duration = probe.get("format", {}).get("duration")
    if duration is None:
        duration = _first_stream_duration(probe)
    if duration is None:
        return 0
    return int(round(float(duration) * 1000))


def _first_stream_duration(probe: dict[str, Any]) -> str | None:
    for stream in probe.get("streams", []):
        duration = stream.get("duration")
        if duration is not None:
            return str(duration)
    return None

