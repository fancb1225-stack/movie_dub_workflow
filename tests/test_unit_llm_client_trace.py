from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from eval.eval_framework.loader import load_case
from src.graph import with_trace
from src.llm_client import LLMClient, LLMSettings
from src.state import WorkflowState
from src.trace_collector import (
    TraceCollector,
    clear_active_collector,
    get_active_collector,
    set_active_collector,
)


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - stdlib signature
        length = int(self.headers.get("Content-Length", 0))
        self.server.received_requests.append(self.rfile.read(length).decode("utf-8"))
        status, body = self.server.response
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *args: Any) -> None:
        pass


class MockLLMServer:
    def __init__(self, response_body: dict, status: int = 200) -> None:
        self.received_requests: list[str] = []
        httpd = HTTPServer(("127.0.0.1", 0), _Handler)
        httpd.response = (status, json.dumps(response_body))
        httpd.received_requests = self.received_requests
        self.httpd = httpd
        self.port = httpd.server_address[1]
        self.thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def _client(port: int, max_retries: int = 0) -> LLMClient:
    return LLMClient(
        LLMSettings(
            api_key="test-key",
            base_url=f"http://127.0.0.1:{port}/v1",
            model="test-model",
            timeout=5,
            max_retries=max_retries,
        )
    )


class LLMClientTraceTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_active_collector()

    def tearDown(self) -> None:
        clear_active_collector()

    def test_complete_records_token_usage_and_record_when_collector_active(self) -> None:
        server = MockLLMServer(
            {
                "choices": [{"message": {"content": "hello"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        )
        try:
            collector = TraceCollector()
            collector.set_current_node("summarize_plot")
            set_active_collector(collector)

            content = _client(server.port).complete(
                "sys", "usr", "fb", attempt=1, parent_call_id=None
            )

            self.assertEqual(content, "hello")
            rows = collector.records_for("summarize_plot")
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["system_prompt"], "sys")
            self.assertEqual(row["user_prompt"], "usr")
            self.assertEqual(row["model_output"], "hello")
            self.assertEqual(row["token_usage"]["prompt_tokens"], 10)
            self.assertEqual(row["token_usage"]["completion_tokens"], 5)
            self.assertEqual(row["token_usage"]["total_tokens"], 15)
            self.assertEqual(row["attempt"], 1)
            self.assertIsNone(row["parent_call_id"])
            self.assertIsNone(row["error"])
            self.assertGreaterEqual(row["duration_ms"], 0)
        finally:
            server.stop()

    def test_complete_records_zero_usage_when_response_lacks_usage(self) -> None:
        server = MockLLMServer({"choices": [{"message": {"content": "hi"}}]})
        try:
            collector = TraceCollector()
            collector.set_current_node("critic_srt")
            set_active_collector(collector)

            _client(server.port).complete("sys", "usr", "fb")

            row = collector.records_for("critic_srt")[0]
            self.assertEqual(row["token_usage"]["prompt_tokens"], 0)
            self.assertEqual(row["token_usage"]["completion_tokens"], 0)
            self.assertEqual(row["token_usage"]["total_tokens"], 0)
            self.assertEqual(row["model_output"], "hi")
        finally:
            server.stop()

    def test_complete_records_error_and_reraises_when_request_fails(self) -> None:
        server = MockLLMServer({"error": "boom"}, status=500)
        try:
            collector = TraceCollector()
            collector.set_current_node("translate_to_english")
            set_active_collector(collector)

            with self.assertRaises(RuntimeError):
                _client(server.port).complete(
                    "sys", "usr", "fb", attempt=2, parent_call_id="translate_to_english"
                )

            rows = collector.records_for("translate_to_english")
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["model_output"], "")
            self.assertEqual(row["attempt"], 2)
            self.assertEqual(row["parent_call_id"], "translate_to_english")
            self.assertIsNotNone(row["error"])
            self.assertIn("500", row["error"])
        finally:
            server.stop()

    def test_complete_does_not_record_when_no_active_collector(self) -> None:
        server = MockLLMServer(
            {
                "choices": [{"message": {"content": "hello"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        )
        try:
            self.assertIsNone(get_active_collector())

            content = _client(server.port).complete("sys", "usr", "fb")

            self.assertEqual(content, "hello")
        finally:
            server.stop()

    def test_complete_does_not_record_when_llm_disabled(self) -> None:
        collector = TraceCollector()
        collector.set_current_node("summarize_plot")
        set_active_collector(collector)

        disabled = LLMClient(
            LLMSettings(api_key="", base_url="", model="mock", timeout=1, max_retries=0)
        )
        content = disabled.complete("sys", "usr", "fallback-text")

        self.assertEqual(content, "fallback-text")
        self.assertEqual(collector.records_for("summarize_plot"), [])


class TraceIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_active_collector()

    def tearDown(self) -> None:
        clear_active_collector()

    def test_with_trace_records_under_node_and_writes_loadable_case(self) -> None:
        server = MockLLMServer(
            {
                "choices": [{"message": {"content": "A plot summary."}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
            }
        )
        try:
            collector = TraceCollector()
            set_active_collector(collector)
            client = _client(server.port)

            def fake_summarize(state: WorkflowState) -> WorkflowState:
                client.complete("sys", "usr", "fb", attempt=1, parent_call_id=None)
                return state

            with_trace("summarize_plot", fake_summarize)({"config": {}})

            with tempfile.TemporaryDirectory() as temp_dir:
                cases_dir = Path(temp_dir) / "cases"
                case_dir = collector.write_case(cases_dir, "movie_int", run_error=None)

                case = load_case(case_dir, {"summarize_plot"})

            self.assertEqual(case.case_name, "movie_int")
            self.assertEqual(case.nodes_name, ["summarize_plot"])
            self.assertEqual(case.total_tokens_usage.total_tokens, 20)
            self.assertEqual(len(case.traces["summarize_plot"]), 1)
            self.assertEqual(
                case.traces["summarize_plot"][0].model_output, "A plot summary."
            )
            self.assertIsNone(case.traces["summarize_plot"][0].parent_call_id)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
