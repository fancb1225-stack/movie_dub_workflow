from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from uuid import uuid4

from src.state import SrtCue
from src.tools.asr_words import (
    extract_whisperx_words,
    split_words_to_short_cues,
    write_asr_words_json,
)
from src.tools.duration_tools import get_audio_duration_ms
from src.tools.file_tools import write_json
from src.tools.srt_tools import format_srt, make_cue
from src.tools.tos_tools import upload_file_to_tos


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
        _assign_default_speaker(cues, str(asr_config.get("default_speaker_id", "speaker_0")))
    elif provider == "doubao_file":
        cues, words = _transcribe_with_doubao_file(input_path, asr_config, config)
        if not asr_config.get("enable_speaker_info", False):
            _assign_default_speaker(cues, str(asr_config.get("default_speaker_id", "speaker_0")))
            _assign_default_speaker_to_words(words, str(asr_config.get("default_speaker_id", "speaker_0")))
        diarized = bool(asr_config.get("enable_speaker_info", False)) and any(
            "speaker_id" in cue for cue in cues
        )
        if output_words_json is not None and words:
            words_json_path = write_asr_words_json(output_words_json, words)
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
    alignment = {}
    if provider == "whisperx":
        alignment = {
            "enabled": bool(asr_config.get("align", True)),
            "succeeded": bool(words),
            "error": None if words else "No word-level timestamps produced.",
        }
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
        "alignment": alignment,
    }


def _assign_default_speaker(cues: list[SrtCue], speaker_id: str) -> None:
    if not speaker_id:
        return
    for cue in cues:
        cue.setdefault("speaker_id", speaker_id)


def _assign_default_speaker_to_words(words: list[dict[str, Any]], speaker_id: str) -> None:
    if not speaker_id:
        return
    for word in words:
        word.setdefault("speaker_id", speaker_id)


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
        "alignment": asr_result.get("alignment", {}),
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

def map_doubao_result_to_cues(
    result: dict[str, Any], speaker_normalize: bool = True
) -> list[SrtCue]:
    payload = _doubao_result_payload(result)
    utterances = payload.get("utterances") if isinstance(payload, dict) else None
    cues: list[SrtCue] = []
    if isinstance(utterances, list) and utterances:
        for idx, utterance in enumerate(utterances, start=1):
            if not isinstance(utterance, dict):
                continue
            start_ms = _coerce_int_ms(utterance.get("start_time"))
            end_ms = _coerce_int_ms(utterance.get("end_time"))
            cue = make_cue(
                idx,
                start_ms,
                max(end_ms, start_ms + 1),
                str(utterance.get("text", "")).strip(),
            )
            speaker = _doubao_speaker(utterance)
            if speaker:
                cue["speaker_id"] = _normalize_doubao_speaker(speaker) if speaker_normalize else speaker
            cues.append(cue)
        return cues

    if isinstance(payload, dict) and payload.get("text"):
        duration_ms = _coerce_int_ms(result.get("audio_info", {}).get("duration"))
        return [make_cue(1, 0, max(duration_ms, 1), str(payload["text"]).strip())]
    return []


def extract_doubao_words(
    result: dict[str, Any], speaker_normalize: bool = True
) -> list[dict[str, Any]]:
    payload = _doubao_result_payload(result)
    utterances = payload.get("utterances") if isinstance(payload, dict) else None
    if not isinstance(utterances, list):
        return []
    words: list[dict[str, Any]] = []
    for utterance in utterances:
        if not isinstance(utterance, dict):
            continue
        utterance_speaker = _doubao_speaker(utterance)
        for raw_word in utterance.get("words", []) or []:
            if not isinstance(raw_word, dict):
                continue
            speaker = _doubao_speaker(raw_word) or utterance_speaker
            word: dict[str, Any] = {
                "index": len(words) + 1,
                "word": str(raw_word.get("word", raw_word.get("text", ""))).strip(),
                "start_ms": _coerce_int_ms(raw_word.get("start_time")),
                "end_ms": _coerce_int_ms(raw_word.get("end_time")),
            }
            if speaker:
                word["speaker_id"] = _normalize_doubao_speaker(speaker) if speaker_normalize else speaker
            words.append(word)
    return words


