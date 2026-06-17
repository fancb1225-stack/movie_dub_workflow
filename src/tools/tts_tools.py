from __future__ import annotations

import asyncio
import logging
import math
import traceback
import wave
from pathlib import Path
from typing import Any

from src.state import SrtCue, TtsSegment
from src.tools.duration_tools import get_audio_duration_ms
from src.tools.file_tools import clean_dir, ensure_dir

logger = logging.getLogger(__name__)


def generate_tts_segments(
    cues: list[SrtCue],
    output_dir: str | Path,
    config: dict[str, Any],
) -> list[TtsSegment]:
    directory = ensure_dir(output_dir)
    clean_dir(directory, "segment_*.mp3")
    tts_config = config.get("tts", {})
    provider = str(tts_config.get("provider", "mock")).lower()
    logger.info("TTS generate: provider=%s, cues=%d, output_dir=%s", provider, len(cues), directory)
    logger.debug("TTS config: %s", tts_config)
    segments: list[TtsSegment] = []
    for cue in cues:
        segment_path = directory / f"segment_{cue['index']:04d}.mp3"
        try:
            if provider == "edge_tts":
                _generate_edge_tts(cue["text"], segment_path, tts_config)
            else:
                _generate_mock_audio(cue["text"], segment_path, tts_config)
            if not segment_path.exists():
                raise FileNotFoundError(f"TTS output file was not created: {segment_path}")
            file_size = segment_path.stat().st_size
            if file_size == 0:
                raise RuntimeError(f"TTS output file is empty (0 bytes): {segment_path}")
            duration_ms = get_audio_duration_ms(segment_path, config)
            logger.debug("TTS segment %d OK: size=%d, duration_ms=%d", cue["index"], file_size, duration_ms)
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
            logger.error(
                "TTS segment %d FAILED: %s\n%s",
                cue["index"],
                exc,
                traceback.format_exc(),
            )
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
    success_count = sum(1 for s in segments if s["success"])
    logger.info("TTS generate done: %d/%d segments succeeded", success_count, len(segments))
    return segments


def _generate_edge_tts(
    text: str, output_path: Path, tts_config: dict[str, Any]
) -> None:
    try:
        import edge_tts  # type: ignore
    except ImportError as exc:
        raise RuntimeError("TTS provider edge_tts requires the edge-tts package.") from exc

    voice = str(tts_config.get("voice", "en-US-AriaNeural"))
    rate = str(tts_config.get("rate", "+30%"))
    logger.debug("edge_tts: voice=%s, rate=%s, text=%r, output=%s", voice, rate, text[:80], output_path)

    async def _save() -> None:
        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=rate,
        )
        await communicate.save(str(output_path))

    try:
        _run_async(_save())
    except Exception as exc:
        logger.error("edge_tts _run_async failed for %s: %s", output_path, exc)
        raise


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


def _run_async(coro: Any) -> Any:
    """Run an async coroutine, compatible with both standalone and event-loop contexts.

    When called inside an already-running event loop (e.g. from uvicorn/FastAPI),
    ``asyncio.run()`` raises ``RuntimeError``.  In that case we create a new
    thread with its own loop and schedule the coroutine there.
    """
    import threading

    try:
        logger.debug("_run_async: trying asyncio.run() directly")
        return asyncio.run(coro)
    except RuntimeError as exc:
        if "cannot be called from a running event loop" not in str(exc):
            raise
        logger.info("_run_async: detected running event loop, spawning thread")

    result: Any = None
    error: BaseException | None = None

    def _target() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(coro)
        except BaseException as exc:
            error = exc

    thread = threading.Thread(target=_target)
    thread.start()
    logger.debug("_run_async: thread started, waiting for completion")
    thread.join()
    if error is not None:
        logger.error("_run_async: thread failed: %s", error)
        raise error
    logger.debug("_run_async: thread completed successfully, result=%s", type(result).__name__)
    return result

