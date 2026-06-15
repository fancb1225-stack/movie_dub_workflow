from __future__ import annotations

from src.state import SrtCue
from src.tools.srt_tools import make_cue, reindex_cues


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

