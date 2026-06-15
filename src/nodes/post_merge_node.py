from __future__ import annotations

from src.config import config_path
from src.state import WorkflowState
from src.tools.file_tools import write_text
from src.tools.merge_tools import merge_cues_by_rules
from src.tools.srt_tools import format_srt


def post_merge(state: WorkflowState) -> WorkflowState:
    config = state["config"]
    srt_config = config.get("srt", {})
    merged_cues = merge_cues_by_rules(
        state.get("corrected_cues", []),
        int(srt_config.get("merge_max_chars", 38)),
        int(srt_config.get("merge_max_gap_ms", 450)),
        int(srt_config.get("merge_max_duration_ms", 6500)),
    )
    merged_srt = format_srt(merged_cues)
    write_text(config_path(config, "paths.merged_after_critic_srt"), merged_srt)
    state["merged_after_critic_cues"] = merged_cues
    state["merged_after_critic_srt"] = merged_srt
    return state

