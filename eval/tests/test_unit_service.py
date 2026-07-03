from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eval.eval_framework.config import EvalConfig, LLMConfig, NodeEvalConfig
from eval.eval_framework.judge import DryRunJudgeClient
from eval.eval_framework.schema import EvalCase, TokenUsage, TraceRecord
from eval.eval_framework.service import evaluate_cases


class ServiceTests(unittest.TestCase):
    def test_evaluates_case_and_aggregates_scores_tokens_and_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prompt = Path(temp_dir) / "prompt.md"
            prompt.write_text("judge", encoding="utf-8")
            config = _config(Path(temp_dir), prompt)
            case = EvalCase(
                case_name="movie_001",
                total_tokens_usage=TokenUsage(2, 4, 6),
                nodes_name=["translate_to_english"],
                error=None,
                traces={
                    "translate_to_english": [
                        _record(_valid_srt(), TokenUsage(1, 2, 3)),
                        _record("", TokenUsage(1, 2, 3), error="LLM failed"),
                    ]
                },
            )

            result = evaluate_cases([case], config, DryRunJudgeClient(), "run_001")

            self.assertEqual(result["summary"]["record_count"], 2)
            self.assertEqual(result["summary"]["pass_count"], 1)
            self.assertEqual(result["summary"]["fail_count"], 1)
            self.assertEqual(result["summary"]["total_tokens"], 6)
            self.assertEqual(result["cases"][0]["nodes"][0]["average_score"], 2)


def _config(root: Path, prompt: Path) -> EvalConfig:
    return EvalConfig(
        repo_root=root,
        cases_dir=root / "cases",
        reports_dir=root / "reports",
        llm=LLMConfig("EVAL_LLM_API_KEY", "https://example.com/v1", "judge", 60, 2),
        nodes={
            "translate_to_english": NodeEvalConfig(
                "translate_to_english",
                prompt,
                ["srt_format"],
            )
        },
    )


def _record(output: str, usage: TokenUsage, error: str | None = None) -> TraceRecord:
    return TraceRecord(
        node_name="translate_to_english",
        system_prompt="system",
        user_prompt="user",
        model_output=output,
        token_usage=usage,
        attempt=1,
        parent_call_id=None,
        timestamp_start="2026-07-01T10:00:00+08:00",
        timestamp_end="2026-07-01T10:00:05+08:00",
        duration_ms=5000,
        error=error,
    )


def _valid_srt() -> str:
    return "1\n00:00:00,000 --> 00:00:01,000\nHello."


if __name__ == "__main__":
    unittest.main()
