from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.nodes.merge_and_critic_node import critic_srt
from src.tools.srt_tools import format_srt, make_cue


class CriticNodeTests(unittest.TestCase):
    def test_llm_request_error_falls_back_to_cleaned_srt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = _state(temp_dir)
            client = FakeFailingClient("LLM request failed: The read operation timed out")

            with patch("src.nodes.merge_and_critic_node.LLMClient.from_config", return_value=client):
                result = critic_srt(state)

            self.assertEqual(result["corrected_cues"], state["cleaned_cues"])
            self.assertEqual(result["corrected_srt"], state["cleaned_srt"])
            corrected_path = Path(state["config"]["paths"]["corrected_srt"])
            self.assertTrue(corrected_path.exists())
            self.assertEqual(corrected_path.read_text(encoding="utf-8"), state["cleaned_srt"])


class FakeFailingClient:
    def __init__(self, error: str):
        self.error = error

    def complete(self, system_prompt: str, user_content: str, fallback_text: str) -> str:
        raise RuntimeError(self.error)


def _state(temp_dir: str) -> dict:
    root = Path(temp_dir)
    cues = [
        make_cue(1, 0, 1000, "給阿嬤的情書是一部電影"),
        make_cue(2, 1000, 2500, "現在很多人都在吹它"),
    ]
    cleaned_srt = format_srt(cues)
    return {
        "config": {
            "project_root": temp_dir,
            "paths": {
                "corrected_srt": str(root / "critic" / "zh_corrected.srt"),
            },
            "llm": {
                "api_key": "test-key",
                "base_url": "https://example.invalid/v1",
                "model": "test-model",
                "timeout": 1,
                "max_retries": 0,
            },
        },
        "cleaned_cues": cues,
        "cleaned_srt": cleaned_srt,
        "reports": {},
    }


if __name__ == "__main__":
    unittest.main()
