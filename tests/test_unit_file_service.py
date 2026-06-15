from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from src.services.file_service import FileService
from src.services.job_service import JobService


class FakeUpload:
    def __init__(self, filename: str, payload: bytes):
        self.filename = filename
        self._payload = payload
        self._offset = 0

    async def read(self, size: int = -1) -> bytes:
        if self._offset >= len(self._payload):
            return b""
        if size < 0:
            size = len(self._payload) - self._offset
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class FileServiceTests(unittest.TestCase):
    def test_list_job_files_includes_uploaded_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            job = asyncio.run(
                JobService(config).create_job_from_upload(FakeUpload("clip.mp4", b"abc"))
            )

            listing = FileService(config).list_job_files(job["job_id"])

            paths = {entry["relative_path"] for entry in listing["files"]}
            self.assertIn("input/original.mp4", paths)
            self.assertIn("job.json", paths)

    def test_resolve_job_file_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            job = asyncio.run(
                JobService(config).create_job_from_upload(FakeUpload("clip.mp4", b"abc"))
            )

            with self.assertRaises(ValueError):
                FileService(config).resolve_job_file(job["job_id"], "../outside.txt")

    def test_resolve_job_file_returns_existing_job_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            job = asyncio.run(
                JobService(config).create_job_from_upload(FakeUpload("clip.mp4", b"abc"))
            )

            path = FileService(config).resolve_job_file(job["job_id"], "input/original.mp4")

            self.assertEqual(path.read_bytes(), b"abc")


def _config(tmp: str) -> dict:
    return {
        "project_root": tmp,
        "jobs": {"root_dir": "jobs"},
    }


if __name__ == "__main__":
    unittest.main()

