from __future__ import annotations

from src.config import config_path
from src.state import WorkflowState
from src.tools.file_tools import write_text
from src.tools.srt_tools import clean_cues, format_srt, parse_srt


def clean_srt(state: WorkflowState) -> WorkflowState:
    config = state["config"]
    cues = state.get("raw_cues") or parse_srt(state.get("raw_srt", ""))
    cleaned_cues = clean_cues(cues)
    cleaned_srt = format_srt(cleaned_cues)
    write_text(config_path(config, "paths.cleaned_srt"), cleaned_srt)
    state["cleaned_cues"] = cleaned_cues
    state["cleaned_srt"] = cleaned_srt
    return state

