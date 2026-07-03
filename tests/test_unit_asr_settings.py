from __future__ import annotations

import json
import tempfile
import unittest
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from src.services.asr_settings_service import (
    build_asr_overrides,
    build_asr_settings_response,
)
from src.services.job_service import JobService
from src.services.workflow_service import WorkflowService


class AsrSettingsServiceTests(unittest.TestCase):
    def test_settings_metadata_marks_required_optional_and_tos_without_secrets(self) -> None:
        config = _config("unused")
        config["tos"].update(
            {
                "endpoint": "https://tos.example",
                "region": "cn-beijing",
                "bucket": "movie-bucket",
                "object_prefix": "movie-dub/asr",
                "access_key_id_env": "TOS_AK",
                "secret_access_key_env": "TOS_SK",
            }
        )

        with patch.dict("os.environ", {"TOS_AK": "ak-secret", "TOS_SK": "sk-secret"}, clear=True):
            settings = build_asr_settings_response(config, video_type="movie_commentary")

        self.assertFalse(settings["defaults"]["enable_speaker_info"])
        self.assertEqual(settings["defaults"]["model_name"], "bigmodel")
        self.assertEqual(settings["defaults"]["audio_format"], "wav")
        self.assertTrue(settings["defaults"]["show_utterances"])
        self.assertTrue(settings["fields"]["audio_format"]["required"])
        self.assertTrue(settings["fields"]["show_utterances"]["required"])
        self.assertFalse(settings["fields"]["language"]["required"])
        self.assertTrue(settings["fields"]["language"]["allow_empty"])
        self.assertEqual(settings["fields"]["enable_itn"]["official_default"], True)
        self.assertEqual(settings["fields"]["enable_punc"]["official_default"], False)
        self.assertEqual(settings["fields"]["enable_ddc"]["official_default"], False)
        self.assertTrue(settings["tos"]["ready"])
        serialized = json.dumps(settings, ensure_ascii=False)
        self.assertNotIn("ak-secret", serialized)
        self.assertNotIn("sk-secret", serialized)

    def test_settings_defaults_enable_speaker_info_for_manju(self) -> None:
        settings = build_asr_settings_response(_config("unused"), video_type="manju")

        self.assertTrue(settings["defaults"]["enable_speaker_info"])

    def test_asr_overrides_whitelist_and_blank_language(self) -> None:
        overrides = build_asr_overrides(
            {
                "language": "",
                "enable_punc": False,
                "enable_itn": True,
                "enable_ddc": True,
                "enable_speaker_info": True,
                "max_query_attempts": 7,
                "poll_interval_seconds": 0.25,
                "provider": "legacy_local",
                "api_key_env": "LEAK",
            }
        )

        self.assertNotIn("asr.language", overrides)
        self.assertEqual(overrides["asr.enable_punc"], False)
        self.assertEqual(overrides["asr.enable_itn"], True)
        self.assertEqual(overrides["asr.enable_ddc"], True)
        self.assertEqual(overrides["asr.enable_speaker_info"], True)
        self.assertEqual(overrides["asr.max_query_attempts"], 7)
        self.assertEqual(overrides["asr.poll_interval"], 0.25)
        self.assertNotIn("asr.provider", overrides)
        self.assertNotIn("asr.api_key_env", overrides)


class WorkflowServiceAsrOverrideTests(unittest.TestCase):
    def test_run_job_asr_applies_allowlisted_overrides_after_video_type_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir, allow_mock_asr_for_jobs=False)
            job = _create_job(config, "job-asr-overrides")
            job["video_type"] = "movie_commentary"
            JobService(config).save_job(job)
            vocals_path = Path(job["paths"]["media_dir"]) / "separation" / "vocals.wav"
            _write_wav(vocals_path)
            captured_asr: list[dict[str, Any]] = []

            def fake_transcribe(input_audio: Path, output_words: Path, job_config: dict[str, Any]) -> dict[str, Any]:
                captured_asr.append(dict(job_config["asr"]))
                return {
                    "provider": job_config["asr"]["provider"],
                    "input_mp3": str(input_audio),
                    "words_json": None,
                    "subtitle_count": 1,
                    "cues": [],
                    "srt": "1\n00:00:00,000 --> 00:00:01,000\n测试\n",
                    "words": [],
                    "speakers": ["speaker_1"],
                }

            overrides = build_asr_overrides(
                {
                    "enable_speaker_info": True,
                    "language": "en-US",
                    "poll_interval_seconds": 0.1,
                    "provider": "mock",
                }
            )
            with patch("src.services.workflow_service.transcribe_mp3_to_srt", side_effect=fake_transcribe):
                report = WorkflowService(config).run_job_asr(job["job_id"], overrides=overrides)

            self.assertEqual(report["provider"], "doubao_file")
            self.assertEqual(captured_asr[0]["provider"], "doubao_file")
            self.assertTrue(captured_asr[0]["enable_speaker_info"])
            self.assertEqual(captured_asr[0]["language"], "en-US")
            self.assertEqual(captured_asr[0]["poll_interval"], 0.1)
            self.assertNotIn("default_speaker_id", captured_asr[0])


def _config(temp_dir: str, allow_mock_asr_for_jobs: bool = True) -> dict[str, Any]:
    return {
        "project_root": temp_dir,
        "jobs": {"root_dir": "jobs"},
        "paths": {
            "input_mp3": "input/input.mp3",
            "outputs_dir": "outputs",
            "asr_srt": "outputs/asr/zh_raw.srt",
            "asr_words": "outputs/asr/zh_raw.words.json",
            "merged_asr_srt": "outputs/merged/zh_asr_merged.srt",
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
        "asr": {
            "provider": "doubao_file",
            "api_key_env": "DOUBAO_ASR_API_KEY",
            "audio_format": "wav",
            "doubao_model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
            "enable_ddc": False,
            "show_utterances": True,
            "enable_speaker_info": False,
            "poll_interval": 2.0,
            "max_query_attempts": 300,
        },
        "tos": {
            "endpoint": "",
            "region": "",
            "bucket": "",
            "object_prefix": "movie-dub/asr",
            "access_key_id_env": "DOUBAO_TOS_ACCESS_KEY_ID",
            "secret_access_key_env": "DOUBAO_TOS_SECRET_ACCESS_KEY",
        },
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
        "video_type": "movie_commentary",
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
