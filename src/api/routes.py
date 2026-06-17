from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from src.api.schemas import (
    BackgroundResponse,
    ExtractAudioResponse,
    JobListResponse,
    JobResponse,
    JobFilesResponse,
    LangGraphWorkflowResponse,
    MediaProbeResponse,
    OpenDirectoryResponse,
    PackageVideoRequest,
    PackageVideoResponse,
    SeparationResponse,
    SpeakerResponse,
)
from src.services.file_service import FileService
from src.services.job_service import JobService
from src.services.media_service import MediaService
from src.services.separation_service import SeparationService
from src.services.speaker_service import SpeakerService
from src.services.video_service import VideoService
from src.services.workflow_service import WorkflowService


router = APIRouter(prefix="/api")


def get_config(request: Request) -> dict[str, Any]:
    return request.app.state.config


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(config: dict[str, Any] = Depends(get_config)) -> dict[str, Any]:
    try:
        return JobService(config).list_jobs()
    except Exception as exc:
        raise _to_http_exception(exc) from exc


@router.post("/jobs", response_model=JobResponse)
async def create_job(
    file: UploadFile = File(...),
    config: dict[str, Any] = Depends(get_config),
) -> dict[str, Any]:
    try:
        return await JobService(config).create_job_from_upload(file)
    except Exception as exc:
        raise _to_http_exception(exc) from exc


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, config: dict[str, Any] = Depends(get_config)) -> dict[str, Any]:
    try:
        return JobService(config).get_job(job_id)
    except Exception as exc:
        raise _to_http_exception(exc) from exc


@router.get("/jobs/{job_id}/files", response_model=JobFilesResponse)
def list_job_files(
    job_id: str, config: dict[str, Any] = Depends(get_config)
) -> dict[str, Any]:
    try:
        return FileService(config).list_job_files(job_id)
    except Exception as exc:
        raise _to_http_exception(exc) from exc


@router.get("/jobs/{job_id}/files/download")
def download_job_file(
    job_id: str,
    path: str = Query(..., min_length=1),
    config: dict[str, Any] = Depends(get_config),
) -> FileResponse:
    try:
        file_path = FileService(config).resolve_job_file(job_id, path)
        return FileResponse(file_path, filename=file_path.name)
    except Exception as exc:
        raise _to_http_exception(exc) from exc


@router.post("/jobs/{job_id}/open-workdir", response_model=OpenDirectoryResponse)
def open_job_workdir(
    job_id: str, config: dict[str, Any] = Depends(get_config)
) -> dict[str, Any]:
    try:
        return FileService(config).open_job_directory(job_id)
    except Exception as exc:
        raise _to_http_exception(exc) from exc


@router.get("/jobs/{job_id}/media/probe", response_model=MediaProbeResponse)
def probe_job_media(
    job_id: str, config: dict[str, Any] = Depends(get_config)
) -> dict[str, Any]:
    try:
        return MediaService(config).probe_job(job_id)
    except Exception as exc:
        raise _to_http_exception(exc) from exc


@router.post("/jobs/{job_id}/media/extract-audio", response_model=ExtractAudioResponse)
def extract_job_audio(
    job_id: str, config: dict[str, Any] = Depends(get_config)
) -> dict[str, Any]:
    try:
        return MediaService(config).extract_audio_for_job(job_id)
    except Exception as exc:
        raise _to_http_exception(exc) from exc


@router.post("/jobs/{job_id}/audio/separate", response_model=SeparationResponse)
def separate_job_audio(
    job_id: str, config: dict[str, Any] = Depends(get_config)
) -> dict[str, Any]:
    try:
        return SeparationService(config).separate_job_audio(job_id)
    except Exception as exc:
        raise _to_http_exception(exc) from exc


@router.post("/jobs/{job_id}/audio/background", response_model=BackgroundResponse)
def get_or_create_background(
    job_id: str, config: dict[str, Any] = Depends(get_config)
) -> dict[str, Any]:
    try:
        return SeparationService(config).get_or_create_background(job_id)
    except Exception as exc:
        raise _to_http_exception(exc) from exc


@router.post("/jobs/{job_id}/speakers/identify", response_model=SpeakerResponse)
def identify_speakers(
    job_id: str, config: dict[str, Any] = Depends(get_config)
) -> dict[str, Any]:
    try:
        return SpeakerService(config).identify_placeholder_speakers(job_id)
    except Exception as exc:
        raise _to_http_exception(exc) from exc


