from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import traceback
import wave
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from src.state import SrtCue, TtsSegment
from src.tools.duration_tools import get_audio_duration_ms
from src.tools.file_tools import clean_dir, ensure_dir

logger = logging.getLogger(__name__)


class FatalTtsError(RuntimeError):
    """Unrecoverable TTS configuration or provider error."""


def is_fatal_tts_error(exc_or_message: Exception | str) -> bool:
    message = str(exc_or_message).lower()
    fatal_markers = (
        "access_denied",
        "http 401",
        "http 403",
        "ip whitelist",
        "ip white list",
        "ip is not allowed",
        "not in the user allowed access list",
        "not in user allowed access list",
        "不在用户允许访问",
        "允许访问的列表",
        "minimax tts task timeout",
    )
    return any(marker in message for marker in fatal_markers)


TTS_SEGMENT_MANIFEST = "segment_manifest.json"


def generate_tts_segments(
    cues: list[SrtCue],
    output_dir: str | Path,
    config: dict[str, Any],
    *,
    reuse_existing: bool = False,
    force_regenerate_indices: set[int] | None = None,
) -> list[TtsSegment]:
    directory = ensure_dir(output_dir)
    tts_config = config.get("tts", {})
    provider = str(tts_config.get("provider", "mock")).lower()
    force_indices = force_regenerate_indices or set()
    if reuse_existing:
        manifest = _load_tts_segment_manifest(directory)
    else:
        clean_dir(directory, "segment_*.mp3")
        _manifest_path(directory).unlink(missing_ok=True)
        manifest = {"version": 1, "segments": {}}
    logger.info(
        "TTS generate: provider=%s, cues=%d, output_dir=%s, reuse_existing=%s",
        provider,
        len(cues),
        directory,
        reuse_existing,
    )
    logger.debug("TTS config: %s", tts_config)

    reused_by_index: dict[int, TtsSegment] = {}
    cues_to_generate: list[SrtCue] = []
    for cue in cues:
        reused = None
        if reuse_existing:
            reused = _try_reuse_tts_segment(cue, directory, config, tts_config, provider, manifest, force_indices)
        if reused is None:
            cues_to_generate.append(cue)
        else:
            reused_by_index[int(cue["index"])] = reused

    generated = _generate_tts_segments_batch(cues_to_generate, directory, config, tts_config, provider)
    segments_by_index = dict(reused_by_index)
    for segment in generated:
        segments_by_index[int(segment["index"])] = segment

    segments = [segments_by_index[int(cue["index"])] for cue in cues]
    _write_tts_segment_manifest(directory, _build_tts_segment_manifest(cues, segments, tts_config, provider))
    success_count = sum(1 for segment in segments if segment["success"])
    logger.info(
        "TTS generate done: %d/%d segments succeeded (reused=%d, generated=%d)",
        success_count,
        len(segments),
        len(reused_by_index),
        len(generated),
    )
    return segments


def _generate_tts_segments_batch(
    cues: list[SrtCue],
    directory: Path,
    config: dict[str, Any],
    tts_config: dict[str, Any],
    provider: str,
) -> list[TtsSegment]:
    if not cues:
        return []
    max_workers = max(1, int(tts_config.get("concurrency", 25 if provider == "minimax" else 1)))
    if max_workers <= 1 or len(cues) <= 1:
        return [_generate_one_tts_segment(cue, directory, config, tts_config, provider) for cue in cues]
    results: dict[int, TtsSegment] = {0: _generate_one_tts_segment(cues[0], directory, config, tts_config, provider)}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(cues))) as executor:
        futures = {
            executor.submit(_generate_one_tts_segment, cue, directory, config, tts_config, provider): idx
            for idx, cue in enumerate(cues[1:], start=1)
        }
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return [results[idx] for idx in range(len(cues))]


