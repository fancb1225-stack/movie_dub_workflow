from __future__ import annotations

import unittest

from src.tools.media_tools import has_audio_stream, has_video_stream, media_duration_ms


class MediaToolsTests(unittest.TestCase):
    def test_stream_detection_reads_probe_stream_types(self) -> None:
        probe = {
            "streams": [
                {"codec_type": "video", "duration": "2.0"},
                {"codec_type": "audio", "duration": "2.0"},
            ],
            "format": {"duration": "2.0"},
        }

        self.assertTrue(has_audio_stream(probe))
        self.assertTrue(has_video_stream(probe))
        self.assertEqual(media_duration_ms(probe), 2000)

    def test_duration_falls_back_to_first_stream_duration(self) -> None:
        probe = {"streams": [{"codec_type": "audio", "duration": "1.25"}], "format": {}}

        self.assertEqual(media_duration_ms(probe), 1250)

    def test_missing_duration_returns_zero(self) -> None:
        self.assertEqual(media_duration_ms({"streams": [], "format": {}}), 0)


if __name__ == "__main__":
    unittest.main()

