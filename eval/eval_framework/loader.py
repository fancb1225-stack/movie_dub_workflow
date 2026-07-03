from __future__ import annotations

import json
from pathlib import Path

from eval.eval_framework.config import EvalConfig
from eval.eval_framework.schema import (
    EvalCase,
    SchemaError,
    TokenUsage,
    TraceRecord,
    parse_case,
    parse_trace_record,
    sum_token_usage,
)


def load_cases(config: EvalConfig) -> list[EvalCase]:
    if not config.cases_dir.exists():
        raise SchemaError(f"Cases directory does not exist: {config.cases_dir}")
    cases: list[EvalCase] = []
    for case_dir in sorted(path for path in config.cases_dir.iterdir() if path.is_dir()):
        cases.append(load_case(case_dir, set(config.nodes)))
    if not cases:
        raise SchemaError(f"No case directories found under {config.cases_dir}")
    return cases


def load_case(case_dir: Path, configured_nodes: set[str]) -> EvalCase:
    case_file = case_dir / "case.json"
    traces_dir = case_dir / "traces"
    if not case_file.exists():
        raise SchemaError(f"Missing case file: {case_file}")
    if not traces_dir.is_dir():
        raise SchemaError(f"Missing traces directory: {traces_dir}")
    case_data = parse_case(_read_json(case_file), case_dir.name, configured_nodes)
    traces: dict[str, list[TraceRecord]] = {}
    all_records: list[TraceRecord] = []
    for node_name in case_data["nodes_name"]:
        trace_file = traces_dir / f"{node_name}_trace.jsonl"
        if not trace_file.exists():
            raise SchemaError(f"Missing trace file for node '{node_name}': {trace_file}")
        records = _read_trace_jsonl(trace_file, node_name)
        traces[node_name] = records
        all_records.extend(records)
    actual = sum_token_usage(all_records)
    expected: TokenUsage = case_data["total_tokens_usage"]
    if actual != expected:
        raise SchemaError(
            f"{case_dir.name}/case.json total_tokens_usage must equal trace token sum "
            f"(expected {expected.as_dict()}, got {actual.as_dict()})."
        )
    return EvalCase(
        case_name=case_data["case_name"],
        total_tokens_usage=expected,
        nodes_name=case_data["nodes_name"],
        error=case_data["error"],
        traces=traces,
    )


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SchemaError(f"Invalid JSON in {path}: {exc}") from exc


def _read_trace_jsonl(path: Path, node_name: str) -> list[TraceRecord]:
    records: list[TraceRecord] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SchemaError(f"Invalid JSON in {path}:{line_number}: {exc}") from exc
        records.append(parse_trace_record(data, node_name, f"{path}:{line_number}"))
    if not records:
        raise SchemaError(f"Trace file must contain at least one record: {path}")
    return records
