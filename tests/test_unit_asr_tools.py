from __future__ import annotations

import sys
import tempfile
import types
import unittest
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.tools import asr_tools
from src.tools.asr_tools import (
    _transcribe_with_whisperx,
    extract_doubao_words,
    map_doubao_result_to_cues,
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

    def test_doubao_file_provider_uploads_and_writes_words(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            audio = Path(d) / "x.wav"
            audio.write_bytes(b"audio")
            out = Path(d) / "out.words.json"
            fake_result = {
                "result": {
                    "utterances": [
                        {
                            "start_time": 0,
                            "end_time": 1000,
                            "text": "hello.",
                            "speaker_id": "1",
                            "words": [
                                {"start_time": 0, "end_time": 500, "text": "hel", "speaker_id": "1"},
                                {"start_time": 500, "end_time": 1000, "text": "lo", "speaker_id": "1"},
                            ],
                        }
                    ]
                }
            }
            with patch.object(asr_tools, "upload_file_to_tos", return_value={"url": "https://signed.example/x.wav"}):
                with patch.object(asr_tools, "_run_doubao_file_recognition", return_value=fake_result) as run:
                    result = transcribe_mp3_to_srt(
                        audio,
                        out,
                        {
                            "asr": {
                                "provider": "doubao_file",
                                "enable_speaker_info": True,
                                "srt_emit_speaker": True,
                            }
                        },
                    )
                    self.assertTrue(out.exists())

        run.assert_called_once()
        self.assertEqual(result["provider"], "doubao_file")
        self.assertTrue(result["diarized"])
        self.assertEqual(result["speakers"], ["speaker_1"])
        self.assertEqual(result["cues"][0]["speaker_id"], "speaker_1")
        self.assertEqual(result["word_count"], 2)

    def test_doubao_file_provider_assigns_default_speaker_for_single_speaker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            audio = Path(d) / "x.wav"
            audio.write_bytes(b"audio")
            fake_result = {
                "result": {
                    "utterances": [
                        {"start_time": 0, "end_time": 1000, "text": "旁白。"}
                    ]
                }
            }
            with patch.object(asr_tools, "upload_file_to_tos", return_value={"url": "https://signed.example/x.wav"}):
                with patch.object(asr_tools, "_run_doubao_file_recognition", return_value=fake_result):
                    result = transcribe_mp3_to_srt(
                        audio,
                        None,
                        {
                            "asr": {
                                "provider": "doubao_file",
                                "enable_speaker_info": False,
                                "default_speaker_id": "speaker_0",
                            }
                        },
                    )

        self.assertFalse(result["diarized"])
        self.assertEqual(result["speakers"], ["speaker_0"])
        self.assertEqual(result["cues"][0]["speaker_id"], "speaker_0")


class DoubaoMappingTests(unittest.TestCase):
    def test_maps_utterances_to_cues_and_normalizes_speakers(self) -> None:
        result = {
            "result": {
                "utterances": [
                    {"start_time": 0, "end_time": 1000, "text": "你好", "speaker_id": "1"},
                    {"start_time": 1200, "end_time": 2000, "text": "再见", "speaker": "2"},
                ]
            }
        }

        cues = map_doubao_result_to_cues(result, speaker_normalize=True)

        self.assertEqual(cues[0]["speaker_id"], "speaker_1")
        self.assertEqual(cues[1]["speaker_id"], "speaker_2")
        self.assertEqual(cues[1]["start_ms"], 1200)
        self.assertEqual(cues[1]["text"], "再见")

    def test_extracts_words_from_utterances(self) -> None:
        result = {
            "result": {
                "utterances": [
                    {
                        "speaker_id": "1",
                        "words": [
                            {"start_time": 0, "end_time": 100, "text": "你"},
                            {"start_time": 100, "end_time": 200, "word": "好", "speaker": "2"},
                        ],
                    }
                ]
            }
        }

        words = extract_doubao_words(result, speaker_normalize=True)

        self.assertEqual(words[0]["word"], "你")
        self.assertEqual(words[0]["speaker_id"], "speaker_1")
        self.assertEqual(words[1]["speaker_id"], "speaker_2")


class DoubaoHttpFlowTests(unittest.TestCase):
    def test_submit_and_query_use_official_headers_and_body(self) -> None:
        requests = []

        def fake_urlopen(request, timeout=None):
            requests.append(request)
            if len(requests) == 1:
                return _FakeHttpResponse(
                    b"",
                    {
                        "X-Api-Status-Code": "20000000",
                        "X-Api-Message": "OK",
                        "X-Tt-Logid": "submit-log",
                    },
                )
            return _FakeHttpResponse(
                json.dumps(
                    {
                        "result": {
                            "utterances": [
                                {"start_time": 0, "end_time": 1000, "text": "你好。"}
                            ]
                        }
                    }
                ).encode("utf-8"),
                {
                    "X-Api-Status-Code": "20000000",
                    "X-Api-Message": "OK",
                    "X-Tt-Logid": "query-log",
                },
            )

        config = {
            "api_key_env": "DOUBAO_ASR_API_KEY",
            "resource_id": "volc.seedasr.auc",
            "submit_url": "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit",
            "query_url": "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query",
            "uid": "unit-user",
            "language": "zh-CN",
            "audio_format": "wav",
            "enable_speaker_info": True,
            "enable_punc": True,
            "poll_interval": 0,
            "max_query_attempts": 1,
        }

        with patch.dict("os.environ", {"DOUBAO_ASR_API_KEY": "api-key"}, clear=True):
            with patch.object(asr_tools, "urlopen", side_effect=fake_urlopen, create=True):
                with patch.object(asr_tools, "uuid4", return_value=types.SimpleNamespace(__str__=lambda self: "task-1")):
                    result = asr_tools._run_doubao_file_recognition("https://signed.example/x.wav", config)

        self.assertEqual(result["result"]["utterances"][0]["text"], "你好。")
        submit_request = requests[0]
        submit_headers = {key.lower(): value for key, value in submit_request.header_items()}
        self.assertEqual(submit_request.full_url, config["submit_url"])
        self.assertEqual(submit_headers["x-api-key"], "api-key")
        self.assertEqual(submit_headers["x-api-resource-id"], "volc.seedasr.auc")
        self.assertEqual(submit_headers["x-api-sequence"], "-1")
        submit_body = json.loads(submit_request.data.decode("utf-8"))
        self.assertEqual(submit_body["audio"]["url"], "https://signed.example/x.wav")
        self.assertEqual(submit_body["audio"]["format"], "wav")
        self.assertEqual(submit_body["audio"]["language"], "zh-CN")
        self.assertTrue(submit_body["request"]["enable_speaker_info"])
        self.assertTrue(submit_body["request"]["show_utterances"])
        query_request = requests[1]
        self.assertEqual(query_request.full_url, config["query_url"])
        self.assertEqual(json.loads(query_request.data.decode("utf-8")), {})


class _FakeHttpResponse:
    def __init__(self, body: bytes, headers: dict[str, str]) -> None:
        self._body = body
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._body

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return self.headers.get(name, default)


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
