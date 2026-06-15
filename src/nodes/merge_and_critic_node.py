from __future__ import annotations

from src.config import config_path
from src.llm_client import LLMClient
from src.prompts import CRITIC_ZH_SRT_PROMPT
from src.state import SrtCue, WorkflowState
from src.tools.file_tools import write_text
from src.tools.merge_tools import merge_cues_by_rules
from src.tools.srt_tools import clean_cues, format_srt, parse_srt


def merge_and_critic(state: WorkflowState) -> WorkflowState:
    config = state["config"]
    srt_config = config.get("srt", {})
    merged_cues = merge_cues_by_rules(
        state.get("cleaned_cues", []),
        int(srt_config.get("merge_max_chars", 38)),
        int(srt_config.get("merge_max_gap_ms", 450)),
        int(srt_config.get("merge_max_duration_ms", 6500)),
    )
    merged_srt = format_srt(merged_cues)
    write_text(config_path(config, "paths.merged_before_critic_srt"), merged_srt)
    corrected_srt = _critic_srt(config, merged_srt)
    corrected_cues = _parse_or_fallback(corrected_srt, merged_cues)
    corrected_srt = format_srt(corrected_cues)
    write_text(config_path(config, "paths.corrected_srt"), corrected_srt)
    state["merged_before_critic_cues"] = merged_cues
    state["merged_before_critic_srt"] = merged_srt
    state["corrected_cues"] = corrected_cues
    state["corrected_srt"] = corrected_srt
    return state


def _critic_srt(config: dict, srt_text: str) -> str:
    client = LLMClient.from_config(config)
    return client.complete(CRITIC_ZH_SRT_PROMPT, srt_text, srt_text)


def _parse_or_fallback(srt_text: str, fallback_cues: list[SrtCue]) -> list[SrtCue]:
    cues = clean_cues(parse_srt(srt_text))
    if not cues or len(cues) != len(fallback_cues):
        return fallback_cues
    for cue, fallback in zip(cues, fallback_cues):
        if cue["start_ms"] != fallback["start_ms"] or cue["end_ms"] != fallback["end_ms"]:
            return fallback_cues
    return cues

