from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.nodes.merge_zh_asr_node import (
    _parse_or_fallback,
    _snap_timestamps_to_source_boundaries,
    merge_zh_asr_srt,
)
from src.tools.srt_tools import format_srt, make_cue


class MergeZhAsrNodeTests(unittest.TestCase):
    def test_real_llm_merge_updates_raw_cues_and_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = _state(temp_dir)

            result = merge_zh_asr_srt(state)

            self.assertTrue(Path(result["reports"]["merge_zh_asr_report"]).exists())
            self.assertTrue(Path(state["config"]["paths"]["merged_asr_srt"]).exists())
            self.assertGreaterEqual(len(result["raw_cues"]), 1)
            self.assertLessEqual(len(result["raw_cues"]), 3)
            self.assertEqual(result["raw_cues"][0]["start_ms"], 0)
            self.assertEqual(result["raw_cues"][-1]["end_ms"], 3000)

    def test_invalid_llm_output_falls_back_to_original_cues(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = _state(temp_dir)
            result, error = _parse_or_fallback("not an srt", state["raw_cues"])

            self.assertEqual(len(result), 3)
            self.assertEqual(result[0]["text"], "这个男人")
            self.assertEqual(error, "LLM output is not valid SRT; fallback to original ASR cues.")

    def test_llm_output_with_small_timestamp_rounding_is_snapped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = _state(temp_dir)
            rounded = [
                make_cue(1, 0, 2500, "这个男人 被逼相亲"),
                make_cue(2, 2000, 3000, "态度还挺无所谓"),
            ]

            snapped = _snap_timestamps_to_source_boundaries(rounded, state["raw_cues"])
            result, error = _parse_or_fallback(snapped, state["raw_cues"])

            self.assertIsNone(error)
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]["end_ms"], 2000)
            self.assertEqual(result[0]["text"], "这个男人 被逼相亲")

    def test_llm_output_with_invalid_timeline_per_cue_fallback(self) -> None:
        """单条 cue 时间戳无效 → 仅丢弃该条,其余 LLM 合并结果保留,不全量回退。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            state = _state(temp_dir)
            # cue1 合法(0->2000 覆盖源1+2),cue2 时间戳严重错位(6900000 超出源范围)
            invalid = [
                make_cue(1, 0, 2000, "这个男人 被逼相亲"),
                make_cue(2, 6900000, 6950000, "态度还挺无所谓"),
            ]
            snapped = _snap_timestamps_to_source_boundaries(invalid, state["raw_cues"])
            result, error = _parse_or_fallback(snapped, state["raw_cues"])

            # cue1(合法)保留;cue2(无效)被丢弃,不全量回退到 3 条源 cue
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["text"], "这个男人 被逼相亲")
            self.assertEqual(result[0]["speaker_id"], "speaker_1")
            self.assertTrue(error)
            self.assertIn("Dropped", (error or ""))

    def test_disabled_llm_uses_fallback_without_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = _state(temp_dir)
            state["config"]["llm"] = {
                "api_key": "",
                "base_url": "",
                "model": "mock",
                "timeout": 1,
                "max_retries": 0,
            }

            result = merge_zh_asr_srt(state)

            self.assertEqual(len(result["raw_cues"]), 3)
            self.assertTrue(Path(result["reports"]["merge_zh_asr_report"]).exists())

    def test_llm_request_error_falls_back_to_original_cues(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = _state(temp_dir)
            state["config"]["llm"] = {
                "api_key": "test-key",
                "base_url": "https://example.invalid/v1",
                "model": "test-model",
                "timeout": 1,
                "max_retries": 0,
            }

            result = merge_zh_asr_srt(state)

            self.assertEqual(len(result["raw_cues"]), 3)
            self.assertEqual(result["raw_cues"][0]["text"], "这个男人")
            report_path = Path(result["reports"]["merge_zh_asr_report"])
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(report["used_fallback"])
            self.assertIn("LLM merge request failed", report["error"])


def _state(temp_dir: str) -> dict:
    root = Path(temp_dir)
    cues = [
        make_cue(1, 0, 1000, "这个男人", "speaker_1"),
        make_cue(2, 1000, 2000, "被逼相亲", "speaker_1"),
        make_cue(3, 2000, 3000, "态度还挺无所谓", "speaker_2"),
    ]
    return {
        "config": {
            "project_root": temp_dir,
            "paths": {
                "asr_srt": str(root / "asr" / "zh_raw.srt"),
                "merged_asr_srt": str(root / "merged" / "zh_asr_merged.srt"),
                "reports_dir": str(root / "reports"),
            },
            "llm": {
                "api_key": "sk-J3SAe2TtgYyfIE27M9ff96bQez6SU4SAorPJtGc8l2EawBcs",
                "base_url": "https://token.cxtfun.com/v1",
                "model": "glm-5.1",
                "timeout": 60,
                "max_retries": 0,
            },
        },
        "raw_srt": format_srt(cues),
        "raw_cues": cues,
        "reports": {},
    }


if __name__ == "__main__":
    unittest.main()
