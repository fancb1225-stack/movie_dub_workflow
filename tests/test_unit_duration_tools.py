from __future__ import annotations

import unittest

from src.state import SrtCue, TtsSegment
from src.tools.duration_tools import detect_duration_issues


def _cue(index: int, text: str, start_ms: int, end_ms: int) -> SrtCue:
    return {
        "index": index,
        "start": "00:00:00,000",
        "end": "00:00:00,000",
        "start_ms": start_ms,
        "end_ms": end_ms,
        "text": text,
    }


def _segment(index: int, duration_ms: int) -> TtsSegment:
    return {
        "index": index,
        "text": "",
        "start_ms": 0,
        "end_ms": 0,
        "path": "",
        "duration_ms": duration_ms,
        "success": True,
    }


class DetectDurationIssuesTests(unittest.TestCase):
    def test_issue_carries_word_count_wpm_issue_types_and_en_text(self) -> None:
        cues = [_cue(1, "This is a clearly too long subtitle line here.", 0, 1000)]
        segments = [_segment(1, 1500)]
        issues = detect_duration_issues(cues, segments, max_overrun_ms=350, max_ratio=1.12)
        self.assertEqual(len(issues), 1)
        issue = issues[0]
        self.assertEqual(issue["en_text"], cues[0]["text"])
        self.assertEqual(issue["word_count"], 9)
        self.assertGreater(issue["wpm"], 190)
        self.assertIn("too_long", issue["issue_types"])
        self.assertIn("high_wpm", issue["issue_types"])

    def test_issue_includes_zh_text_when_zh_cues_provided(self) -> None:
        en_cues = [_cue(1, "Apocalypse.", 0, 600)]
        zh_cues = [_cue(1, "天启。", 0, 600)]
        segments = [_segment(1, 1416)]
        issues = detect_duration_issues(
            en_cues, segments, max_overrun_ms=350, max_ratio=1.12, zh_cues=zh_cues
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["zh_text"], "天启。")

    def test_zh_cues_optional_keeps_backward_compat(self) -> None:
        cues = [_cue(1, "Short.", 0, 1000)]
        segments = [_segment(1, 1500)]
        issues = detect_duration_issues(cues, segments, max_overrun_ms=350, max_ratio=1.12)
        self.assertEqual(len(issues), 1)
        # Without zh_cues the field is absent, not an error.
        self.assertNotIn("zh_text", issues[0])

    def test_no_issue_when_within_tolerance(self) -> None:
        cues = [_cue(1, "Fine.", 0, 2000)]
        segments = [_segment(1, 2100)]
        issues = detect_duration_issues(cues, segments, max_overrun_ms=350, max_ratio=1.12)
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
