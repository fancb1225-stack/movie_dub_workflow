from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.config import config_value, find_binary, load_config, resolve_path


class ConfigTests(unittest.TestCase):
    def test_load_config_contains_media_defaults(self) -> None:
        config = load_config("config.yaml")

        self.assertEqual(config_value(config, "server.host"), "127.0.0.1")
        self.assertEqual(config_value(config, "jobs.root_dir"), "outputs/jobs")
        self.assertEqual(config_value(config, "speaker.mode"), "placeholder")

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

