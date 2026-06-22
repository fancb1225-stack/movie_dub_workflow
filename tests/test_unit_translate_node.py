from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from src.nodes.translate_node import translate_to_english
from src.tools.srt_tools import format_srt, make_cue
from src import manju_prompt, prompts


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

    def test_translation_falls_back_on_invalid_llm_srt(self) -> None:
        """LLM 返回非 SRT → 重试耗尽后用源文本占位，不抛错，条数对齐。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            state = _state(temp_dir, allow_mock_fallback=False)
            state["config"]["llm"] = {
                "api_key": "test-key",
                "base_url": "https://example.invalid/v1",
                "model": "test-model",
                "timeout": 1,
                "max_retries": 0,
            }
            state["config"]["translation"]["chunk_max_retries"] = 1

            class FakeClient:
                def enabled(self) -> bool:
                    return True

                def complete(
                    self, system_prompt: str, user_content: str, fallback_text: str
                ) -> str:
                    return "This is not an SRT response."

            with patch("src.nodes.translate_node.LLMClient.from_config", return_value=FakeClient()):
                result = translate_to_english(state)

            # 占位保留源文本，条数对齐
            self.assertEqual(len(result["final_cues"]), 2)
            self.assertEqual(result["final_cues"][0]["text"], "主角进入房间。")
            report = Path(result["reports"]["translation_report"])
            self.assertTrue(report.exists())

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

    def test_parallel_chunked_translation_retries_bad_chunk_then_succeeds(self) -> None:
        """坏块重试成功：第 2 块首次返回 1 条(应 2)，重试后返回 2 条，整体不抛错。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            state = _state_with_count(temp_dir, count=4, allow_mock_fallback=False)
            state["config"]["translation"]["chunk_size"] = 2
            state["config"]["translation"]["max_parallel_chunks"] = 2
            state["config"]["translation"]["chunk_max_retries"] = 3
            state["config"]["llm"] = _enabled_llm_config()
            client = FakeRetryChunkClient(
                [
                    _translated_chunk("Good A", 2),  # chunk 1 一次成功
                    [  # chunk 2: 首次坏，重试好
                        _translated_chunk("Bad", 1),
                        _translated_chunk("Good B", 2),
                    ],
                ]
            )

            with patch("src.nodes.translate_node.LLMClient.from_config", return_value=client):
                result = translate_to_english(state)

            self.assertEqual(len(result["final_cues"]), 4)
            self.assertIn("Good B", result["final_srt"])

    def test_parallel_chunked_translation_falls_back_when_chunk_keeps_failing(self) -> None:
        """坏块重试耗尽仍失败 → 用源文本占位该块，不抛错，条数对齐，报告记录失败块。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            state = _state_with_count(temp_dir, count=4, allow_mock_fallback=False)
            state["config"]["translation"]["chunk_size"] = 2
            state["config"]["translation"]["max_parallel_chunks"] = 2
            state["config"]["translation"]["chunk_max_retries"] = 2
            state["config"]["llm"] = _enabled_llm_config()
            client = FakeChunkClient([
                _translated_chunk("Good", 2),
                _translated_chunk("Bad", 1),  # chunk 2 始终坏
            ])

            with patch("src.nodes.translate_node.LLMClient.from_config", return_value=client):
                result = translate_to_english(state)

            # 整体不抛错，4 条全部保留(chunk 2 用源文本占位)
            self.assertEqual(len(result["final_cues"]), 4)
            # chunk 2 的两条保留源文本
            self.assertEqual(result["final_cues"][2]["text"], "第 3 条字幕。")
            self.assertEqual(result["final_cues"][3]["text"], "第 4 条字幕。")
            report = Path(result["reports"]["translation_report"])
            report_data = __import__("json").loads(report.read_text(encoding="utf-8"))
            self.assertEqual(report_data["failed_chunks"], [2])

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

    def test_default_video_type_uses_movie_commentary_translate_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = _state_with_count(temp_dir, count=2, allow_mock_fallback=False)
            state["config"]["translation"]["chunk_size"] = 0
            state["config"]["llm"] = _enabled_llm_config()
            client = FakeChunkClient([_translated_chunk("Translated", 2)])

            with patch("src.nodes.translate_node.LLMClient.from_config", return_value=client):
                translate_to_english(state)

            self.assertIs(client.last_system_prompt, prompts.TRANSLATE_TO_ENGLISH_SRT_PROMPT)

    def test_manju_video_type_uses_manju_translate_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = _state_with_count(temp_dir, count=2, allow_mock_fallback=False)
            state["config"]["translation"]["chunk_size"] = 0
            state["config"]["llm"] = _enabled_llm_config()
            state["config"]["job"] = {"video_type": "manju"}
            client = FakeChunkClient([_translated_chunk("Translated", 2)])

            with patch("src.nodes.translate_node.LLMClient.from_config", return_value=client):
                translate_to_english(state)

            self.assertIs(client.last_system_prompt, manju_prompt.TRANSLATE_TO_ENGLISH_SRT_PROMPT)


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
        self.last_system_prompt: str | None = None
        self._next_index = 0

    @property
    def call_count(self) -> int:
        return len(self.inputs)

    def enabled(self) -> bool:
        return True

    def complete(self, system_prompt: str, user_content: str, fallback_text: str) -> str:
        self.inputs.append(user_content)
        self.last_system_prompt = system_prompt
        index = self._next_index
        self._next_index += 1
        if index < len(self.responses):
            return self.responses[index]
        return self.responses[-1]


class FakeRetryChunkClient:
    """按 user_content 维护返回队列，支持同一块多次重试返回不同结果。

    responses 元素为 str(单次返回)或 list[str](按重试顺序返回)。
    """

    def __init__(self, responses: list):
        # 首次见到某 user_content 时，从 responses 按序取一个元素作为该块的队列
        self._queues: dict[str, list[str]] = {}
        self._pending = list(responses)
        self._assignment_order: list[str] = []

    def enabled(self) -> bool:
        return True

    def complete(self, system_prompt: str, user_content: str, fallback_text: str) -> str:
        if user_content not in self._queues:
            spec = self._pending.pop(0) if self._pending else ""
            if isinstance(spec, list):
                self._queues[user_content] = list(spec)
            else:
                self._queues[user_content] = [spec]
            self._assignment_order.append(user_content)
        queue = self._queues[user_content]
        if len(queue) > 1:
            return queue.pop(0)
        return queue[0] if queue else ""


if __name__ == "__main__":
    unittest.main()
