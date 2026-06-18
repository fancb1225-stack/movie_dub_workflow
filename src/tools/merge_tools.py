from __future__ import annotations

from src.state import SrtCue
from src.tools.srt_tools import make_cue, reindex_cues


def split_cues_by_gap(
    cues: list[SrtCue],
    max_gap_ms: int = 450,
    max_chunk_size: int = 200,
) -> tuple[list[list[SrtCue]], list[dict]]:
    """两阶段切块,供合并节点分块调用 LLM。

    1. 按 max_gap_ms 切:相邻 cue 间隙 > max_gap_ms 处断开。
       与 MERGE_ZH_ASR_SRT_PROMPT "间隙>500ms 不合并" 一致,不割裂可合并片段。
    2. 超 max_chunk_size 的块再硬切到 max_chunk_size:可能割裂连续片段,
       记录为 hard_cut,留给 restitch 节点局部 LLM 重合并修复。

    返回 (chunks, hard_cuts)。hard_cuts 每项形如
    {"cut_start_ms": 后块首条 start_ms, "cut_end_ms": 前块末条 end_ms},
    记录硬切点的时间边界,供 restitch 节点在合并结果中定位切点两侧。
    """
    if not cues:
        return [], []
    # 阶段 1:按间隙切
    gap_chunks: list[list[SrtCue]] = []
    current: list[SrtCue] = [cues[0]]
    for prev, cue in zip(cues, cues[1:]):
        gap = cue["start_ms"] - prev["end_ms"]
        if gap > max_gap_ms:
            gap_chunks.append(current)
            current = [cue]
        else:
            current.append(cue)
    gap_chunks.append(current)

    # 阶段 2:超 max_chunk_size 硬切
    chunks: list[list[SrtCue]] = []
    hard_cuts: list[dict] = []
    for block in gap_chunks:
        if len(block) <= max_chunk_size:
            chunks.append(block)
            continue
        for start in range(0, len(block), max_chunk_size):
            sub = block[start : start + max_chunk_size]
            if chunks:
                # 硬切点:前块末条 end_ms 与本 sub 首条 start_ms 之间的时间边界
                prev_last = chunks[-1][-1]
                cur_first = sub[0]
                hard_cuts.append(
                    {
                        "cut_end_ms": prev_last["end_ms"],
                        "cut_start_ms": cur_first["start_ms"],
                    }
                )
            chunks.append(sub)
    return chunks, hard_cuts


def merge_cues_by_rules(
    cues: list[SrtCue],
    max_chars: int,
    max_gap_ms: int,
    max_duration_ms: int,
) -> list[SrtCue]:
    if not cues:
        return []
    ordered = reindex_cues(cues)
    merged: list[SrtCue] = []
    current = ordered[0]
    for cue in ordered[1:]:
        if _can_merge(current, cue, max_chars, max_gap_ms, max_duration_ms):
            current = make_cue(
                current["index"],
                current["start_ms"],
                cue["end_ms"],
                _join_text(current["text"], cue["text"]),
            )
        else:
            merged.append(current)
            current = cue
    merged.append(current)
    return reindex_cues(merged)


def _can_merge(
    first: SrtCue,
    second: SrtCue,
    max_chars: int,
    max_gap_ms: int,
    max_duration_ms: int,
) -> bool:
    gap = second["start_ms"] - first["end_ms"]
    duration = second["end_ms"] - first["start_ms"]
    combined_chars = len(first["text"].replace("\n", "")) + len(
        second["text"].replace("\n", "")
    )
    return (
        0 <= gap <= max_gap_ms
        and duration <= max_duration_ms
        and combined_chars <= max_chars
    )


def _join_text(first: str, second: str) -> str:
    separator = "" if _looks_like_cjk(first + second) else " "
    return f"{first.rstrip()}{separator}{second.lstrip()}".strip()


def _looks_like_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)

