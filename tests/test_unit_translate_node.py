from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from src.nodes.translate_node import translate_to_english
from src.tools.srt_tools import format_srt, make_cue


class TranslateNodeTests(unittest.TestCase):
    def test_translation_requires_configured_llm_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = _state(temp_dir, allow_mock_fallback=False)

            with self.assertRaisesRegex(RuntimeError, "LLM translation is not configured"):
                translate_to_english(state)

    def test_translation_allows_mock_fallback_only_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = _state(temp_dir, allow_mock_fallback=True)

            result = translate_to_english(state)

            self.assertEqual(len(result["final_cues"]), 2)
            self.assertIn("decisive moment", result["final_srt"])
            report = Path(result["reports"]["translation_report"])
            self.assertTrue(report.exists())

    def test_translation_rejects_invalid_llm_srt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = _state(temp_dir, allow_mock_fallback=False)
            state["config"]["llm"] = {
                "api_key": "test-key",
                "base_url": "https://example.invalid/v1",
                "model": "test-model",
                "timeout": 1,
                "max_retries": 0,
            }

            class FakeClient:
                def enabled(self) -> bool:
                    return True

                def complete(
                    self, system_prompt: str, user_content: str, fallback_text: str
                ) -> str:
                    return "This is not an SRT response."

            with patch("src.nodes.translate_node.LLMClient.from_config", return_value=FakeClient()):
                with self.assertRaisesRegex(RuntimeError, "translation output is invalid"):
                    translate_to_english(state)


def _state(temp_dir: str, allow_mock_fallback: bool) -> dict[str, Any]:
    cues = [
        make_cue(1, 0, 2000, "主角进入房间。"),
        make_cue(2, 2000, 4200, "他发现事情不对。"),
    ]
    root = Path(temp_dir)
    return {
        "config": {
            "project_root": temp_dir,
            "paths": {
                "translated_srt": str(root / "translated" / "en_translated.srt"),
                "final_srt": str(root / "final" / "en_final.srt"),
                "reports_dir": str(root / "reports"),
            },
            "translation": {"allow_mock_fallback": allow_mock_fallback},
            "llm": {
                "api_key": "",
                "base_url": "",
                "model": "mock",
                "timeout": 1,
                "max_retries": 0,
            },
        },
        "merged_after_critic_cues": cues,
        "merged_after_critic_srt": format_srt(cues),
        "plot_summary": "主角发现异常。",
        "reports": {},
    }


if __name__ == "__main__":
    unittest.main()
