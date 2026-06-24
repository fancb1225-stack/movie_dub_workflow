from __future__ import annotations

from collections import Counter
from typing import Iterable

from src.state import SrtCue


def inherit_speaker_id(cue: SrtCue, source_cues: Iterable[SrtCue]) -> SrtCue:
    """Return cue with speaker_id inferred from overlapping source cues."""
    if cue.get("speaker_id"):
        return cue
    speaker_id = dominant_speaker_id(cue["start_ms"], cue["end_ms"], source_cues)
    if not speaker_id:
        return cue
    return {**cue, "speaker_id": speaker_id}


def inherit_speaker_ids(cues: Iterable[SrtCue], source_cues: Iterable[SrtCue]) -> list[SrtCue]:
    sources = list(source_cues)
    return [inherit_speaker_id(cue, sources) for cue in cues]


def dominant_speaker_id(
    start_ms: int,
    end_ms: int,
    source_cues: Iterable[SrtCue],
) -> str | None:
    """Pick the speaker with the largest time overlap in [start_ms, end_ms]."""
    weights: Counter[str] = Counter()
    for source in source_cues:
        speaker_id = source.get("speaker_id")
        if not speaker_id:
            continue
        overlap = min(end_ms, source["end_ms"]) - max(start_ms, source["start_ms"])
        if overlap > 0:
            weights[speaker_id] += overlap
        elif source["start_ms"] == start_ms and source["end_ms"] == end_ms:
            weights[speaker_id] += 1
    if not weights:
        return None
    return weights.most_common(1)[0][0]


def copy_timing_and_speaker(source: SrtCue, text: str) -> SrtCue:
    from src.tools.srt_tools import make_cue

    return make_cue(
        source["index"],
        source["start_ms"],
        source["end_ms"],
        text,
        source.get("speaker_id"),
    )
