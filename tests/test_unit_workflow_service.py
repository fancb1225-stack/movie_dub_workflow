from __future__ import annotations

import tempfile
import unittest
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from src.services.job_service import JobService
from src.services.workflow_service import (
    WorkflowService,
    _ensure_job_config_metadata,
    _job_workflow_config,
    _workflow_hint,
)


class WorkflowServiceTests(unittest.TestCase):
    def test_run_job_langgraph_workflow_uses_raw_srt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir)
            job = _create_job(config, "job-1")
            # Create ASR SRT as if preprocess already ran
            asr_dir = Path(job["paths"]["job_dir"]) / "workflow" / "asr"
            asr_dir.mkdir(parents=True, exist_ok=True)
            raw_srt_path = asr_dir / "zh_raw.srt"
            raw_srt_path.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\n测试字幕\n", encoding="utf-8"
            )
            background_path = Path(job["paths"]["media_dir"]) / "separation" / "background.wav"
            _write_wav(background_path)
            JobService(config).update_job(
                job["job_id"],
                status="preprocessed",
                artifacts={
                    "raw_srt": str(raw_srt_path),
                    "background_wav": str(background_path),
                },
            )

            report = WorkflowService(config).run_job_langgraph_workflow(job["job_id"])

            self.assertEqual(report["status"], "success")
            self.assertEqual(report["background_audio"], str(background_path))
            self.assertIsNotNone(report.get("raw_srt"))
            self.assertTrue(Path(report["final_srt"]).exists())
            self.assertTrue(Path(report["narration_wav"]).exists())
            self.assertTrue(Path(report["narration_mp3"]).exists())
            self.assertTrue(Path(report["report"]).exists())
            updated = JobService(config).get_job(job["job_id"])
            self.assertEqual(updated["status"], "langgraph_completed")
            self.assertIn("final_srt", updated["artifacts"])
            self.assertIn("langgraph_workflow_report", updated["reports"])

    def test_run_job_langgraph_workflow_requires_raw_srt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir)
            job = _create_job(config, "job-2")

            report = WorkflowService(config).run_job_langgraph_workflow(job["job_id"])

            self.assertEqual(report["status"], "failed")
            self.assertIn("预处理", report["hint"])
            updated = JobService(config).get_job(job["job_id"])
            self.assertEqual(updated["status"], "langgraph_failed")

    def test_preprocess_streaming_forces_configured_job_asr_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir, allow_mock_asr_for_jobs=False)
            config["workflow"]["force_job_asr_provider"] = "faster_whisper"
            config["asr"]["provider"] = "mock"
            job = _create_job(config, "job-preprocess-asr-provider")
            vocals_path = Path(job["paths"]["media_dir"]) / "separation" / "vocals.wav"
            _write_wav(vocals_path)
            captured_providers: list[str] = []

            def fake_transcribe(input_audio: Path, output_srt: Path, job_config: dict[str, Any]) -> dict[str, Any]:
                captured_providers.append(job_config["asr"]["provider"])
                srt_text = "1\n00:00:00,000 --> 00:00:01,000\n测试字幕\n"
                return {
                    "provider": job_config["asr"]["provider"],
                    "input_mp3": str(input_audio),
                    "output_srt": str(output_srt),
                    "subtitle_count": 1,
                    "cues": [],
                    "srt": srt_text,
                }

            with (
                patch(
                    "src.services.workflow_service.MediaService.extract_audio_for_job",
                    return_value={"status": "extracted"},
                ),
                patch(
                    "src.services.workflow_service.SeparationService.separate_job_audio",
                    return_value={"status": "success"},
                ),
                patch(
                    "src.services.workflow_service.transcribe_mp3_to_srt",
                    side_effect=fake_transcribe,
                ),
            ):
                events = list(WorkflowService(config).run_job_preprocess_streaming(job["job_id"]))

            self.assertEqual(events[-1]["event"], "done")
            self.assertEqual(captured_providers, ["faster_whisper"])

    def test_preprocess_streaming_rejects_mock_asr_when_not_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir, allow_mock_asr_for_jobs=False)
            config["workflow"]["force_job_asr_provider"] = ""
            config["asr"]["provider"] = "mock"
            job = _create_job(config, "job-preprocess-mock-blocked")
            vocals_path = Path(job["paths"]["media_dir"]) / "separation" / "vocals.wav"
            _write_wav(vocals_path)

            with (
                patch(
                    "src.services.workflow_service.MediaService.extract_audio_for_job",
                    return_value={"status": "extracted"},
                ),
                patch(
                    "src.services.workflow_service.SeparationService.separate_job_audio",
                    return_value={"status": "success"},
                ),
                patch("src.services.workflow_service.transcribe_mp3_to_srt") as transcribe,
            ):
                events = list(WorkflowService(config).run_job_preprocess_streaming(job["job_id"]))

            self.assertEqual(events[-1]["event"], "error")
            self.assertIn("mock ASR", events[-1]["error"])
            transcribe.assert_not_called()

    def test_preprocess_streaming_allows_mock_asr_when_configured_for_tests(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir, allow_mock_asr_for_jobs=True)
            config["workflow"]["force_job_asr_provider"] = ""
            config["asr"]["provider"] = "mock"
            job = _create_job(config, "job-preprocess-mock-allowed")
            vocals_path = Path(job["paths"]["media_dir"]) / "separation" / "vocals.wav"
            _write_wav(vocals_path)

            def fake_transcribe(input_audio: Path, output_srt: Path, job_config: dict[str, Any]) -> dict[str, Any]:
                srt_text = "1\n00:00:00,000 --> 00:00:01,000\n测试字幕\n"
                return {
                    "provider": job_config["asr"]["provider"],
                    "input_mp3": str(input_audio),
                    "output_srt": str(output_srt),
                    "subtitle_count": 1,
                    "cues": [],
                    "srt": srt_text,
                }

            with (
                patch(
                    "src.services.workflow_service.MediaService.extract_audio_for_job",
                    return_value={"status": "extracted"},
                ),
                patch(
                    "src.services.workflow_service.SeparationService.separate_job_audio",
                    return_value={"status": "success"},
                ),
                patch(
                    "src.services.workflow_service.transcribe_mp3_to_srt",
                    side_effect=fake_transcribe,
                ) as transcribe,
            ):
                events = list(WorkflowService(config).run_job_preprocess_streaming(job["job_id"]))

            self.assertEqual(events[-1]["event"], "done")
            self.assertEqual(transcribe.call_count, 1)

    def test_run_job_langgraph_workflow_handles_invoke_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir)
            job = _create_job(config, "job-3")
            asr_dir = Path(job["paths"]["job_dir"]) / "workflow" / "asr"
            asr_dir.mkdir(parents=True, exist_ok=True)
            raw_srt_path = asr_dir / "zh_raw.srt"
            raw_srt_path.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\n测试\n", encoding="utf-8"
            )
            JobService(config).update_job(
                job["job_id"],
                artifacts={"raw_srt": str(raw_srt_path)},
            )

            class FailingWorkflow:
                def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
                    raise RuntimeError("LLM HTTP 403: access_denied")

            with patch(
                "src.services.workflow_service.build_workflow",
                return_value=FailingWorkflow(),
            ):
                report = WorkflowService(config).run_job_langgraph_workflow(job["job_id"])

            self.assertEqual(report["status"], "failed")
            self.assertIn("LLM 服务拒绝访问", report["hint"])
            updated = JobService(config).get_job(job["job_id"])
            self.assertEqual(updated["status"], "langgraph_failed")

    def test_workflow_hint_explains_cuda_dependency_error(self) -> None:
        hint = _workflow_hint("Library cublas64_12.dll is not found or cannot be loaded")

        self.assertIn("CUDA", hint)
        self.assertIn("asr.device", hint)
        self.assertIn("cpu", hint)

    def test_workflow_hint_explains_llm_access_denied(self) -> None:
        hint = _workflow_hint("LLM HTTP 403: access_denied: IP is not allowed")

        self.assertIn("LLM 服务拒绝访问", hint)
        self.assertIn("IP 白名单", hint)

    def test_job_workflow_config_writes_video_type_into_job_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir)
            job = _create_job(config, "job-video-type")
            job["video_type"] = "manju"

            job_config = _job_workflow_config(config, job)

            self.assertEqual(job_config["job"]["video_type"], "manju")
            self.assertEqual(job_config["job"]["job_id"], job["job_id"])

    def test_job_workflow_config_defaults_video_type_for_legacy_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir)
            job = _create_job(config, "job-legacy")
            job.pop("video_type", None)

            job_config = _job_workflow_config(config, job)

            self.assertEqual(job_config["job"]["video_type"], "movie_commentary")

    def test_ensure_job_config_metadata_preserves_existing_video_type_on_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir)
            job = _create_job(config, "job-resume")
            job["video_type"] = "manju"
            snapshot_config: dict[str, Any] = {"job": {"video_type": "movie_commentary"}}

            _ensure_job_config_metadata(snapshot_config, job, overwrite=False)

            self.assertEqual(snapshot_config["job"]["video_type"], "movie_commentary")

    def test_ensure_job_config_metadata_backfills_missing_fields_on_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir)
            job = _create_job(config, "job-resume-backfill")
            job["video_type"] = "manju"
            snapshot_config: dict[str, Any] = {}

            _ensure_job_config_metadata(snapshot_config, job, overwrite=False)

            self.assertEqual(snapshot_config["job"]["video_type"], "manju")
            self.assertEqual(snapshot_config["job"]["job_id"], job["job_id"])


