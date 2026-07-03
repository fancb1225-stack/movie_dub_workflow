from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eval.eval_framework.reports import render_markdown_summary, write_reports


class ReportsTests(unittest.TestCase):
    def test_writes_json_and_markdown_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = write_reports(_result(), Path(temp_dir), "run_001")

            self.assertTrue((output_dir / "result.json").exists())
            self.assertTrue((output_dir / "summary.md").exists())
            data = json.loads((output_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(data["run_id"], "run_001")
            self.assertIn("translate_to_english", (output_dir / "summary.md").read_text(encoding="utf-8"))

    def test_markdown_includes_failed_low_score_record(self) -> None:
        markdown = render_markdown_summary(_result())

        self.assertIn("record 0 attempt 1", markdown)
        self.assertIn("score=1", markdown)


def _result() -> dict:
    return {
        "run_id": "run_001",
        "summary": {
            "case_count": 1,
            "node_count": 1,
            "record_count": 1,
            "pass_count": 0,
            "fail_count": 1,
            "average_score": 1,
            "total_tokens": 3,
            "total_duration_ms": 5000,
            "failed_records": [],
            "low_score_records": [],
        },
        "cases": [
            {
                "case_name": "movie_001",
                "pass": False,
                "error": None,
                "nodes": [
                    {
                        "node_name": "translate_to_english",
                        "pass": False,
                        "record_count": 1,
                        "average_score": 1,
                        "total_tokens": 3,
                        "records": [
                            {
                                "pass": False,
                                "record_index": 0,
                                "attempt": 1,
                                "judge": {"score": 1, "reason": "Bad."},
                            }
                        ],
                    }
                ],
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
