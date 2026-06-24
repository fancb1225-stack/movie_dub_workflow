from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tools.tts_tools import _generate_edge_tts, generate_tts_segments


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


if __name__ == "__main__":
    unittest.main()
