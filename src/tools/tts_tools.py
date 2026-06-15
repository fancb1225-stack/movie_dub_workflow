from __future__ import annotations

import asyncio
import math
import wave
from pathlib import Path
from typing import Any

from src.state import SrtCue, TtsSegment
from src.tools.duration_tools import get_audio_duration_ms
from src.tools.file_tools import clean_dir, ensure_dir


def generate_tts_segments(
    cues: list[SrtCue],
    output_dir: str | Path,
    config: dict[str, Any],
) -> list[TtsSegment]:
    directory = ensure_dir(output_dir)
    clean_dir(directory, "segment_*.mp3")
    tts_config = config.get("tts", {})
    provider = str(tts_config.get("provider", "mock")).lower()
    segments: list[TtsSegment] = []
    for cue in cues:
        segment_path = directory / f"segment_{cue['index']:04d}.mp3"
        try:
            if provider == "edge_tts":
                _generate_edge_tts(cue["text"], segment_path, tts_config)
            else:
                _generate_mock_audio(cue["text"], segment_path, tts_config)
            duration_ms = get_audio_duration_ms(segment_path, config)
            segments.append(
                {
                    "index": cue["index"],
                    "text": cue["text"],
                    "start_ms": cue["start_ms"],
                    "end_ms": cue["end_ms"],
                    "path": str(segment_path),
                    "duration_ms": duration_ms,
                    "success": True,
                }
            )
        except Exception as exc:
            segments.append(
                {
                    "index": cue["index"],
                    "text": cue["text"],
                    "start_ms": cue["start_ms"],
                    "end_ms": cue["end_ms"],
                    "path": str(segment_path),
                    "duration_ms": 0,
                    "success": False,
                    "error": str(exc),
                }
            )
    return segments


def _generate_edge_tts(
    text: str, output_path: Path, tts_config: dict[str, Any]
) -> None:
    try:
        import edge_tts  # type: ignore
    except ImportError as exc:
        raise RuntimeError("TTS provider edge_tts requires the edge-tts package.") from exc

    async def _save() -> None:
        communicate = edge_tts.Communicate(
            text=text,
            voice=str(tts_config.get("voice", "en-US-AriaNeural")),
        )
        await communicate.save(str(output_path))

    asyncio.run(_save())


def _generate_mock_audio(
    text: str, output_path: Path, tts_config: dict[str, Any]
) -> None:
    sample_rate = int(tts_config.get("sample_rate", 24000))
    duration_ms = _estimate_speech_duration_ms(
        text, int(tts_config.get("words_per_minute", 155))
    )
    frame_count = int(sample_rate * duration_ms / 1000)
    amplitude = 1800
    frequency = 220.0
    with wave.open(str(output_path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        for frame in range(frame_count):
            sample = int(amplitude * math.sin(2 * math.pi * frequency * frame / sample_rate))
            writer.writeframesraw(sample.to_bytes(2, byteorder="little", signed=True))


def _estimate_speech_duration_ms(text: str, words_per_minute: int) -> int:
    words = max(1, len(text.split()))
    if words == 1:
        words = max(1, math.ceil(len(text) / 7))
    duration = int(words / max(words_per_minute, 80) * 60_000)
    return max(700, min(duration, 20_000))

