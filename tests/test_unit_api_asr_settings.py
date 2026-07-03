from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

try:
    import pytest
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("pytest is not installed.") from exc

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from src.api.app import create_app


def test_asr_settings_endpoint_returns_sanitized_tos_metadata() -> None:
    app = create_app()
    app.state.config = _config()
    client = TestClient(app)

    response = client.get("/api/asr/settings", params={"video_type": "manju"})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["provider"] == "doubao_file"
    assert payload["defaults"]["enable_speaker_info"] is True
    assert payload["fields"]["enable_punc"]["official_default"] is False
    assert payload["tos"]["ready"] is False


def test_asr_route_passes_request_body_as_overrides() -> None:
    app = create_app()
    app.state.config = _config()
    client = TestClient(app)
    captured: dict[str, Any] = {}

    def fake_run_job_asr(self, job_id: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        captured["job_id"] = job_id
        captured["overrides"] = overrides
        return {
            "job_id": job_id,
            "status": "done",
            "input_audio": "vocals.wav",
            "raw_words": "words.json",
            "asr_report": "asr_report.json",
            "provider": "doubao_file",
            "subtitle_count": 1,
            "speakers": ["speaker_1"],
        }

    with patch("src.api.routes.WorkflowService.run_job_asr", new=fake_run_job_asr):
        response = client.post(
            "/api/jobs/job-1/asr",
            json={
                "asr": {
                    "language": "",
                    "enable_speaker_info": True,
                    "poll_interval_seconds": 0.5,
                    "provider": "legacy_local",
                }
            },
        )

    assert response.status_code == 200, response.text
    assert captured["job_id"] == "job-1"
    assert captured["overrides"]["asr.enable_speaker_info"] is True
    assert captured["overrides"]["asr.poll_interval"] == 0.5
    assert "asr.language" not in captured["overrides"]
    assert "asr.provider" not in captured["overrides"]


def _config() -> dict[str, Any]:
    return {
        "jobs": {"root_dir": "outputs/jobs"},
        "asr": {
            "audio_format": "wav",
            "doubao_model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": False,
            "enable_ddc": False,
            "show_utterances": True,
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
            "movie_commentary_default_speaker_id": "speaker_0",
            "movie_commentary_asr_provider": "doubao_file",
            "manju_asr_provider": "doubao_file",
        },
    }
