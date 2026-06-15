from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from src.config import find_binary


class FFmpegError(RuntimeError):
    def __init__(self, command: list[str], returncode: int, stderr: str):
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        command_text = " ".join(command)
        super().__init__(
            f"FFmpeg command failed with exit code {returncode}: {command_text}\n{stderr}"
        )


def run_ffmpeg(config: dict[str, Any], args: list[str | Path]) -> subprocess.CompletedProcess[str]:
    binary = find_binary(config, "ffmpeg.ffmpeg_path", "ffmpeg")
    return _run_binary(binary, args)


def run_ffprobe(config: dict[str, Any], args: list[str | Path]) -> subprocess.CompletedProcess[str]:
    binary = find_binary(config, "ffmpeg.ffprobe_path", "ffprobe")
    return _run_binary(binary, args)


def probe_media(path: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    result = run_ffprobe(
        config,
        [
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            Path(path),
        ],
    )
    return json.loads(result.stdout or "{}")


def _run_binary(
    binary: Path, args: list[str | Path]
) -> subprocess.CompletedProcess[str]:
    command = [str(binary), *[str(arg) for arg in args]]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise FFmpegError(command, result.returncode, result.stderr)
    return result