def _generate_one_tts_segment(
    cue: SrtCue,
    directory: Path,
    config: dict[str, Any],
    tts_config: dict[str, Any],
    provider: str,
) -> TtsSegment:
    segment_path = directory / f"segment_{cue['index']:04d}.mp3"
    try:
        speaker_profile = _resolve_speaker_profile(cue, tts_config)
        if provider == "edge_tts":
            _generate_edge_tts(cue["text"], segment_path, tts_config)
        elif provider == "minimax":
            _generate_minimax_tts(cue["text"], segment_path, tts_config, speaker_profile)
        else:
            _generate_mock_audio(cue["text"], segment_path, tts_config)
        if not segment_path.exists():
            raise FileNotFoundError(f"TTS output file was not created: {segment_path}")
        file_size = segment_path.stat().st_size
        if file_size == 0:
            raise RuntimeError(f"TTS output file is empty (0 bytes): {segment_path}")
        duration_ms = get_audio_duration_ms(segment_path, config)
        logger.debug("TTS segment %d OK: size=%d, duration_ms=%d", cue["index"], file_size, duration_ms)
        return _build_success_tts_segment(cue, segment_path, duration_ms, provider, speaker_profile)
    except FatalTtsError:
        logger.error("TTS segment %d FATAL:\n%s", cue["index"], traceback.format_exc())
        raise
    except Exception as exc:
        if is_fatal_tts_error(exc):
            logger.error("TTS segment %d FATAL:\n%s", cue["index"], traceback.format_exc())
            raise FatalTtsError(str(exc)) from exc
        logger.error(
            "TTS segment %d FAILED: %s\n%s",
            cue["index"],
            exc,
            traceback.format_exc(),
        )
        failed_segment: TtsSegment = {
            "index": cue["index"],
            "text": cue["text"],
            "start_ms": cue["start_ms"],
            "end_ms": cue["end_ms"],
            "path": str(segment_path),
            "duration_ms": 0,
            "success": False,
            "error": str(exc),
            "provider": provider,
        }
        if cue.get("speaker_id"):
            failed_segment["speaker_id"] = cue["speaker_id"]
        return failed_segment


def _manifest_path(directory: Path) -> Path:
    return directory / TTS_SEGMENT_MANIFEST


def _load_tts_segment_manifest(directory: Path) -> dict[str, Any]:
    path = _manifest_path(directory)
    if not path.exists():
        return {"version": 1, "segments": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("segments"), dict):
            return data
    except Exception as exc:
        logger.warning("TTS segment manifest cannot be read; regenerating as needed: %s", exc)
    return {"version": 1, "segments": {}}


def _write_tts_segment_manifest(directory: Path, manifest: dict[str, Any]) -> None:
    _manifest_path(directory).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )


def _try_reuse_tts_segment(
    cue: SrtCue,
    directory: Path,
    config: dict[str, Any],
    tts_config: dict[str, Any],
    provider: str,
    manifest: dict[str, Any],
    force_regenerate_indices: set[int],
) -> TtsSegment | None:
    index = int(cue["index"])
    if index in force_regenerate_indices:
        return None
    speaker_profile = _resolve_speaker_profile(cue, tts_config)
    signature = _tts_segment_signature(cue, tts_config, speaker_profile, provider)
    entry = manifest.get("segments", {}).get(str(index))
    if not isinstance(entry, dict) or not entry.get("success") or entry.get("signature") != signature:
        return None
    segment_path = directory / f"segment_{index:04d}.mp3"
    try:
        if not segment_path.exists() or segment_path.stat().st_size <= 0:
            return None
        duration_ms = get_audio_duration_ms(segment_path, config)
    except Exception as exc:
        logger.warning("Existing TTS segment %d cannot be reused; regenerating: %s", index, exc)
        return None
    segment = _build_success_tts_segment(cue, segment_path, duration_ms, provider, speaker_profile)
    segment["reused"] = True
    return segment


def _build_success_tts_segment(
    cue: SrtCue,
    segment_path: Path,
    duration_ms: int,
    provider: str,
    speaker_profile: dict[str, Any],
) -> TtsSegment:
    segment: TtsSegment = {
        "index": cue["index"],
        "text": cue["text"],
        "start_ms": cue["start_ms"],
        "end_ms": cue["end_ms"],
        "path": str(segment_path),
        "duration_ms": duration_ms,
        "success": True,
        "provider": provider,
    }
    if cue.get("speaker_id"):
        segment["speaker_id"] = cue["speaker_id"]
    if speaker_profile.get("voice_id"):
        segment["voice_id"] = str(speaker_profile["voice_id"])
    if speaker_profile.get("speed") is not None:
        segment["speed"] = float(speaker_profile["speed"])
    return segment


