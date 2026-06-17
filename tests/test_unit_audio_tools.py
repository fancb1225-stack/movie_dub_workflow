from __future__ import annotations

import tempfile
import unittest
import wave
from array import array
from pathlib import Path
from unittest.mock import patch

from src.tools.audio_tools import align_and_merge_segments, compute_adjusted_positions


def _write_wav(path: Path, samples: list[int], sample_rate: int = 8000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = array("h", samples)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm.tobytes())


def _read_wav_samples(path: Path) -> array:
    with wave.open(str(path), "rb") as reader:
        samples = array("h")
        samples.frombytes(reader.readframes(reader.getnframes()))
        return samples


class AudioToolsTests(unittest.TestCase):
    def test_align_and_merge_wav_segment_outputs_non_silent_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            segment = root / "segment.wav"
            _write_wav(segment, [0, 1000, -1000, 0] * 100)
            out_wav = root / "narration.wav"
            out_mp3 = root / "narration.mp3"

            report = align_and_merge_segments(
                cues=[{"index": 1, "start": "", "end": "", "start_ms": 0, "end_ms": 1000, "text": "hello"}],
                segments=[{"index": 1, "text": "hello", "start_ms": 0, "end_ms": 1000, "path": str(segment), "duration_ms": 50, "success": True}],
                output_wav=out_wav,
                output_mp3=out_mp3,
                config=_config(root),
            )

            samples = _read_wav_samples(out_wav)
            self.assertTrue(any(sample != 0 for sample in samples))
            self.assertEqual(report["warnings"], [])

    def test_non_wav_segment_is_decoded_with_project_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            segment = root / "segment.mp3"
            segment.write_bytes(b"fake mp3")
            out_wav = root / "narration.wav"
            out_mp3 = root / "narration.mp3"
            raw_pcm = array("h", [0, 1200, -1200, 0] * 100).tobytes()

            with patch("src.tools.audio_tools.find_binary", return_value=root / "ffmpeg.exe"):
                with patch("subprocess.run") as run:
                    run.return_value.stdout = raw_pcm
                    run.return_value.stderr = ""
                    align_and_merge_segments(
                        cues=[{"index": 1, "start": "", "end": "", "start_ms": 0, "end_ms": 1000, "text": "hello"}],
                        segments=[{"index": 1, "text": "hello", "start_ms": 0, "end_ms": 1000, "path": str(segment), "duration_ms": 50, "success": True}],
                        output_wav=out_wav,
                        output_mp3=out_mp3,
                        config=_config(root),
                    )

            samples = _read_wav_samples(out_wav)
            self.assertTrue(any(sample != 0 for sample in samples))
            first_cmd = run.call_args_list[0].args[0]
            self.assertEqual(str(first_cmd[0]), str(root / "ffmpeg.exe"))
            self.assertIn("s16le", first_cmd)

    def test_mp3_export_uses_project_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            segment = root / "segment.wav"
            _write_wav(segment, [1000] * 100)
            out_wav = root / "narration.wav"
            out_mp3 = root / "narration.mp3"

            with patch("src.tools.audio_tools.find_binary", return_value=root / "ffmpeg.exe"):
                with patch("subprocess.run") as run:
                    run.return_value.stdout = b""
                    run.return_value.stderr = ""
                    report = align_and_merge_segments(
                        cues=[{"index": 1, "start": "", "end": "", "start_ms": 0, "end_ms": 1000, "text": "hello"}],
                        segments=[{"index": 1, "text": "hello", "start_ms": 0, "end_ms": 1000, "path": str(segment), "duration_ms": 20, "success": True}],
                        output_wav=out_wav,
                        output_mp3=out_mp3,
                        config=_config(root),
                    )

            self.assertEqual(report["mp3_created_with"], "ffmpeg")
            export_cmd = run.call_args_list[-1].args[0]
            self.assertEqual(str(export_cmd[0]), str(root / "ffmpeg.exe"))
            self.assertEqual(str(export_cmd[-1]), str(out_mp3))

    def test_unreadable_segment_adds_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            segment = root / "segment.mp3"
            segment.write_bytes(b"fake mp3")
            out_wav = root / "narration.wav"
            out_mp3 = root / "narration.mp3"

            with patch("src.tools.audio_tools.find_binary", side_effect=FileNotFoundError("missing ffmpeg")):
                report = align_and_merge_segments(
                    cues=[],
                    segments=[{"index": 1, "text": "hello", "start_ms": 0, "end_ms": 1000, "path": str(segment), "duration_ms": 20, "success": True}],
                    output_wav=out_wav,
                    output_mp3=out_mp3,
                    config=_config(root),
                )

            self.assertEqual(report["segment_count"], 1)
            self.assertTrue(report["warnings"])
            self.assertIn("Skip unreadable TTS segment 1", report["warnings"][0])


