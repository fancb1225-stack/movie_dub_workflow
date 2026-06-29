from __future__ import annotations

import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.tools.tts_tools import (
    FatalTtsError,
    _generate_edge_tts,
    _generate_minimax_tts,
    _minimax_request_json,
    generate_tts_segments,
)
from src.nodes.tts_duration_node import tts_generate_and_detect


class TtsToolsTests(unittest.TestCase):
    def test_edge_tts_uses_default_rate_1_3(self) -> None:
        calls = []

        class FakeCommunicate:
            def __init__(self, text: str, voice: str, rate: str):
                calls.append({"text": text, "voice": voice, "rate": rate})

            async def save(self, output_path: str) -> None:
                Path(output_path).write_bytes(b"mp3")

        with tempfile.TemporaryDirectory() as tmp:
            with patch("edge_tts.Communicate", FakeCommunicate):
                _generate_edge_tts(
                    "hello",
                    Path(tmp) / "segment.mp3",
                    {"voice": "en-US-AriaNeural"},
                )

        self.assertEqual(calls[0]["rate"], "+30%")

    def test_edge_tts_uses_configured_rate(self) -> None:
        calls = []

        class FakeCommunicate:
            def __init__(self, text: str, voice: str, rate: str):
                calls.append({"text": text, "voice": voice, "rate": rate})

            async def save(self, output_path: str) -> None:
                Path(output_path).write_bytes(b"mp3")

        with tempfile.TemporaryDirectory() as tmp:
            with patch("edge_tts.Communicate", FakeCommunicate):
                _generate_edge_tts(
                    "hello",
                    Path(tmp) / "segment.mp3",
                    {"voice": "en-US-AriaNeural", "rate": "+10%"},
                )

        self.assertEqual(calls[0]["rate"], "+10%")
    def test_generate_segments_preserves_speaker_and_profile_metadata(self) -> None:
        cues = [
            {
                "index": 1,
                "start": "00:00:00,000",
                "end": "00:00:01,000",
                "start_ms": 0,
                "end_ms": 1000,
                "text": "hello",
                "speaker_id": "speaker_1",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            segments = generate_tts_segments(
                cues,
                Path(tmp),
                {
                    "tts": {
                        "provider": "mock",
                        "speaker_profiles": {"speaker_1": {"voice_id": "voice-a", "speed": 1.2}},
                        "sample_rate": 24000,
                    }
                },
            )

        self.assertTrue(segments[0]["success"])
        self.assertEqual(segments[0]["speaker_id"], "speaker_1")
        self.assertEqual(segments[0]["voice_id"], "voice-a")
        self.assertEqual(segments[0]["speed"], 1.2)
    def test_minimax_uses_llm_api_key_tts_model_and_token_base_url(self) -> None:
        calls = []

        def fake_request(method, url, api_key, payload, timeout, max_retries):
            calls.append({"method": method, "url": url, "api_key": api_key, "payload": payload})
            if method == "POST":
                return {"task_id": "task-1"}
            return {"status": "SUCCESS", "result_url": "https://example.test/audio.mp3"}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"mp3"

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"LLM_API_KEY": "key-1", "TTS_MODEL": "speech-01"}, clear=False), \
                patch("src.tools.tts_tools._minimax_request_json", side_effect=fake_request), \
                patch("urllib.request.urlopen", return_value=FakeResponse()):
                _generate_minimax_tts(
                    "hello",
                    Path(tmp) / "segment.mp3",
                    {
                        "minimax": {
                            "base_url": "https://token.cxtfun.com",
                            "create_path": "/v1/minimax/tts/async",
                            "query_path": "/v1/minimax/tts/tasks/{task_id}",
                            "task_timeout": 1,
                        },
                        "sample_rate": 24000,
                    },
                    {"voice_id": "voice-a", "speed": 1.1},
                )

        self.assertEqual(calls[0]["api_key"], "key-1")
        self.assertEqual(calls[0]["payload"]["model"], "speech-01")
        self.assertEqual(calls[0]["url"], "https://token.cxtfun.com/v1/minimax/tts/async")
        self.assertEqual(calls[1]["url"], "https://token.cxtfun.com/v1/minimax/tts/tasks/task-1")

    def test_minimax_json_error_response_raises_fatal_tts_error(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return (
                    b'{"error":{"code":"access_denied","message":"IP is not allowed",'
                    b'"type":"fun_api_error"}}'
                )

        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            with self.assertRaisesRegex(FatalTtsError, "access_denied.*IP is not allowed"):
                _minimax_request_json(
                    "POST",
                    "https://example.test/tts",
                    "key-1",
                    {"text": "hello"},
                    timeout=1,
                    max_retries=3,
                )

    def test_minimax_access_denied_http_error_does_not_retry(self) -> None:
        calls = []

        class FakeHttpError(urllib.error.HTTPError):
            def read(self):
                return (
                    b'{"error":{"code":"access_denied","message":"IP is not allowed",'
                    b'"type":"fun_api_error"}}'
                )

        def fake_urlopen(request, timeout):
            calls.append(request)
            raise FakeHttpError(
                "https://example.test/tts",
                403,
                "Forbidden",
                hdrs=None,
                fp=None,
            )

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with self.assertRaisesRegex(FatalTtsError, "HTTP 403.*access_denied.*IP is not allowed"):
                _minimax_request_json(
                    "POST",
                    "https://example.test/tts",
                    "key-1",
                    {"text": "hello"},
                    timeout=1,
                    max_retries=3,
                )

        self.assertEqual(len(calls), 1)

    def test_generate_segments_aborts_on_fatal_tts_error(self) -> None:
        cues = [
            {
                "index": i,
                "start": "00:00:00,000",
                "end": "00:00:01,000",
                "start_ms": 0,
                "end_ms": 1000,
                "text": f"hello {i}",
            }
            for i in range(1, 4)
        ]

        def fail_minimax(text, path, config, speaker_profile):
            raise FatalTtsError("MiniMax TTS access_denied: IP is not allowed")

        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.tools.tts_tools._generate_minimax_tts", side_effect=fail_minimax) as minimax, \
                patch("src.tools.tts_tools.logger"):
                with self.assertRaisesRegex(FatalTtsError, "access_denied"):
                    generate_tts_segments(
                        cues,
                        Path(tmp),
                        {
                            "tts": {
                                "provider": "minimax",
                                "concurrency": 25,
                                "speaker_profiles": {"default": {"voice_id": "voice-a"}},
                            }
                        },
                    )

        self.assertEqual(minimax.call_count, 1)

    def test_minimax_task_timeout_raises_fatal_tts_error(self) -> None:
        calls = []

        def fake_request(method, url, api_key, payload, timeout, max_retries):
            calls.append(method)
            if method == "POST":
                return {"task_id": "task-timeout"}
            return {"status": "PROCESSING"}

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"LLM_API_KEY": "key-1", "TTS_MODEL": "speech-01"}, clear=False), \
                patch("src.tools.tts_tools._minimax_request_json", side_effect=fake_request):
                with self.assertRaisesRegex(FatalTtsError, "MiniMax TTS task timeout"):
                    _generate_minimax_tts(
                        "hello",
                        Path(tmp) / "segment.mp3",
                        {
                            "minimax": {
                                "base_url": "https://token.cxtfun.com",
                                "create_path": "/v1/minimax/tts/async",
                                "query_path": "/v1/minimax/tts/tasks/{task_id}",
                                "task_timeout": 0.001,
                                "poll_interval": 0.001,
                            },
                            "sample_rate": 24000,
                        },
                        {"voice_id": "voice-a", "speed": 1.1},
                    )

        self.assertIn("POST", calls)
        self.assertIn("GET", calls)

    def test_tts_node_raises_fatal_error_when_any_segment_failed(self) -> None:
        cue = {
            "index": 1,
            "start": "00:00:00,000",
            "end": "00:00:01,000",
            "start_ms": 0,
            "end_ms": 1000,
            "text": "hello",
        }
        failed_segment = {
            **cue,
            "path": "missing.mp3",
            "duration_ms": 0,
            "success": False,
            "error": "MiniMax TTS task timeout: task_id=task-1",
            "provider": "minimax",
        }

        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp) / "reports"
            with patch("src.nodes.tts_duration_node.generate_tts_segments", return_value=[failed_segment]):
                with self.assertRaisesRegex(FatalTtsError, "failed 1/1.*MiniMax TTS task timeout"):
                    tts_generate_and_detect(
                        {
                            "config": {
                                "project_root": tmp,
                                "paths": {
                                    "tts_segments_dir": "tts_segments",
                                    "reports_dir": "reports",
                                },
                                "duration": {"max_overrun_ms": 350, "max_ratio": 1.12},
                            },
                            "final_cues": [cue],
                            "corrected_cues": [],
                            "reports": {},
                        }
                    )

            self.assertTrue((report_dir / "tts_duration_report.json").exists())

    def test_generate_segments_uses_configured_concurrency(self) -> None:
        cues = [
            {
                "index": i,
                "start": "00:00:00,000",
                "end": "00:00:01,000",
                "start_ms": 0,
                "end_ms": 1000,
                "text": f"hello {i}",
            }
            for i in range(1, 4)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.tools.tts_tools._generate_mock_audio", side_effect=lambda text, path, cfg: Path(path).write_bytes(b"wav")), \
                patch("src.tools.tts_tools.get_audio_duration_ms", return_value=1000), \
                patch("src.tools.tts_tools.ThreadPoolExecutor") as executor_cls:
                executor_cls.return_value.__enter__.return_value.submit.side_effect = lambda fn, *args: MagicMock(result=lambda: fn(*args))
                executor_cls.return_value.__enter__.return_value.__exit__.return_value = False
                with patch("src.tools.tts_tools.as_completed", side_effect=lambda futures: futures):
                    generate_tts_segments(cues, Path(tmp), {"tts": {"provider": "mock", "concurrency": 25}})

        executor_cls.assert_called_once()
        self.assertEqual(executor_cls.call_args.kwargs["max_workers"], 3)


if __name__ == "__main__":
    unittest.main()
