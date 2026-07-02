from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from eval.eval_framework.loader import load_case
from src.trace_collector import TraceCollector


class TraceCollectorRecordTests(unittest.TestCase):
    def test_record_stores_row_under_current_node(self) -> None:
        collector = TraceCollector()
        collector.set_current_node("translate_to_english")
        collector.record(
            system_prompt="sys",
            user_prompt="usr",
            model_output="1\n00:00:00,000 --> 00:00:01,000\nHello.",
            token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            attempt=1,
            parent_call_id=None,
            duration_ms=100,
            error=None,
            timestamp_start="2026-07-02T10:00:00+08:00",
            timestamp_end="2026-07-02T10:00:01+08:00",
        )

        rows = collector.records_for("translate_to_english")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["node_name"], "translate_to_english")
        self.assertEqual(row["system_prompt"], "sys")
        self.assertEqual(row["user_prompt"], "usr")
        self.assertEqual(row["model_output"], "1\n00:00:00,000 --> 00:00:01,000\nHello.")
        self.assertEqual(row["token_usage"]["total_tokens"], 15)
        self.assertEqual(row["attempt"], 1)
        self.assertIsNone(row["parent_call_id"])
        self.assertEqual(row["duration_ms"], 100)
        self.assertIsNone(row["error"])

    def test_record_ignored_when_no_current_node(self) -> None:
        collector = TraceCollector()
        collector.record(
            system_prompt="sys",
            user_prompt="usr",
            model_output="out",
            token_usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            attempt=1,
            parent_call_id=None,
            duration_ms=1,
            error=None,
            timestamp_start="2026-07-02T10:00:00+08:00",
            timestamp_end="2026-07-02T10:00:01+08:00",
        )
        self.assertEqual(collector.records_for("translate_to_english"), [])

    def test_record_ignored_for_node_outside_eval_allowlist(self) -> None:
        collector = TraceCollector()
        collector.set_current_node("restitch_merge_cuts")
        collector.record(
            system_prompt="sys",
            user_prompt="usr",
            model_output="out",
            token_usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            attempt=1,
            parent_call_id=None,
            duration_ms=1,
            error=None,
            timestamp_start="2026-07-02T10:00:00+08:00",
            timestamp_end="2026-07-02T10:00:01+08:00",
        )
        self.assertEqual(collector.records_for("restitch_merge_cuts"), [])

    def test_concurrent_records_from_multiple_threads_are_all_kept(self) -> None:
        collector = TraceCollector()
        collector.set_current_node("translate_to_english")

        def worker(index: int) -> None:
            collector.record(
                system_prompt="sys",
                user_prompt=f"usr-{index}",
                model_output=f"out-{index}",
                token_usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                attempt=index + 1,
                parent_call_id="translate_to_english",
                duration_ms=1,
                error=None,
                timestamp_start="2026-07-02T10:00:00+08:00",
                timestamp_end="2026-07-02T10:00:01+08:00",
            )

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(collector.records_for("translate_to_english")), 50)


class TraceCollectorWriteCaseTests(unittest.TestCase):
    def test_write_case_produces_case_loadable_by_eval_loader(self) -> None:
        collector = TraceCollector()
        collector.set_current_node("translate_to_english")
        collector.record(
            system_prompt="sys-t",
            user_prompt="usr-t",
            model_output="1\n00:00:00,000 --> 00:00:01,000\nHello.",
            token_usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            attempt=1,
            parent_call_id="translate_to_english",
            duration_ms=500,
            error=None,
            timestamp_start="2026-07-02T10:00:00+08:00",
            timestamp_end="2026-07-02T10:00:01+08:00",
        )
        collector.set_current_node("summarize_plot")
        collector.record(
            system_prompt="sys-s",
            user_prompt="usr-s",
            model_output="A plot summary.",
            token_usage={"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300},
            attempt=1,
            parent_call_id=None,
            duration_ms=400,
            error=None,
            timestamp_start="2026-07-02T10:01:00+08:00",
            timestamp_end="2026-07-02T10:01:01+08:00",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            cases_dir = Path(temp_dir) / "cases"
            case_dir = collector.write_case(cases_dir, "movie_001", run_error=None)

            case = load_case(case_dir, {"translate_to_english", "summarize_plot"})

        self.assertEqual(case.case_name, "movie_001")
        self.assertEqual(case.nodes_name, ["summarize_plot", "translate_to_english"])
        self.assertEqual(case.total_tokens_usage.total_tokens, 450)
        self.assertEqual(case.total_tokens_usage.prompt_tokens, 300)
        self.assertEqual(case.total_tokens_usage.completion_tokens, 150)
        self.assertIsNone(case.error)
        self.assertEqual(len(case.traces["translate_to_english"]), 1)
        self.assertEqual(len(case.traces["summarize_plot"]), 1)
        self.assertEqual(
            case.traces["translate_to_english"][0].parent_call_id,
            "translate_to_english",
        )
        self.assertIsNone(case.traces["summarize_plot"][0].parent_call_id)

    def test_write_case_records_run_error_in_case_json(self) -> None:
        collector = TraceCollector()
        collector.set_current_node("summarize_plot")
        collector.record(
            system_prompt="sys",
            user_prompt="usr",
            model_output="out",
            token_usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            attempt=1,
            parent_call_id=None,
            duration_ms=10,
            error=None,
            timestamp_start="2026-07-02T10:00:00+08:00",
            timestamp_end="2026-07-02T10:00:01+08:00",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            cases_dir = Path(temp_dir) / "cases"
            case_dir = collector.write_case(cases_dir, "movie_002", run_error="pipeline crashed")

            case_json = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))

        self.assertEqual(case_json["error"], "pipeline crashed")

    def test_write_case_skips_nodes_without_records(self) -> None:
        collector = TraceCollector()
        collector.set_current_node("critic_srt")
        collector.record(
            system_prompt="sys",
            user_prompt="usr",
            model_output="out",
            token_usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            attempt=1,
            parent_call_id=None,
            duration_ms=10,
            error=None,
            timestamp_start="2026-07-02T10:00:00+08:00",
            timestamp_end="2026-07-02T10:00:01+08:00",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            cases_dir = Path(temp_dir) / "cases"
            case_dir = collector.write_case(cases_dir, "movie_003", run_error=None)

            case = load_case(case_dir, {"critic_srt"})

        self.assertEqual(case.nodes_name, ["critic_srt"])


if __name__ == "__main__":
    unittest.main()
