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


class DurationIssue(TypedDict):
    index: int
    start_ms: int
    end_ms: int
    subtitle_duration_ms: int
    tts_duration_ms: int
    overrun_ms: int
    ratio: float
    text: str


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
    raw_srt: str
    raw_cues: list[SrtCue]
    cleaned_srt: str
    cleaned_cues: list[SrtCue]
    merged_before_critic_srt: str
    merged_before_critic_cues: list[SrtCue]
    corrected_srt: str
    corrected_cues: list[SrtCue]
    merged_after_critic_srt: str
    merged_after_critic_cues: list[SrtCue]
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
