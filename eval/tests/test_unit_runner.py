from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eval.eval_framework.runner import main


class RunnerTests(unittest.TestCase):
    def test_dry_run_cli_writes_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prompt = root / "prompt.md"
            prompt.write_text("judge", encoding="utf-8")
            cases_dir = root / "cases"
            reports_dir = root / "reports"
            _write_case(cases_dir)
            config = root / "config.yaml"
            config.write_text(
                "\n".join(
                    [
                        f"cases_dir: {cases_dir.as_posix()}",
                        f"reports_dir: {reports_dir.as_posix()}",
                        "llm:",
                        "  api_key_env: EVAL_LLM_API_KEY",
                        "  base_url: https://example.com/v1",
                        "  model: judge",
                        "nodes:",
                        "  translate_to_english:",
                        f"    judge_prompt: {prompt.as_posix()}",
                        '    deterministic_checks: ["srt_format"]',
                    ]
                ),
                encoding="utf-8",
            )

            exit_code = main(["--config", str(config), "--run-id", "dry_run", "--dry-run"])

            self.assertEqual(exit_code, 0)
            self.assertTrue((reports_dir / "dry_run" / "result.json").exists())
            result = json.loads((reports_dir / "dry_run" / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["summary"]["pass_count"], 1)


def _write_case(cases_dir: Path) -> None:
    case_dir = cases_dir / "movie_001"
    traces_dir = case_dir / "traces"
    traces_dir.mkdir(parents=True)
    (case_dir / "case.json").write_text(
        json.dumps(
            {
                "case_name": "movie_001",
                "total_tokens_usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
                "nodes_name": ["translate_to_english"],
                "error": None,
            }
        ),
        encoding="utf-8",
    )
    row = {
        "node_name": "translate_to_english",
        "system_prompt": "system",
        "user_prompt": "user",
        "model_output": "1\n00:00:00,000 --> 00:00:01,000\nHello.",
        "token_usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        "attempt": 1,
        "parent_call_id": "call_parent_001",
        "timestamp_start": "2026-07-01T10:00:00+08:00",
        "timestamp_end": "2026-07-01T10:00:05+08:00",
        "duration_ms": 5000,
        "error": None,
    }
    (traces_dir / "translate_to_english_trace.jsonl").write_text(json.dumps(row), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
