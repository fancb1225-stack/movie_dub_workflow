from __future__ import annotations

import unittest

from eval.eval_framework.schema import SchemaError, parse_trace_record


class SchemaTests(unittest.TestCase):
    def test_valid_trace_record_parses(self) -> None:
        record = parse_trace_record(_trace_row(), "translate_to_english", "trace:1")

        self.assertEqual(record.node_name, "translate_to_english")
        self.assertEqual(record.token_usage.total_tokens, 3)

    def test_rejects_token_total_mismatch(self) -> None:
        row = _trace_row()
        row["token_usage"]["total_tokens"] = 99

        with self.assertRaisesRegex(SchemaError, "total_tokens"):
            parse_trace_record(row, "translate_to_english", "trace:1")

    def test_rejects_invalid_timestamp(self) -> None:
        row = _trace_row()
        row["timestamp_start"] = "not-a-date"

        with self.assertRaisesRegex(SchemaError, "ISO-8601"):
            parse_trace_record(row, "translate_to_english", "trace:1")

    def test_allows_empty_output_only_when_error_is_present(self) -> None:
        row = _trace_row()
        row["model_output"] = ""
        with self.assertRaisesRegex(SchemaError, "model_output"):
            parse_trace_record(row, "translate_to_english", "trace:1")

        row["error"] = "LLM failed"
        record = parse_trace_record(row, "translate_to_english", "trace:1")
        self.assertEqual(record.model_output, "")


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
