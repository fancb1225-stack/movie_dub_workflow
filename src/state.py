from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class SrtCue(TypedDict):
    index: int
    start: str
    end: str
    start_ms: int
    end_ms: int
    text: str
    speaker_id: NotRequired[str]


class AsrWord(TypedDict):
    index: int
    word: str
    start_ms: int
    end_ms: int
    speaker_id: NotRequired[str]


class TtsSegment(TypedDict, total=False):
    index: int
    text: str
    start_ms: int
    end_ms: int
    path: str
    duration_ms: int
    success: bool
    error: str
    speaker_id: str
    provider: str
    voice_id: str
    speed: float


class DurationIssue(TypedDict, total=False):
    index: int
    start_ms: int
    end_ms: int
    subtitle_duration_ms: int
    tts_duration_ms: int
    overrun_ms: int
    ratio: float
    text: str
    en_text: str
    zh_text: str
    word_count: int
    wpm: int
    speaker_id: str
    issue_types: list[str]


class AdjustedPosition(TypedDict):
    index: int
    original_start_ms: int
    adjusted_start_ms: int
    shift_ms: int
    strategy: str           # "delay" | "shift_back" | "fallback" | "none"
    overlap_with_previous_ms: int


class WorkflowState(TypedDict, total=False):
    config: dict[str, Any]
    input_mode: str
    input_video_path: str
    source_audio_path: str
    vocals_path: str
    background_path: str
    mixed_audio_path: str
    final_video_path: str
    speaker_report: dict[str, Any]
    media_report: dict[str, Any]
    separation_report: dict[str, Any]
    asr_result: dict[str, Any]
    raw_words: list[AsrWord]
    raw_srt: str
    raw_cues: list[SrtCue]
    merged_asr_srt: str
    merged_asr_cues: list[SrtCue]
    merge_hard_cuts: list[dict[str, Any]]
    cleaned_srt: str
    cleaned_cues: list[SrtCue]
    corrected_srt: str
    corrected_cues: list[SrtCue]
    plot_summary: str
    en_translated_srt: str
    en_translated_cues: list[SrtCue]
    final_srt: str
    final_cues: list[SrtCue]
    tts_segments: list[TtsSegment]
    duration_issues: list[DurationIssue]
    reflection_rounds: int
    narration_wav_path: str
    narration_mp3_path: str
    reports: dict[str, Any]
    errors: list[str]
