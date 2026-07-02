from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Collection


EVAL_TRACEABLE_NODES = frozenset({
    "merge_zh_asr_srt",
    "critic_srt",
    "summarize_plot",
    "translate_to_english",
    "reflect_duration_issues",
})


class TraceCollector:
    """Collects LLM call traces and writes eval-framework-compatible case data."""

    def __init__(self, node_allowlist: Collection[str] | None = None) -> None:
        self._records: dict[str, list[dict[str, Any]]] = {}
        self._current_node: str | None = None
        self._allowlist = (
            frozenset(node_allowlist) if node_allowlist is not None else EVAL_TRACEABLE_NODES
        )
        self._lock = threading.Lock()

    def set_current_node(self, name: str | None) -> None:
        self._current_node = name

    def clear_current_node(self) -> None:
        self._current_node = None

    def record(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model_output: str,
        token_usage: dict[str, int],
        attempt: int,
        parent_call_id: str | None,
        duration_ms: int,
        error: str | None,
        timestamp_start: str,
        timestamp_end: str,
    ) -> None:
        node = self._current_node
        if node is None or node not in self._allowlist:
            return
        row = {
            "node_name": node,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "model_output": model_output,
            "token_usage": {
                "prompt_tokens": int(token_usage.get("prompt_tokens", 0)),
                "completion_tokens": int(token_usage.get("completion_tokens", 0)),
                "total_tokens": int(token_usage.get("total_tokens", 0)),
            },
            "attempt": attempt,
            "parent_call_id": parent_call_id,
            "timestamp_start": timestamp_start,
            "timestamp_end": timestamp_end,
            "duration_ms": duration_ms,
            "error": error,
        }
        with self._lock:
            self._records.setdefault(node, []).append(row)

    def records_for(self, node_name: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._records.get(node_name, []))

    def ordered_nodes(self) -> list[str]:
        from src.graph import NODE_ORDER

        with self._lock:
            present = {name for name, rows in self._records.items() if rows}
        return [name for name in NODE_ORDER if name in present]

    def write_case(self, cases_dir: Path, run_id: str, run_error: str | None) -> Path:
        from eval.eval_framework.schema import parse_case, parse_trace_record

        nodes_name = self.ordered_nodes()
        with self._lock:
            snapshot = {name: [dict(row) for row in self._records[name]] for name in nodes_name}

        prompt_tokens = sum(
            row["token_usage"]["prompt_tokens"] for rows in snapshot.values() for row in rows
        )
        completion_tokens = sum(
            row["token_usage"]["completion_tokens"] for rows in snapshot.values() for row in rows
        )
        total_tokens = sum(
            row["token_usage"]["total_tokens"] for rows in snapshot.values() for row in rows
        )
        case_data = {
            "case_name": run_id,
            "total_tokens_usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
            "nodes_name": nodes_name,
            "error": run_error,
        }

        parse_case(case_data, run_id, set(nodes_name))
        for name in nodes_name:
            for index, row in enumerate(snapshot[name], start=1):
                parse_trace_record(row, name, f"{run_id}/traces/{name}_trace.jsonl:{index}")

        case_dir = cases_dir / run_id
        traces_dir = case_dir / "traces"
        traces_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "case.json").write_text(
            json.dumps(case_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for name in nodes_name:
            lines = [json.dumps(row, ensure_ascii=False) for row in snapshot[name]]
            (traces_dir / f"{name}_trace.jsonl").write_text("\n".join(lines), encoding="utf-8")
        return case_dir


_active_collector: TraceCollector | None = None
_active_lock = threading.Lock()


def get_active_collector() -> TraceCollector | None:
    with _active_lock:
        return _active_collector


def set_active_collector(collector: TraceCollector) -> None:
    global _active_collector
    with _active_lock:
        _active_collector = collector


def clear_active_collector() -> None:
    global _active_collector
    with _active_lock:
        _active_collector = None
