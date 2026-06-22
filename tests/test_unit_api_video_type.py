from __future__ import annotations

import io
import unittest

try:
    import pytest
except ModuleNotFoundError as exc:  # pragma: no cover
    raise unittest.SkipTest("pytest is not installed.") from exc

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.api.app import create_app  # noqa: E402
from src.config import load_config  # noqa: E402


def _client(tmp_path):
    config = load_config("config.yaml")
    config["jobs"]["root_dir"] = str(tmp_path / "jobs")
    app = create_app()
    app.state.config = config
    return TestClient(app)


class VideoTypeApiTests(unittest.TestCase):
    def test_upload_with_manju_video_type(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            client = _client(Path(tmp))
            payload = b"fake mp4 bytes"
            response = client.post(
                "/api/jobs",
                files={"file": ("clip.mp4", io.BytesIO(payload), "video/mp4")},
                data={"video_type": "manju"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            job = response.json()
            self.assertEqual(job["video_type"], "manju")

    def test_upload_defaults_to_movie_commentary(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            client = _client(Path(tmp))
            response = client.post(
                "/api/jobs",
                files={"file": ("clip.mp3", io.BytesIO(b"x"), "audio/mpeg")},
            )
            self.assertEqual(response.status_code, 200, response.text)
            job = response.json()
            self.assertEqual(job["video_type"], "movie_commentary")

    def test_upload_rejects_unknown_video_type(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            client = _client(Path(tmp))
            response = client.post(
                "/api/jobs",
                files={"file": ("clip.mp3", io.BytesIO(b"x"), "audio/mpeg")},
                data={"video_type": "anime"},
            )
            self.assertEqual(response.status_code, 400, response.text)


if __name__ == "__main__":
    unittest.main()
