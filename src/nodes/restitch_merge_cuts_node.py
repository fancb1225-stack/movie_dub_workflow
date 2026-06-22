from __future__ import annotations

import logging

from src.config import config_path
from src.llm_client import LLMClient
from src.prompt_registry import prompt_for
from src.state import SrtCue, WorkflowState
from src.tools.file_tools import write_json, write_text
from src.tools.srt_tools import clean_cues, format_srt, parse_srt, reindex_cues

logger = logging.getLogger(__name__)


def restitch_merge_cuts(state: WorkflowState) -> WorkflowState:
    """对 merge 节点产生的硬切点做局部 LLM 重合并,修复被硬切割裂的可合并片段。

    仅当 state["merge_hard_cuts"] 非空时工作,否则空操作直接返回。
    对每个硬切点,取前块末尾 2 条 + 后块开头 2 条已合并 cue,单独调 LLM 重合并,
    结果回填替换,全局重新编号。失败则保留原 cue 不动。
    """
    logger.info("restitch_merge_cuts: entering node")
    config = state["config"]
    hard_cuts = state.get("merge_hard_cuts") or []
    if not hard_cuts:
        logger.info("restitch_merge_cuts: no hard cuts, skip")
        state["merge_hard_cuts"] = []
        report_path = config_path(config, "paths.reports_dir") / "restitch_merge_cuts_report.json"
        write_json(
            report_path,
            {"hard_cut_count": 0, "restitched_count": 0, "failed_count": 0},
        )
        state.setdefault("reports", {})["restitch_merge_cuts_report"] = str(report_path)
        return state

    merged_cues: list[SrtCue] = list(state.get("merged_asr_cues") or [])
    max_retries = int(config.get("translation", {}).get("chunk_max_retries", 3))
    client = LLMClient.from_config(config)
    merge_prompt = prompt_for(config, "merge_zh_asr_srt")

    restitched_count = 0
    failed_count = 0

    if client.enabled():
        for cut in hard_cuts:
            try:
                merged_cues, ok = _restitch_one(client, merged_cues, cut, max_retries, merge_prompt)
                if ok:
                    restitched_count += 1
                else:
                    failed_count += 1
            except Exception as exc:
                logger.warning("restitch cut %s failed: %s", cut, exc)
                failed_count += 1
    else:
        logger.warning("restitch_merge_cuts: LLM disabled, skip restitch")
        failed_count = len(hard_cuts)

    merged_cues = reindex_cues(merged_cues)
    merged_srt = format_srt(merged_cues)
    write_text(config_path(config, "paths.merged_asr_srt"), merged_srt)
    report_path = config_path(config, "paths.reports_dir") / "restitch_merge_cuts_report.json"
    write_json(
        report_path,
        {
            "hard_cut_count": len(hard_cuts),
            "restitched_count": restitched_count,
            "failed_count": failed_count,
        },
    )
    state["raw_cues"] = merged_cues
    state["raw_srt"] = merged_srt
    state["merged_asr_cues"] = merged_cues
    state["merged_asr_srt"] = merged_srt
    state["merge_hard_cuts"] = []
    state.setdefault("reports", {})["restitch_merge_cuts_report"] = str(report_path)
    return state


def _restitch_one(
    client: LLMClient,
    cues: list[SrtCue],
    cut: dict,
    max_retries: int,
    merge_prompt: str,
) -> tuple[list[SrtCue], bool]:
    """对单个硬切点重合并。返回 (新 cues 列表, 是否成功)。"""
    cut_start_ms = int(cut.get("cut_start_ms", 0))
    # 定位后块首条:第一个 start_ms >= cut_start_ms 的 cue
    next_idx = 0
    for i, cue in enumerate(cues):
        if cue["start_ms"] >= cut_start_ms:
            next_idx = i
            break
    else:
        next_idx = len(cues)
    # 前块末尾 2 条,后块开头 2 条
    tail_start = max(0, next_idx - 2)
    head_end = min(len(cues), next_idx + 2)
    window = cues[tail_start:head_end]
    if len(window) < 2:
        return cues, False

    window_srt = format_srt(window)
    last_error: str | None = None
    for attempt in range(max_retries + 1):
        try:
            response = client.complete(
                merge_prompt,
                window_srt,
                window_srt,
            )
            remerged = clean_cues(parse_srt(response))
            if not remerged:
                last_error = "invalid SRT"
                continue
            # 校验重合并结果时间范围落在 window 范围内
            win_start = window[0]["start_ms"]
            win_end = window[-1]["end_ms"]
            if all(c["start_ms"] >= win_start and c["end_ms"] <= win_end for c in remerged):
                return cues[:tail_start] + remerged + cues[head_end:], True
            last_error = "remerged cues out of window range"
        except Exception as exc:
            last_error = str(exc)
            logger.warning("restitch attempt %d/%d failed: %s", attempt + 1, max_retries + 1, exc)
    logger.warning("restitch cut %s exhausted retries: %s", cut, last_error)
    return cues, False
