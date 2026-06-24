from __future__ import annotations

from pathlib import Path
from typing import Any

from src.state import AsrWord, SrtCue
from src.tools.file_tools import write_json
from src.tools.srt_tools import make_cue, reindex_cues


# 标点切句集合:中文与英文常用句末/句中标点。
_PUNCT_CHARS = "，。！？；,.!?;、:："


def extract_whisperx_words(
    result: dict[str, Any], speaker_normalize: bool = True
) -> list[AsrWord]:
    """从 whisperx align + diarize 后的 result 提取词级时间戳。

    优先 result["word_segments"];回退遍历 segment["words"]。
    每词带 speaker_id,来源优先级:word["speaker"] > 所属 segment["speaker"]。
    缺 start/end 的词用前后词/segment 边界补齐,保证时间戳单调递增。

    纯函数,不依赖 whisperx 运行时,便于单测。
    """
    raw_words = _collect_raw_words(result)
    if not raw_words:
        return []

    segment_boundaries = _segment_boundaries(result)
    words: list[AsrWord] = []
    prev_end_ms: int | None = None
    for idx, raw in enumerate(raw_words, start=1):
        start_ms = _coerce_ms(raw.get("start"))
        end_ms = _coerce_ms(raw.get("end"))
        # 缺失时间戳时,用前词 end 或 segment 边界补齐
        if start_ms is None:
            start_ms = prev_end_ms if prev_end_ms is not None else _nearest_boundary(segment_boundaries, 0, lower=True)
        if end_ms is None or end_ms < start_ms:
            end_ms = max(start_ms, start_ms + 1)
        # 单调递增保护
        if prev_end_ms is not None and start_ms < prev_end_ms:
            start_ms = prev_end_ms
            if end_ms < start_ms:
                end_ms = start_ms + 1
        speaker = raw.get("speaker") or raw.get("speaker_id")
        word: AsrWord = {
            "index": idx,
            "word": str(raw.get("word", "")).strip(),
            "start_ms": start_ms,
            "end_ms": end_ms,
        }
        if speaker:
            word["speaker_id"] = _normalize_speaker(str(speaker)) if speaker_normalize else str(speaker)
        words.append(word)
        prev_end_ms = end_ms
    return words


def _collect_raw_words(result: dict[str, Any]) -> list[dict[str, Any]]:
    """收集词级原始数据,优先 word_segments,回退 segment['words']。"""
    word_segments = result.get("word_segments")
    if isinstance(word_segments, list) and word_segments:
        return list(word_segments)
    collected: list[dict[str, Any]] = []
    for segment in result.get("segments", []):
        if not isinstance(segment, dict):
            continue
        seg_speaker = segment.get("speaker")
        for word in segment.get("words", []) or []:
            if isinstance(word, dict):
                # 词未自带 speaker 时继承所属 segment 的 speaker
                if not word.get("speaker") and seg_speaker:
                    word = {**word, "speaker": seg_speaker}
                collected.append(word)
    return collected


def _segment_boundaries(result: dict[str, Any]) -> list[tuple[int, int]]:
    """提取每个 segment 的 (start_ms, end_ms),用于补齐缺失时间戳。"""
    boundaries: list[tuple[int, int]] = []
    for segment in result.get("segments", []):
        if not isinstance(segment, dict):
            continue
        start = _coerce_ms(segment.get("start"))
        end = _coerce_ms(segment.get("end"))
        if start is not None and end is not None:
            boundaries.append((start, end))
    return boundaries


def _nearest_boundary(
    boundaries: list[tuple[int, int]], value: int, *, lower: bool
) -> int:
    """在 segment 边界中取 >=value 的最小起点(lower=True)或最接近的边界。"""
    if not boundaries:
        return 0
    starts = [b[0] for b in boundaries]
    if lower:
        candidates = [s for s in starts if s >= value]
        return min(candidates) if candidates else max(starts)
    return min(starts, key=lambda s: abs(s - value))


def _coerce_ms(value: Any) -> int | None:
    """把 whisperx 秒级 float 统一成毫秒 int。无效值返回 None。"""
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num < 0:
        return 0
    return max(0, int(round(num * 1000)))


def _normalize_speaker(label: str) -> str:
    """SPEAKER_00 -> speaker_1, SPEAKER_01 -> speaker_2。无法解析时原样返回。"""
    try:
        num = int(label.rsplit("_", 1)[-1])
        return f"speaker_{num + 1}"
    except (ValueError, IndexError):
        return label


def write_asr_words_json(path: str | Path, words: list[AsrWord]) -> str:
    """把词级时间戳写入 JSON,复用 file_tools.write_json。"""
    return write_json(path, words)


def split_words_to_short_cues(
    words: list[AsrWord],
    max_duration_ms: int = 6000,
    max_chars: int = 30,
    punct: str = _PUNCT_CHARS,
) -> list[SrtCue]:
    """标点+时长+字数组合切短句 cue(带 speaker_id)。

    断句条件(满足任一即断开):
    - 当前词尾部带切分标点
    - 累计时长超过 max_duration_ms
    - 累计字数超过 max_chars
    - speaker 切换

    复用 srt_tools.make_cue/reindex_cues。
    """
    if not words:
        return []
    punct_set = set(punct)
    cues: list[SrtCue] = []
    buffer: list[AsrWord] = []
    buffer_speaker: str | None = None

    def _flush() -> None:
        nonlocal buffer, buffer_speaker
        if not buffer:
            buffer_speaker = None
            return
        text = "".join(w["word"] for w in buffer).strip()
        if text:
            start_ms = buffer[0]["start_ms"]
            end_ms = buffer[-1]["end_ms"]
            cue = make_cue(0, start_ms, end_ms, text)
            if buffer_speaker:
                cue["speaker_id"] = buffer_speaker
            cues.append(cue)
        buffer = []
        buffer_speaker = None

    for word in words:
        word_speaker = word.get("speaker_id")
        current_text = "".join(w["word"] for w in buffer)
        ends_with_punct = bool(word["word"]) and word["word"][-1] in punct_set
        # 判定是否需在加入当前词前断句
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
            _flush()
        buffer.append(word)
        if word_speaker:
            buffer_speaker = word_speaker
        # 标点处断句:加入该词后立即 flush
        if ends_with_punct:
            _flush()
    _flush()
    return reindex_cues(cues)


def cues_from_asr_words_file(path: str | Path) -> list[SrtCue]:
    """从 words.json 重建短句 cues,供 workflow 入口使用。"""
    from src.tools.file_tools import read_json

    data = read_json(path)
    if not isinstance(data, list):
        return []
    return split_words_to_short_cues([_word_from_dict(item) for item in data])


def _word_from_dict(item: Any) -> AsrWord:
    """把 dict(可能来自 JSON 反序列化)规整为 AsrWord。"""
    word: AsrWord = {
        "index": int(item.get("index", 0)),
        "word": str(item.get("word", "")),
        "start_ms": int(item.get("start_ms", 0)),
        "end_ms": int(item.get("end_ms", 0)),
    }
    if item.get("speaker_id"):
        word["speaker_id"] = str(item["speaker_id"])
    return word
