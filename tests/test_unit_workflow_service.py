from __future__ import annotations

import tempfile
import unittest
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from src.services.job_service import JobService
from src.services.state_persistence import save_state_snapshot
from src.services.workflow_service import (
    WorkflowService,
    _ensure_job_config_metadata,
    _job_workflow_config,
    _workflow_hint,
)
from src.tools.tts_tools import FatalTtsError


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

    def test_run_job_langgraph_workflow_requires_raw_asr(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir)
            job = _create_job(config, "job-2")

            report = WorkflowService(config).run_job_langgraph_workflow(job["job_id"])

            self.assertEqual(report["status"], "failed")
            self.assertIn("ASR", report["hint"])
            updated = JobService(config).get_job(job["job_id"])
            self.assertEqual(updated["status"], "langgraph_failed")

    def test_run_job_asr_defaults_movie_commentary_to_doubao_single_speaker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir, allow_mock_asr_for_jobs=False)
            config["asr"]["provider"] = "mock"
            job = _create_job(config, "job-asr-provider")
            vocals_path = Path(job["paths"]["media_dir"]) / "separation" / "vocals.wav"
            _write_wav(vocals_path)
            captured_asr: list[dict[str, Any]] = []

            def fake_transcribe(input_audio: Path, output_words: Path, job_config: dict[str, Any]) -> dict[str, Any]:
                captured_asr.append(dict(job_config["asr"]))
                srt_text = "1\n00:00:00,000 --> 00:00:01,000\n测试字幕\n"
                return {
                    "provider": job_config["asr"]["provider"],
                    "input_mp3": str(input_audio),
                    "words_json": None,
                    "subtitle_count": 1,
                    "cues": [],
                    "srt": srt_text,
                    "words": [],
                    "speakers": [],
                }

            with patch(
                "src.services.workflow_service.transcribe_mp3_to_srt",
                side_effect=fake_transcribe,
            ):
                report = WorkflowService(config).run_job_asr(job["job_id"])

            self.assertEqual(report["status"], "done")
            self.assertEqual(captured_asr[0]["provider"], "doubao_file")
            self.assertFalse(captured_asr[0]["enable_speaker_info"])
            updated = JobService(config).get_job(job["job_id"])
            self.assertEqual(updated["status"], "asr_completed")
            self.assertIn("raw_srt", updated["artifacts"])

    def test_run_job_asr_uses_doubao_single_speaker_for_movie_commentary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir, allow_mock_asr_for_jobs=False)
            job = _create_job(config, "job-asr-movie")
            job["video_type"] = "movie_commentary"
            JobService(config).save_job(job)
            vocals_path = Path(job["paths"]["media_dir"]) / "separation" / "vocals.wav"
            _write_wav(vocals_path)
            captured_asr: list[dict[str, Any]] = []

            def fake_transcribe(input_audio: Path, output_words: Path, job_config: dict[str, Any]) -> dict[str, Any]:
                captured_asr.append(dict(job_config["asr"]))
                srt_text = "1\n00:00:00,000 --> 00:00:01,000\n测试字幕\n"
                return {
                    "provider": job_config["asr"]["provider"],
                    "input_mp3": str(input_audio),
                    "words_json": None,
                    "subtitle_count": 1,
                    "cues": [{"index": 1, "start_ms": 0, "end_ms": 1000, "text": "测试字幕", "speaker_id": "speaker_0"}],
                    "srt": srt_text,
                    "words": [],
                    "speakers": ["speaker_0"],
                }

            with patch("src.services.workflow_service.transcribe_mp3_to_srt", side_effect=fake_transcribe):
                report = WorkflowService(config).run_job_asr(job["job_id"])

            self.assertEqual(report["provider"], "doubao_file")
            self.assertEqual(report["speakers"], ["speaker_0"])
            self.assertEqual(captured_asr[0]["provider"], "doubao_file")
            self.assertFalse(captured_asr[0]["enable_speaker_info"])
            self.assertEqual(captured_asr[0]["default_speaker_id"], "speaker_0")

    def test_run_job_asr_uses_doubao_multi_speaker_for_manju(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir, allow_mock_asr_for_jobs=False)
            job = _create_job(config, "job-asr-manju")
            job["video_type"] = "manju"
            JobService(config).save_job(job)
            vocals_path = Path(job["paths"]["media_dir"]) / "separation" / "vocals.wav"
            _write_wav(vocals_path)
            captured_asr: list[dict[str, Any]] = []

            def fake_transcribe(input_audio: Path, output_words: Path, job_config: dict[str, Any]) -> dict[str, Any]:
                captured_asr.append(dict(job_config["asr"]))
                srt_text = "1\n00:00:00,000 --> 00:00:01,000\n测试字幕\n"
                return {
                    "provider": job_config["asr"]["provider"],
                    "input_mp3": str(input_audio),
                    "words_json": None,
                    "subtitle_count": 1,
                    "cues": [],
                    "srt": srt_text,
                    "words": [],
                    "speakers": ["speaker_1"],
                }

            with patch("src.services.workflow_service.transcribe_mp3_to_srt", side_effect=fake_transcribe):
                report = WorkflowService(config).run_job_asr(job["job_id"])

            self.assertEqual(report["provider"], "doubao_file")
            self.assertEqual(captured_asr[0]["provider"], "doubao_file")
            self.assertTrue(captured_asr[0]["enable_speaker_info"])
            self.assertNotIn("default_speaker_id", captured_asr[0])

    def test_run_job_asr_overrides_mock_for_movie_commentary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir, allow_mock_asr_for_jobs=False)
            config["asr"]["provider"] = "mock"
            job = _create_job(config, "job-asr-mock-blocked")
            vocals_path = Path(job["paths"]["media_dir"]) / "separation" / "vocals.wav"
            _write_wav(vocals_path)

            def fake_transcribe(input_audio: Path, output_words: Path, job_config: dict[str, Any]) -> dict[str, Any]:
                srt_text = "1\n00:00:00,000 --> 00:00:01,000\n测试字幕\n"
                return {
                    "provider": job_config["asr"]["provider"],
                    "input_mp3": str(input_audio),
                    "words_json": None,
                    "subtitle_count": 1,
                    "cues": [],
                    "srt": srt_text,
                    "words": [],
                    "speakers": ["speaker_0"],
                }

            with patch("src.services.workflow_service.transcribe_mp3_to_srt", side_effect=fake_transcribe) as transcribe:
                report = WorkflowService(config).run_job_asr(job["job_id"])

            self.assertEqual(report["provider"], "doubao_file")
            self.assertEqual(transcribe.call_args.args[2]["asr"]["provider"], "doubao_file")

    def test_run_job_asr_allows_mock_when_configured_for_tests(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir, allow_mock_asr_for_jobs=True)
            config["workflow"]["force_job_asr_provider"] = ""
            config["asr"]["provider"] = "mock"
            job = _create_job(config, "job-asr-mock-allowed")
            vocals_path = Path(job["paths"]["media_dir"]) / "separation" / "vocals.wav"
            _write_wav(vocals_path)

            def fake_transcribe(input_audio: Path, output_words: Path, job_config: dict[str, Any]) -> dict[str, Any]:
                srt_text = "1\n00:00:00,000 --> 00:00:01,000\n测试字幕\n"
                return {
                    "provider": job_config["asr"]["provider"],
                    "input_mp3": str(input_audio),
                    "words_json": None,
                    "subtitle_count": 1,
                    "cues": [],
                    "srt": srt_text,
                    "words": [],
                    "speakers": [],
                }

            with patch(
                "src.services.workflow_service.transcribe_mp3_to_srt",
                side_effect=fake_transcribe,
            ) as transcribe:
                report = WorkflowService(config).run_job_asr(job["job_id"])

            self.assertEqual(report["status"], "done")
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

    def test_streaming_workflow_generic_node_error_targets_wrapped_node(self) -> None:
        from src.graph import with_trace

        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir)
            job = _create_job(config, "job-reflect-timeout-stream")
            asr_dir = Path(job["paths"]["job_dir"]) / "workflow" / "asr"
            asr_dir.mkdir(parents=True, exist_ok=True)
            raw_srt_path = asr_dir / "zh_raw.srt"
            raw_srt_path.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\n测试\n", encoding="utf-8"
            )
            JobService(config).update_job(job["job_id"], artifacts={"raw_srt": str(raw_srt_path)})

            def failing_reflection(state: dict[str, Any]) -> dict[str, Any]:
                raise RuntimeError("LLM request failed: The read operation timed out")

            class FailingStreamWorkflow:
                def stream(self, state: dict[str, Any]):
                    state["duration_issues"] = [{"index": 1, "duration_ms": 1000}]
                    yield {"tts_generate_and_detect": state}
                    with_trace("reflect_duration_issues", failing_reflection)(state)

            with patch("src.services.workflow_service.build_workflow", return_value=FailingStreamWorkflow()):
                events = list(WorkflowService(config).run_job_langgraph_workflow_streaming(job["job_id"]))

            error_event = events[-1]
            self.assertEqual(error_event["event"], "error")
            self.assertEqual(error_event["node"], "reflect_duration_issues")
            self.assertEqual(error_event["status"], "error")
            self.assertIn("LLM request failed", error_event["message"])
            self.assertIn("LLM request failed", error_event["error"])
            self.assertEqual(error_event["report"]["status"], "failed")
            updated = JobService(config).get_job(job["job_id"])
            self.assertEqual(updated["status"], "langgraph_failed")
            self.assertEqual(updated["langgraph_progress"]["node"], "reflect_duration_issues")

    def test_streaming_workflow_tts_fatal_error_targets_tts_node(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir)
            job = _create_job(config, "job-tts-fatal-stream")
            asr_dir = Path(job["paths"]["job_dir"]) / "workflow" / "asr"
            asr_dir.mkdir(parents=True, exist_ok=True)
            raw_srt_path = asr_dir / "zh_raw.srt"
            raw_srt_path.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\n测试\n", encoding="utf-8"
            )
            JobService(config).update_job(job["job_id"], artifacts={"raw_srt": str(raw_srt_path)})

            class FailingStreamWorkflow:
                def stream(self, state: dict[str, Any]):
                    raise FatalTtsError("MiniMax TTS task timeout: task_id=task-1")

            with patch("src.services.workflow_service.build_workflow", return_value=FailingStreamWorkflow()):
                events = list(WorkflowService(config).run_job_langgraph_workflow_streaming(job["job_id"]))

            error_event = events[-1]
            self.assertEqual(error_event["event"], "error")
            self.assertEqual(error_event["node"], "tts_generate_and_detect")
            self.assertEqual(error_event["status"], "error")
            self.assertIn("MiniMax TTS task timeout", error_event["message"])
            updated = JobService(config).get_job(job["job_id"])
            self.assertEqual(updated["status"], "langgraph_failed")
            self.assertEqual(updated["langgraph_progress"]["node"], "tts_generate_and_detect")

    def test_resume_langgraph_workflow_allows_generic_failed_job_with_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir)
            job = _create_job(config, "job-resume-failed")
            raw_srt_path = _write_raw_asr(job)
            background_path = Path(job["paths"]["media_dir"]) / "separation" / "background.wav"
            _write_wav(background_path)
            job_config = _job_workflow_config(config, job, background_path)
            save_state_snapshot(
                job["paths"]["job_dir"],
                {
                    "config": job_config,
                    "raw_srt": raw_srt_path.read_text(encoding="utf-8"),
                    "raw_cues": [],
                    "reports": {},
                    "errors": [],
                    "reflection_rounds": 0,
                },
                "translate_to_english",
            )
            JobService(config).update_job(
                job["job_id"],
                status="failed",
                artifacts={"raw_srt": str(raw_srt_path), "background_wav": str(background_path)},
                reports={"langgraph_workflow_report": str(Path(job["paths"]["reports_dir"]) / "langgraph_workflow_report.json")},
            )
            resume_from_values: list[str | None] = []
            reuse_flags: list[bool] = []

            class FakeWorkflow:
                def stream(self, state: dict[str, Any]):
                    state["final_cues"] = []
                    state["narration_wav_path"] = state["config"]["paths"]["narration_wav"]
                    state["narration_mp3_path"] = state["config"]["paths"]["narration_mp3"]
                    yield {"tts_generate_and_detect": state}

            def fake_build_workflow(job_config: dict[str, Any], resume_from: str | None = None) -> FakeWorkflow:
                resume_from_values.append(resume_from)
                reuse_flags.append(bool(job_config.get("workflow", {}).get("reuse_existing_tts_segments")))
                return FakeWorkflow()

            with patch("src.services.workflow_service.build_workflow", side_effect=fake_build_workflow):
                events = list(WorkflowService(config).resume_job_langgraph_workflow_streaming(job["job_id"]))

            self.assertEqual(resume_from_values, ["tts_generate_and_detect"])
            self.assertEqual(reuse_flags, [True])
            self.assertEqual(events[0]["event"], "start")
            self.assertTrue(any(event.get("node") == "tts_generate_and_detect" for event in events))
            self.assertEqual(events[-1]["event"], "done")
            updated = JobService(config).get_job(job["job_id"])
            self.assertEqual(updated["status"], "langgraph_completed")

    def test_resume_langgraph_workflow_allows_generic_failed_job_with_artifact_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir)
            job = _create_job(config, "job-resume-failed-artifact")
            raw_srt_path = _write_raw_asr(job)
            background_path = Path(job["paths"]["media_dir"]) / "separation" / "background.wav"
            _write_wav(background_path)
            translated_path = Path(job["paths"]["job_dir"]) / "workflow" / "translated" / "en_translated.srt"
            translated_path.parent.mkdir(parents=True, exist_ok=True)
            translated_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nTest\n", encoding="utf-8")
            JobService(config).update_job(
                job["job_id"],
                status="failed",
                artifacts={"raw_srt": str(raw_srt_path), "background_wav": str(background_path)},
                reports={"langgraph_workflow_report": str(Path(job["paths"]["reports_dir"]) / "langgraph_workflow_report.json")},
            )
            resume_from_values: list[str | None] = []

            class FakeWorkflow:
                def stream(self, state: dict[str, Any]):
                    state["final_cues"] = []
                    yield {"tts_generate_and_detect": state}

            def fake_build_workflow(job_config: dict[str, Any], resume_from: str | None = None) -> FakeWorkflow:
                resume_from_values.append(resume_from)
                return FakeWorkflow()

            with patch("src.services.workflow_service.build_workflow", side_effect=fake_build_workflow):
                events = list(WorkflowService(config).resume_job_langgraph_workflow_streaming(job["job_id"]))

            self.assertEqual(resume_from_values, ["tts_generate_and_detect"])
            self.assertEqual(events[-1]["event"], "done")
            updated = JobService(config).get_job(job["job_id"])
            self.assertEqual(updated["status"], "langgraph_completed")

    def test_workflow_hint_explains_doubao_asr_error(self) -> None:
        hint = _workflow_hint("Doubao ASR query failed: 40000001")

        self.assertIn("豆包 ASR", hint)
        self.assertIn("DOUBAO_ASR_API_KEY", hint)
        self.assertIn("TOS", hint)

    def test_workflow_hint_explains_llm_access_denied(self) -> None:
        hint = _workflow_hint("LLM HTTP 403: access_denied: IP is not allowed")

        self.assertIn("LLM 服务拒绝访问", hint)
        self.assertIn("IP 白名单", hint)

    def test_workflow_hint_prioritizes_minimax_access_denied(self) -> None:
        hint = _workflow_hint(
            "MiniMax TTS request fatal error: HTTP 403: Forbidden: access_denied: IP is not allowed"
        )

        self.assertIn("MiniMax", hint)
        self.assertIn("IP", hint)

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
            "movie_commentary_asr_provider": "doubao_file",
            "movie_commentary_default_speaker_id": "speaker_0",
            "manju_asr_provider": "doubao_file",
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


def _write_raw_asr(job: dict[str, Any]) -> Path:
    asr_dir = Path(job["paths"]["job_dir"]) / "workflow" / "asr"
    asr_dir.mkdir(parents=True, exist_ok=True)
    raw_srt_path = asr_dir / "zh_raw.srt"
    raw_srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\n测试字幕\n", encoding="utf-8")
    return raw_srt_path


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(8000)
        writer.writeframes(b"\0\0" * 8000)


if __name__ == "__main__":
    unittest.main()
