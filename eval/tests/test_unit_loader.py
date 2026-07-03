from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eval.eval_framework.config import EvalConfig, LLMConfig, NodeEvalConfig
from eval.eval_framework.loader import load_case
from eval.eval_framework.schema import SchemaError


class LoaderTests(unittest.TestCase):
    def test_loads_valid_case_with_traces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            case_dir = _write_case(Path(temp_dir), "movie_001")

            case = load_case(case_dir, {"translate_to_english"})

            self.assertEqual(case.case_name, "movie_001")
            self.assertEqual(len(case.traces["translate_to_english"]), 1)

    def test_case_name_must_match_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            case_dir = _write_case(Path(temp_dir), "movie_001", case_name="other")

            with self.assertRaisesRegex(SchemaError, "must match directory"):
                load_case(case_dir, {"translate_to_english"})

    def test_requires_trace_file_for_each_node(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            case_dir = _write_case(Path(temp_dir), "movie_001")
            (case_dir / "traces" / "translate_to_english_trace.jsonl").unlink()

            with self.assertRaisesRegex(SchemaError, "Missing trace file"):
                load_case(case_dir, {"translate_to_english"})

    def test_rejects_trace_node_name_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            case_dir = _write_case(Path(temp_dir), "movie_001")
            _write_jsonl(case_dir / "traces" / "translate_to_english_trace.jsonl", [{**_trace_row(), "node_name": "critic_srt"}])

            with self.assertRaisesRegex(SchemaError, "must match file node"):
                load_case(case_dir, {"translate_to_english"})

    def test_rejects_case_token_total_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            case_dir = _write_case(Path(temp_dir), "movie_001", total_tokens=4)

            with self.assertRaisesRegex(SchemaError, "trace token sum"):
                load_case(case_dir, {"translate_to_english"})


def _write_case(root: Path, dirname: str, case_name: str | None = None, total_tokens: int = 3) -> Path:
    case_dir = root / dirname
    traces_dir = case_dir / "traces"
    traces_dir.mkdir(parents=True)
    (case_dir / "case.json").write_text(
        json.dumps(
            {
                "case_name": case_name or dirname,
                "total_tokens_usage": {
                    "prompt_tokens": max(0, total_tokens - 2),
                    "completion_tokens": 2,
                    "total_tokens": total_tokens,
                },
                "nodes_name": ["translate_to_english"],
                "error": None,
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(traces_dir / "translate_to_english_trace.jsonl", [_trace_row()])
    return case_dir


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def _trace_row() -> dict:
    return {
        "node_name": "translate_to_english",
        "system_prompt": "system",
        "user_prompt": "user",
        "model_output": "output",
        "token_usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        "attempt": 1,
        "parent_call_id": "call_parent_001",
        "timestamp_start": "2026-07-01T10:00:00+08:00",
        "timestamp_end": "2026-07-01T10:00:05+08:00",
        "duration_ms": 5000,
        "error": None,
    }


if __name__ == "__main__":
    unittest.main()
