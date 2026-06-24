from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.config import config_path
from src.llm_client import LLMClient
from src.prompt_registry import prompt_for
from src.state import SrtCue, WorkflowState
from src.tools.cue_tools import inherit_speaker_ids
from src.tools.file_tools import write_json, write_text
from src.tools.merge_tools import split_cues_by_gap
from src.tools.srt_tools import clean_cues, format_srt, ms_to_srt_time, parse_srt, reindex_cues

logger = logging.getLogger(__name__)


def merge_zh_asr_srt(state: WorkflowState) -> WorkflowState:
    logger.info("merge_zh_asr_srt: entering node")
    config = state["config"]
    raw_cues = state.get("raw_cues") or clean_cues(parse_srt(state.get("raw_srt", "")))
    # ASR 主产物已改为词级 JSON;此处由 raw_cues 派生短句 SRT 落盘,
    # 满足 raw_srt artifact/API/resume 对 zh_raw.srt 的文件契约。
    raw_srt_text = format_srt(raw_cues)
    write_text(config_path(config, "paths.asr_srt"), raw_srt_text)
    state["raw_srt"] = raw_srt_text
    srt_config = config.get("srt", {})
    max_gap_ms = int(srt_config.get("merge_max_gap_ms", 450))
    max_retries = int(config.get("translation", {}).get("chunk_max_retries", 3))
    max_parallel = max(1, int(config.get("translation", {}).get("max_parallel_chunks", 3)))

    client = LLMClient.from_config(config)
    chunks, hard_cuts = split_cues_by_gap(raw_cues, max_gap_ms=max_gap_ms)
    merge_prompt = prompt_for(config, "merge_zh_asr_srt")

    used_fallback = False
    error: str | None = None
    failed_chunks: list[int] = []

    if not client.enabled():
        merged_cues = raw_cues
        used_fallback = True
        error = "LLM merge is disabled; original ASR SRT was used."
    elif len(chunks) <= 1:
        # 单块:走原逻辑(单次 LLM 调用 + snap + 逐条容错)
        merged_cues, used_fallback, error = _merge_single(client, raw_cues, max_retries, merge_prompt)
        if used_fallback:
            failed_chunks = [1]
    else:
        # 多块:并发合并 + 块级重试容错
        merged_cues, failed_chunks, error = _merge_chunks_concurrent(
            client, chunks, max_retries, max_parallel, merge_prompt
        )
        used_fallback = len(failed_chunks) == len(chunks)

    merged_cues = reindex_cues(inherit_speaker_ids(merged_cues, raw_cues))
    merged_srt = format_srt(merged_cues)
    write_text(config_path(config, "paths.merged_asr_srt"), merged_srt)
    write_json(config_path(config, "paths.merged_asr_srt").with_suffix(".cues.json"), merged_cues)
    report_path = config_path(config, "paths.reports_dir") / "merge_zh_asr_report.json"
    write_json(
        report_path,
        {
            "input_cue_count": len(raw_cues),
            "output_cue_count": len(merged_cues),
            "used_fallback": used_fallback,
            "chunk_count": len(chunks),
            "hard_cut_count": len(hard_cuts),
            "failed_chunks": failed_chunks,
            "error": error,
        },
    )
    state["raw_cues"] = merged_cues
    state["raw_srt"] = merged_srt
    state["merged_asr_cues"] = merged_cues
    state["merged_asr_srt"] = merged_srt
    state["merge_hard_cuts"] = hard_cuts
    state.setdefault("reports", {})["merge_zh_asr_report"] = str(report_path)
    return state


def _merge_single(
    client: LLMClient, raw_cues: list[SrtCue], max_retries: int, merge_prompt: str
) -> tuple[list[SrtCue], bool, str | None]:
    """单块合并:重试 max_retries 次,成功返回合并结果,全失败回退源 cue。"""
    fallback_srt = format_srt(raw_cues)
    last_error: str | None = None
    for attempt in range(max_retries + 1):
        try:
            response = client.complete(merge_prompt, fallback_srt, fallback_srt)
            normalized_cues = _snap_timestamps_to_source_boundaries(
                clean_cues(parse_srt(response)), raw_cues
            )
            merged_cues, err = _parse_or_fallback(normalized_cues, raw_cues)
            if merged_cues is not raw_cues:
                return merged_cues, False, None
            last_error = err or "LLM merge returned invalid result"
        except Exception as exc:
            last_error = f"LLM merge request failed: {exc}"
            logger.warning("merge single attempt %d/%d failed: %s", attempt + 1, max_retries + 1, exc)
    return raw_cues, True, last_error


def _merge_chunks_concurrent(
    client: LLMClient,
    chunks: list[list[SrtCue]],
    max_retries: int,
    max_parallel: int,
    merge_prompt: str,
) -> tuple[list[SrtCue], list[int], str | None]:
    """多块并发合并,块级重试,失败块用源 cue 占位。"""
    worker_count = min(max_parallel, max(1, len(chunks)))
    results: dict[int, list[SrtCue]] = {}
    failed: list[int] = []
    last_error: str | None = None
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(_merge_chunk, client, chunk, idx, max_retries, merge_prompt): idx
            for idx, chunk in enumerate(chunks)
        }
        for future in as_completed(futures):
            idx, merged, chunk_failed, err = future.result()
            results[idx] = merged
            if chunk_failed:
                failed.append(idx + 1)
                if err:
                    last_error = err
    merged_cues: list[SrtCue] = []
    for idx in range(len(chunks)):
        merged_cues.extend(results.get(idx, chunks[idx]))
    return merged_cues, sorted(failed), last_error


def _merge_chunk(
    client: LLMClient,
    chunk_cues: list[SrtCue],
    chunk_index: int,
    max_retries: int,
    merge_prompt: str,
) -> tuple[int, list[SrtCue], bool, str | None]:
    """合并单个分块,失败重试;耗尽用源 cue 占位。
    返回 (chunk_index, merged_cues, failed, error)。"""
    chunk_srt = format_srt(chunk_cues)
    last_error: str | None = None
    for attempt in range(max_retries + 1):
        try:
            response = client.complete(merge_prompt, chunk_srt, chunk_srt)
            normalized = _snap_timestamps_to_source_boundaries(
                clean_cues(parse_srt(response)), chunk_cues
            )
            merged, err = _parse_or_fallback(normalized, chunk_cues)
            if merged is not chunk_cues:
                return chunk_index, merged, False, None
            last_error = err or "invalid result"
        except Exception as exc:
            last_error = f"LLM merge chunk {chunk_index + 1} failed: {exc}"
            logger.warning(
                "merge chunk %d attempt %d/%d failed: %s",
                chunk_index + 1, attempt + 1, max_retries + 1, exc,
            )
    logger.error("merge chunk %d exhausted retries; fallback to source cues", chunk_index + 1)
    return chunk_index, chunk_cues, True, last_error



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
            kept.append(inherit_speaker_ids([cue], fallback_cues)[0])
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
