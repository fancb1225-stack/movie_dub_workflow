from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from src.api.schemas import (
    BackgroundResponse,
    ExtractAudioResponse,
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
    job_id: str, config: dict[str, Any] = Depends(get_config)
) -> dict[str, Any]:
    try:
        return WorkflowService(config).run_job_langgraph_workflow(job_id)
    except Exception as exc:
        raise _to_http_exception(exc) from exc


@router.post("/jobs/{job_id}/video/package", response_model=PackageVideoResponse)
def package_video(
    job_id: str,
    request: PackageVideoRequest,
    config: dict[str, Any] = Depends(get_config),
) -> dict[str, Any]:
    try:
        return VideoService(config).package_job_video(
            job_id,
            audio_path=request.audio_path,
            output_filename=request.output_filename,
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
