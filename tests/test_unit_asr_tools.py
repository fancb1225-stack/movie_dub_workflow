from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.tools import asr_tools
from src.tools.asr_tools import (
    _transcribe_with_whisperx,
    map_whisperx_result_to_cues,
    transcribe_mp3_to_srt,
    write_asr_report,
)


def _whisperx_result(with_speaker: bool = True) -> dict:
    seg = {"start": 0.0, "end": 2.5, "text": "hello world"}
    if with_speaker:
        seg["speaker"] = "SPEAKER_00"
    return {"segments": [seg, {"start": 2.5, "end": 5.0, "text": "second", "speaker": "SPEAKER_01"}]}


class MapWhisperxResultToCuesTests(unittest.TestCase):
    def test_normalizes_speaker_labels(self) -> None:
        cues = map_whisperx_result_to_cues(_whisperx_result(), speaker_normalize=True)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0]["speaker_id"], "speaker_1")
        self.assertEqual(cues[1]["speaker_id"], "speaker_2")

    def test_keeps_raw_label_when_normalize_false(self) -> None:
        cues = map_whisperx_result_to_cues(_whisperx_result(), speaker_normalize=False)
        self.assertEqual(cues[0]["speaker_id"], "SPEAKER_00")

    def test_missing_speaker_omits_speaker_id(self) -> None:
        cues = map_whisperx_result_to_cues(_whisperx_result(with_speaker=False), speaker_normalize=True)
        self.assertNotIn("speaker_id", cues[0])

    def test_index_timestamps_and_text(self) -> None:
        cues = map_whisperx_result_to_cues(_whisperx_result())
        self.assertEqual(cues[0]["index"], 1)
        self.assertEqual(cues[0]["start_ms"], 0)
        self.assertEqual(cues[0]["end_ms"], 2500)
        self.assertEqual(cues[0]["text"], "hello world")


