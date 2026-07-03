from __future__ import annotations

from pathlib import Path
from typing import Any

from src.state import AsrWord, SrtCue
from src.tools.file_tools import write_json
from src.tools.srt_tools import make_cue, reindex_cues


_PUNCT_CHARS = "，。！？；,.!?;、：:"


def write_asr_words_json(path: str | Path, words: list[AsrWord]) -> str:
    return write_json(path, words)


def split_words_to_short_cues(
    words: list[AsrWord],
    max_duration_ms: int = 6000,
    max_chars: int = 30,
    punct: str = _PUNCT_CHARS,
) -> list[SrtCue]:
    if not words:
        return []
    punct_set = set(punct)
    cues: list[SrtCue] = []
    buffer: list[AsrWord] = []
    buffer_speaker: str | None = None

    def flush() -> None:
        nonlocal buffer, buffer_speaker
        if not buffer:
            buffer_speaker = None
            return
        text = "".join(w["word"] for w in buffer).strip()
        if text:
            cue = make_cue(0, buffer[0]["start_ms"], buffer[-1]["end_ms"], text)
            if buffer_speaker:
                cue["speaker_id"] = buffer_speaker
            cues.append(cue)
        buffer = []
        buffer_speaker = None

    for word in words:
        word_speaker = word.get("speaker_id")
        current_text = "".join(w["word"] for w in buffer)
        ends_with_punct = bool(word["word"]) and word["word"][-1] in punct_set
        should_break = False
        if buffer:
            projected_duration = word["end_ms"] - buffer[0]["start_ms"]
            if word_speaker and buffer_speaker and word_speaker != buffer_speaker:
                should_break = True
            elif projected_duration > max_duration_ms:
                should_break = True
            elif len(current_text) + len(word["word"]) > max_chars:
                should_break = True
        if should_break:
            flush()
        buffer.append(word)
        if word_speaker:
            buffer_speaker = word_speaker
        if ends_with_punct:
            flush()
    flush()
    return reindex_cues(cues)


def cues_from_asr_words_file(path: str | Path) -> list[SrtCue]:
    from src.tools.file_tools import read_json

    data = read_json(path)
    if not isinstance(data, list):
        return []
    return split_words_to_short_cues([_word_from_dict(item) for item in data])


def _word_from_dict(item: Any) -> AsrWord:
    word: AsrWord = {
        "index": int(item.get("index", 0)),
        "word": str(item.get("word", "")),
        "start_ms": int(item.get("start_ms", 0)),
        "end_ms": int(item.get("end_ms", 0)),
    }
    if item.get("speaker_id"):
        word["speaker_id"] = str(item["speaker_id"])
    return word
