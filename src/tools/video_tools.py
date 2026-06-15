from __future__ import annotations

from pathlib import Path
from typing import Any

from src.tools.ffmpeg_tools import run_ffmpeg
from src.tools.file_tools import ensure_parent


def package_video_with_audio(
    input_mp4: str | Path,
    audio_path: str | Path,
    output_mp4: str | Path,
    config: dict[str, Any],
) -> str:
    output_path = ensure_parent(output_mp4)
    copy_video = bool(config.get("video", {}).get("copy_video", True))
    video_codec_args = ["-c:v", "copy"] if copy_video else ["-c:v", "libx264"]
    run_ffmpeg(
        config,
        [
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            Path(input_mp4),
            "-i",
            Path(audio_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            *video_codec_args,
            "-c:a",
            "aac",
            "-shortest",
            output_path,
        ],
    )
    return str(output_path)

