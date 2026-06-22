from __future__ import annotations

import json
import unittest

from src.nodes.reflection_node import _build_reflection_input


class BuildReflectionInputTests(unittest.TestCase):
    def test_includes_plot_summary_and_issue_fields(self) -> None:
        issues = [
            {
                "index": 8,
                "start_ms": 34650,
                "end_ms": 35250,
                "subtitle_duration_ms": 600,
                "tts_duration_ms": 1416,
                "overrun_ms": 816,
                "ratio": 2.36,
                "text": "Apocalypse.",
                "en_text": "Apocalypse.",
                "zh_text": "天启。",
                "word_count": 1,
                "wpm": 100,
                "issue_types": ["too_long", "mistranslation"],
            }
        ]
        state = {"plot_summary": "末世极寒灾厄已持续半年。"}
        payload = _build_reflection_input(issues, state)
        data = json.loads(payload)
        self.assertEqual(data["plot_summary"], "末世极寒灾厄已持续半年。")
        self.assertEqual(data["issues"][0]["zh_text"], "天启。")
        self.assertIn("mistranslation", data["issues"][0]["issue_types"])

    def test_missing_plot_summary_defaults_to_empty(self) -> None:
        issues = [{"index": 1, "text": "x."}]
        payload = _build_reflection_input(issues, {})
        data = json.loads(payload)
        self.assertEqual(data["plot_summary"], "")


if __name__ == "__main__":
    unittest.main()
