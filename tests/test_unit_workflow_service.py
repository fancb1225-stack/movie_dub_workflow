from __future__ import annotations

import tempfile
import unittest
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from src.services.job_service import JobService
from src.services.workflow_service import WorkflowService, _workflow_hint


class WorkflowServiceTests(unittest.TestCase):
    def test_run_job_langgraph_workflow_uses_separated_vocals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir)
            job = _create_job(config, "job-1")
            vocals_path = Path(job["paths"]["media_dir"]) / "separation" / "vocals.wav"
            background_path = Path(job["paths"]["media_dir"]) / "separation" / "background.wav"
            source_audio_path = Path(job["paths"]["media_dir"]) / "source_audio.wav"
            _write_wav(vocals_path)
            _write_wav(background_path)
            _write_wav(source_audio_path)
            JobService(config).update_job(
                job["job_id"],
                status="audio_separated",
                artifacts={
                    "source_audio_wav": str(source_audio_path),
                    "vocals_wav": str(vocals_path),
                    "background_wav": str(background_path),
                },
            )

            report = WorkflowService(config).run_job_langgraph_workflow(job["job_id"])

            self.assertEqual(report["status"], "success")
            self.assertEqual(report["input_audio"], str(vocals_path))
            self.assertEqual(report["background_audio"], str(background_path))
            self.assertEqual(report["asr_provider"], "mock")
            self.assertTrue(report["used_mock_asr"])
            self.assertNotEqual(report["input_audio"], str(source_audio_path))
            self.assertTrue(Path(report["final_srt"]).exists())
            self.assertTrue(Path(report["narration_wav"]).exists())
            self.assertTrue(Path(report["narration_mp3"]).exists())
            self.assertTrue(Path(report["report"]).exists())
            updated = JobService(config).get_job(job["job_id"])
            self.assertEqual(updated["status"], "langgraph_completed")
            self.assertIn("final_srt", updated["artifacts"])
            self.assertIn("langgraph_input_audio", updated["artifacts"])
            self.assertEqual(updated["artifacts"]["langgraph_input_audio"], str(vocals_path))
            self.assertIn("langgraph_workflow_report", updated["reports"])

    def test_run_job_langgraph_workflow_requires_vocals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir)
            job = _create_job(config, "job-2")

            report = WorkflowService(config).run_job_langgraph_workflow(job["job_id"])

            self.assertEqual(report["status"], "failed")
            self.assertIn("分离人声与背景音", report["hint"])
            updated = JobService(config).get_job(job["job_id"])
            self.assertEqual(updated["status"], "langgraph_failed")

    def test_job_langgraph_workflow_disables_mock_asr_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir, allow_mock_asr_for_jobs=False)
            job = _create_job(config, "job-3")
            vocals_path = Path(job["paths"]["media_dir"]) / "separation" / "vocals.wav"
            _write_wav(vocals_path)
            seen_provider: list[str] = []

            class ProviderAssertingWorkflow:
                def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
                    asr_config = state["config"]["asr"]
                    seen_provider.append(str(asr_config["provider"]))
                    assert asr_config["mock_when_missing_input"] is False
                    assert asr_config["device"] == "cpu"
                    assert asr_config["compute_type"] == "int8"
                    raise RuntimeError(
                        "ASR provider faster_whisper requires the faster-whisper package."
                    )

            with patch(
                "src.services.workflow_service.build_workflow",
                return_value=ProviderAssertingWorkflow(),
            ):
                report = WorkflowService(config).run_job_langgraph_workflow(job["job_id"])

            self.assertEqual(seen_provider, ["faster_whisper"])
            self.assertEqual(report["status"], "failed")
            self.assertIn("不再使用 mock ASR", report["hint"])
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


def _config(temp_dir: str, allow_mock_asr_for_jobs: bool = True) -> dict[str, Any]:
    return {
        "project_root": temp_dir,
        "jobs": {"root_dir": "jobs"},
        "paths": {
            "input_mp3": "input/input.mp3",
            "outputs_dir": "outputs",
            "asr_srt": "outputs/asr/zh_raw.srt",
            "cleaned_srt": "outputs/cleaned/zh_cleaned.srt",
            "merged_before_critic_srt": "outputs/merged/zh_merged_before_critic.srt",
            "corrected_srt": "outputs/critic/zh_corrected.srt",
            "merged_after_critic_srt": "outputs/merged/zh_merged_after_critic.srt",
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
