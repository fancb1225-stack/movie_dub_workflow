from __future__ import annotations

from src.state import SrtCue
from src.tools.srt_tools import make_cue, parse_srt


def assign_placeholder_speakers_from_srt(srt_text: str) -> list[dict[str, object]]:
    cues = parse_srt(srt_text)
    return [
        {
            "index": cue["index"],
            "start_ms": cue["start_ms"],
            "end_ms": cue["end_ms"],
            "speaker_id": "speaker_1",
            "text": cue["text"],
        }
        for cue in cues
    ]


def assign_placeholder_speakers_from_duration(duration_ms: int) -> list[dict[str, object]]:
    return [
        {
            "index": 1,
            "start_ms": 0,
            "end_ms": max(duration_ms, 0),
            "speaker_id": "speaker_1",
            "text": "",
        }
    ]


def add_placeholder_speaker_to_cues(cues: list[SrtCue]) -> list[SrtCue]:
    return [{**cue, "speaker_id": "speaker_1"} for cue in cues]


def duration_to_cue(duration_ms: int) -> SrtCue:
    return make_cue(1, 0, max(duration_ms, 1000), "")
