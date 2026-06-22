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

    def test_create_job_from_wav_upload_writes_input_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = JobService(_config(tmp))
            upload = FakeUpload("voice.wav", b"fake wav bytes")

            job = asyncio.run(service.create_job_from_upload(upload))

            self.assertEqual(job["status"], "created")
            self.assertEqual(job["input_kind"], "wav")
            self.assertEqual(Path(job["paths"]["input"]).name, "original.wav")
            self.assertTrue(Path(job["paths"]["input"]).exists())

    def test_create_job_defaults_video_type_to_movie_commentary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = JobService(_config(tmp))
            job = asyncio.run(service.create_job_from_upload(FakeUpload("clip.mp4", b"x")))

            self.assertEqual(job["video_type"], "movie_commentary")
            persisted = service.get_job(job["job_id"])
            self.assertEqual(persisted["video_type"], "movie_commentary")

    def test_create_job_persists_manju_video_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = JobService(_config(tmp))
            job = asyncio.run(
                service.create_job_from_upload(FakeUpload("clip.mp4", b"x"), video_type="manju")
            )

            self.assertEqual(job["video_type"], "manju")
            persisted = service.get_job(job["job_id"])
            self.assertEqual(persisted["video_type"], "manju")

    def test_create_job_rejects_unknown_video_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = JobService(_config(tmp))
            with self.assertRaises(ValueError):
                asyncio.run(
                    service.create_job_from_upload(FakeUpload("clip.mp4", b"x"), video_type="anime")
                )

    def test_get_job_backfills_default_video_type_for_legacy_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = JobService(_config(tmp))
            job = asyncio.run(service.create_job_from_upload(FakeUpload("clip.mp4", b"x")))
            del job["video_type"]
            service.save_job(job)

            persisted = service.get_job(job["job_id"])

            self.assertEqual(persisted["video_type"], "movie_commentary")

    def test_list_jobs_returns_video_type_with_default_for_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = JobService(_config(tmp))
            job_a = asyncio.run(service.create_job_from_upload(FakeUpload("a.mp4", b"x")))
            job_b = asyncio.run(
                service.create_job_from_upload(FakeUpload("b.mp3", b"x"), video_type="manju")
            )
            del job_a["video_type"]
            service.save_job(job_a)

            result = service.list_jobs()

            by_id = {item["job_id"]: item for item in result["jobs"]}
            self.assertEqual(by_id[job_a["job_id"]]["video_type"], "movie_commentary")
            self.assertEqual(by_id[job_b["job_id"]]["video_type"], "manju")

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

    def test_list_jobs_returns_all_created_jobs_sorted_desc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = JobService(_config(tmp))
            job_a = asyncio.run(service.create_job_from_upload(FakeUpload("a.mp4", b"x")))
            job_b = asyncio.run(service.create_job_from_upload(FakeUpload("b.mp3", b"x")))
            job_a["created_at"] = "2026-01-01T00:00:00+00:00"
            job_b["created_at"] = "2026-01-01T00:00:01+00:00"
            service.save_job(job_a)
            service.save_job(job_b)

            result = service.list_jobs()

            self.assertEqual(result["total"], 2)
            self.assertEqual(len(result["jobs"]), 2)
            # Most recent first (job_b created after job_a)
            self.assertEqual(result["jobs"][0]["job_id"], job_b["job_id"])
            self.assertEqual(result["jobs"][1]["job_id"], job_a["job_id"])
            # Each item contains expected fields
            for item in result["jobs"]:
                self.assertIn("job_id", item)
                self.assertIn("status", item)
                self.assertIn("original_filename", item)
                self.assertIn("input_kind", item)
                self.assertIn("video_type", item)
                self.assertIn("created_at", item)

    def test_list_jobs_returns_empty_when_no_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = JobService(_config(tmp))
            result = service.list_jobs()
            self.assertEqual(result["total"], 0)
            self.assertEqual(result["jobs"], [])

    def test_list_jobs_ignores_corrupted_job_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = JobService(_config(tmp))
            job = asyncio.run(service.create_job_from_upload(FakeUpload("a.mp4", b"x")))
            # Corrupt another job dir
            bad_dir = Path(service.root_dir) / "badjob"
            bad_dir.mkdir()
            (bad_dir / "job.json").write_text("{invalid json", encoding="utf-8")

            result = service.list_jobs()
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["jobs"][0]["job_id"], job["job_id"])


def _config(tmp: str) -> dict:
    return {
        "project_root": tmp,
        "jobs": {"root_dir": "jobs"},
    }


if __name__ == "__main__":
    unittest.main()
