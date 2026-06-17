from __future__ import annotations

import os
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from src.services.job_service import JobService


class FileService:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.jobs = JobService(config)

    def list_job_files(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get_job(job_id)
        job_dir = Path(job["paths"]["job_dir"]).resolve()
        files = [_file_entry(job_id, job_dir, path) for path in sorted(job_dir.rglob("*")) if path.is_file()]
        return {
            "job_id": job_id,
            "job_dir": str(job_dir),
            "file_count": len(files),
            "files": files,
        }

    def open_job_directory(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get_job(job_id)
        job_dir = Path(job["paths"]["job_dir"]).resolve()
        if not job_dir.exists():
            raise FileNotFoundError(f"Job directory does not exist: {job_dir}")
        _open_directory(job_dir)
        return {"job_id": job_id, "job_dir": str(job_dir), "opened": True}

    def resolve_job_file(self, job_id: str, relative_path: str) -> Path:
        job = self.jobs.get_job(job_id)
        job_dir = Path(job["paths"]["job_dir"]).resolve()
        target = (job_dir / relative_path).resolve()
        if not _is_relative_to(target, job_dir):
            raise ValueError(f"Path is outside the job directory: {relative_path}")
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"Job file not found: {relative_path}")
        return target

    def create_artifact_archive(self, job_id: str) -> Path:
        """Create a ZIP archive of all artifacts, excluding reports/ and job.json."""
        job = self.jobs.get_job(job_id)
        job_dir = Path(job["paths"]["job_dir"]).resolve()

        EXCLUDED_DIRS = {"reports"}
        EXCLUDED_FILES = {"job.json"}
        EXCLUDED_PATTERNS = {"artifacts_"}

        archive_path = job_dir / f"artifacts_{job_id[:8]}.zip"

        # Check if archive can be reused
        if archive_path.exists():
            archive_mtime = archive_path.stat().st_mtime
            needs_rebuild = False
            for file_path in job_dir.rglob("*"):
                if not file_path.is_file():
                    continue
                relative = file_path.relative_to(job_dir)
                if relative.parts[0] in EXCLUDED_DIRS:
                    continue
                if relative.name in EXCLUDED_FILES:
                    continue
                if any(p in relative.name for p in EXCLUDED_PATTERNS):
                    continue
                if file_path.stat().st_mtime > archive_mtime:
                    needs_rebuild = True
                    break
            if not needs_rebuild:
                return archive_path

        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in sorted(job_dir.rglob("*")):
                if not file_path.is_file():
                    continue
                relative = file_path.relative_to(job_dir)
                # Skip excluded items
                if relative.parts[0] in EXCLUDED_DIRS:
                    continue
                if relative.name in EXCLUDED_FILES:
                    continue
                if any(p in relative.name for p in EXCLUDED_PATTERNS):
                    continue
                zf.write(file_path, relative)
        return archive_path


def _file_entry(job_id: str, job_dir: Path, path: Path) -> dict[str, Any]:
    stat = path.stat()
    relative = path.relative_to(job_dir).as_posix()
    return {
        "name": path.name,
        "relative_path": relative,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "download_url": f"/api/jobs/{job_id}/files/download?path={quote(relative)}",
    }


def _open_directory(path: Path) -> None:
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    if os.name == "posix":
        command = ["open", str(path)] if sys_platform_is_macos() else ["xdg-open", str(path)]
        subprocess.Popen(command)
        return
    raise RuntimeError(f"Opening directories is not supported on this OS: {os.name}")


def sys_platform_is_macos() -> bool:
    import sys

    return sys.platform == "darwin"


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
