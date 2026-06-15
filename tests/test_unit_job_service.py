from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

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


class JobServiceTests(unittest.TestCase):
    def test_create_job_from_upload_writes_input_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = JobService(_config(tmp))
            upload = FakeUpload("clip.mp4", b"fake mp4 bytes")

            job = asyncio.run(service.create_job_from_upload(upload))

            self.assertEqual(job["status"], "created")
            self.assertEqual(job["input_kind"], "mp4")
            self.assertTrue(Path(job["paths"]["input"]).exists())
            self.assertTrue((Path(job["paths"]["job_dir"]) / "job.json").exists())

    def test_create_job_rejects_unsupported_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = JobService(_config(tmp))

            with self.assertRaises(ValueError):
                asyncio.run(service.create_job_from_upload(FakeUpload("clip.txt", b"x")))

    def test_update_job_merges_artifacts_and_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = JobService(_config(tmp))
            job = asyncio.run(service.create_job_from_upload(FakeUpload("audio.mp3", b"x")))

            updated = service.update_job(
                job["job_id"],
                status="tested",
                artifacts={"source_audio_wav": "a.wav"},
                reports={"media_report": "report.json"},
            )

            self.assertEqual(updated["status"], "tested")
            self.assertEqual(updated["artifacts"]["source_audio_wav"], "a.wav")
            self.assertEqual(updated["reports"]["media_report"], "report.json")


def _config(tmp: str) -> dict:
    return {
        "project_root": tmp,
        "jobs": {"root_dir": "jobs"},
    }


if __name__ == "__main__":
    unittest.main()

