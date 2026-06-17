from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tools.tts_tools import _generate_edge_tts


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


if __name__ == "__main__":
    unittest.main()