def _build_tts_segment_manifest(
    cues: list[SrtCue],
    segments: list[TtsSegment],
    tts_config: dict[str, Any],
    provider: str,
) -> dict[str, Any]:
    by_index = {int(segment["index"]): segment for segment in segments}
    entries: dict[str, Any] = {}
    for cue in cues:
        index = int(cue["index"])
        segment = by_index[index]
        speaker_profile = _resolve_speaker_profile(cue, tts_config)
        entries[str(index)] = _manifest_entry_for_segment(
            cue,
            segment,
            _tts_segment_signature(cue, tts_config, speaker_profile, provider),
        )
    return {"version": 1, "segments": entries}


def _manifest_entry_for_segment(cue: SrtCue, segment: TtsSegment, signature: str) -> dict[str, Any]:
    path = Path(str(segment.get("path", "")))
    entry: dict[str, Any] = {
        "index": cue["index"],
        "path": str(path),
        "text": cue["text"],
        "success": bool(segment.get("success")),
        "provider": segment.get("provider"),
        "speaker_id": cue.get("speaker_id") or "default",
        "voice_id": segment.get("voice_id"),
        "speed": segment.get("speed"),
        "duration_ms": segment.get("duration_ms"),
        "signature": signature,
    }
    if path.exists():
        entry["file_size"] = path.stat().st_size
    if segment.get("error"):
        entry["error"] = segment["error"]
    return entry


def _tts_segment_signature(
    cue: SrtCue,
    tts_config: dict[str, Any],
    speaker_profile: dict[str, Any],
    provider: str,
) -> str:
    minimax = _minimax_config(tts_config)
    payload = {
        "index": cue["index"],
        "text": cue["text"],
        "provider": provider,
        "speaker_id": cue.get("speaker_id") or "default",
        "voice_id": speaker_profile.get("voice_id"),
        "speed": speaker_profile.get("speed"),
        "volume": speaker_profile.get("volume", speaker_profile.get("vol")),
        "pitch": speaker_profile.get("pitch"),
        "language_boost": speaker_profile.get("language_boost", minimax.get("language_boost")),
        "voice": tts_config.get("voice"),
        "rate": tts_config.get("rate"),
        "sample_rate": tts_config.get("sample_rate"),
        "minimax": {
            "model": minimax.get("model"),
            "base_url": minimax.get("base_url"),
            "create_path": minimax.get("create_path"),
        },
    }
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _resolve_speaker_profile(cue: SrtCue, tts_config: dict[str, Any]) -> dict[str, Any]:
    speaker_id = cue.get("speaker_id") or "default"
    profiles = tts_config.get("speaker_profiles", {})
    profile: dict[str, Any] = {}
    if isinstance(profiles, dict):
        raw_profile = profiles.get(speaker_id) or profiles.get("default") or {}
        if isinstance(raw_profile, dict):
            profile = dict(raw_profile)
    if not profile and str(tts_config.get("provider", "")).lower() == "minimax":
        default_voice = _minimax_config(tts_config).get("default_voice_id") or tts_config.get("voice")
        if default_voice:
            profile = {"voice_id": default_voice}
    if str(tts_config.get("provider", "")).lower() == "minimax" and not profile.get("voice_id"):
        profile["voice_id"] = "Wise_Woman"
    if speaker_id != "default":
        profile.setdefault("speaker_id", speaker_id)
    if "speed" not in profile:
        profile["speed"] = _rate_to_speed(tts_config.get("rate", "+0%"))
    return profile


def _rate_to_speed(rate: Any) -> float:
    if isinstance(rate, (int, float)):
        return float(rate)
    text = str(rate or "+0%").strip()
    if text.endswith("%"):
        try:
            return max(0.5, min(3.0, 1 + float(text[:-1]) / 100))
        except ValueError:
            return 1.0
    try:
        return float(text)
    except ValueError:
        return 1.0