class WhisperxProviderDispatchTests(unittest.TestCase):
    def test_mock_provider_default(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.srt"
            with patch.object(asr_tools, "_mock_transcribe", return_value=[]):
                result = transcribe_mp3_to_srt(Path(d) / "x.mp3", out, {"asr": {"provider": "mock"}})
            self.assertEqual(result["provider"], "mock")
            self.assertEqual(result["speakers"], [])
            self.assertFalse(result["diarized"])

    def test_whisperx_provider_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.words.json"
            fake_cues = map_whisperx_result_to_cues(_whisperx_result())
            with patch.object(asr_tools, "_transcribe_with_whisperx", return_value=(fake_cues, [])) as m:
                result = transcribe_mp3_to_srt(
                    Path(d) / "x.mp3", out, {"asr": {"provider": "whisperx"}}
                )
            m.assert_called_once()
            self.assertEqual(result["provider"], "whisperx")
            self.assertEqual(result["speakers"], ["speaker_1", "speaker_2"])
            self.assertTrue(result["diarized"])

    def test_whisperx_missing_dep_falls_back_to_faster_whisper(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.words.json"
            fake_cues = map_whisperx_result_to_cues(_whisperx_result(with_speaker=False))
            with patch.object(
                asr_tools, "_transcribe_with_whisperx", side_effect=RuntimeError("no whisperx")
            ), patch.object(
                asr_tools, "_transcribe_with_faster_whisper", return_value=fake_cues
            ) as fb:
                result = transcribe_mp3_to_srt(
                    Path(d) / "x.mp3",
                    out,
                    {"asr": {"provider": "whisperx", "whisperx_missing_dep_fallback": True}},
                )
            fb.assert_called_once()
            self.assertEqual(result["provider"], "whisperx")
            self.assertFalse(result["diarized"])

    def test_whisperx_missing_dep_no_fallback_raises(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.words.json"
            with patch.object(
                asr_tools, "_transcribe_with_whisperx", side_effect=RuntimeError("no whisperx")
            ):
                with self.assertRaises(RuntimeError):
                    transcribe_mp3_to_srt(Path(d) / "x.mp3", out, {"asr": {"provider": "whisperx"}})

    def test_faster_whisper_assigns_default_speaker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.words.json"
            fake_cues = [{"index": 1, "start_ms": 0, "end_ms": 1000, "text": "hello"}]
            with patch.object(asr_tools, "_transcribe_with_faster_whisper", return_value=fake_cues):
                result = transcribe_mp3_to_srt(
                    Path(d) / "x.mp3",
                    out,
                    {"asr": {"provider": "faster_whisper", "default_speaker_id": "speaker_0"}},
                )

        self.assertEqual(result["provider"], "faster_whisper")
        self.assertEqual(result["cues"][0]["speaker_id"], "speaker_0")
        self.assertEqual(result["speakers"], ["speaker_0"])
        self.assertFalse(result["diarized"])


class WhisperxTranscribeTests(unittest.TestCase):
    def _install_fake_whisperx(self, diarize_fail: bool = False) -> types.ModuleType:
        fake = types.ModuleType("whisperx")
        diarize_mod = types.ModuleType("whisperx.diarize")

        class FakePipeline:
            def __init__(self, *a, **k):
                pass

            def __call__(self, audio, min_speakers=None, max_speakers=None):
                if diarize_fail:
                    raise RuntimeError("diarize boom")
                import pandas as pd

                return pd.DataFrame(
                    [{"start": 0.0, "end": 5.0, "label": "SPEAKER_00", "speaker": "SPEAKER_00"}]
                )

        def assign_word_speakers(diarize_df, transcript_result, **k):
            for seg in transcript_result["segments"]:
                seg["speaker"] = "SPEAKER_00"
                for word in seg.get("words", []) or []:
                    word["speaker"] = "SPEAKER_00"
            for word in transcript_result.get("word_segments", []) or []:
                word["speaker"] = "SPEAKER_00"
            return transcript_result

        diarize_mod.DiarizationPipeline = FakePipeline
        diarize_mod.assign_word_speakers = assign_word_speakers
        fake.diarize = diarize_mod
        fake.load_model = MagicMock(return_value=MagicMock())
        fake.load_audio = MagicMock(return_value=object())
        fake.load_align_model = MagicMock(return_value=(MagicMock(), {}))
        fake.align = MagicMock(
            side_effect=lambda segments, *a, **k: {
                "segments": [
                    {
                        **segments[0],
                        "words": [
                            {"word": "hello", "start": 0.0, "end": 0.5},
                        ],
                    }
                ],
                "word_segments": [
                    {"word": "hello", "start": 0.0, "end": 0.5},
                ],
            }
        )

        def transcribe(audio, batch_size=None, language=None):
            return {"segments": [{"start": 0.0, "end": 2.5, "text": "hello"}]}

        fake.load_model.return_value.transcribe = transcribe
        return fake

    def test_missing_whisperx_dep_raises_runtime_error(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / "x.wav"
            wav.write_bytes(b"")
            with patch.dict(sys.modules, {"whisperx": None, "whisperx.diarize": None}):
                with self.assertRaises(RuntimeError):
                    _transcribe_with_whisperx(wav, {})

    def test_diarize_failure_falls_back_to_asr(self) -> None:
        fake = self._install_fake_whisperx(diarize_fail=True)
        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / "x.wav"
            wav.write_bytes(b"")
            with patch.dict(sys.modules, {"whisperx": fake, "whisperx.diarize": fake.diarize}):
                cues, words = _transcribe_with_whisperx(
                    wav,
                    {"diarize": True, "diarize_fallback_to_asr": True, "hf_token_env": "HF_TOKEN"},
                )
        self.assertEqual(len(cues), 1)
        self.assertNotIn("speaker_id", cues[0])
        self.assertEqual(words, [{"index": 1, "word": "hello", "start_ms": 0, "end_ms": 500}])

    def test_diarize_failure_without_fallback_raises(self) -> None:
        fake = self._install_fake_whisperx(diarize_fail=True)
        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / "x.wav"
            wav.write_bytes(b"")
            with patch.dict(sys.modules, {"whisperx": fake, "whisperx.diarize": fake.diarize}):
                with self.assertRaises(RuntimeError):
                    _transcribe_with_whisperx(
                        wav,
                        {"diarize": True, "diarize_fallback_to_asr": False, "hf_token_env": "HF_TOKEN"},
                    )

    def test_missing_hf_token_falls_back(self) -> None:
        fake = self._install_fake_whisperx()
        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / "x.wav"
            wav.write_bytes(b"")
            with patch.dict(sys.modules, {"whisperx": fake, "whisperx.diarize": fake.diarize}):
                with patch("os.getenv", return_value=""):
                    cues, _words = _transcribe_with_whisperx(
                        wav,
                        {"diarize": True, "diarize_fallback_to_asr": True, "hf_token_env": "HF_TOKEN"},
                    )
        self.assertNotIn("speaker_id", cues[0])
        self.assertEqual(_words, [{"index": 1, "word": "hello", "start_ms": 0, "end_ms": 500}])

    def test_whisperx_align_receives_segments_and_returns_words(self) -> None:
        fake = self._install_fake_whisperx()
        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / "x.wav"
            wav.write_bytes(b"")
            with patch.dict(sys.modules, {"whisperx": fake, "whisperx.diarize": fake.diarize}):
                with patch("os.getenv", return_value=""):
                    cues, words = _transcribe_with_whisperx(
                        wav,
                        {"align": True, "diarize": False, "language": "zh", "device": "cpu"},
                    )

        first_arg = fake.align.call_args.args[0]
        self.assertIsInstance(first_arg, list)
        self.assertEqual(first_arg[0]["text"], "hello")
        self.assertEqual(words[0]["word"], "hello")
        self.assertEqual(cues[0]["text"], "hello")

    def test_whisperx_align_failure_strict_raises(self) -> None:
        fake = self._install_fake_whisperx()
        fake.align.side_effect = RuntimeError("align boom")
        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / "x.wav"
            wav.write_bytes(b"")
            with patch.dict(sys.modules, {"whisperx": fake, "whisperx.diarize": fake.diarize}):
                with self.assertRaisesRegex(RuntimeError, "whisperx alignment failed"):
                    _transcribe_with_whisperx(
                        wav,
                        {"align": True, "align_strict": True, "diarize": False},
                    )

    def test_diarize_success_assigns_speaker(self) -> None:
        fake = self._install_fake_whisperx()
        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / "x.wav"
            wav.write_bytes(b"")
            with patch.dict(sys.modules, {"whisperx": fake, "whisperx.diarize": fake.diarize}):
                with patch("os.getenv", return_value="fake-token"):
                    cues, _words = _transcribe_with_whisperx(
                        wav,
                        {"diarize": True, "diarize_fallback_to_asr": True, "hf_token_env": "HF_TOKEN"},
                    )
        self.assertEqual(cues[0]["speaker_id"], "speaker_1")
        self.assertEqual(_words[0]["speaker_id"], "speaker_1")


class AsrReportTests(unittest.TestCase):
    def test_report_includes_speakers_and_diarized(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.json"
            write_asr_report(
                path,
                {"provider": "whisperx", "speakers": ["speaker_1"], "diarized": True},
            )
            import json

            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["speakers"], ["speaker_1"])
            self.assertTrue(data["diarized"])


if __name__ == "__main__":
    unittest.main()
