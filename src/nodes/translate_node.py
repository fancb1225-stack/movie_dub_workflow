from __future__ import annotations

from src.config import config_path
from src.llm_client import LLMClient
from src.prompts import TRANSLATE_TO_ENGLISH_SRT_PROMPT
from src.state import SrtCue, WorkflowState
from src.tools.file_tools import write_json, write_text
from src.tools.srt_tools import clean_cues, format_srt, make_cue, parse_srt


def translate_to_english(state: WorkflowState) -> WorkflowState:
    config = state["config"]
    source_cues = state.get("merged_after_critic_cues", [])
    source_srt = state.get("merged_after_critic_srt", "")
    client = LLMClient.from_config(config)
    allow_fallback = _allow_mock_fallback(config)
    fallback_srt = format_srt(_fallback_translation(source_cues))

    if not client.enabled():
        if not allow_fallback:
            raise RuntimeError(
                "LLM translation is not configured. Set LLM_API_KEY, "
                "LLM_BASE_URL, and LLM_MODEL, or set "
                "translation.allow_mock_fallback=true for tests only."
            )
        translated_srt = fallback_srt
        used_fallback = True
        error = "LLM translation is disabled; mock fallback was explicitly allowed."
    else:
        translated_srt = client.complete(
            TRANSLATE_TO_ENGLISH_SRT_PROMPT,
            _build_translation_input(state, source_srt),
            fallback_srt if allow_fallback else "",
        )
        used_fallback = False
        error = None

    translated_cues = _parse_translation_or_raise(translated_srt, source_cues)
    final_srt = format_srt(translated_cues)
    write_text(config_path(config, "paths.translated_srt"), final_srt)
    write_text(config_path(config, "paths.final_srt"), final_srt)
    report_path = config_path(config, "paths.reports_dir") / "translation_report.json"
    write_json(
        report_path,
        {
            "provider": "llm" if client.enabled() else "mock",
            "used_fallback": used_fallback,
            "allow_mock_fallback": allow_fallback,
            "source_subtitle_count": len(source_cues),
            "output_subtitle_count": len(translated_cues),
            "error": error,
        },
    )
    state["en_translated_cues"] = translated_cues
    state["en_translated_srt"] = final_srt
    state["final_cues"] = translated_cues
    state["final_srt"] = final_srt
    state.setdefault("reports", {})["translation_report"] = str(report_path)
    return state


def _allow_mock_fallback(config: dict) -> bool:
    return bool(config.get("translation", {}).get("allow_mock_fallback", False))


def _build_translation_input(state: WorkflowState, source_srt: str) -> str:
    summary = state.get("plot_summary", "")
    return f"Plot summary:\n{summary}\n\nChinese SRT:\n{source_srt}"


def _fallback_translation(cues: list[SrtCue]) -> list[SrtCue]:
    templates = [
        "The story opens as the main character steps into a decisive moment.",
        "The conflict grows, and the characters' goals become clear.",
        "A difficult choice pushes the plot into a tense turn.",
        "The story closes as the central mystery is answered.",
    ]
    translated: list[SrtCue] = []
    for cue in cues:
        text = templates[(cue["index"] - 1) % len(templates)]
        translated.append(make_cue(cue["index"], cue["start_ms"], cue["end_ms"], text))
    return translated


def _parse_translation_or_raise(
    srt_text: str, source_cues: list[SrtCue]
) -> list[SrtCue]:
    cues = clean_cues(parse_srt(srt_text))
    if not cues or len(cues) != len(source_cues):
        raise RuntimeError(
            "LLM translation output is invalid: expected "
            f"{len(source_cues)} SRT cues, got {len(cues)}."
        )
    validated: list[SrtCue] = []
    for cue, source in zip(cues, source_cues):
        validated.append(
            make_cue(source["index"], source["start_ms"], source["end_ms"], cue["text"])
        )
    return validated