def _transcribe_with_doubao_file(
    input_path: Path,
    asr_config: dict[str, Any],
    config: dict[str, Any],
) -> tuple[list[SrtCue], list[dict[str, Any]]]:
    if not input_path.exists():
        raise FileNotFoundError(f"ASR input does not exist: {input_path}")
    upload_prefix = str(asr_config.get("tos_object_prefix") or config.get("tos", {}).get("object_prefix", "asr"))
    upload = upload_file_to_tos(input_path, config, object_prefix=upload_prefix)
    result = _run_doubao_file_recognition(str(upload["url"]), asr_config)
    return map_doubao_result_to_cues(result, speaker_normalize=True), extract_doubao_words(
        result, speaker_normalize=True
    )


def _run_doubao_file_recognition(audio_url: str, asr_config: dict[str, Any]) -> dict[str, Any]:
    task_id = str(uuid4())
    _doubao_submit_task(audio_url, task_id, asr_config)
    max_attempts = int(asr_config.get("max_query_attempts", 300))
    poll_interval = float(asr_config.get("poll_interval", 2.0))
    for _attempt in range(max_attempts):
        status_code, message, payload = _doubao_query_task(task_id, asr_config)
        if status_code == "20000000":
            return payload
        if status_code not in {"20000001", "20000002"}:
            raise RuntimeError(f"Doubao ASR query failed: {status_code} {message}")
        if poll_interval > 0:
            time.sleep(poll_interval)
    raise TimeoutError(f"Doubao ASR query timed out after {max_attempts} attempts.")


def _doubao_submit_task(audio_url: str, task_id: str, asr_config: dict[str, Any]) -> None:
    body = {
        "user": {"uid": str(asr_config.get("uid", "movie_dub_workflow"))},
        "audio": _doubao_audio_payload(audio_url, asr_config),
        "request": _doubao_request_payload(asr_config),
    }
    request = _doubao_request(
        str(asr_config.get("submit_url", "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit")),
        task_id,
        asr_config,
        body,
        include_sequence=True,
    )
    with urlopen(request, timeout=float(asr_config.get("http_timeout", 30))) as response:
        status_code = str(response.getheader("X-Api-Status-Code", ""))
        message = str(response.getheader("X-Api-Message", ""))
    if status_code != "20000000":
        raise RuntimeError(f"Doubao ASR submit failed: {status_code} {message}")


def _doubao_query_task(
    task_id: str, asr_config: dict[str, Any]
) -> tuple[str, str, dict[str, Any]]:
    request = _doubao_request(
        str(asr_config.get("query_url", "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query")),
        task_id,
        asr_config,
        {},
        include_sequence=False,
    )
    with urlopen(request, timeout=float(asr_config.get("http_timeout", 30))) as response:
        raw_body = response.read()
        status_code = str(response.getheader("X-Api-Status-Code", ""))
        message = str(response.getheader("X-Api-Message", ""))
    payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    return status_code, message, payload


def _doubao_request(
    url: str,
    task_id: str,
    asr_config: dict[str, Any],
    body: dict[str, Any],
    *,
    include_sequence: bool,
) -> Request:
    api_key_env = str(asr_config.get("api_key_env", "DOUBAO_ASR_API_KEY"))
    api_key = os.getenv(api_key_env, "")
    if not api_key:
        raise RuntimeError(f"Doubao ASR requires environment variable {api_key_env}.")
    headers = {
        "Content-Type": "application/json",
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": str(asr_config.get("resource_id", "volc.seedasr.auc")),
        "X-Api-Request-Id": task_id,
    }
    if include_sequence:
        headers["X-Api-Sequence"] = "-1"
    return Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")


def _doubao_audio_payload(audio_url: str, asr_config: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "format": str(asr_config.get("audio_format", "wav")),
        "url": audio_url,
    }
    language = asr_config.get("language")
    if language:
        payload["language"] = _doubao_language(str(language))
    for key in ("codec", "rate", "bits", "channel"):
        value = asr_config.get(f"audio_{key}")
        if value is not None:
            payload[key] = value
    return payload


