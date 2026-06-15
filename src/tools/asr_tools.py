from __future__ import annotations

from pathlib import Path
from typing import Any

from src.state import SrtCue
from src.tools.duration_tools import get_audio_duration_ms
from src.tools.file_tools import write_json, write_text
from src.tools.srt_tools import format_srt, make_cue


def transcribe_mp3_to_srt(
    input_mp3: str | Path,
    output_srt: str | Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    input_path = Path(input_mp3)
    asr_config = config.get("asr", {})
    provider = str(asr_config.get("provider", "mock")).lower()
    if provider == "faster_whisper":
        cues = _transcribe_with_faster_whisper(input_path, asr_config)
    else:
        cues = _mock_transcribe(input_path, asr_config)
    srt_text = format_srt(cues)
    write_text(output_srt, srt_text)
    return {
        "provider": provider,
        "input_mp3": str(input_path),
        "output_srt": str(output_srt),
        "subtitle_count": len(cues),
        "cues": cues,
        "srt": srt_text,
    }


def write_asr_report(path: str | Path, asr_result: dict[str, Any]) -> str:
    report = {
        "provider": asr_result.get("provider"),
        "input_mp3": asr_result.get("input_mp3"),
        "output_srt": asr_result.get("output_srt"),
        "subtitle_count": asr_result.get("subtitle_count", 0),
    }
    return write_json(path, report)


def _transcribe_with_faster_whisper(
    input_path: Path, asr_config: dict[str, Any]
) -> list[SrtCue]:
    if not input_path.exists():
        raise FileNotFoundError(f"ASR input does not exist: {input_path}")
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "ASR provider faster_whisper requires the faster-whisper package."
        ) from exc
    model = WhisperModel(
        str(asr_config.get("model_name", "small")),
        device=str(asr_config.get("device", "auto")),
        compute_type=str(asr_config.get("compute_type", "default")),
    )
    segments, _info = model.transcribe(
        str(input_path),
        language=str(asr_config.get("language", "zh")),
        vad_filter=bool(asr_config.get("vad_filter", True)),
    )
    cues: list[SrtCue] = []
    for idx, segment in enumerate(segments, start=1):
        cues.append(
            make_cue(
                idx,
                int(round(segment.start * 1000)),
                int(round(segment.end * 1000)),
                segment.text.strip(),
            )
        )
    return cues


def _mock_transcribe(input_path: Path, asr_config: dict[str, Any]) -> list[SrtCue]:
    if not input_path.exists() and not asr_config.get("mock_when_missing_input", True):
        raise FileNotFoundError(f"ASR input does not exist: {input_path}")
    duration_ms = _safe_input_duration(input_path)
    if duration_ms < 9000:
        duration_ms = 15000
    cue_count = 4
    slot = max(2500, duration_ms // cue_count)
    texts = [
        "这里是电影解说的开场，主角进入故事的关键场景。",
        "冲突逐渐出现，人物关系和目标开始变得清晰。",
        "主角做出重要选择，剧情进入紧张的转折。",
        "故事收束，关键悬念得到回应。",
    ]
    cues: list[SrtCue] = []
    for idx, text in enumerate(texts, start=1):
        start_ms = (idx - 1) * slot
        end_ms = min(start_ms + slot - 300, duration_ms)
        cues.append(make_cue(idx, start_ms, max(end_ms, start_ms + 1800), text))
    return cues


def _safe_input_duration(input_path: Path) -> int:
    if not input_path.exists():
        return 15000
    try:
        return get_audio_duration_ms(input_path)
    except Exception:
        return 15000

