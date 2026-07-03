from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import config_value, find_binary, load_config, resolve_path


class ConfigTests(unittest.TestCase):
    def test_load_config_contains_media_defaults(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "DOUBAO_TOS_ENDPOINT": "",
                "DOUBAO_TOS_REGION": "",
                "DOUBAO_TOS_BUCKET": "",
                "DOUBAO_TOS_PREFIX": "",
            },
        ):
            config = load_config("config.yaml")

        self.assertEqual(config_value(config, "server.host"), "127.0.0.1")
        self.assertEqual(config_value(config, "jobs.root_dir"), "outputs/jobs")
        self.assertEqual(config_value(config, "asr.provider"), "mock")
        self.assertEqual(config_value(config, "asr.resource_id"), "volc.seedasr.auc")
        self.assertEqual(config_value(config, "tos.object_prefix"), "movie-dub/asr")
        self.assertEqual(config_value(config, "tts.provider"), "doubao")
        self.assertEqual(config_value(config, "tts.doubao.resource_id"), "seed-tts-2.0")
        self.assertEqual(config_value(config, "tts.doubao.endpoint"), "https://openspeech.bytedance.com/api/v3/tts/unidirectional")

    def test_load_config_applies_tos_env_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text("tos:\n  bucket: \"\"\n", encoding="utf-8")
            env = {
                "DOUBAO_TOS_ENDPOINT": "tos-cn-beijing.volces.com",
                "DOUBAO_TOS_REGION": "cn-beijing",
                "DOUBAO_TOS_BUCKET": "movie-dub",
                "DOUBAO_TOS_PREFIX": "movie-dub/asr",
            }

            with patch.dict("os.environ", env, clear=True):
                config = load_config(config_path)

        self.assertEqual(config_value(config, "tos.endpoint"), "tos-cn-beijing.volces.com")
        self.assertEqual(config_value(config, "tos.region"), "cn-beijing")
        self.assertEqual(config_value(config, "tos.bucket"), "movie-dub")
        self.assertEqual(config_value(config, "tos.object_prefix"), "movie-dub/asr")

    def test_resolve_path_uses_project_root_for_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = {"project_root": tmp}

            resolved = resolve_path(config, "outputs/jobs")

            self.assertEqual(resolved, Path(tmp).joinpath("outputs/jobs").resolve())

    def test_find_binary_prefers_configured_existing_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "tool.exe"
            binary.write_text("", encoding="utf-8")
            config = {
                "project_root": tmp,
                "ffmpeg": {"ffmpeg_path": "tool.exe"},
            }

            self.assertEqual(find_binary(config, "ffmpeg.ffmpeg_path", "missing"), binary.resolve())


if __name__ == "__main__":
    unittest.main()