def _config(root: Path) -> dict:
    return {
        "project_root": str(root),
        "tts": {"sample_rate": 8000},
        "ffmpeg": {"ffmpeg_path": "ffmpeg/bin/ffmpeg.exe"},
        "alignment": {
            "max_shift_back_overlap_ms": 200,
            "shift_back_gap_ms": 50,
            "enable_overlap_resolution": True,
        },
    }


class ComputeAdjustedPositionsTests(unittest.TestCase):
    """Pure-function tests for overlap resolution algorithm."""

    def _cues(self, *entries: tuple[int, int, int]) -> list[dict]:
        return [
            {"index": idx, "start": "", "end": "", "start_ms": start, "end_ms": end, "text": ""}
            for idx, start, end in entries
        ]

    def _segments(self, *entries: tuple[int, int, int]) -> list[dict]:
        return [
            {"index": idx, "start_ms": start, "end_ms": start + 100, "duration_ms": dur, "path": "", "success": True, "text": ""}
            for idx, start, dur in entries
        ]

    def test_no_overlap_all_none_strategy(self) -> None:
        """Test A: no overlap → all strategies are 'none'."""
        cues = self._cues((1, 0, 500), (2, 600, 1000), (3, 1100, 1500))
        segments = self._segments((1, 0, 400), (2, 600, 300), (3, 1100, 300))
        positions = compute_adjusted_positions(segments, cues)
        self.assertEqual(len(positions), 3)
        for pos in positions:
            self.assertEqual(pos["strategy"], "none")
            self.assertEqual(pos["adjusted_start_ms"], pos["original_start_ms"])

    def test_delay_succeeds(self) -> None:
        """Test B: overlap, delay resolves because shifted end < next cue start."""
        # seg1: start=0, duration=1500 → ends at 1500
        # seg2: start=1000 (SRT), duration=800 → overlap=500ms
        # next cue starts at 3000 → delayed_end=2300 < 3000 ✓
        cues = self._cues((1, 0, 1000), (2, 1000, 2000), (3, 3000, 4000))
        segments = self._segments((1, 0, 1500), (2, 1000, 800))
        positions = compute_adjusted_positions(segments, cues)
        self.assertEqual(positions[0]["strategy"], "none")
        self.assertEqual(positions[1]["strategy"], "delay")
        self.assertEqual(positions[1]["adjusted_start_ms"], 1500)
        self.assertEqual(positions[1]["shift_ms"], 500)

    def test_delay_blocked_fallback(self) -> None:
        """Test B2: overlap, delay blocked by next cue, overlap > 200ms → fallback."""
        # seg1: start=0, duration=1500 → ends at 1500
        # seg2: start=1000, duration=800 → overlap=500ms, delayed_end=2300
        # next cue starts at 2000 → delayed_end > 2000, blocked
        # overlap 500ms > 200ms threshold → shift_back also blocked
        cues = self._cues((1, 0, 1000), (2, 1000, 2000), (3, 2000, 3000))
        segments = self._segments((1, 0, 1500), (2, 1000, 800))
        positions = compute_adjusted_positions(segments, cues)
        self.assertEqual(positions[0]["strategy"], "none")
        self.assertEqual(positions[1]["strategy"], "fallback")
        self.assertEqual(positions[1]["adjusted_start_ms"], 1000)

    def test_shift_back_succeeds(self) -> None:
        """Test C: overlap ≤ 200ms, previous can shift backward."""
        # seg0: start=300, duration=1200 → ends at 1500
        # seg1: start=1300, duration=500 → overlap=200ms (≤ 200 threshold)
        # delay: seg1 shifted to 1500, end=2000. Next cue at 1800 → blocked
        # shift_back: move seg0 back by 200+50=250. New seg0 start=300-250=50. 50>=0 ✓
        cues = self._cues((0, 300, 500), (1, 1300, 1500), (2, 1800, 2000))
        segments = self._segments((0, 300, 1200), (1, 1300, 500))
        positions = compute_adjusted_positions(segments, cues)
        # seg0 should be shifted back to 50
        self.assertEqual(positions[0]["strategy"], "shift_back")
        self.assertEqual(positions[0]["adjusted_start_ms"], 50)
        self.assertEqual(positions[0]["shift_ms"], -250)
        # seg1 stays at original start
        self.assertEqual(positions[1]["strategy"], "none")
        self.assertEqual(positions[1]["adjusted_start_ms"], 1300)

    def test_shift_back_blocked_fallback(self) -> None:
        """Test C2: overlap ≤ 200ms but previous cannot shift back → fallback."""
        # seg0: start=50, duration=1200 → ends at 1250
        # seg1: start=1100, duration=500 → overlap=150ms
        # delay: shifted_end=1250+500=1750, next cue at 1500 → blocked
        # shift_back: move seg0 back by 150+50=200. New seg0 start=50-200=-150 <0 → blocked
        cues = self._cues((0, 50, 200), (1, 1100, 1300), (2, 1500, 1700))
        segments = self._segments((0, 50, 1200), (1, 1100, 500))
        positions = compute_adjusted_positions(segments, cues)
        self.assertEqual(positions[0]["strategy"], "none")
        self.assertEqual(positions[1]["strategy"], "fallback")

    def test_single_segment_no_overlap(self) -> None:
        """Test D: single segment, no overlap possible."""
        cues = self._cues((1, 0, 1000))
        segments = self._segments((1, 0, 500))
        positions = compute_adjusted_positions(segments, cues)
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["strategy"], "none")
        self.assertEqual(positions[0]["adjusted_start_ms"], 0)

    def test_failed_segment_skipped(self) -> None:
        """Test E: failed segment in the middle is skipped."""
        cues = self._cues((1, 0, 500), (2, 600, 1000), (3, 1100, 1500))
        segments = [
            {"index": 1, "start_ms": 0, "end_ms": 500, "duration_ms": 600, "path": "", "success": True, "text": ""},
            {"index": 2, "start_ms": 600, "end_ms": 1000, "duration_ms": 0, "path": "", "success": False, "text": ""},
            {"index": 3, "start_ms": 1100, "end_ms": 1500, "duration_ms": 300, "path": "", "success": True, "text": ""},
        ]
        positions = compute_adjusted_positions(segments, cues)
        # Only 2 positions (seg 1 and 3, skipping failed seg 2)
        self.assertEqual(len(positions), 2)
        self.assertEqual(positions[0]["index"], 1)
        self.assertEqual(positions[1]["index"], 3)
        # seg1 ends at 600, seg3 starts at 1100 → no overlap
        self.assertEqual(positions[1]["strategy"], "none")

    def test_toggle_disabled(self) -> None:
        """Test F: enable_overlap_resolution=False → no adjusted_positions in report."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            segment = root / "segment.wav"
            _write_wav(segment, [1000] * 100)
            out_wav = root / "narration.wav"
            out_mp3 = root / "narration.mp3"
            config_no_align = _config(root)
            config_no_align["alignment"]["enable_overlap_resolution"] = False
            with patch("src.tools.audio_tools.find_binary", side_effect=FileNotFoundError):
                report = align_and_merge_segments(
                    cues=[{"index": 1, "start": "", "end": "", "start_ms": 0, "end_ms": 1000, "text": "hello"}],
                    segments=[{"index": 1, "text": "hello", "start_ms": 0, "end_ms": 1000, "path": str(segment), "duration_ms": 50, "success": True}],
                    output_wav=out_wav,
                    output_mp3=out_mp3,
                    config=config_no_align,
                )
            self.assertNotIn("adjusted_positions", report)
            self.assertNotIn("alignment_summary", report)

    def test_large_overlap_both_blocked_fallback(self) -> None:
        """Test G: overlap > 200ms, delay blocked, shift_back blocked → fallback."""
        # seg0: start=0, duration=3000 → ends at 3000
        # seg1: start=1000, duration=2000 → overlap=2000ms
        # delay: shifted_end=5000, next cue at 4000 → blocked
        # shift_back: overlap 2000 > 200 → blocked
        cues = self._cues((0, 0, 2000), (1, 1000, 2000), (2, 4000, 5000))
        segments = self._segments((0, 0, 3000), (1, 1000, 2000))
        positions = compute_adjusted_positions(segments, cues)
        self.assertEqual(positions[1]["strategy"], "fallback")

    def test_last_segment_delay_always_succeeds(self) -> None:
        """Test H: last segment overlaps, delay always succeeds (no next constraint)."""
        # seg0: start=0, duration=1500 → ends at 1500
        # seg1: start=1000, duration=500 → overlap=500ms
        # No next cue → delay always works
        cues = self._cues((1, 0, 1000), (2, 1000, 1500))
        segments = self._segments((1, 0, 1500), (2, 1000, 500))
        positions = compute_adjusted_positions(segments, cues)
        self.assertEqual(positions[1]["strategy"], "delay")
        self.assertEqual(positions[1]["adjusted_start_ms"], 1500)

    def test_canvas_size_extends_after_delay(self) -> None:
        """Test I: delay extends canvas beyond original max_cue_end."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Two overlapping segments
            seg1 = root / "seg1.wav"
            seg2 = root / "seg2.wav"
            _write_wav(seg1, [800] * 2000)  # 2000 samples @ 8kHz = 250ms
            _write_wav(seg2, [600] * 2000)
            out_wav = root / "narration.wav"
            out_mp3 = root / "narration.mp3"
            config = _config(root)
            # seg1 starts at 0, duration 250ms
            # seg2 starts at 100ms (SRT), duration 250ms → overlap
            # delay: seg2 starts at 250ms, ends at 500ms
            cues = [
                {"index": 1, "start": "", "end": "", "start_ms": 0, "end_ms": 200, "text": "a"},
                {"index": 2, "start": "", "end": "", "start_ms": 100, "end_ms": 300, "text": "b"},
                {"index": 3, "start": "", "end": "", "start_ms": 1000, "end_ms": 1200, "text": "c"},
            ]
            segments = [
                {"index": 1, "start_ms": 0, "end_ms": 200, "path": str(seg1), "duration_ms": 250, "success": True, "text": "a"},
                {"index": 2, "start_ms": 100, "end_ms": 300, "path": str(seg2), "duration_ms": 250, "success": True, "text": "b"},
            ]
            report = align_and_merge_segments(
                cues=cues, segments=segments,
                output_wav=out_wav, output_mp3=out_mp3,
                config=config,
            )
            self.assertIn("adjusted_positions", report)
            self.assertIn("alignment_summary", report)
            # Canvas should be at least 500ms (seg2 ends at 500) + 500ms buffer = 1000+
            self.assertGreaterEqual(report["duration_ms"], 500)


if __name__ == "__main__":
    unittest.main()
