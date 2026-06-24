from __future__ import annotations

import unittest
from pathlib import Path

from src.tools.asr_words import (
    cues_from_asr_words_file,
    extract_whisperx_words,
    split_words_to_short_cues,
    write_asr_words_json,
)


def _word_segments_result() -> dict:
    return {
        "segments": [
            {
                "start": 0.0,
                "end": 3.0,
                "text": "你好世界。",
                "speaker": "SPEAKER_00",
                "words": [
                    {"word": "你好", "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
                    {"word": "世界", "start": 1.0, "end": 2.0, "speaker": "SPEAKER_00"},
                    {"word": "。", "start": 2.0, "end": 2.5, "speaker": "SPEAKER_00"},
                ],
            }
        ],
        "word_segments": [
            {"word": "你好", "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
            {"word": "世界", "start": 1.0, "end": 2.0, "speaker": "SPEAKER_01"},
            {"word": "。", "start": 2.0, "end": 2.5, "speaker": "SPEAKER_01"},
        ],
    }


class ExtractWordsTests(unittest.TestCase):
    def test_extract_from_word_segments(self) -> None:
        words = extract_whisperx_words(_word_segments_result(), speaker_normalize=True)
        self.assertEqual(len(words), 3)
        self.assertEqual(words[0]["word"], "你好")
        self.assertEqual(words[0]["start_ms"], 0)
        self.assertEqual(words[0]["end_ms"], 1000)
        self.assertEqual(words[0]["speaker_id"], "speaker_1")
        self.assertEqual(words[1]["speaker_id"], "speaker_2")

    def test_extract_fallback_to_segment_words(self) -> None:
        result = {
            "segments": [
                {
                    "start": 0.0,
                    "end": 2.0,
                    "text": "你好",
                    "speaker": "SPEAKER_00",
                    "words": [
                        {"word": "你好", "start": 0.0, "end": 1.0},
                        {"word": "世界", "start": 1.0, "end": 2.0},
                    ],
                }
            ]
        }
        words = extract_whisperx_words(result)
        self.assertEqual(len(words), 2)
        # 词未自带 speaker 时继承 segment speaker
        self.assertEqual(words[0]["speaker_id"], "speaker_1")
        self.assertEqual(words[1]["speaker_id"], "speaker_1")

    def test_extract_fills_missing_timestamps(self) -> None:
        result = {
            "segments": [{"start": 0.0, "end": 5.0, "words": [
                {"word": "a", "start": 0.0, "end": 1.0},
                {"word": "b"},  # 缺 start/end
                {"word": "c", "start": 2.0, "end": 3.0},
            ]}]
        }
        words = extract_whisperx_words(result)
        self.assertEqual(len(words), 3)
        # b 缺时间戳:start 用前词 end, end >= start
        self.assertGreaterEqual(words[1]["start_ms"], words[0]["end_ms"])
        self.assertGreater(words[1]["end_ms"], words[1]["start_ms"])
        # 单调递增
        self.assertLessEqual(words[0]["end_ms"], words[1]["start_ms"])
        self.assertLessEqual(words[1]["end_ms"], words[2]["start_ms"])

    def test_extract_empty_result(self) -> None:
        self.assertEqual(extract_whisperx_words({}), [])

    def test_keeps_raw_label_when_normalize_false(self) -> None:
        words = extract_whisperx_words(_word_segments_result(), speaker_normalize=False)
        self.assertEqual(words[0]["speaker_id"], "SPEAKER_00")


class WriteWordsJsonTests(unittest.TestCase):
    def test_write_and_reread(self) -> None:
        import tempfile

        words = extract_whisperx_words(_word_segments_result())
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "words.json"
            written = write_asr_words_json(path, words)
            self.assertTrue(Path(written).exists())
            reread = cues_from_asr_words_file(path)
        self.assertGreater(len(reread), 0)


class SplitWordsToShortCuesTests(unittest.TestCase):
    def _words(self, specs: list[tuple[str, int, int, str | None]]) -> list:
        from src.state import AsrWord

        out = []
        for idx, (word, start, end, speaker) in enumerate(specs, start=1):
            w: AsrWord = {"index": idx, "word": word, "start_ms": start, "end_ms": end}
            if speaker:
                w["speaker_id"] = speaker
            out.append(w)
        return out

    def test_split_by_punctuation(self) -> None:
        words = self._words([
            ("你好", 0, 500, "speaker_1"),
            ("世界", 500, 1000, "speaker_1"),
            ("。", 1000, 1100, "speaker_1"),
            ("再见", 1100, 1600, "speaker_1"),
            ("。", 1600, 1700, "speaker_1"),
        ])
        cues = split_words_to_short_cues(words)
        # 两个标点各断一次 -> 2 条 cue
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0]["text"], "你好世界。")
        self.assertEqual(cues[1]["text"], "再见。")

    def test_split_by_max_duration(self) -> None:
        words = self._words([
            ("a", 0, 1000, "speaker_1"),
            ("b", 1000, 2000, "speaker_1"),
            ("c", 2000, 3000, "speaker_1"),
            ("d", 3000, 6500, "speaker_1"),  # 累计达 6500ms > 6000
        ])
        cues = split_words_to_short_cues(words, max_duration_ms=6000)
        # d 加入前累计 3000ms,加入 d 后 6500ms 超限 -> 但判定在加入前
        # 0-3000 (abc) 一条, d 单独一条
        self.assertEqual(len(cues), 2)

    def test_split_by_max_chars(self) -> None:
        words = self._words([
            ("一二三四五六七八九十", 0, 1000, "speaker_1"),  # 10 字
            ("一二三四五六七八九十", 1000, 2000, "speaker_1"),  # 再加 10 -> 20 > 30? 否
            ("一二三四五六七八九十一", 2000, 3000, "speaker_1"),  # 21 字
            ("一二三四五六七八九十一", 3000, 4000, "speaker_1"),  # 32 > 30 -> 断
        ])
        cues = split_words_to_short_cues(words, max_chars=30)
        self.assertEqual(len(cues), 2)

    def test_split_by_speaker_switch(self) -> None:
        words = self._words([
            ("你好", 0, 500, "speaker_1"),
            ("再见", 500, 1000, "speaker_2"),  # speaker 切换
        ])
        cues = split_words_to_short_cues(words)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0]["speaker_id"], "speaker_1")
        self.assertEqual(cues[1]["speaker_id"], "speaker_2")

    def test_cues_carry_speaker_id(self) -> None:
        words = self._words([
            ("你好", 0, 500, "speaker_1"),
            ("。", 500, 600, "speaker_1"),
        ])
        cues = split_words_to_short_cues(words)
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0]["speaker_id"], "speaker_1")

    def test_empty_words(self) -> None:
        self.assertEqual(split_words_to_short_cues([]), [])

    def test_reindex_is_sequential(self) -> None:
        words = self._words([
            ("你好", 0, 500, "speaker_1"),
            ("。", 500, 600, "speaker_1"),
            ("再见", 600, 1100, "speaker_1"),
            ("。", 1100, 1200, "speaker_1"),
        ])
        cues = split_words_to_short_cues(words)
        self.assertEqual([c["index"] for c in cues], [1, 2])


if __name__ == "__main__":
    unittest.main()
