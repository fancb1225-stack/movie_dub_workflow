from __future__ import annotations

from statistics import mean

from eval.eval_framework.checks import run_deterministic_checks
from eval.eval_framework.config import EvalConfig
from eval.eval_framework.judge import JudgeClient, evaluate_with_judge
from eval.eval_framework.schema import EvalCase, TraceRecord


LOW_SCORE_THRESHOLD = 2


def evaluate_cases(cases: list[EvalCase], config: EvalConfig, judge_client: JudgeClient, run_id: str) -> dict:
    case_results = [evaluate_case(case, config, judge_client) for case in cases]
    records = [
        record_result
        for case_result in case_results
        for node_result in case_result["nodes"]
        for record_result in node_result["records"]
    ]
    scores = [record["judge"]["score"] for record in records]
    passed = [record for record in records if record["pass"]]
    failed = [record for record in records if not record["pass"]]
    total_tokens = sum(case.total_tokens_usage.total_tokens for case in cases)
    total_duration = sum(record["duration_ms"] for record in records)
    return {
        "run_id": run_id,
        "summary": {
            "case_count": len(cases),
            "node_count": sum(len(case.nodes_name) for case in cases),
            "record_count": len(records),
            "pass_count": len(passed),
            "fail_count": len(failed),
            "average_score": round(mean(scores), 2) if scores else 0,
            "total_tokens": total_tokens,
            "total_duration_ms": total_duration,
            "failed_records": _record_refs(failed),
            "low_score_records": _record_refs(
                [record for record in records if record["judge"]["score"] <= LOW_SCORE_THRESHOLD]
            ),
        },
        "cases": case_results,
    }


def evaluate_case(case: EvalCase, config: EvalConfig, judge_client: JudgeClient) -> dict:
    node_results = []
    for node_name in case.nodes_name:
        node_config = config.nodes[node_name]
        records = case.traces[node_name]
        record_results = [
            evaluate_record(case.case_name, node_name, index, record, node_config, judge_client)
            for index, record in enumerate(records)
        ]
        node_results.append(_node_summary(node_name, record_results))
    case_pass = case.error is None and all(node["pass"] for node in node_results)
    return {
        "case_name": case.case_name,
        "pass": case_pass,
        "error": case.error,
        "total_tokens_usage": case.total_tokens_usage.as_dict(),
        "nodes": node_results,
    }


def evaluate_record(case_name: str, node_name: str, index: int, record: TraceRecord, node_config, judge_client: JudgeClient) -> dict:
    deterministic = run_deterministic_checks(record, node_config)
    judge = evaluate_with_judge(record, node_config, judge_client)
    record_pass = deterministic["pass"] and judge.passed
    return {
        "case_name": case_name,
        "node_name": node_name,
        "record_index": index,
        "attempt": record.attempt,
        "parent_call_id": record.parent_call_id,
        "duration_ms": record.duration_ms,
        "token_usage": record.token_usage.as_dict(),
        "error": record.error,
        "pass": record_pass,
        "deterministic_checks": deterministic,
        "judge": judge.as_dict(),
    }


def _node_summary(node_name: str, records: list[dict]) -> dict:
    scores = [record["judge"]["score"] for record in records]
    return {
        "node_name": node_name,
        "pass": all(record["pass"] for record in records),
        "record_count": len(records),
        "pass_count": sum(1 for record in records if record["pass"]),
        "fail_count": sum(1 for record in records if not record["pass"]),
        "average_score": round(mean(scores), 2) if scores else 0,
        "total_tokens": sum(record["token_usage"]["total_tokens"] for record in records),
        "total_duration_ms": sum(record["duration_ms"] for record in records),
        "records": records,
    }


def _record_refs(records: list[dict]) -> list[dict]:
    return [
        {
            "case_name": record["case_name"],
            "node_name": record["node_name"],
            "record_index": record["record_index"],
            "attempt": record["attempt"],
            "score": record["judge"]["score"],
            "reason": record["judge"]["reason"],
        }
        for record in records
    ]