@router.post("/jobs/{job_id}/workflow/langgraph", response_model=LangGraphWorkflowResponse)
def run_langgraph_workflow(
    job_id: str,
    max_reflection_rounds: int | None = Query(None),
    llm_timeout: int | None = Query(None),
    llm_max_retries: int | None = Query(None),
    tts_rate: float | None = Query(None),
    config: dict[str, Any] = Depends(get_config),
) -> dict[str, Any]:
    overrides = _build_workflow_overrides(max_reflection_rounds, llm_timeout, llm_max_retries, tts_rate)
    try:
        return WorkflowService(config).run_job_langgraph_workflow(job_id, overrides=overrides)
    except Exception as exc:
        raise _to_http_exception(exc) from exc


@router.post("/jobs/{job_id}/preprocess/stream")
def stream_preprocess(
    job_id: str, config: dict[str, Any] = Depends(get_config)
) -> StreamingResponse:
    def event_stream():
        try:
            for event in WorkflowService(config).run_job_preprocess_streaming(job_id):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            error = {"event": "error", "error": str(exc), "hint": "预处理执行失败。"}
            yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/jobs/{job_id}/workflow/langgraph/stream")
def stream_langgraph_workflow(
    job_id: str,
    max_reflection_rounds: int | None = Query(None),
    llm_timeout: int | None = Query(None),
    llm_max_retries: int | None = Query(None),
    tts_rate: float | None = Query(None),
    config: dict[str, Any] = Depends(get_config),
) -> StreamingResponse:
    overrides = _build_workflow_overrides(max_reflection_rounds, llm_timeout, llm_max_retries, tts_rate)
    def event_stream():
        try:
            for event in WorkflowService(config).run_job_langgraph_workflow_streaming(job_id, overrides=overrides):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            error = {"event": "error", "error": str(exc), "hint": "翻译与配音工作流执行失败。"}
            yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/jobs/{job_id}/workflow/langgraph/resume/stream")
def resume_langgraph_workflow_stream(
    job_id: str,
    max_reflection_rounds: int | None = Query(None),
    llm_timeout: int | None = Query(None),
    llm_max_retries: int | None = Query(None),
    tts_rate: float | None = Query(None),
    config: dict[str, Any] = Depends(get_config),
) -> StreamingResponse:
    overrides = _build_workflow_overrides(max_reflection_rounds, llm_timeout, llm_max_retries, tts_rate)
    def event_stream():
        try:
            for event in WorkflowService(config).resume_job_langgraph_workflow_streaming(job_id, overrides=overrides):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            error = {"event": "error", "error": str(exc), "hint": "恢复工作流失败。"}
            yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/jobs/{job_id}/artifacts/download")
def download_artifacts(
    job_id: str,
    config: dict[str, Any] = Depends(get_config),
) -> FileResponse:
    try:
        archive_path = FileService(config).create_artifact_archive(job_id)
        return FileResponse(
            archive_path,
            filename=archive_path.name,
            media_type="application/zip",
        )
    except Exception as exc:
        raise _to_http_exception(exc) from exc


@router.post("/jobs/{job_id}/video/package", response_model=PackageVideoResponse)
async def package_video(
    job_id: str,
    audio_file: UploadFile | None = File(None),
    output_filename: str = Query("final_en.mp4"),
    config: dict[str, Any] = Depends(get_config),
) -> dict[str, Any]:
    try:
        return await VideoService(config).package_job_video(
            job_id,
            audio_file=audio_file,
            output_filename=output_filename,
        )
    except Exception as exc:
        raise _to_http_exception(exc) from exc


def _to_http_exception(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _build_workflow_overrides(
    max_reflection_rounds: int | None,
    llm_timeout: int | None,
    llm_max_retries: int | None,
    tts_rate: float | None,
) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if max_reflection_rounds is not None:
        overrides["duration.max_reflection_rounds"] = max_reflection_rounds
    if llm_timeout is not None:
        overrides["llm.timeout"] = llm_timeout
    if llm_max_retries is not None:
        overrides["llm.max_retries"] = llm_max_retries
    if tts_rate is not None:
        # Frontend sends a multiplier (e.g. 1.3), edge_tts expects "+30%".
        if isinstance(tts_rate, float) and tts_rate >= 0:
            pct = round((tts_rate - 1) * 100)
            overrides["tts.rate"] = f"+{pct}%" if pct >= 0 else f"{pct}%"
        else:
            overrides["tts.rate"] = tts_rate
    return overrides
