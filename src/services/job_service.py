from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from src.config import config_path
from src.tools.file_tools import ensure_dir, read_json, write_json


ALLOWED_UPLOAD_SUFFIXES = {".mp4", ".mp3", ".wav"}
MAX_LIST_JOBS = 50


class UploadFileLike(Protocol):
    filename: str | None

    async def read(self, size: int = -1) -> bytes:
        ...


class JobService:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.root_dir = ensure_dir(config_path(config, "jobs.root_dir"))

    async def create_job_from_upload(self, file: UploadFileLike) -> dict[str, Any]:
        filename = file.filename or "input.bin"
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_UPLOAD_SUFFIXES:
            allowed = ", ".join(sorted(ALLOWED_UPLOAD_SUFFIXES))
            raise ValueError(f"Unsupported upload type '{suffix}'. Allowed: {allowed}")
        job_id = uuid.uuid4().hex
        job_dir = self.job_dir(job_id)
        input_dir = ensure_dir(job_dir / "input")
        ensure_dir(job_dir / "media")
        ensure_dir(job_dir / "reports")
        ensure_dir(job_dir / "video")
        input_path = input_dir / f"original{suffix}"
        await _save_upload(file, input_path)
        job = {
            "job_id": job_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "status": "created",
            "original_filename": filename,
            "input_kind": suffix.lstrip("."),
            "paths": {
                "job_dir": str(job_dir),
                "input": str(input_path),
                "media_dir": str(job_dir / "media"),
                "reports_dir": str(job_dir / "reports"),
                "video_dir": str(job_dir / "video"),
            },
            "artifacts": {},
            "reports": {},
        }
        self.save_job(job)
        return job

    def get_job(self, job_id: str) -> dict[str, Any]:
        path = self.job_json_path(job_id)
        if not path.exists():
            raise FileNotFoundError(f"Job not found: {job_id}")
        return read_json(path)

    def save_job(self, job: dict[str, Any]) -> dict[str, Any]:
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        write_json(self.job_json_path(str(job["job_id"])), job)
        return job

    def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        artifacts: dict[str, Any] | None = None,
        reports: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job = self.get_job(job_id)
        if status is not None:
            job["status"] = status
        if artifacts:
            job.setdefault("artifacts", {}).update(artifacts)
        if reports:
            job.setdefault("reports", {}).update(reports)
        if extra:
            job.update(extra)
        return self.save_job(job)

    def job_dir(self, job_id: str) -> Path:
        return self.root_dir / job_id

    def job_json_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "job.json"

    def list_jobs(self) -> dict[str, Any]:
        """List all jobs, most recent first, up to MAX_LIST_JOBS entries."""
        jobs: list[dict[str, Any]] = []
        if not self.root_dir.exists():
            return {"jobs": [], "total": 0}
        for child in sorted(self.root_dir.iterdir(), key=_created_at_key, reverse=True):
            json_path = child / "job.json"
            if not json_path.exists():
                continue
            try:
                data = read_json(json_path)
            except Exception:
                continue
            jobs.append({
                "job_id": data.get("job_id", ""),
                "status": data.get("status", ""),
                "original_filename": data.get("original_filename", ""),
                "input_kind": data.get("input_kind", ""),
                "created_at": data.get("created_at", ""),
            })
            if len(jobs) >= MAX_LIST_JOBS:
                break
        return {"jobs": jobs, "total": len(jobs)}


async def _save_upload(file: UploadFileLike, path: Path) -> None:
    with path.open("wb") as writer:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            writer.write(chunk)


def _created_at_key(child: Path) -> str:
    """Extract created_at from job.json for sorting; fallback to empty string."""
    json_path = child / "job.json"
    if json_path.exists():
        try:
            return str(read_json(json_path).get("created_at", ""))
        except Exception:
            pass
    return ""
