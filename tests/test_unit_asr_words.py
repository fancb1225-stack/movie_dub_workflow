from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.tools.asr_words import (
    cues_from_asr_words_file,
    split_words_to_short_cues,
    write_asr_words_json,
)


class AsrWordsTests(unittest.TestCase):
    def test_write_words_json_and_rebuild_cues(self) -> None:
        words = [
            {"index": 1, "word": "你好", "start_ms": 0, "end_ms": 500, "speaker_id": "speaker_1"},
            {"index": 2, "word": "。", "start_ms": 500, "end_ms": 600, "speaker_id": "speaker_1"},
        ]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "words.json"

            written = write_asr_words_json(path, words)
            cues = cues_from_asr_words_file(path)

        self.assertEqual(written, str(path))
        self.assertEqual(cues[0]["text"], "你好。")
        self.assertEqual(cues[0]["speaker_id"], "speaker_1")

    def test_split_by_punctuation_duration_chars_and_speaker(self) -> None:
        words = [
            {"index": 1, "word": "你好", "start_ms": 0, "end_ms": 500, "speaker_id": "speaker_1"},
            {"index": 2, "word": "世界", "start_ms": 500, "end_ms": 1000, "speaker_id": "speaker_1"},
            {"index": 3, "word": "。", "start_ms": 1000, "end_ms": 1100, "speaker_id": "speaker_1"},
            {"index": 4, "word": "再见", "start_ms": 1100, "end_ms": 1600, "speaker_id": "speaker_2"},
            {"index": 5, "word": "。", "start_ms": 1600, "end_ms": 1700, "speaker_id": "speaker_2"},
        ]

        cues = split_words_to_short_cues(words, max_duration_ms=6000, max_chars=30)

        self.assertEqual([cue["text"] for cue in cues], ["你好世界。", "再见。"])
        self.assertEqual(cues[0]["speaker_id"], "speaker_1")
        self.assertEqual(cues[1]["speaker_id"], "speaker_2")

    def test_split_before_word_that_exceeds_limits(self) -> None:
        words = [
            {"index": 1, "word": "a", "start_ms": 0, "end_ms": 1000, "speaker_id": "speaker_1"},
            {"index": 2, "word": "b", "start_ms": 1000, "end_ms": 7000, "speaker_id": "speaker_1"},
        ]

        cues = split_words_to_short_cues(words, max_duration_ms=6000, max_chars=30)

        self.assertEqual([cue["text"] for cue in cues], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