def _minimax_config(tts_config: dict[str, Any]) -> dict[str, Any]:
    raw = tts_config.get("minimax", {})
    return raw if isinstance(raw, dict) else {}


def _clean_config_value(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    return text


def _join_minimax_url(base_url: str, path: str, group_id: str = "") -> str:
    if not base_url:
        raise RuntimeError("TTS provider minimax requires base_url or MINIMAX_BASE_URL.")
    if path.startswith(("http://", "https://")):
        url = path
    elif not path:
        url = base_url.rstrip("/")
    else:
        url = base_url.rstrip("/") + "/" + path.lstrip("/")
    if group_id:
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if not any(key.lower() == "groupid" for key, _ in query):
            query.append(("GroupId", group_id))
        url = urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(query)))
    return url


def _find_first(data: Any, names: set[str]) -> Any:
    if isinstance(data, dict):
        for key, value in data.items():
            if key in names and value not in (None, ""):
                return value
        for value in data.values():
            found = _find_first(value, names)
            if found not in (None, ""):
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_first(item, names)
            if found not in (None, ""):
                return found
    return None


def _minimax_error_message(error: Any, *, status_code: int | None = None, reason: str = "") -> str | None:
    if not isinstance(error, dict):
        return None
    code = str(error.get("code") or error.get("type") or "unknown")
    message = str(error.get("message") or error.get("msg") or "")
    parts = ["MiniMax TTS request fatal error"]
    if status_code is not None:
        parts.append(f"HTTP {status_code}")
    if reason:
        parts.append(reason)
    parts.append(code)
    if message:
        parts.append(message)
    return ": ".join(parts)


def _minimax_fatal_error_from_body(
    body: str,
    *,
    status_code: int | None = None,
    reason: str = "",
) -> FatalTtsError | None:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    error = parsed.get("error")
    message = _minimax_error_message(error, status_code=status_code, reason=reason)
    if message is None:
        return None
    code = str(error.get("code") or "").lower() if isinstance(error, dict) else ""
    if code == "access_denied" or status_code in {401, 403}:
        return FatalTtsError(message)
    return None


def _minimax_request_json(
    method: str,
    url: str,
    api_key: str,
    payload: dict[str, Any] | None,
    timeout: float,
    max_retries: int,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    last_error: Exception | str | None = None
    for attempt in range(max_retries + 1):
        try:
            request = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
            if not body.strip():
                return {}
            parsed = json.loads(body)
            if not isinstance(parsed, dict):
                raise RuntimeError(f"MiniMax returned non-object JSON: {body[:300]}")
            fatal_error = _minimax_fatal_error_from_body(body)
            if fatal_error is not None:
                raise fatal_error
            return parsed
        except FatalTtsError:
            raise
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            fatal_error = _minimax_fatal_error_from_body(body, status_code=exc.code, reason=exc.reason)
            if fatal_error is not None:
                raise fatal_error
            last_error = f"HTTP {exc.code}: {exc.reason}; response={body[:500]}"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = exc
        if attempt < max_retries:
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"MiniMax TTS request failed: {method} {url} -> {last_error}")


