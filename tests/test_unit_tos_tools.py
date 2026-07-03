from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tools.tos_tools import upload_file_to_tos


class TosUploadTests(unittest.TestCase):
    def test_missing_source_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            missing = Path(d) / "missing.wav"

            with self.assertRaises(FileNotFoundError):
                upload_file_to_tos(missing, _config())

    def test_missing_credentials_raise_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            audio = Path(d) / "vocals.wav"
            audio.write_bytes(b"audio")

            with patch.dict("os.environ", {}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "DOUBAO_TOS_ACCESS_KEY_ID"):
                    upload_file_to_tos(audio, _config())

    def test_uploads_file_and_returns_presigned_url(self) -> None:
        fake_tos = _fake_tos_module()
        with tempfile.TemporaryDirectory() as d:
            audio = Path(d) / "vocals.wav"
            audio.write_bytes(b"audio")
            env = {
                "DOUBAO_TOS_ACCESS_KEY_ID": "ak",
                "DOUBAO_TOS_SECRET_ACCESS_KEY": "sk",
            }
            with patch.dict(sys.modules, {"tos": fake_tos}):
                with patch.dict("os.environ", env, clear=True):
                    with patch("src.tools.tos_tools.uuid4", return_value=types.SimpleNamespace(hex="abc123")):
                        result = upload_file_to_tos(
                            audio,
                            _config(),
                            object_prefix="jobs/job-1/asr",
                        )

        client = fake_tos.created_clients[0]
        self.assertEqual(client.init_args, ("ak", "sk", "tos-cn-beijing.volces.com", "cn-beijing"))
        self.assertEqual(client.uploads[0][0], "movie-dub")
        self.assertEqual(client.uploads[0][1], "jobs/job-1/asr/abc123_vocals.wav")
        self.assertEqual(client.uploads[0][2], str(audio))
        self.assertEqual(result["bucket"], "movie-dub")
        self.assertEqual(result["object_key"], "jobs/job-1/asr/abc123_vocals.wav")
        self.assertEqual(result["url"], "https://signed.example/jobs/job-1/asr/abc123_vocals.wav")
        self.assertEqual(result["expires"], 900)


def _config() -> dict:
    return {
        "tos": {
            "endpoint": "tos-cn-beijing.volces.com",
            "region": "cn-beijing",
            "bucket": "movie-dub",
            "access_key_id_env": "DOUBAO_TOS_ACCESS_KEY_ID",
            "secret_access_key_env": "DOUBAO_TOS_SECRET_ACCESS_KEY",
            "presign_expires": 900,
            "object_prefix": "asr",
        }
    }


def _fake_tos_module() -> types.ModuleType:
    module = types.ModuleType("tos")
    module.created_clients = []

    class HttpMethodType:
        Http_Method_Get = "GET"

    class FakeClient:
        def __init__(self, ak: str, sk: str, endpoint: str, region: str) -> None:
            self.init_args = (ak, sk, endpoint, region)
            self.uploads: list[tuple[str, str, str]] = []
            module.created_clients.append(self)

        def put_object_from_file(self, bucket: str, key: str, file_path: str) -> None:
            self.uploads.append((bucket, key, file_path))

        def pre_signed_url(self, method: str, bucket: str, key: str, expires: int) -> object:
            self.signed_args = (method, bucket, key, expires)
            return types.SimpleNamespace(signed_url=f"https://signed.example/{key}")

    module.TosClientV2 = FakeClient
    module.HttpMethodType = HttpMethodType
    return module


if __name__ == "__main__":
    unittest.main()
