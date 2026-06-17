from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from src.nodes.translate_node import translate_to_english
from src.tools.srt_tools import format_srt, make_cue


class TranslateNodeTests(unittest.TestCase):
    def test_translation_requires_configured_llm_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = _state(temp_dir, allow_mock_fallback=False)

            with self.assertRaisesRegex(RuntimeError, "LLM translation is not configured"):
                translate_to_english(state)

    def test_translation_allows_mock_fallback_only_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = _state(temp_dir, allow_mock_fallback=True)

            result = translate_to_english(state)

            self.assertEqual(len(result["final_cues"]), 2)
            self.assertIn("decisive moment", result["final_srt"])
            report = Path(result["reports"]["translation_report"])
            self.assertTrue(report.exists())

    def test_translation_rejects_invalid_llm_srt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = _state(temp_dir, allow_mock_fallback=False)
            state["config"]["llm"] = {
                "api_key": "test-key",
                "base_url": "https://example.invalid/v1",
                "model": "test-model",
                "timeout": 1,
                "max_retries": 0,
            }

            class FakeClient:
                def enabled(self) -> bool:
                    return True

                def complete(
                    self, system_prompt: str, user_content: str, fallback_text: str
                ) -> str:
                    return "This is not an SRT response."

            with patch("src.nodes.translate_node.LLMClient.from_config", return_value=FakeClient()):
                with self.assertRaisesRegex(RuntimeError, "translation output is invalid"):
                    translate_to_english(state)

    def test_parallel_chunked_translation_calls_llm_per_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = _state_with_count(temp_dir, count=6, allow_mock_fallback=False)
            state["config"]["translation"]["chunk_size"] = 2
            state["config"]["translation"]["max_parallel_chunks"] = 3
            state["config"]["llm"] = _enabled_llm_config()
            client = FakeChunkClient([
                _translated_chunk("Chunk one", 2),
                _translated_chunk("Chunk two", 2),
                _translated_chunk("Chunk three", 2),
            ])

            with patch("src.nodes.translate_node.LLMClient.from_config", return_value=client):
                result = translate_to_english(state)

            self.assertEqual(client.call_count, 3)
            self.assertEqual(len(result["final_cues"]), 6)
            report = Path(result["reports"]["translation_report"])
            self.assertTrue(report.exists())
            self.assertIn("Chunk", result["final_srt"])

    def test_parallel_chunked_translation_rejects_bad_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = _state_with_count(temp_dir, count=4, allow_mock_fallback=False)
            state["config"]["translation"]["chunk_size"] = 2
            state["config"]["translation"]["max_parallel_chunks"] = 2
            state["config"]["llm"] = _enabled_llm_config()
            client = FakeChunkClient([
                _translated_chunk("Good", 2),
                _translated_chunk("Bad", 1),
            ])

            with patch("src.nodes.translate_node.LLMClient.from_config", return_value=client):
                with self.assertRaisesRegex(RuntimeError, "chunk 2.*expected 2.*got 1"):
                    translate_to_english(state)

    def test_chunked_translation_preserves_source_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = _state_with_count(temp_dir, count=3, allow_mock_fallback=False)
            state["config"]["translation"]["chunk_size"] = 2
            state["config"]["translation"]["max_parallel_chunks"] = 2
            state["config"]["llm"] = _enabled_llm_config()
            wrong_time_cues = [make_cue(1, 999000, 999500, "Wrong time A"), make_cue(2, 999500, 999900, "Wrong time B")]
            wrong_time_cues_2 = [make_cue(1, 888000, 888500, "Wrong time C")]
            client = FakeChunkClient([format_srt(wrong_time_cues), format_srt(wrong_time_cues_2)])

            with patch("src.nodes.translate_node.LLMClient.from_config", return_value=client):
                result = translate_to_english(state)

            for source, translated in zip(state["corrected_cues"], result["final_cues"]):
                self.assertEqual(translated["start_ms"], source["start_ms"])
                self.assertEqual(translated["end_ms"], source["end_ms"])

    def test_chunk_size_zero_uses_single_llm_call(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = _state_with_count(temp_dir, count=4, allow_mock_fallback=False)
            state["config"]["translation"]["chunk_size"] = 0
            state["config"]["translation"]["max_parallel_chunks"] = 3
            state["config"]["llm"] = _enabled_llm_config()
            client = FakeChunkClient([_translated_chunk("Single", 4)])

            with patch("src.nodes.translate_node.LLMClient.from_config", return_value=client):
                result = translate_to_english(state)

            self.assertEqual(client.call_count, 1)
            self.assertEqual(len(result["final_cues"]), 4)


def _state(temp_dir: str, allow_mock_fallback: bool) -> dict[str, Any]:
    cues = [
        make_cue(1, 0, 2000, "主角进入房间。"),
        make_cue(2, 2000, 4200, "他发现事情不对。"),
    ]
    root = Path(temp_dir)
    return {
        "config": {
            "project_root": temp_dir,
            "paths": {
                "translated_srt": str(root / "translated" / "en_translated.srt"),
                "final_srt": str(root / "final" / "en_final.srt"),
                "reports_dir": str(root / "reports"),
            },
            "translation": {"allow_mock_fallback": allow_mock_fallback},
            "llm": {
                "api_key": "",
                "base_url": "",
                "model": "mock",
                "timeout": 1,
                "max_retries": 0,
            },
        },
        "corrected_cues": cues,
        "corrected_srt": format_srt(cues),
        "plot_summary": "主角发现异常。",
        "reports": {},
    }


def _state_with_count(temp_dir: str, count: int, allow_mock_fallback: bool) -> dict[str, Any]:
    root = Path(temp_dir)
    cues = [make_cue(i, (i - 1) * 1000, i * 1000, f"第 {i} 条字幕。") for i in range(1, count + 1)]
    return {
        "config": {
            "project_root": temp_dir,
            "paths": {
                "translated_srt": str(root / "translated" / "en_translated.srt"),
                "final_srt": str(root / "final" / "en_final.srt"),
                "reports_dir": str(root / "reports"),
            },
            "translation": {"allow_mock_fallback": allow_mock_fallback},
            "llm": {
                "api_key": "",
                "base_url": "",
                "model": "mock",
                "timeout": 1,
                "max_retries": 0,
            },
        },
        "corrected_cues": cues,
        "corrected_srt": format_srt(cues),
        "plot_summary": "测试剧情。",
        "reports": {},
    }


def _enabled_llm_config() -> dict[str, Any]:
    return {
        "api_key": "test-key",
        "base_url": "https://example.invalid/v1",
        "model": "test-model",
        "timeout": 1,
        "max_retries": 0,
    }


def _translated_chunk(prefix: str, count: int) -> str:
    cues = [make_cue(i, (i - 1) * 1000, i * 1000, f"{prefix} {i}") for i in range(1, count + 1)]
    return format_srt(cues)


class FakeChunkClient:
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.inputs: list[str] = []
        self._next_index = 0

    @property
    def call_count(self) -> int:
        return len(self.inputs)

    def enabled(self) -> bool:
        return True

    def complete(self, system_prompt: str, user_content: str, fallback_text: str) -> str:
        self.inputs.append(user_content)
        index = self._next_index
        self._next_index += 1
        if index < len(self.responses):
            return self.responses[index]
        return self.responses[-1]


if __name__ == "__main__":
    unittest.main()
