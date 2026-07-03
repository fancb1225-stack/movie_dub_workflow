from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eval.eval_framework.config import NodeEvalConfig
from eval.eval_framework.judge import build_judge_user_prompt, evaluate_with_judge, parse_judge_output
from eval.eval_framework.schema import TokenUsage, TraceRecord


class JudgeTests(unittest.TestCase):
    def test_build_judge_user_prompt_uses_trace_fields(self) -> None:
        prompt = build_judge_user_prompt(_record())

        self.assertIn('"system_prompt": "system"', prompt)
        self.assertIn('"user_prompt": "user"', prompt)
        self.assertIn('"model_output": "output"', prompt)
        self.assertIn('"duration_ms": 5000', prompt)

    def test_parse_valid_judge_json(self) -> None:
        result = parse_judge_output('{"pass": true, "score": 4, "reason": "Good."}', "system", "user")

        self.assertTrue(result.passed)
        self.assertEqual(result.score, 4)
        self.assertEqual(result.reason, "Good.")

    def test_invalid_judge_json_falls_back_to_failure(self) -> None:
        result = parse_judge_output("not json", "system", "user")

        self.assertFalse(result.passed)
        self.assertEqual(result.score, 1)
        self.assertIn("Invalid judge output", result.reason)

    def test_error_record_skips_client_call(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            node = _node_config(Path(temp_dir) / "prompt.md")
            node.judge_prompt_path.write_text("judge system", encoding="utf-8")
            client = FakeClient('{"pass": true, "score": 5, "reason": "Good."}')

            result = evaluate_with_judge(_record(error="LLM failed"), node, client)

            self.assertFalse(result.passed)
            self.assertEqual(result.score, 1)
            self.assertEqual(client.calls, 0)

    def test_valid_client_output_is_returned(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            node = _node_config(Path(temp_dir) / "prompt.md")
            node.judge_prompt_path.write_text("judge system", encoding="utf-8")
            client = FakeClient(json.dumps({"pass": True, "score": 5, "reason": "Excellent."}))

            result = evaluate_with_judge(_record(), node, client)

            self.assertTrue(result.passed)
            self.assertEqual(result.score, 5)
            self.assertEqual(client.calls, 1)
            self.assertEqual(result.system_prompt, "judge system")


class FakeClient:
    def __init__(self, response: str):
        self.response = response
        self.calls = 0

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        return self.response


def _record(error: str | None = None) -> TraceRecord:
    return TraceRecord(
        node_name="translate_to_english",
        system_prompt="system",
        user_prompt="user",
        model_output="" if error else "output",
        token_usage=TokenUsage(1, 2, 3),
        attempt=1,
        parent_call_id=None,
        timestamp_start="2026-07-01T10:00:00+08:00",
        timestamp_end="2026-07-01T10:00:05+08:00",
        duration_ms=5000,
        error=error,
    )


def _node_config(path: Path) -> NodeEvalConfig:
    return NodeEvalConfig("translate_to_english", path, [])


if __name__ == "__main__":
    unittest.main()