def _config(temp_dir: str, allow_mock_asr_for_jobs: bool = True) -> dict[str, Any]:
    return {
        "project_root": temp_dir,
        "jobs": {"root_dir": "jobs"},
        "paths": {
            "input_mp3": "input/input.mp3",
            "outputs_dir": "outputs",
            "asr_srt": "outputs/asr/zh_raw.srt",
            "cleaned_srt": "outputs/cleaned/zh_cleaned.srt",
            "corrected_srt": "outputs/critic/zh_corrected.srt",
            "translated_srt": "outputs/translated/en_translated.srt",
            "final_srt": "outputs/final/en_final.srt",
            "tts_segments_dir": "outputs/tts_segments",
            "reports_dir": "outputs/reports",
            "audio_dir": "outputs/audio",
            "narration_wav": "outputs/audio/narration_en.wav",
            "narration_mp3": "outputs/audio/narration_en.mp3",
        },
        "asr": {"provider": "mock", "mock_when_missing_input": True},
        "workflow": {
            "allow_mock_asr_for_jobs": allow_mock_asr_for_jobs,
            "force_job_asr_provider": "faster_whisper",
        },
        "translation": {"allow_mock_fallback": True},
        "llm": {"model": "mock", "api_key": "", "base_url": "", "timeout": 1, "max_retries": 0},
        "tts": {"provider": "mock", "sample_rate": 8000, "words_per_minute": 600},
        "srt": {"merge_max_chars": 38, "merge_max_gap_ms": 450, "merge_max_duration_ms": 6500},
        "duration": {"max_overrun_ms": 350, "max_ratio": 10.0, "max_reflection_rounds": 0},
    }


def _create_job(config: dict[str, Any], job_id: str) -> dict[str, Any]:
    service = JobService(config)
    job_dir = service.job_dir(job_id)
    input_dir = job_dir / "input"
    media_dir = job_dir / "media"
    reports_dir = job_dir / "reports"
    video_dir = job_dir / "video"
    for directory in [input_dir, media_dir, reports_dir, video_dir]:
        directory.mkdir(parents=True, exist_ok=True)
    input_path = input_dir / "original.mp3"
    input_path.write_bytes(b"placeholder")
    now = datetime.now(timezone.utc).isoformat()
    job = {
        "job_id": job_id,
        "created_at": now,
        "updated_at": now,
        "status": "created",
        "original_filename": "original.mp3",
        "input_kind": "mp3",
        "paths": {
            "job_dir": str(job_dir),
            "input": str(input_path),
            "media_dir": str(media_dir),
            "reports_dir": str(reports_dir),
            "video_dir": str(video_dir),
        },
        "artifacts": {},
        "reports": {},
    }
    service.save_job(job)
    return job


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(8000)
        writer.writeframes(b"\0\0" * 8000)


if __name__ == "__main__":
    unittest.main()
