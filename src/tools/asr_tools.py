from __future__ import annotations

import json
import os
import time
import urllib.error
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from uuid import uuid4

from src.state import SrtCue
from src.tools.asr_words import write_asr_words_json
from src.tools.duration_tools import get_audio_duration_ms
from src.tools.file_tools import write_json
from src.tools.srt_tools import format_srt, make_cue
from src.tools.tos_tools import upload_file_to_tos


def transcribe_mp3_to_srt(
    input_mp3: str | Path,
    output_words_json: str | Path | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Transcribe audio with Doubao file ASR or the local mock provider."""
    input_path = Path(input_mp3)
    asr_config = config.get("asr", {})
    provider = str(asr_config.get("provider", "doubao_file")).lower()
    cues: list[SrtCue] = []
    words: list[dict[str, Any]] = []
    words_json_path: str | None = None
    diarized = False

    if provider == "doubao_file":
        cues, words = _transcribe_with_doubao_file(input_path, asr_config, config)
        if not asr_config.get("enable_speaker_info", False):
            default_speaker = str(asr_config.get("default_speaker_id", "speaker_0"))
            _assign_default_speaker(cues, default_speaker)
            _assign_default_speaker_to_words(words, default_speaker)
        diarized = bool(asr_config.get("enable_speaker_info", False)) and any(
            "speaker_id" in cue for cue in cues
        )
        if output_words_json is not None and words:
            words_json_path = write_asr_words_json(output_words_json, words)
    elif provider == "mock":
        cues = _mock_transcribe(input_path, asr_config)
    else:
        raise ValueError(f"Unsupported ASR provider: {provider}. Use doubao_file.")

    speakers = sorted({cue["speaker_id"] for cue in cues if cue.get("speaker_id")})
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
        "alignment": {},
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
    try:
        response_context = urlopen(request, timeout=float(asr_config.get("http_timeout", 30)))
    except urllib.error.HTTPError as exc:
        raise _doubao_http_error("submit", exc) from exc
    with response_context as response:
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
    try:
        response_context = urlopen(request, timeout=float(asr_config.get("http_timeout", 30)))
    except urllib.error.HTTPError as exc:
        raise _doubao_http_error("query", exc) from exc
    with response_context as response:
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


def _doubao_http_error(stage: str, exc: urllib.error.HTTPError) -> RuntimeError:
    raw_body = exc.read()
    body = raw_body.decode("utf-8", errors="replace").strip() if raw_body else ""
    detail = f"Doubao ASR {stage} HTTP {exc.code} {exc.reason}"
    if body:
        detail = f"{detail}: {body[:500]}"
    return RuntimeError(detail)


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
        "enable_punc": bool(asr_config.get("enable_punc", False)),
        "enable_ddc": bool(asr_config.get("enable_ddc", False)),
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
        try:
            number = int(normalized.rsplit("_", 1)[-1])
            return f"speaker_{number + 1}"
        except (ValueError, IndexError):
            return normalized
    if normalized.isdigit():
        number = int(normalized)
        return f"speaker_{number if number > 0 else 1}"
    return normalized


def _coerce_int_ms(value: Any) -> int:
    try:
        return max(0, int(round(float(value))))
    except (TypeError, ValueError):
        return 0


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
