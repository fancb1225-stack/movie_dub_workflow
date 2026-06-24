from __future__ import annotations

import shutil
import unittest
import wave
from pathlib import Path

try:
    import pytest
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("pytest is not installed.") from exc

from src.config import find_binary, load_config

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from src.api.app import create_app


def test_media_api_upload_extract_and_package(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    config["jobs"]["root_dir"] = str(tmp_path / "jobs")
    config.setdefault("workflow", {})["allow_mock_asr_for_jobs"] = True
    config.setdefault("translation", {})["allow_mock_fallback"] = True
    config.setdefault("jianying", {})["auto_install"] = False
    config.setdefault("jianying", {})["auto_launch"] = False
    config["llm"]["api_key"] = ""
    config["llm"]["model"] = "mock"
    config.setdefault("tts", {})["provider"] = "mock"
    config["tts"]["pause_before_tts"] = False
    ffmpeg = find_binary(config, "ffmpeg.ffmpeg_path", "ffmpeg")
    source_mp4 = tmp_path / "source.mp4"
    _make_test_mp4(ffmpeg, source_mp4)

    app = create_app()
    app.state.config = config
    client = TestClient(app)

    with source_mp4.open("rb") as reader:
        response = client.post(
            "/api/jobs",
            files={"file": ("source.mp4", reader, "video/mp4")},
        )
    assert response.status_code == 200, response.text
    job = response.json()
    job_id = job["job_id"]

    response = client.get(f"/api/jobs/{job_id}/files")
    assert response.status_code == 200, response.text
    files = response.json()
    assert files["file_count"] >= 2
    assert any(item["relative_path"] == "input/original.mp4" for item in files["files"])

    response = client.get(
        f"/api/jobs/{job_id}/files/download",
        params={"path": "input/original.mp4"},
    )
    assert response.status_code == 200, response.text

    response = client.get(f"/api/jobs/{job_id}/media/probe")
    assert response.status_code == 200, response.text
    probe = response.json()
    assert probe["has_audio"] is True
    assert probe["has_video"] is True

    response = client.post(f"/api/jobs/{job_id}/media/extract-audio")
    assert response.status_code == 200, response.text
    extracted = response.json()
    assert Path(extracted["source_audio_wav"]).exists()

    raw_srt = Path(job["paths"]["job_dir"]) / "workflow" / "asr" / "zh_raw.srt"
    raw_srt.parent.mkdir(parents=True, exist_ok=True)
    raw_srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n测试字幕\n",
        encoding="utf-8",
    )
    response = client.post(f"/api/jobs/{job_id}/workflow/langgraph")
    assert response.status_code == 200, response.text
    workflow = response.json()
    assert workflow["status"] == "success"
    assert workflow["raw_srt"] == str(raw_srt)
    assert Path(workflow["final_srt"]).exists()
    assert Path(workflow["narration_wav"]).exists()
    assert Path(workflow["narration_mp3"]).exists()

    response = client.post(
        f"/api/jobs/{job_id}/video/package",
        json={"audio_path": extracted["source_audio_wav"]},
    )
    assert response.status_code == 200, response.text
    packaged = response.json()
    assert Path(packaged["final_video"]).exists()


def test_web_index_is_served(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    config["jobs"]["root_dir"] = str(tmp_path / "jobs")
    app = create_app()
    app.state.config = config
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "电影配音媒体控制台" in response.text


def test_media_api_accepts_wav_upload(tmp_path: Path) -> None:
    config = load_config("config.yaml")
    config["jobs"]["root_dir"] = str(tmp_path / "jobs")
    source_wav = tmp_path / "source.wav"
    _write_test_wav(source_wav)

    app = create_app()
    app.state.config = config
    client = TestClient(app)

    with source_wav.open("rb") as reader:
        response = client.post(
            "/api/jobs",
            files={"file": ("source.wav", reader, "audio/wav")},
        )
    assert response.status_code == 200, response.text
    job = response.json()
    job_id = job["job_id"]
    assert job["input_kind"] == "wav"
    assert Path(job["paths"]["input"]).name == "original.wav"

    response = client.get(f"/api/jobs/{job_id}/media/probe")
    assert response.status_code == 200, response.text
    probe = response.json()
    assert probe["has_audio"] is True
    assert probe["has_video"] is False

    response = client.post(f"/api/jobs/{job_id}/media/extract-audio")
    assert response.status_code == 200, response.text
    extracted = response.json()
    assert Path(extracted["source_audio_wav"]).exists()


def _write_test_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\0\0" * 16000)


def _make_test_mp4(ffmpeg: Path, output_path: Path) -> None:
    if not ffmpeg.exists():
        pytest.skip("FFmpeg is not available.")
    command = [
        str(ffmpeg),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=160x90:r=25",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=16000",
        "-t",
        "1",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(output_path),
    ]
    result = shutil.which(str(ffmpeg))
    assert ffmpeg.exists() or result is not None
    import subprocess

    subprocess.run(command, check=True, capture_output=True, text=True)
