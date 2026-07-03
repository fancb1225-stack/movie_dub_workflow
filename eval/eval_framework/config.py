from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when eval configuration is invalid."""


@dataclass(frozen=True)
class LLMConfig:
    api_key_env: str
    base_url: str
    model: str
    timeout: int
    max_retries: int

    @property
    def api_key(self) -> str:
        return os.getenv(self.api_key_env, "")


@dataclass(frozen=True)
class NodeEvalConfig:
    node_name: str
    judge_prompt_path: Path
    deterministic_checks: list[str]


@dataclass(frozen=True)
class EvalConfig:
    repo_root: Path
    cases_dir: Path
    reports_dir: Path
    llm: LLMConfig
    nodes: dict[str, NodeEvalConfig]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_dotenv_if_present(root: Path) -> None:
    env_path = root / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config(path: str | Path) -> EvalConfig:
    root = repo_root()
    load_dotenv_if_present(root)
    config_path = _resolve_path(root, path)
    if not config_path.exists():
        raise ConfigError(f"Config file does not exist: {config_path}")
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError("Config root must be an object.")

    llm_data = _required_dict(data, "llm")
    llm = LLMConfig(
        api_key_env=_required_str(llm_data, "api_key_env"),
        base_url=_required_str(llm_data, "base_url").rstrip("/"),
        model=_required_str(llm_data, "model"),
        timeout=int(llm_data.get("timeout", 60)),
        max_retries=int(llm_data.get("max_retries", 2)),
    )

    node_data = _required_dict(data, "nodes")
    nodes: dict[str, NodeEvalConfig] = {}
    for node_name, raw_node in node_data.items():
        if not isinstance(node_name, str) or not node_name:
            raise ConfigError("Node names must be non-empty strings.")
        if not isinstance(raw_node, dict):
            raise ConfigError(f"Node config for {node_name} must be an object.")
        checks = raw_node.get("deterministic_checks", [])
        if not isinstance(checks, list) or not all(isinstance(item, str) for item in checks):
            raise ConfigError(f"deterministic_checks for {node_name} must be a list of strings.")
        nodes[node_name] = NodeEvalConfig(
            node_name=node_name,
            judge_prompt_path=_resolve_path(root, _required_str(raw_node, "judge_prompt")),
            deterministic_checks=list(checks),
        )

    return EvalConfig(
        repo_root=root,
        cases_dir=_resolve_path(root, _required_str(data, "cases_dir")),
        reports_dir=_resolve_path(root, _required_str(data, "reports_dir")),
        llm=llm,
        nodes=nodes,
    )


def _resolve_path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return root / path


def _required_dict(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"Missing required object: {key}")
    return value


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Missing required string: {key}")
    return value
