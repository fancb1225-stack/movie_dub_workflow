from __future__ import annotations

import json
from typing import Any

from src.config import config_path
from src.llm_client import LLMClient
from src.prompt_registry import prompt_for
from src.state import DurationIssue, SrtCue, WorkflowState
from src.tools.file_tools import write_json, write_text
from src.tools.srt_tools import format_srt, replace_text_for_indices


def reflect_duration_issues(state: WorkflowState) -> WorkflowState:
    config = state["config"]
    issues = state.get("duration_issues", [])
    if not issues:
        return state
    current_round = int(state.get("reflection_rounds", 0))
    max_rounds = int(config.get("duration", {}).get("max_reflection_rounds", 1))
    if current_round >= max_rounds:
        return state
    fallback_replacements = _fallback_replacements(
        state.get("final_cues", []), issues, config
    )
    response = LLMClient.from_config(config).complete(
        prompt_for(config, "reflect_duration_issues"),
        _build_reflection_input(issues),
        json.dumps(
            [
                {"index": index, "text": text}
                for index, text in fallback_replacements.items()
            ],
            ensure_ascii=False,
        ),
    )
    replacements = _parse_replacements(response, fallback_replacements, issues)
    reflected_cues = replace_text_for_indices(state.get("final_cues", []), replacements)
    reflected_srt = format_srt(reflected_cues)
    next_round = current_round + 1
    reflection_dir = config_path(config, "paths.outputs_dir") / "reflection"
    write_text(reflection_dir / f"round_{next_round}_en_reflected.srt", reflected_srt)
    write_json(
        reflection_dir / f"round_{next_round}_replacements.json",
        [{"index": index, "text": text} for index, text in replacements.items()],
    )
    write_text(config_path(config, "paths.final_srt"), reflected_srt)
    state["reflection_rounds"] = next_round
    state["final_cues"] = reflected_cues
    state["final_srt"] = reflected_srt
    return state


def _build_reflection_input(issues: list[DurationIssue]) -> str:
    return json.dumps(issues, ensure_ascii=False, indent=2)


def _fallback_replacements(
    cues: list[SrtCue], issues: list[DurationIssue], config: dict[str, Any]
) -> dict[int, str]:
    cue_by_index = {cue["index"]: cue for cue in cues}
    words_per_minute = int(config.get("tts", {}).get("words_per_minute", 155))
    replacements: dict[int, str] = {}
    for issue in issues:
        cue = cue_by_index.get(issue["index"])
        if cue is None:
            continue
        available_words = max(
            3,
            int(issue["subtitle_duration_ms"] / 60_000 * words_per_minute * 0.78),
        )
        replacements[cue["index"]] = _shorten_text(cue["text"], available_words)
    return replacements


def _shorten_text(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    shortened = " ".join(words[:max_words]).rstrip(",.;:")
    return f"{shortened}."


def _parse_replacements(
    response: str,
    fallback: dict[int, str],
    issues: list[DurationIssue],
) -> dict[int, str]:
    issue_indices = {issue["index"] for issue in issues}
    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        return fallback
    if not isinstance(data, list):
        return fallback
    replacements: dict[int, str] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        text = item.get("text")
        if isinstance(index, int) and isinstance(text, str) and index in issue_indices:
            replacements[index] = text.strip()
    return replacements or fallback

