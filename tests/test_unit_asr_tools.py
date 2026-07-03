from __future__ import annotations

import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tools import asr_tools
from src.tools.asr_tools import (
    extract_doubao_words,
    map_doubao_result_to_cues,
    transcribe_mp3_to_srt,
    write_asr_report,
)


class AsrProviderDispatchTests(unittest.TestCase):
    def test_mock_provider_default(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.srt"
            with patch.object(asr_tools, "_mock_transcribe", return_value=[]):
                result = transcribe_mp3_to_srt(Path(d) / "x.mp3", out, {"asr": {"provider": "mock"}})
            self.assertEqual(result["provider"], "mock")
            self.assertEqual(result["speakers"], [])
            self.assertFalse(result["diarized"])

    def test_unsupported_legacy_provider_raises(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError, "Unsupported ASR provider"):
                transcribe_mp3_to_srt(
                    Path(d) / "x.mp3",
                    None,
                    {"asr": {"provider": "legacy_local"}},
                )

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
    def test_doubao_payload_omits_empty_language_and_uses_official_defaults(self) -> None:
        audio_payload = asr_tools._doubao_audio_payload(
            "https://signed.example/x.wav",
            {"audio_format": "wav", "language": ""},
        )
        request_payload = asr_tools._doubao_request_payload({"doubao_model_name": "bigmodel"})

        self.assertNotIn("language", audio_payload)
        self.assertEqual(audio_payload["format"], "wav")
        self.assertEqual(request_payload["model_name"], "bigmodel")
        self.assertTrue(request_payload["enable_itn"])
        self.assertFalse(request_payload["enable_punc"])
        self.assertFalse(request_payload["enable_ddc"])
        self.assertTrue(request_payload["show_utterances"])

    def test_doubao_payload_sends_enable_ddc_when_enabled(self) -> None:
        request_payload = asr_tools._doubao_request_payload({"enable_ddc": True})

        self.assertTrue(request_payload["enable_ddc"])

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
            "enable_ddc": True,
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
        self.assertTrue(submit_body["request"]["enable_ddc"])
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


class AsrReportTests(unittest.TestCase):
    def test_report_includes_speakers_and_diarized(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.json"
            write_asr_report(
                path,
                {"provider": "doubao_file", "speakers": ["speaker_1"], "diarized": True},
            )
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["speakers"], ["speaker_1"])
            self.assertTrue(data["diarized"])


if __name__ == "__main__":
    unittest.main()
