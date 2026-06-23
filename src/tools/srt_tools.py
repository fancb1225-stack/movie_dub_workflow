from __future__ import annotations

import html
import re
from typing import Iterable

from src.state import SrtCue


TIME_PATTERN = re.compile(
    r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{3})"
)


def parse_srt(srt_text: str) -> list[SrtCue]:
    normalized = srt_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    blocks = re.split(r"\n\s*\n", normalized)
    cues: list[SrtCue] = []
    for block in blocks:
        cue = _parse_block(block)
        if cue is not None:
            cues.append(cue)
    return reindex_cues(cues)


def format_srt(cues: Iterable[SrtCue], include_speaker: bool = False) -> str:
    blocks: list[str] = []
    for cue in reindex_cues(list(cues)):
        text = cue["text"].strip()
        if include_speaker and cue.get("speaker_id"):
            text = f"[{cue['speaker_id']}] {text}"
        blocks.append(
            "\n".join(
                [
                    str(cue["index"]),
                    f'{cue["start"]} --> {cue["end"]}',
                    text,
                ]
            )
        )
    return "\n\n".join(blocks).strip() + "\n"


def clean_cues(cues: Iterable[SrtCue]) -> list[SrtCue]:
    cleaned: list[SrtCue] = []
    for cue in cues:
        text = clean_text(cue["text"])
        if not text:
            continue
        if cue["end_ms"] <= cue["start_ms"]:
            continue
        cleaned.append({**cue, "text": text})
    return reindex_cues(cleaned)


def clean_text(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\ufeff", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return text.strip()


def seconds_to_srt_time(seconds: float) -> str:
    return ms_to_srt_time(int(round(seconds * 1000)))


def ms_to_srt_time(ms: int) -> str:
    if ms < 0:
        ms = 0
    hours = ms // 3_600_000
    ms %= 3_600_000
    minutes = ms // 60_000
    ms %= 60_000
    seconds = ms // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def srt_time_to_ms(value: str) -> int:
    match = TIME_PATTERN.fullmatch(value.strip())
    if not match:
        raise ValueError(f"Invalid SRT timestamp: {value}")
    hours = int(match.group("h"))
    minutes = int(match.group("m"))
    seconds = int(match.group("s"))
    millis = int(match.group("ms"))
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def make_cue(index: int, start_ms: int, end_ms: int, text: str) -> SrtCue:
    return {
        "index": index,
        "start": ms_to_srt_time(start_ms),
        "end": ms_to_srt_time(end_ms),
        "start_ms": start_ms,
        "end_ms": end_ms,
        "text": clean_text(text),
    }


def reindex_cues(cues: list[SrtCue]) -> list[SrtCue]:
    reindexed: list[SrtCue] = []
    for idx, cue in enumerate(sorted(cues, key=lambda item: item["start_ms"]), start=1):
        reindexed.append(
            {
                **cue,
                "index": idx,
                "start": ms_to_srt_time(cue["start_ms"]),
                "end": ms_to_srt_time(cue["end_ms"]),
            }
        )
    return reindexed


def replace_text_for_indices(
    cues: Iterable[SrtCue], replacements: dict[int, str]
) -> list[SrtCue]:
    updated: list[SrtCue] = []
    for cue in cues:
        text = replacements.get(cue["index"], cue["text"])
        updated.append({**cue, "text": clean_text(text)})
    return updated


def _parse_block(block: str) -> SrtCue | None:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    index = 0
    time_line_pos = 0
    if lines[0].isdigit():
        index = int(lines[0])
        time_line_pos = 1
    time_line = lines[time_line_pos]
    if "-->" not in time_line:
        return None
    start_raw, end_raw = [part.strip() for part in time_line.split("-->", 1)]
    start_match = TIME_PATTERN.search(start_raw)
    end_match = TIME_PATTERN.search(end_raw)
    if start_match is None or end_match is None:
        return None
    start = start_match.group(0)
    end = end_match.group(0)
    start_ms = srt_time_to_ms(start)
    end_ms = srt_time_to_ms(end)
    text = "\n".join(lines[time_line_pos + 1 :])
    if index <= 0:
        index = len(lines)
    return make_cue(index, start_ms, end_ms, text)

