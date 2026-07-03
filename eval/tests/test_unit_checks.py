from __future__ import annotations

import unittest
from pathlib import Path

from eval.eval_framework.checks import check_srt_format, run_deterministic_checks
from eval.eval_framework.config import NodeEvalConfig
from eval.eval_framework.schema import TokenUsage, TraceRecord


class ChecksTests(unittest.TestCase):
    def test_valid_srt_passes(self) -> None:
        result = check_srt_format(_valid_srt())

        self.assertTrue(result["pass"])
        self.assertEqual(result["reason"], "Valid SRT format.")

    def test_rejects_non_sequential_index(self) -> None:
        result = check_srt_format(_valid_srt().replace("\n2\n", "\n3\n"))

        self.assertFalse(result["pass"])
        self.assertIn("index", result["reason"])

    def test_rejects_invalid_timestamp(self) -> None:
        result = check_srt_format(_valid_srt().replace("00:00:02,000 --> 00:00:03,000", "bad timestamp"))

        self.assertFalse(result["pass"])
        self.assertIn("timestamp", result["reason"])

    def test_rejects_non_positive_duration(self) -> None:
        result = check_srt_format(_valid_srt().replace("00:00:01,000", "00:00:00,000"))

        self.assertFalse(result["pass"])
        self.assertIn("before end", result["reason"])

    def test_rejects_overlap(self) -> None:
        result = check_srt_format(_valid_srt().replace("00:00:02,000 -->", "00:00:00,500 -->"))

        self.assertFalse(result["pass"])
        self.assertIn("overlaps", result["reason"])

    def test_no_checks_passes_with_empty_list(self) -> None:
        result = run_deterministic_checks(_record(_valid_srt()), _node_config([]))

        self.assertTrue(result["pass"])
        self.assertEqual(result["checks"], [])

    def test_record_error_fails_without_srt_parse(self) -> None:
        result = run_deterministic_checks(_record("", error="LLM failed"), _node_config(["srt_format"]))

        self.assertFalse(result["pass"])
        self.assertEqual(result["checks"][0]["name"], "trace_error")


def _valid_srt() -> str:
    return (
        "1\n"
        "00:00:00,000 --> 00:00:01,000\n"
        "Hello.\n\n"
        "2\n"
        "00:00:02,000 --> 00:00:03,000\n"
        "World."
    )


def _record(output: str, error: str | None = None) -> TraceRecord:
    return TraceRecord(
        node_name="translate_to_english",
        system_prompt="system",
        user_prompt="user",
        model_output=output,
        token_usage=TokenUsage(1, 2, 3),
        attempt=1,
        parent_call_id=None,
        timestamp_start="2026-07-01T10:00:00+08:00",
        timestamp_end="2026-07-01T10:00:05+08:00",
        duration_ms=5000,
        error=error,
    )


def _node_config(checks: list[str]) -> NodeEvalConfig:
    return NodeEvalConfig(
        node_name="translate_to_english",
        judge_prompt_path=Path("prompt.md"),
        deterministic_checks=checks,
    )


if __name__ == "__main__":
    unittest.main()
