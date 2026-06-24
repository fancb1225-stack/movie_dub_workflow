from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from src.state import SrtCue
from src.tools.asr_words import (
    extract_whisperx_words,
    split_words_to_short_cues,
    write_asr_words_json,
)
from src.tools.duration_tools import get_audio_duration_ms
from src.tools.file_tools import write_json
from src.tools.srt_tools import format_srt, make_cue


def transcribe_mp3_to_srt(
    input_mp3: str | Path,
    output_words_json: str | Path | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    """ASR 转写,主产物为词级时间戳 JSON。

    - whisperx 分支:输出 zh_raw.words.json,raw_cues 由 words 切短句派生,
      不再写 zh_raw.srt(SRT 字符串仍放进返回值,供调用方按需落盘)。
    - faster_whisper/mock 分支:无真实 words,words=[],不写 words.json。
    output_words_json 为 None 且无 words 时不写文件。
    """
    input_path = Path(input_mp3)
    asr_config = config.get("asr", {})
    provider = str(asr_config.get("provider", "mock")).lower()
    cues: list[SrtCue] = []
    words: list[dict[str, Any]] = []
    words_json_path: str | None = None
    diarized = False
    if provider == "faster_whisper":
        cues = _transcribe_with_faster_whisper(input_path, asr_config)
    elif provider == "whisperx":
        try:
            cues, words = _transcribe_with_whisperx(input_path, asr_config)
            diarized = any("speaker_id" in cue for cue in cues)
            if output_words_json is not None:
                words_json_path = write_asr_words_json(output_words_json, words)
        except RuntimeError:
            if asr_config.get("whisperx_missing_dep_fallback", False):
                cues = _transcribe_with_faster_whisper(input_path, asr_config)
            else:
                raise
    else:
        cues = _mock_transcribe(input_path, asr_config)
    speakers = sorted(
        {cue["speaker_id"] for cue in cues if cue.get("speaker_id")}
    )
    srt_text = format_srt(cues, include_speaker=bool(asr_config.get("srt_emit_speaker", False)))
    return {
        "provider": provider,
        "input_mp3": str(input_path),
        "words_json": words_json_path,
        "output_srt": None,
        "subtitle_count": len(cues),
        "cues": cues,
        "words": words,
        "word_count": len(words),
        "srt": srt_text,
        "speakers": speakers,
        "diarized": diarized,
    }


def write_asr_report(path: str | Path, asr_result: dict[str, Any]) -> str:
    report = {
        "provider": asr_result.get("provider"),
        "input_mp3": asr_result.get("input_mp3"),
        "words_json": asr_result.get("words_json"),
        "output_srt": asr_result.get("output_srt"),
        "subtitle_count": asr_result.get("subtitle_count", 0),
        "word_count": asr_result.get("word_count", 0),
        "speakers": asr_result.get("speakers", []),
        "diarized": asr_result.get("diarized", False),
    }
    return write_json(path, report)


def map_whisperx_result_to_cues(
    result: dict[str, Any], speaker_normalize: bool = True
) -> list[SrtCue]:
    """把 whisperx transcribe + assign_word_speakers 后的 result 映射为 SrtCue 列表。

    纯函数，不依赖 whisperx 运行时，便于单测。
    result["segments"] 每项含 start/end/text/speaker(可能缺失)。
    speaker_normalize 为 True 时把 "SPEAKER_00" 归一化为 "speaker_1"。
    """
    cues: list[SrtCue] = []
    for idx, segment in enumerate(result.get("segments", []), start=1):
        start_ms = int(round(float(segment.get("start", 0.0)) * 1000))
        end_ms = int(round(float(segment.get("end", 0.0)) * 1000))
        text = str(segment.get("text", "")).strip()
        cue = make_cue(idx, start_ms, end_ms, text)
        speaker = segment.get("speaker")
        if speaker:
            cue["speaker_id"] = _normalize_speaker(str(speaker)) if speaker_normalize else str(speaker)
        cues.append(cue)
    return cues


def _normalize_speaker(label: str) -> str:
    """SPEAKER_00 -> speaker_1, SPEAKER_01 -> speaker_2。无法解析时原样返回。"""
    try:
        num = int(label.rsplit("_", 1)[-1])
        return f"speaker_{num + 1}"
    except (ValueError, IndexError):
        return label


def _ensure_ffmpeg_on_path(config: dict[str, Any]) -> None:
    """whisperx.load_audio 调用 ffmpeg 子进程，需把项目 ffmpeg/bin 目录加入 PATH。

    config 可能是完整 config（含 ffmpeg.ffmpeg_path）或仅 asr_config；两者都尝试。
    """
    candidates: list[Path] = []
    ffmpeg_cfg = config.get("ffmpeg") if isinstance(config, dict) else None
    if isinstance(ffmpeg_cfg, dict) and ffmpeg_cfg.get("ffmpeg_path"):
        candidates.append(Path(str(ffmpeg_cfg["ffmpeg_path"])).resolve().parent)
    project_root = Path(__file__).resolve().parents[2]
    candidates.append(project_root / "ffmpeg" / "bin")
    path_sep = os.pathsep
    existing = os.environ.get("PATH", "")
    for bin_dir in candidates:
        if bin_dir.exists() and str(bin_dir) not in existing.split(path_sep):
            os.environ["PATH"] = f"{bin_dir}{path_sep}{existing}"
            return


def _transcribe_with_whisperx(
    input_path: Path, asr_config: dict[str, Any]
) -> tuple[list[SrtCue], list[dict[str, Any]]]:
    """whisperx 转写 + 对齐 + diarization,返回 (短句 cues, 词级 words)。

    cues 由 words 经标点/时长/字数切短句派生;words 保留逐词时间戳与 speaker。
    """
    if not input_path.exists():
        raise FileNotFoundError(f"ASR input does not exist: {input_path}")
    try:
        import whisperx  # type: ignore
        from whisperx.diarize import DiarizationPipeline, assign_word_speakers  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "ASR provider whisperx requires the whisperx package (and torch/torchaudio)."
        ) from exc

    device = str(asr_config.get("device", "cpu"))
    compute_type = str(asr_config.get("compute_type", "default"))
    language = str(asr_config.get("language", "zh"))
    model_name = str(asr_config.get("model_name", "small"))
    batch_size = int(asr_config.get("batch_size", 8))

    _ensure_ffmpeg_on_path(asr_config)

    model = whisperx.load_model(
        model_name, device=device, compute_type=compute_type, language=language
    )
    audio = whisperx.load_audio(str(input_path))
    result = model.transcribe(audio, batch_size=batch_size, language=language)

    if asr_config.get("align", True):
        try:
            align_model, align_meta = whisperx.load_align_model(language, device)
            result = whisperx.align(result, align_model, align_meta, audio, device)
        except Exception:
            # 对齐失败不阻断，退回未对齐的 segment 级结果。
            pass

    if asr_config.get("diarize", True):
        hf_token = os.getenv(str(asr_config.get("hf_token_env", "HF_TOKEN")), "")
        try:
            if not hf_token:
                raise RuntimeError(
                    "whisperx diarization requires a HuggingFace token "
                    f"(env {asr_config.get('hf_token_env', 'HF_TOKEN')}); "
                    "accept pyannote speaker-diarization-3.1 and segmentation-3.0 licenses on HF."
                )
            pipeline = DiarizationPipeline(token=hf_token, device=device)
            diarize_segments = pipeline(
                audio,
                min_speakers=asr_config.get("min_speakers"),
                max_speakers=asr_config.get("max_speakers"),
            )
            result = assign_word_speakers(diarize_segments, result)
        except Exception as exc:
            if not asr_config.get("diarize_fallback_to_asr", True):
                raise RuntimeError(f"whisperx diarization failed: {exc}") from exc
            # 退回纯 ASR：不分配 speaker，result 已有的 segments 继续使用。

    words = extract_whisperx_words(result, speaker_normalize=True)
    if words:
        cues = split_words_to_short_cues(
            words,
            max_duration_ms=int(asr_config.get("word_cue_max_duration_ms", 6000)),
            max_chars=int(asr_config.get("word_cue_max_chars", 30)),
        )
    else:
        # 无词级数据(对齐失败或旧格式):回退 segment 级映射
        cues = map_whisperx_result_to_cues(result, speaker_normalize=True)
    return cues, words


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