def _doubao_request_payload(asr_config: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model_name": str(asr_config.get("doubao_model_name", "bigmodel")),
        "enable_itn": bool(asr_config.get("enable_itn", True)),
        "enable_punc": bool(asr_config.get("enable_punc", True)),
        "show_utterances": bool(asr_config.get("show_utterances", True)),
        "enable_speaker_info": bool(asr_config.get("enable_speaker_info", False)),
    }
    if payload["enable_speaker_info"] and asr_config.get("ssd_version"):
        payload["ssd_version"] = str(asr_config["ssd_version"])
    return payload


def _doubao_language(language: str) -> str:
    return {"zh": "zh-CN", "en": "en-US"}.get(language, language)


def _doubao_result_payload(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("result", {})
    if isinstance(payload, list):
        first = payload[0] if payload else {}
        return first if isinstance(first, dict) else {}
    return payload if isinstance(payload, dict) else {}


def _doubao_speaker(item: dict[str, Any]) -> str | None:
    for key in ("speaker_id", "speaker", "speakerId"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    speaker_info = item.get("speaker_info")
    if isinstance(speaker_info, dict):
        for key in ("speaker_id", "speaker", "speakerId"):
            value = speaker_info.get(key)
            if value not in (None, ""):
                return str(value)
    additions = item.get("additions")
    if isinstance(additions, str):
        try:
            additions = json.loads(additions)
        except json.JSONDecodeError:
            additions = {}
    if isinstance(additions, dict):
        for key in ("speaker_id", "speaker", "speakerId"):
            value = additions.get(key)
            if value not in (None, ""):
                return str(value)
    return None


def _normalize_doubao_speaker(label: str) -> str:
    normalized = label.strip()
    if not normalized:
        return normalized
    lowered = normalized.lower()
    if lowered.startswith("speaker_"):
        return lowered
    if normalized.upper().startswith("SPEAKER_"):
        return _normalize_speaker(normalized.upper())
    if normalized.isdigit():
        number = int(normalized)
        return f"speaker_{number if number > 0 else 1}"
    return normalized


def _coerce_int_ms(value: Any) -> int:
    try:
        return max(0, int(round(float(value))))
    except (TypeError, ValueError):
        return 0


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
        alignment_succeeded = False
        alignment_error: str | None = None
        try:
            align_model, align_meta = whisperx.load_align_model(language, device)
            result = _align_whisperx_result(
                whisperx,
                result,
                align_model,
                align_meta,
                audio,
                device,
                asr_config,
            )
            alignment_succeeded = True
        except Exception as exc:
            alignment_error = f"{type(exc).__name__}: {exc}"
            if asr_config.get("align_strict", False):
                raise RuntimeError(f"whisperx alignment failed: {exc}") from exc
            logger = __import__("logging").getLogger(__name__)
            logger.warning("whisperx alignment failed; fallback to segment-level ASR: %s", alignment_error)
        result["alignment"] = {
            "enabled": True,
            "succeeded": alignment_succeeded,
            "error": alignment_error,
        }
    else:
        result["alignment"] = {"enabled": False, "succeeded": False, "error": None}

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


def _align_whisperx_result(
    whisperx_module: Any,
    result: dict[str, Any],
    align_model: Any,
    align_meta: dict[str, Any],
    audio: Any,
    device: str,
    asr_config: dict[str, Any],
) -> dict[str, Any]:
    """Run whisperx.align with the API shape used by current WhisperX releases."""
    aligned = whisperx_module.align(
        result.get("segments", []),
        align_model,
        align_meta,
        audio,
        device,
        return_char_alignments=bool(asr_config.get("return_char_alignments", False)),
    )
    if not isinstance(aligned, dict):
        raise RuntimeError(f"whisperx.align returned {type(aligned).__name__}, expected dict")
    if "segments" not in aligned and "word_segments" not in aligned:
        raise RuntimeError("whisperx.align returned no segments or word_segments")
    merged = {**result, **aligned}
    return merged


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

