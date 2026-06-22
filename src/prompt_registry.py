from __future__ import annotations

from typing import Any, Literal

from src import manju_prompt, prompts
from src.video_types import VIDEO_TYPE_MANJU, VIDEO_TYPE_MOVIE_COMMENTARY, normalize_video_type

PromptName = Literal[
    "critic_zh_srt",
    "merge_zh_asr_srt",
    "summarize_plot",
    "translate_to_english_srt",
    "reflect_duration_issues",
]

_PROMPTS: dict[str, dict[PromptName, str]] = {
    VIDEO_TYPE_MOVIE_COMMENTARY: {
        "critic_zh_srt": prompts.CRITIC_ZH_SRT_PROMPT,
        "merge_zh_asr_srt": prompts.MERGE_ZH_ASR_SRT_PROMPT,
        "summarize_plot": prompts.SUMMARIZE_PLOT_PROMPT,
        "translate_to_english_srt": prompts.TRANSLATE_TO_ENGLISH_SRT_PROMPT,
        "reflect_duration_issues": prompts.REFLECT_DURATION_ISSUES_PROMPT,
    },
    VIDEO_TYPE_MANJU: {
        "critic_zh_srt": manju_prompt.CRITIC_ZH_SRT_PROMPT,
        "merge_zh_asr_srt": manju_prompt.MERGE_ZH_ASR_SRT_PROMPT,
        "summarize_plot": manju_prompt.SUMMARIZE_PLOT_PROMPT,
        "translate_to_english_srt": manju_prompt.TRANSLATE_TO_ENGLISH_SRT_PROMPT,
        "reflect_duration_issues": manju_prompt.MANJU_QC_REFLECT_PROMPT,
    },
}


def prompt_for(config: dict[str, Any], name: PromptName) -> str:
    video_type = normalize_video_type(config.get("job", {}).get("video_type"))
    return _PROMPTS[video_type][name]
