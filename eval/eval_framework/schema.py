from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


class SchemaError(ValueError):
    """Raised when case or trace data violates the strict schema."""


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    def as_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class TraceRecord:
    node_name: str
    system_prompt: str
    user_prompt: str
    model_output: str
    token_usage: TokenUsage
    attempt: int
    parent_call_id: str | None
    timestamp_start: str
    timestamp_end: str
    duration_ms: int
    error: str | None


@dataclass(frozen=True)
class EvalCase:
    case_name: str
    total_tokens_usage: TokenUsage
    nodes_name: list[str]
    error: str | None
    traces: dict[str, list[TraceRecord]]


def parse_case(data: Any, case_dir_name: str, configured_nodes: set[str]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise SchemaError(f"{case_dir_name}/case.json must be an object.")
    allowed = {"case_name", "total_tokens_usage", "nodes_name", "error"}
    _reject_extra_keys(data, allowed, f"{case_dir_name}/case.json")
    case_name = _required_str(data, "case_name", f"{case_dir_name}/case.json")
    if case_name != case_dir_name:
        raise SchemaError(f"case_name '{case_name}' must match directory '{case_dir_name}'.")
    nodes_name = data.get("nodes_name")
    if not isinstance(nodes_name, list) or not nodes_name:
        raise SchemaError(f"{case_name}/case.json nodes_name must be a non-empty array.")
    for node_name in nodes_name:
        if not isinstance(node_name, str) or not node_name:
            raise SchemaError(f"{case_name}/case.json nodes_name entries must be non-empty strings.")
        if node_name not in configured_nodes:
            raise SchemaError(f"{case_name}/case.json node '{node_name}' is not configured.")
    error = _nullable_str(data, "error", f"{case_name}/case.json")
    return {
        "case_name": case_name,
        "total_tokens_usage": parse_token_usage(data.get("total_tokens_usage"), f"{case_name}/case.json total_tokens_usage"),
        "nodes_name": list(nodes_name),
        "error": error,
    }


def parse_trace_record(data: Any, expected_node_name: str, location: str) -> TraceRecord:
    if not isinstance(data, dict):
        raise SchemaError(f"{location} must be an object.")
    allowed = {
        "node_name",
        "system_prompt",
        "user_prompt",
        "model_output",
        "token_usage",
        "attempt",
        "parent_call_id",
        "timestamp_start",
        "timestamp_end",
        "duration_ms",
        "error",
    }
    _reject_extra_keys(data, allowed, location)
    node_name = _required_str(data, "node_name", location)
    if node_name != expected_node_name:
        raise SchemaError(f"{location} node_name '{node_name}' must match file node '{expected_node_name}'.")
    error = _nullable_str(data, "error", location)
    model_output = _required_str_allow_empty(data, "model_output", location)
    if error is None and not model_output:
        raise SchemaError(f"{location} model_output must be non-empty when error is null.")
    timestamp_start = _required_str(data, "timestamp_start", location)
    timestamp_end = _required_str(data, "timestamp_end", location)
    _parse_iso(timestamp_start, f"{location} timestamp_start")
    _parse_iso(timestamp_end, f"{location} timestamp_end")
    return TraceRecord(
        node_name=node_name,
        system_prompt=_required_str(data, "system_prompt", location),
        user_prompt=_required_str(data, "user_prompt", location),
        model_output=model_output,
        token_usage=parse_token_usage(data.get("token_usage"), f"{location} token_usage"),
        attempt=_required_int_min(data, "attempt", 1, location),
        parent_call_id=_nullable_str(data, "parent_call_id", location),
        timestamp_start=timestamp_start,
        timestamp_end=timestamp_end,
        duration_ms=_required_int_min(data, "duration_ms", 0, location),
        error=error,
    )


def parse_token_usage(data: Any, location: str) -> TokenUsage:
    if not isinstance(data, dict):
        raise SchemaError(f"{location} must be an object.")
    allowed = {"prompt_tokens", "completion_tokens", "total_tokens"}
    _reject_extra_keys(data, allowed, location)
    usage = TokenUsage(
        prompt_tokens=_required_int_min(data, "prompt_tokens", 0, location),
        completion_tokens=_required_int_min(data, "completion_tokens", 0, location),
        total_tokens=_required_int_min(data, "total_tokens", 0, location),
    )
    if usage.total_tokens != usage.prompt_tokens + usage.completion_tokens:
        raise SchemaError(f"{location} total_tokens must equal prompt_tokens + completion_tokens.")
    return usage


def sum_token_usage(records: list[TraceRecord]) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=sum(record.token_usage.prompt_tokens for record in records),
        completion_tokens=sum(record.token_usage.completion_tokens for record in records),
        total_tokens=sum(record.token_usage.total_tokens for record in records),
    )


def _parse_iso(value: str, location: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise SchemaError(f"{location} must be ISO-8601.") from exc


def _reject_extra_keys(data: dict[str, Any], allowed: set[str], location: str) -> None:
    extra = sorted(set(data) - allowed)
    if extra:
        raise SchemaError(f"{location} contains unsupported field(s): {', '.join(extra)}")


def _required_str(data: dict[str, Any], key: str, location: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise SchemaError(f"{location} missing required non-empty string: {key}")
    return value


def _required_str_allow_empty(data: dict[str, Any], key: str, location: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise SchemaError(f"{location} missing required string: {key}")
    return value


def _nullable_str(data: dict[str, Any], key: str, location: str) -> str | None:
    if key not in data:
        raise SchemaError(f"{location} missing required nullable string: {key}")
    value = data[key]
    if value is not None and not isinstance(value, str):
        raise SchemaError(f"{location} {key} must be string or null.")
    return value


def _required_int_min(data: dict[str, Any], key: str, minimum: int, location: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise SchemaError(f"{location} {key} must be an integer >= {minimum}.")
    return value
