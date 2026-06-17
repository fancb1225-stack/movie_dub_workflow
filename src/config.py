from __future__ import annotations

import os
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "paths": {
        "input_mp3": "input/input.mp3",
        "input_video": "",
        "background_mp3": "input/background.mp3",
        "outputs_dir": "outputs",
        "asr_srt": "outputs/asr/zh_raw.srt",
        "merged_asr_srt": "outputs/merged/zh_asr_merged.srt",
        "cleaned_srt": "outputs/cleaned/zh_cleaned.srt",
        "corrected_srt": "outputs/critic/zh_corrected.srt",
        "translated_srt": "outputs/translated/en_translated.srt",
        "final_srt": "outputs/final/en_final.srt",
        "tts_segments_dir": "outputs/tts_segments",
        "reports_dir": "outputs/reports",
        "audio_dir": "outputs/audio",
        "narration_wav": "outputs/audio/narration_en.wav",
        "narration_mp3": "outputs/audio/narration_en.mp3",
        "jianying_draft_dir": "outputs/jianying",
    },
    "server": {
        "host": "127.0.0.1",
        "port": 8000,
    },
    "jobs": {
        "root_dir": "outputs/jobs",
    },
    "ffmpeg": {
        "ffmpeg_path": "ffmpeg/bin/ffmpeg.exe",
        "ffprobe_path": "ffmpeg/bin/ffprobe.exe",
    },
    "media": {
        "audio_sample_rate": 16000,
    },
    "separation": {
        "provider": "demucs",
        "method": "python",
        "model": "htdemucs",
    },
    "speaker": {
        "mode": "placeholder",
    },
    "video": {
        "copy_video": True,
    },
    "workflow": {
        "allow_mock_asr_for_jobs": False,
        "force_job_asr_provider": "faster_whisper",
    },
    "asr": {
        "provider": "mock",
        "model_name": "small",
        "language": "zh",
        "device": "cpu",
        "compute_type": "int8",
        "vad_filter": True,
        "mock_when_missing_input": True,
    },
    "llm": {
        "api_key_env": "LLM_API_KEY",
        "base_url_env": "LLM_BASE_URL",
        "model_env": "LLM_MODEL",
        "timeout_env": "LLM_TIMEOUT",
        "max_retries_env": "LLM_MAX_RETRIES",
        "base_url": "https://api.openai.com/v1",
        "model": "mock",
        "timeout": 60,
        "max_retries": 2,
    },
    "translation": {
        "allow_mock_fallback": False,
        "chunk_size": 20,
        "max_parallel_chunks": 3,
    },
    "srt": {
        "merge_max_chars": 38,
        "merge_max_gap_ms": 450,
        "merge_max_duration_ms": 6500,
    },
    "tts": {
        "provider": "mock",
        "voice": "en-US-AriaNeural",
        "rate": "+30%",
        "sample_rate": 24000,
        "words_per_minute": 155,
        "max_retries": 1,
    },
    "duration": {
        "max_overrun_ms": 350,
        "max_ratio": 1.12,
        "max_reflection_rounds": 1,
    },
    "audio": {
        "mix_background": False,
        "background_volume": 0.18,
    },
    "alignment": {
        "max_shift_back_overlap_ms": 200,
        "shift_back_gap_ms": 50,
        "enable_overlap_resolution": True,
    },
}


def load_config(config_path: str | Path = "config.yaml") -> dict[str, Any]:
    path = Path(config_path)
    data = _read_yaml(path) if path.exists() else {}
    config = _deep_merge(deepcopy(DEFAULT_CONFIG), data)
    _apply_llm_env(config)
    config["project_root"] = str(path.resolve().parent if path.exists() else Path.cwd())
    return config


def resolve_path(config: dict[str, Any], value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return Path(config.get("project_root", Path.cwd())).joinpath(path).resolve()


def config_path(config: dict[str, Any], key: str) -> Path:
    value: Any = config
    for part in key.split("."):
        value = value[part]
    return resolve_path(config, str(value))


def config_value(config: dict[str, Any], key: str, default: Any = None) -> Any:
    value: Any = config
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def find_binary(config: dict[str, Any], key: str, fallback_name: str) -> Path:
    configured = config_value(config, key)
    if configured:
        configured_path = resolve_path(config, str(configured))
        if configured_path.exists():
            return configured_path
    exe_name = _windows_exe_name(fallback_name)
    local_candidate = resolve_path(config, Path("ffmpeg") / "bin" / exe_name)
    if local_candidate.exists():
        return local_candidate
    path_candidate = shutil.which(fallback_name) or shutil.which(exe_name)
    if path_candidate:
        return Path(path_candidate).resolve()
    raise FileNotFoundError(
        f"Unable to find binary for {key}. Checked config value, local ffmpeg/bin, and PATH."
    )


def _read_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(text)
        return loaded or {}
    except ImportError:
        return _parse_simple_yaml(text)


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        key, sep, raw_value = raw_line.strip().partition(":")
        if not sep:
            continue
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if raw_value.strip() == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_scalar(raw_value.strip())
    return root


def _parse_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _deep_merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _apply_llm_env(config: dict[str, Any]) -> None:
    llm = config.setdefault("llm", {})
    env_map = {
        "api_key": llm.get("api_key_env", "LLM_API_KEY"),
        "base_url": llm.get("base_url_env", "LLM_BASE_URL"),
        "model": llm.get("model_env", "LLM_MODEL"),
        "timeout": llm.get("timeout_env", "LLM_TIMEOUT"),
        "max_retries": llm.get("max_retries_env", "LLM_MAX_RETRIES"),
    }
    for key, env_name in env_map.items():
        value = os.getenv(str(env_name), "")
        if not value:
            continue
        if key in {"timeout", "max_retries"}:
            llm[key] = int(value)
        else:
            llm[key] = value


def _windows_exe_name(name: str) -> str:
    if os.name == "nt" and not name.lower().endswith(".exe"):
        return f"{name}.exe"
    return name
