from __future__ import annotations

import os
from typing import Any

from src.video_types import DEFAULT_VIDEO_TYPE, VIDEO_TYPE_MANJU, normalize_video_type


ASR_OVERRIDE_KEYS = {
    "language": "asr.language",
    "enable_punc": "asr.enable_punc",
    "enable_itn": "asr.enable_itn",
    "enable_ddc": "asr.enable_ddc",
    "enable_speaker_info": "asr.enable_speaker_info",
    "max_query_attempts": "asr.max_query_attempts",
    "poll_interval_seconds": "asr.poll_interval",
}


def build_asr_settings_response(
    config: dict[str, Any],
    video_type: str | None = None,
) -> dict[str, Any]:
    asr_config = config.get("asr", {})
    normalized_video_type = normalize_video_type(video_type or config.get("job", {}).get("video_type", DEFAULT_VIDEO_TYPE))
    defaults = _effective_defaults(config, normalized_video_type)
    return {
        "provider": "doubao_file",
        "video_type": normalized_video_type,
        "defaults": defaults,
        "fields": _field_metadata(),
        "language_options": [
            {"value": "", "label": "空值/不传（中英及方言）"},
            {"value": "zh-CN", "label": "中文普通话 zh-CN"},
            {"value": "en-US", "label": "英语 en-US"},
            {"value": "ja-JP", "label": "日语 ja-JP"},
            {"value": "ko-KR", "label": "韩语 ko-KR"},
        ],
        "tos": _tos_status(config),
        "official": {
            "submit_url": str(asr_config.get("submit_url", "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit")),
            "query_url": str(asr_config.get("query_url", "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query")),
            "resource_id": str(asr_config.get("resource_id", "volc.seedasr.auc")),
        },
    }


def build_asr_overrides(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    source = payload.get("asr") if isinstance(payload.get("asr"), dict) else payload
    overrides: dict[str, Any] = {}
    for key, dotted_key in ASR_OVERRIDE_KEYS.items():
        if key not in source:
            continue
        value = source[key]
        if key == "language":
            language = str(value).strip()
            if language:
                overrides[dotted_key] = language
            continue
        if key in {"enable_punc", "enable_itn", "enable_ddc", "enable_speaker_info"}:
            overrides[dotted_key] = bool(value)
            continue
        if key == "max_query_attempts":
            overrides[dotted_key] = max(1, int(value))
            continue
        if key == "poll_interval_seconds":
            overrides[dotted_key] = max(0.0, float(value))
    return overrides


def _effective_defaults(config: dict[str, Any], video_type: str) -> dict[str, Any]:
    asr_config = config.get("asr", {})
    enable_speaker_info = video_type == VIDEO_TYPE_MANJU
    return {
        "audio_format": str(asr_config.get("audio_format", "wav")),
        "model_name": str(asr_config.get("doubao_model_name", "bigmodel")),
        "show_utterances": bool(asr_config.get("show_utterances", True)),
        "language": str(asr_config.get("language") or ""),
        "enable_itn": bool(asr_config.get("enable_itn", True)),
        "enable_punc": bool(asr_config.get("enable_punc", False)),
        "enable_ddc": bool(asr_config.get("enable_ddc", False)),
        "enable_speaker_info": enable_speaker_info,
        "max_query_attempts": int(asr_config.get("max_query_attempts", 300)),
        "poll_interval_seconds": float(asr_config.get("poll_interval", 2.0)),
    }


def _field_metadata() -> dict[str, dict[str, Any]]:
    return {
        "audio_url": {
            "label": "音频 URL",
            "required": True,
            "fixed": True,
            "source": "系统上传 TOS 后生成",
        },
        "audio_format": {
            "label": "音频格式",
            "required": True,
            "fixed": True,
            "official_values": ["raw", "wav", "mp3", "ogg"],
        },
        "model_name": {
            "label": "模型",
            "required": True,
            "fixed": True,
            "official_values": ["bigmodel"],
        },
        "show_utterances": {
            "label": "分句结果",
            "required": True,
            "fixed": True,
            "app_reason": "下游 words/cues 依赖 utterances",
        },
        "language": {
            "label": "语言",
            "required": False,
            "allow_empty": True,
            "empty_behavior": "不传时使用官方中英及方言能力",
        },
        "enable_itn": {
            "label": "ITN",
            "required": False,
            "official_default": True,
        },
        "enable_punc": {
            "label": "标点",
            "required": False,
            "official_default": False,
        },
        "enable_ddc": {
            "label": "顺滑",
            "required": False,
            "official_default": False,
        },
        "enable_speaker_info": {
            "label": "多说话人",
            "required": False,
            "official_default": False,
        },
        "max_query_attempts": {
            "label": "轮询次数",
            "required": False,
            "app_default": 300,
            "source": "应用参数，非豆包请求体",
        },
        "poll_interval_seconds": {
            "label": "轮询间隔",
            "required": False,
            "app_default": 2.0,
            "source": "应用参数，非豆包请求体",
        },
    }


def _tos_status(config: dict[str, Any]) -> dict[str, Any]:
    tos = config.get("tos", {})
    access_key_id_env = str(tos.get("access_key_id_env", "DOUBAO_TOS_ACCESS_KEY_ID"))
    secret_access_key_env = str(tos.get("secret_access_key_env", "DOUBAO_TOS_SECRET_ACCESS_KEY"))
    required = {
        "endpoint": bool(str(tos.get("endpoint", "")).strip()),
        "region": bool(str(tos.get("region", "")).strip()),
        "bucket": bool(str(tos.get("bucket", "")).strip()),
        "access_key_id_env": bool(os.getenv(access_key_id_env, "")),
        "secret_access_key_env": bool(os.getenv(secret_access_key_env, "")),
    }
    return {
        "ready": all(required.values()),
        "endpoint": str(tos.get("endpoint", "")),
        "region": str(tos.get("region", "")),
        "bucket": str(tos.get("bucket", "")),
        "object_prefix": str(tos.get("object_prefix", "movie-dub/asr")),
        "access_key_id_env": access_key_id_env,
        "secret_access_key_env": secret_access_key_env,
        "configured": required,
        "missing": [key for key, configured in required.items() if not configured],
    }
