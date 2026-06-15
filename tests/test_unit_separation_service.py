from __future__ import annotations

import os
import tempfile
import unittest
import wave
from pathlib import Path

import torch

from src.services.separation_service import _separation_hint
from src.tools.separation_tools import _demucs_env, _write_tensor_wav


class SeparationServiceTests(unittest.TestCase):
    def test_torchcodec_error_has_actionable_hint(self) -> None:
        hint = _separation_hint("ModuleNotFoundError: No module named 'torchcodec'")

        self.assertIn("torchcodec", hint)
        self.assertIn("separation.method=python", hint)

    def test_demucs_interruption_has_actionable_hint(self) -> None:
        hint = _separation_hint("Demucs command failed with exit code 3221225786: KeyboardInterrupt")

        self.assertIn("中断", hint)
        self.assertIn("config.yaml", hint)

    def test_demucs_env_prepends_configured_ffmpeg_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ffmpeg_dir = Path(temp_dir) / "ffmpeg" / "bin"
            ffmpeg_dir.mkdir(parents=True)
            ffmpeg_path = ffmpeg_dir / "ffmpeg.exe"
            ffmpeg_path.write_text("", encoding="utf-8")
            config = {"project_root": temp_dir, "ffmpeg": {"ffmpeg_path": "ffmpeg/bin/ffmpeg.exe"}}

            env = _demucs_env(config)

        self.assertEqual(env["PATH"].split(os.pathsep)[0], str(ffmpeg_dir.resolve()))

    def test_write_tensor_wav_creates_readable_pcm(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "audio.wav"
            audio = torch.zeros((2, 800), dtype=torch.float32)

            _write_tensor_wav(path, audio, 8000)

            with wave.open(str(path), "rb") as reader:
                self.assertEqual(reader.getnchannels(), 2)
                self.assertEqual(reader.getframerate(), 8000)
                self.assertEqual(reader.getnframes(), 800)


if __name__ == "__main__":
    unittest.main()
