from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import wave

from src.services.state_persistence import (
    NODE_ORDER,
    clear_state_snapshot,
    detect_last_completed_node,
    get_resume_node,
    get_resume_start_index,
    load_state_snapshot,
    save_state_snapshot,
)


def _sample_state() -> dict:
    return {
        "config": {"llm": {"model": "mock"}, "tts": {"provider": "mock"}},
        "raw_srt": "1\n00:00:00,000 --> 00:00:01,000\nhello\n",
        "raw_cues": [{"index": 1, "start": "00:00:00,000", "end": "00:00:01,000", "start_ms": 0, "end_ms": 1000, "text": "hello"}],
        "reflection_rounds": 0,
        "reports": {},
        "errors": [],
    }


class StatePersistenceTests(unittest.TestCase):
    def test_save_and_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = _sample_state()
            save_state_snapshot(tmp, state, "translate_to_english")
            result = load_state_snapshot(tmp)
            self.assertIsNotNone(result)
            loaded_state, last_node = result
            self.assertEqual(last_node, "translate_to_english")
            self.assertEqual(loaded_state["raw_srt"], state["raw_srt"])
            self.assertEqual(loaded_state["reflection_rounds"], 0)
            self.assertEqual(len(loaded_state["raw_cues"]), 1)

    def test_load_returns_none_when_no_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = load_state_snapshot(tmp)
            self.assertIsNone(result)

    def test_clear_removes_snapshot_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_state_snapshot(tmp, _sample_state(), "clean_srt")
            snapshot_path = Path(tmp) / "workflow" / "state_snapshot.json"
            self.assertTrue(snapshot_path.exists())
            clear_state_snapshot(tmp)
            self.assertFalse(snapshot_path.exists())

    def test_resume_node_mapping(self) -> None:
        self.assertEqual(get_resume_node("merge_zh_asr_srt"), "clean_srt")
        self.assertEqual(get_resume_node("translate_to_english"), "tts_generate_and_detect")
        self.assertEqual(get_resume_node("align_and_merge_audio"), None)

    def test_resume_start_index(self) -> None:
        self.assertEqual(get_resume_start_index("merge_zh_asr_srt"), 1)
        self.assertEqual(get_resume_start_index("clean_srt"), 2)
        self.assertEqual(get_resume_start_index("align_and_merge_audio"), len(NODE_ORDER))

    def test_resume_start_index_unknown_node(self) -> None:
        self.assertEqual(get_resume_start_index("unknown_node"), 0)

    def test_resume_node_none_when_completed(self) -> None:
        self.assertIsNone(get_resume_node("align_and_merge_audio"))

    def test_save_creates_workflow_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "jobs" / "test-job"
            save_state_snapshot(job_dir, _sample_state(), "clean_srt")
            self.assertTrue((job_dir / "workflow" / "state_snapshot.json").exists())

    def test_detect_last_completed_node_from_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            # Create artifacts up to translate_to_english
            (job_dir / "workflow" / "merged").mkdir(parents=True)
            (job_dir / "workflow" / "merged" / "zh_asr_merged.srt").write_text("1", encoding="utf-8")
            (job_dir / "workflow" / "cleaned").mkdir(parents=True)
            (job_dir / "workflow" / "cleaned" / "zh_cleaned.srt").write_text("1", encoding="utf-8")
            (job_dir / "workflow" / "critic").mkdir(parents=True)
            (job_dir / "workflow" / "critic" / "zh_corrected.srt").write_text("1", encoding="utf-8")
            (job_dir / "reports").mkdir(parents=True)
            (job_dir / "reports" / "plot_summary.txt").write_text("plot", encoding="utf-8")
            (job_dir / "workflow" / "translated").mkdir(parents=True)
            (job_dir / "workflow" / "translated" / "en_translated.srt").write_text("1", encoding="utf-8")

            result = detect_last_completed_node(job_dir)
            self.assertEqual(result, "translate_to_english")

    def test_detect_returns_none_when_no_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = detect_last_completed_node(tmp)
            self.assertIsNone(result)

    def test_detect_silent_narration_falls_back_to_tts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            # Create all artifacts including a silent narration
            (job_dir / "workflow" / "merged").mkdir(parents=True)
            (job_dir / "workflow" / "merged" / "zh_asr_merged.srt").write_text("1", encoding="utf-8")
            (job_dir / "workflow" / "cleaned").mkdir(parents=True)
            (job_dir / "workflow" / "cleaned" / "zh_cleaned.srt").write_text("1", encoding="utf-8")
            (job_dir / "workflow" / "critic").mkdir(parents=True)
            (job_dir / "workflow" / "critic" / "zh_corrected.srt").write_text("1", encoding="utf-8")
            (job_dir / "reports").mkdir(parents=True)
            (job_dir / "reports" / "plot_summary.txt").write_text("plot", encoding="utf-8")
            (job_dir / "workflow" / "translated").mkdir(parents=True)
            (job_dir / "workflow" / "translated" / "en_translated.srt").write_text("1", encoding="utf-8")
            (job_dir / "workflow" / "tts_segments").mkdir(parents=True)
            (job_dir / "workflow" / "audio").mkdir(parents=True)
            # Write a silent WAV
            silent_wav = job_dir / "workflow" / "audio" / "narration_en.wav"
            with wave.open(str(silent_wav), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(8000)
                writer.writeframes(b"\0\0" * 8000)

            result = detect_last_completed_node(job_dir)
            # Should fall back to tts_generate_and_detect since narration is silent
            self.assertEqual(result, "tts_generate_and_detect")

    def test_detect_non_silent_narration_stays_at_align(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            # Same as above but with non-silent WAV
            (job_dir / "workflow" / "merged").mkdir(parents=True)
            (job_dir / "workflow" / "merged" / "zh_asr_merged.srt").write_text("1", encoding="utf-8")
            (job_dir / "workflow" / "cleaned").mkdir(parents=True)
            (job_dir / "workflow" / "cleaned" / "zh_cleaned.srt").write_text("1", encoding="utf-8")
            (job_dir / "workflow" / "critic").mkdir(parents=True)
            (job_dir / "workflow" / "critic" / "zh_corrected.srt").write_text("1", encoding="utf-8")
            (job_dir / "reports").mkdir(parents=True)
            (job_dir / "reports" / "plot_summary.txt").write_text("plot", encoding="utf-8")
            (job_dir / "workflow" / "translated").mkdir(parents=True)
            (job_dir / "workflow" / "translated" / "en_translated.srt").write_text("1", encoding="utf-8")
            (job_dir / "workflow" / "tts_segments").mkdir(parents=True)
            (job_dir / "workflow" / "audio").mkdir(parents=True)
            non_silent_wav = job_dir / "workflow" / "audio" / "narration_en.wav"
            with wave.open(str(non_silent_wav), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(8000)
                writer.writeframes(b"\x01\x00" * 8000)  # Non-zero amplitude

            result = detect_last_completed_node(job_dir)
            self.assertEqual(result, "align_and_merge_audio")


if __name__ == "__main__":
    unittest.main()
