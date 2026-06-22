from __future__ import annotations

import unittest

from src import manju_prompt, prompts
from src.prompt_registry import prompt_for
from src.video_types import normalize_video_type, DEFAULT_VIDEO_TYPE


class PromptRegistryTests(unittest.TestCase):
    def test_default_config_uses_movie_commentary_prompts(self) -> None:
        config: dict = {}
        self.assertIs(prompt_for(config, "critic_zh_srt"), prompts.CRITIC_ZH_SRT_PROMPT)
        self.assertIs(prompt_for(config, "translate_to_english_srt"), prompts.TRANSLATE_TO_ENGLISH_SRT_PROMPT)
        self.assertIs(prompt_for(config, "reflect_duration_issues"), prompts.REFLECT_DURATION_ISSUES_PROMPT)

    def test_movie_commentary_uses_movie_commentary_prompts(self) -> None:
        config = {"job": {"video_type": "movie_commentary"}}
        self.assertIs(prompt_for(config, "merge_zh_asr_srt"), prompts.MERGE_ZH_ASR_SRT_PROMPT)
        self.assertIs(prompt_for(config, "summarize_plot"), prompts.SUMMARIZE_PLOT_PROMPT)

    def test_manju_uses_manju_prompts(self) -> None:
        config = {"job": {"video_type": "manju"}}
        self.assertIs(prompt_for(config, "critic_zh_srt"), manju_prompt.CRITIC_ZH_SRT_PROMPT)
        self.assertIs(prompt_for(config, "merge_zh_asr_srt"), manju_prompt.MERGE_ZH_ASR_SRT_PROMPT)
        self.assertIs(prompt_for(config, "summarize_plot"), manju_prompt.SUMMARIZE_PLOT_PROMPT)
        self.assertIs(prompt_for(config, "translate_to_english_srt"), manju_prompt.TRANSLATE_TO_ENGLISH_SRT_PROMPT)

    def test_manju_reflect_uses_qc_reflect_prompt(self) -> None:
        config = {"job": {"video_type": "manju"}}
        self.assertIs(prompt_for(config, "reflect_duration_issues"), manju_prompt.MANJU_QC_REFLECT_PROMPT)

    def test_unknown_video_type_raises(self) -> None:
        config = {"job": {"video_type": "anime"}}
        with self.assertRaises(ValueError):
            prompt_for(config, "translate_to_english_srt")


class NormalizeVideoTypeTests(unittest.TestCase):
    def test_none_defaults_to_movie_commentary(self) -> None:
        self.assertEqual(normalize_video_type(None), DEFAULT_VIDEO_TYPE)

    def test_empty_defaults_to_movie_commentary(self) -> None:
        self.assertEqual(normalize_video_type("   "), DEFAULT_VIDEO_TYPE)

    def test_strips_and_lowercases(self) -> None:
        self.assertEqual(normalize_video_type("  Manju  "), "manju")

    def test_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            normalize_video_type("anime")


if __name__ == "__main__":
    unittest.main()
