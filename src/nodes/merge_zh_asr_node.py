from __future__ import annotations

import logging

from src.config import config_path
from src.llm_client import LLMClient
from src.prompts import MERGE_ZH_ASR_SRT_PROMPT
from src.state import SrtCue, WorkflowState
from src.tools.file_tools import write_json, write_text
from src.tools.srt_tools import clean_cues, format_srt, ms_to_srt_time, parse_srt

logger = logging.getLogger(__name__)


def merge_zh_asr_srt(state: WorkflowState) -> WorkflowState:
    logger.info("merge_zh_asr_srt: entering node")
    config = state["config"]
    raw_cues = state.get("raw_cues") or clean_cues(parse_srt(state.get("raw_srt", "")))
    fallback_srt = format_srt(raw_cues)
    used_fallback = False
    error = None
    client = LLMClient.from_config(config)
    if client.enabled():
        try:
            response = client.complete(MERGE_ZH_ASR_SRT_PROMPT, fallback_srt, fallback_srt)
            normalized_cues = _snap_timestamps_to_source_boundaries(
                clean_cues(parse_srt(response)),
                raw_cues,
            )
            merged_cues, error = _parse_or_fallback(normalized_cues, raw_cues)
            used_fallback = merged_cues is raw_cues
        except Exception as exc:
            merged_cues = raw_cues
            used_fallback = True
            error = f"LLM merge request failed; fallback to original ASR cues: {exc}"
    else:
        merged_cues = raw_cues
        used_fallback = True
        error = "LLM merge is disabled; original ASR SRT was used."
    merged_srt = format_srt(merged_cues)
    write_text(config_path(config, "paths.merged_asr_srt"), merged_srt)
    report_path = config_path(config, "paths.reports_dir") / "merge_zh_asr_report.json"
    write_json(
        report_path,
        {
            "input_cue_count": len(raw_cues),
            "output_cue_count": len(merged_cues),
            "used_fallback": used_fallback,
            "error": error,
        },
    )
    state["raw_cues"] = merged_cues
    state["raw_srt"] = merged_srt
    state["merged_asr_cues"] = merged_cues
    state["merged_asr_srt"] = merged_srt
    state.setdefault("reports", {})["merge_zh_asr_report"] = str(report_path)
    return state


def _parse_or_fallback(
    srt_text: str | list[SrtCue], fallback_cues: list[SrtCue]
) -> tuple[list[SrtCue], str | None]:
    cues = srt_text if isinstance(srt_text, list) else clean_cues(parse_srt(srt_text))
    if not cues:
        return fallback_cues, "LLM output is not valid SRT; fallback to original ASR cues."
    kept: list[SrtCue] = []
    dropped: list[int] = []
    prev_end: int | None = None
    for cue in cues:
        error = _validate_merged_cue(cue, fallback_cues, prev_end)
        if error is None:
            kept.append(cue)
            prev_end = cue["end_ms"]
        else:
            # 单条容错:丢弃无效 cue,保留其余 LLM 合并结果,不全量回退
            dropped.append(cue.get("index", -1))
            logger.warning("merge cue %s invalid, dropped: %s", cue.get("index"), error)
    if not kept:
        return fallback_cues, "All merged cues invalid; fallback to original ASR cues."
    if dropped:
        # 重新编号
        for i, cue in enumerate(kept, start=1):
            cue["index"] = i
        return kept, f"Dropped {len(dropped)} invalid merged cue(s); kept {len(kept)}."
    return kept, None


def _snap_timestamps_to_source_boundaries(
    cues: list[SrtCue], source_cues: list[SrtCue], tolerance_ms: int = 500
) -> list[SrtCue]:
    """Snap small LLM timestamp rounding errors back to source cue boundaries.

    LLMs often round ASR timestamps to whole seconds, e.g. source end 508800ms
    becomes 508000ms.  The merge contract still requires boundaries to come from
    source cues, so accept small drift and normalize before validation.
    """
    if not cues or not source_cues:
        return cues
    boundaries = sorted({cue["start_ms"] for cue in source_cues} | {cue["end_ms"] for cue in source_cues})
    snapped: list[SrtCue] = []
    for cue in cues:
        start_ms = _nearest_boundary(cue["start_ms"], boundaries, tolerance_ms)
        end_ms = _nearest_boundary(cue["end_ms"], boundaries, tolerance_ms)
        snapped.append(
            {
                **cue,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "start": ms_to_srt_time(start_ms),
                "end": ms_to_srt_time(end_ms),
            }
        )
    return snapped


def _nearest_boundary(value: int, boundaries: list[int], tolerance_ms: int) -> int:
    nearest = min(boundaries, key=lambda boundary: abs(boundary - value))
    if abs(nearest - value) <= tolerance_ms:
        return nearest
    return value


def _validate_merged_cue(
    cue: SrtCue, source_cues: list[SrtCue], prev_end: int | None
) -> str | None:
    """校验单条合并 cue。返回 None 表示合法,返回字符串表示无效原因。"""
    if not source_cues:
        return None
    source_start = source_cues[0]["start_ms"]
    source_end = source_cues[-1]["end_ms"]
    source_boundaries = {cue["start_ms"] for cue in source_cues} | {cue["end_ms"] for cue in source_cues}
    if cue["start_ms"] >= cue["end_ms"]:
        return f"non-positive duration [{cue['start_ms']}->{cue['end_ms']}]."
    if cue["start_ms"] < source_start or cue["end_ms"] > source_end:
        return (
            f"timestamp [{cue['start_ms']}->{cue['end_ms']}] "
            f"outside source range [{source_start}->{source_end}]."
        )
    if cue["start_ms"] not in source_boundaries or cue["end_ms"] not in source_boundaries:
        return (
            f"timestamp [{cue['start_ms']}->{cue['end_ms']}] "
            f"does not align with any source cue boundary."
        )
    if prev_end is not None and cue["start_ms"] < prev_end:
        return f"start {cue['start_ms']} < prev end {prev_end} (overlap)."
    return None
