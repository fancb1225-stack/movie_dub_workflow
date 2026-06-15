from __future__ import annotations

import unittest

from src.tools.speaker_tools import (
    add_placeholder_speaker_to_cues,
    assign_placeholder_speakers_from_duration,
    assign_placeholder_speakers_from_srt,
)
from src.tools.srt_tools import make_cue


class SpeakerToolsTests(unittest.TestCase):
    def test_assign_placeholder_speakers_from_srt_preserves_timing_and_text(self) -> None:
        srt = (
            "1\n"
            "00:00:00,000 --> 00:00:01,000\n"
            "Hello\n\n"
            "2\n"
            "00:00:01,000 --> 00:00:02,000\n"
            "World\n"
        )

        segments = assign_placeholder_speakers_from_srt(srt)

        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["speaker_id"], "speaker_1")
        self.assertEqual(segments[0]["text"], "Hello")
        self.assertEqual(segments[1]["start_ms"], 1000)

    def test_assign_placeholder_speakers_from_duration_creates_single_segment(self) -> None:
        segments = assign_placeholder_speakers_from_duration(2500)

        self.assertEqual(
            segments,
            [
                {
                    "index": 1,
                    "start_ms": 0,
                    "end_ms": 2500,
                    "speaker_id": "speaker_1",
                    "text": "",
                }
            ],
        )

    def test_add_placeholder_speaker_to_cues(self) -> None:
        cues = [make_cue(1, 0, 1000, "line")]

        updated = add_placeholder_speaker_to_cues(cues)

        self.assertEqual(updated[0]["speaker_id"], "speaker_1")
        self.assertEqual(updated[0]["text"], "line")


if __name__ == "__main__":
    unittest.main()