def _generate_minimax_tts(
    text: str,
    output_path: Path,
    tts_config: dict[str, Any],
    speaker_profile: dict[str, Any],
) -> None:
    minimax = _minimax_config(tts_config)
    api_key = _clean_config_value(os.getenv(str(minimax.get("api_key_env", "LLM_API_KEY")), ""))
    base_url = _clean_config_value(os.getenv(str(minimax.get("base_url_env", "")), "")) or _clean_config_value(minimax.get("base_url", ""))
    model = _clean_config_value(os.getenv(str(minimax.get("model_env", "TTS_MODEL")), "")) or _clean_config_value(minimax.get("model", ""))
    group_id = _clean_config_value(os.getenv(str(minimax.get("group_id_env", "MINIMAX_GROUP_ID")), ""))
    voice_id = _clean_config_value(speaker_profile.get("voice_id") or minimax.get("default_voice_id") or tts_config.get("voice"))
    if not api_key:
        raise RuntimeError("TTS provider minimax requires LLM_API_KEY.")
    if not model:
        raise RuntimeError("TTS provider minimax requires TTS_MODEL.")
    if not voice_id:
        raise RuntimeError("TTS provider minimax requires voice_id for speaker profile.")

    audio_format = str(minimax.get("format", output_path.suffix.lstrip(".") or "mp3"))
    create_path = str(minimax.get("create_path", "/v1/minimax/tts/async"))
    query_path = str(minimax.get("query_path", "/v1/minimax/tts/tasks/{task_id}"))
    file_path = str(minimax.get("file_path", ""))
    timeout = float(minimax.get("timeout", 60))
    poll_interval = float(minimax.get("poll_interval", 1.5))
    task_timeout = float(minimax.get("task_timeout", 600))
    max_retries = int(tts_config.get("max_retries", minimax.get("max_retries", 2)))
    channel = int(minimax.get("channel", 2))
    bitrate = int(minimax.get("bitrate", 128000))
    sample_rate = int(tts_config.get("sample_rate", minimax.get("sample_rate", 24000)))

    payload = {
        "model": model,
        "text": text,
        "voice_setting": {
            "voice_id": voice_id,
            "speed": float(speaker_profile.get("speed", 1.0)),
            "vol": float(speaker_profile.get("volume", speaker_profile.get("vol", 1.0))),
            "pitch": float(speaker_profile.get("pitch", 0.0)),
        },
        "audio_setting": {
            "audio_sample_rate": sample_rate,
            "bitrate": bitrate,
            "format": audio_format,
            "channel": channel,
        },
        "language_boost": str(speaker_profile.get("language_boost", minimax.get("language_boost", "auto"))),
    }
    create_result = _minimax_request_json(
        "POST",
        _join_minimax_url(base_url, create_path, group_id),
        api_key,
        payload,
        timeout,
        max_retries,
    )
    task_id = _find_first(create_result, {"task_id", "taskId", "id"})
    if not task_id:
        raise RuntimeError("MiniMax TTS create task returned no task_id.")
    deadline = time.monotonic() + task_timeout
    task_result: dict[str, Any] = {}
    while time.monotonic() <= deadline:
        task_result = _minimax_request_json(
            "GET",
            _join_minimax_url(base_url, query_path.format(task_id=urllib.parse.quote(str(task_id), safe="")), group_id),
            api_key,
            None,
            timeout,
            max_retries,
        )
        status = str(_find_first(task_result, {"status", "task_status", "taskStatus", "state"}) or "").upper()
        if status in {"SUCCESS", "SUCCEEDED", "COMPLETED", "DONE"}:
            break
        if status in {"FAILURE", "FAILED", "ERROR", "CANCELLED", "CANCELED"}:
            raise RuntimeError(f"MiniMax TTS task failed: task_id={task_id}, status={status}")
        time.sleep(max(0.5, poll_interval))
    else:
        raise FatalTtsError(f"MiniMax TTS task timeout: task_id={task_id}")

    download_url = _find_first(task_result, {"result_url", "audio_url", "download_url", "file_url", "url", "output_url"})
    if not download_url and file_path:
        file_id = _find_first(task_result, {"file_id", "fileId"})
        if file_id:
            file_result = _minimax_request_json(
                "GET",
                _join_minimax_url(base_url, file_path.format(file_id=urllib.parse.quote(str(file_id), safe="")), group_id),
                api_key,
                None,
                timeout,
                max_retries,
            )
            download_url = _find_first(file_result, {"result_url", "audio_url", "download_url", "file_url", "url"})
    if not download_url:
        raise RuntimeError("MiniMax TTS task succeeded but returned no download url.")
    request = urllib.request.Request(str(download_url), headers={"Authorization": f"Bearer {api_key}"}, method="GET")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = output_path.with_name(f"{output_path.name}.part")
    with urllib.request.urlopen(request, timeout=max(timeout, 180)) as response:
        part_path.write_bytes(response.read())
    part_path.replace(output_path)


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
