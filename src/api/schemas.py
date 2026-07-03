from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.video_types import DEFAULT_VIDEO_TYPE


class JobResponse(BaseModel):
    job_id: str
    status: str
    original_filename: str
    input_kind: str
    video_type: str = DEFAULT_VIDEO_TYPE
    paths: dict[str, str]
    artifacts: dict[str, Any] = Field(default_factory=dict)
    reports: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class MediaProbeResponse(BaseModel):
    job_id: str
    input_path: str
    has_audio: bool
    has_video: bool
    duration_ms: int
    stream_count: int
    format: str
    probe: dict[str, Any] = Field(default_factory=dict)


class ExtractAudioResponse(MediaProbeResponse):
    status: str
    source_audio_wav: str
    audio_sample_rate: int


class SeparationResponse(BaseModel):
    job_id: str
    status: str
    source_audio: str | None = None
    vocals_wav: str | None = None
    background_wav: str | None = None
    provider: str | None = None
    model: str | None = None
    error: str | None = None
    hint: str | None = None


class BackgroundResponse(BaseModel):
    job_id: str
    status: str
    background_wav: str | None = None
    source: str
    error: str | None = None
    hint: str | None = None


class AsrRunOptions(BaseModel):
    language: str | None = None
    enable_punc: bool | None = None
    enable_itn: bool | None = None
    enable_ddc: bool | None = None
    enable_speaker_info: bool | None = None
    max_query_attempts: int | None = Field(None, ge=1)
    poll_interval_seconds: float | None = Field(None, ge=0)


class AsrRunRequest(BaseModel):
    asr: AsrRunOptions | None = None


class AsrSettingsResponse(BaseModel):
    provider: str
    video_type: str
    defaults: dict[str, Any]
    fields: dict[str, dict[str, Any]]
    language_options: list[dict[str, str]]
    tos: dict[str, Any]
    official: dict[str, str]


class AsrResponse(BaseModel):
    job_id: str
    status: str
    input_audio: str
    raw_words: str
    asr_report: str
    provider: str | None = None
    subtitle_count: int | None = None
    speakers: list[str] = Field(default_factory=list)


class PackageVideoRequest(BaseModel):
    output_filename: str = "final_en.mp4"


class PackageVideoResponse(BaseModel):
    job_id: str
    status: str
    input_video: str
    replacement_audio: str
    final_video: str
    subtitles: str


class LangGraphWorkflowResponse(BaseModel):
    job_id: str
    status: str
    source: str | None = None
    workflow_dir: str | None = None
    asr_provider: str | None = None
    used_mock_asr: bool | None = None
    input_audio: str | None = None
    background_audio: str | None = None
    raw_srt: str | None = None
    final_srt: str | None = None
    narration_wav: str | None = None
    narration_mp3: str | None = None
    pipeline_report: str | None = None
    report: str | None = None
    error: str | None = None
    hint: str | None = None


class VoiceOptionEntry(BaseModel):
    voice_id: str
    label: str
    original_label: str
    language: str


class VoiceOptionsResponse(BaseModel):
    voices: list[VoiceOptionEntry]


class HealthResponse(BaseModel):
    status: str


class JobFileEntry(BaseModel):
    name: str
    relative_path: str
    size_bytes: int
    modified_at: str
    download_url: str


class JobFilesResponse(BaseModel):
    job_id: str
    job_dir: str
    file_count: int
    files: list[JobFileEntry]


class OpenDirectoryResponse(BaseModel):
    job_id: str
    job_dir: str
    opened: bool


class JobListItem(BaseModel):
    job_id: str
    status: str
    original_filename: str
    input_kind: str
    video_type: str = DEFAULT_VIDEO_TYPE
    created_at: str


class JobListResponse(BaseModel):
    jobs: list[JobListItem]
    total: int
