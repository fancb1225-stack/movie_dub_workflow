from __future__ import annotations

import logging

from src.config import config_path
from src.llm_client import LLMClient
from src.prompts import CRITIC_ZH_SRT_PROMPT
from src.state import SrtCue, WorkflowState
from src.tools.file_tools import write_text
from src.tools.srt_tools import clean_cues, format_srt, parse_srt

logger = logging.getLogger(__name__)


def critic_srt(state: WorkflowState) -> WorkflowState:
    logger.info("critic_srt: entering node")
    config = state["config"]
    cleaned_srt = state.get("cleaned_srt", "")
    cleaned_cues = state.get("cleaned_cues", [])
    try:
        corrected_srt = _critic_srt(config, cleaned_srt)
    except Exception as exc:
        corrected_srt = cleaned_srt
        state.setdefault("errors", []).append(
            f"LLM critic request failed; fallback to cleaned SRT: {exc}"
        )
    corrected_cues = _parse_or_fallback(corrected_srt, cleaned_cues)
    corrected_srt_text = format_srt(corrected_cues)
    write_text(config_path(config, "paths.corrected_srt"), corrected_srt_text)
    state["corrected_cues"] = corrected_cues
    state["corrected_srt"] = corrected_srt_text
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
