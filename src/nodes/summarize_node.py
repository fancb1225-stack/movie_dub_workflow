from __future__ import annotations

from src.config import config_path
from src.llm_client import LLMClient
from src.prompts import SUMMARIZE_PLOT_PROMPT
from src.state import WorkflowState
from src.tools.file_tools import write_text


def summarize_plot(state: WorkflowState) -> WorkflowState:
    config = state["config"]
    source_srt = state.get("merged_after_critic_srt", "")
    fallback = _fallback_summary(state)
    summary = LLMClient.from_config(config).complete(
        SUMMARIZE_PLOT_PROMPT,
        source_srt,
        fallback,
    )
    summary_path = config_path(config, "paths.reports_dir") / "plot_summary.txt"
    write_text(summary_path, summary.strip() + "\n")
    state["plot_summary"] = summary.strip()
    state.setdefault("reports", {})["plot_summary"] = str(summary_path)
    return state


def _fallback_summary(state: WorkflowState) -> str:
    cues = state.get("merged_after_critic_cues", [])
    if not cues:
        return "No plot summary is available because no subtitles were generated."
    joined = " ".join(cue["text"] for cue in cues[:4])
    return f"Summary generated from Chinese narration: {joined}"

