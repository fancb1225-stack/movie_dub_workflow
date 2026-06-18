from __future__ import annotations

import tempfile
import unittest
import wave
from array import array
from pathlib import Path

from src.tools.audio_tools import align_and_merge_segments_window


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


def _config(root: Path) -> dict:
    return {
        "project_root": str(root),
        "tts": {"sample_rate": 8000},
        "ffmpeg": {"ffmpeg_path": "ffmpeg/bin/ffmpeg.exe"},
        "alignment": {
            "mode": "window",
            "max_shift_forward_ms": 1000,
            "max_shift_back_overlap_ms": 200,
            "shift_back_gap_ms": 50,
            "enable_overlap_resolution": True,
        },
    }


def _cue(idx: int, start: int, end: int, text: str = "") -> dict:
    return {"index": idx, "start": "", "end": "", "start_ms": start, "end_ms": end, "text": text}


def _segment(idx: int, start: int, end: int, path: str, duration_ms: int, success: bool = True) -> dict:
    return {
        "index": idx,
        "text": "",
        "start_ms": start,
        "end_ms": end,
        "path": path,
        "duration_ms": duration_ms,
        "success": success,
    }


class WindowAlignTests(unittest.TestCase):
    def test_short_segment_pinned_to_cue_start(self) -> None:
        """短段无前推 → 贴 cue 起点,尾部静音(能贴起点就贴)。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seg = root / "seg.wav"
            # 400ms @ 8kHz = 3200 samples 非静音
            _write_wav(seg, [1000] * 3200, sample_rate=8000)
            out_wav = root / "narration.wav"
            out_mp3 = root / "narration.mp3"

            report = align_and_merge_segments_window(
                cues=[_cue(1, 0, 1000)],
                segments=[_segment(1, 0, 1000, str(seg), duration_ms=400)],
                output_wav=out_wav,
                output_mp3=out_mp3,
                config=_config(root),
            )

            # 贴起点:start=0
            self.assertEqual(report["placements"][0]["start_ms"], 0)
            self.assertEqual(report["placements"][0]["strategy"], "centered")
            self.assertFalse(report["placements"][0]["shifted"])
            samples = _read_wav_samples(out_wav)
            # 前 400ms(3200 samples)非静音
            self.assertTrue(any(s != 0 for s in samples[:3200]))
            # 400ms 之后到 1000ms 静音
            self.assertTrue(all(s == 0 for s in samples[3200:8000]))

    def test_short_segment_centered_when_pushed_by_previous(self) -> None:
        """短段被上一段前推(prev_end>cue_start) → 在剩余窗口居中。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seg1 = root / "seg1.wav"
            seg2 = root / "seg2.wav"
            _write_wav(seg1, [1000] * 1600, sample_rate=8000)  # 200ms
            _write_wav(seg2, [2000] * 800, sample_rate=8000)   # 100ms

            # seg1 cue 0-100, dur 200 → 溢出, prev_end=200
            # seg2 cue 100-500, dur 100 → cue_start(100) < prev_end(200) 被前推
            #   window_start=max(100,200)=200, window_len=500-200=300, dur100<=300
            #   居中: start=200 + (300-100)//2 = 200+100 = 300
            report = align_and_merge_segments_window(
                cues=[_cue(1, 0, 100), _cue(2, 100, 500)],
                segments=[
                    _segment(1, 0, 100, str(seg1), duration_ms=200),
                    _segment(2, 100, 500, str(seg2), duration_ms=100),
                ],
                output_wav=root / "narration.wav",
                output_mp3=root / "narration.mp3",
                config=_config(root),
            )
            self.assertEqual(report["placements"][1]["start_ms"], 300)
            self.assertEqual(report["placements"][1]["strategy"], "centered")
            # 不重叠:seg2 start(300) >= seg1 end(0+200=200)
            self.assertGreaterEqual(
                report["placements"][1]["start_ms"],
                report["placements"][0]["start_ms"] + report["placements"][0]["duration_ms"],
            )

    def test_long_segment_overflow_from_prev_end(self) -> None:
        """长段(超窗口) → 从上一段结束接续,记入 delay_details。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seg1 = root / "seg1.wav"
            seg2 = root / "seg2.wav"
            _write_wav(seg1, [1000] * 1600, sample_rate=8000)  # 200ms
            _write_wav(seg2, [2000] * 2400, sample_rate=8000)  # 300ms

            # seg1 cue 0-100, dur 200 → 溢出, prev_end=200
            # seg2 cue 100-200, dur 300 → window_start=max(100,200)=200, window_len=200-200=0
            #   dur300 > window_len0 → overflow, start=max(200,100)=200
            report = align_and_merge_segments_window(
                cues=[_cue(1, 0, 100), _cue(2, 100, 200)],
                segments=[
                    _segment(1, 0, 100, str(seg1), duration_ms=200),
                    _segment(2, 100, 200, str(seg2), duration_ms=300),
                ],
                output_wav=root / "narration.wav",
                output_mp3=root / "narration.mp3",
                config=_config(root),
            )
            self.assertEqual(report["placements"][1]["start_ms"], 200)
            self.assertEqual(report["placements"][1]["strategy"], "overflow")
            # seg1(首段超长)与 seg2 均 overflow
            self.assertEqual(len(report["delay_details"]), 2)
            d = next(item for item in report["delay_details"] if item["index"] == 2)
            self.assertEqual(d["actual_start_ms"], 200)
            self.assertEqual(d["shift_ms"], 100)  # 200 - cue_start 100

    def test_delayed_segment_returns_to_cue_when_possible(self) -> None:
        """按需顺延:超长段后,下一段 cue_start 已晚于 prev_end → 回 cue 贴起点。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seg1 = root / "seg1.wav"
            seg2 = root / "seg2.wav"
            _write_wav(seg1, [1000] * 1600, sample_rate=8000)  # 200ms
            _write_wav(seg2, [2000] * 1600, sample_rate=8000)  # 200ms

            # seg1 cue 0-100, dur 200 → 溢出到 200, prev_end=200
            # seg2 cue 500-1000, dur 200 → cue_start(500) >= prev_end(200), 回 cue
            #   window_start=500, window_len=500, dur200<=500, 贴起点 start=500
            report = align_and_merge_segments_window(
                cues=[_cue(1, 0, 100), _cue(2, 500, 1000)],
                segments=[
                    _segment(1, 0, 100, str(seg1), duration_ms=200),
                    _segment(2, 500, 1000, str(seg2), duration_ms=200),
                ],
                output_wav=root / "narration.wav",
                output_mp3=root / "narration.mp3",
                config=_config(root),
            )
            self.assertEqual(report["placements"][1]["start_ms"], 500)
            self.assertEqual(report["placements"][1]["strategy"], "centered")
            self.assertFalse(report["placements"][1]["shifted"])

    def test_delay_summary_aggregates_overflow(self) -> None:
        """delay_summary 汇总 overflow 段数与累计偏移。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seg1 = root / "seg1.wav"
            seg2 = root / "seg2.wav"
            _write_wav(seg1, [1000] * 1600, sample_rate=8000)  # 200ms
            _write_wav(seg2, [2000] * 2400, sample_rate=8000)  # 300ms

            report = align_and_merge_segments_window(
                cues=[_cue(1, 0, 100), _cue(2, 100, 200)],
                segments=[
                    _segment(1, 0, 100, str(seg1), duration_ms=200),
                    _segment(2, 100, 200, str(seg2), duration_ms=300),
                ],
                output_wav=root / "narration.wav",
                output_mp3=root / "narration.mp3",
                config=_config(root),
            )
            summary = report["delay_summary"]
            # seg1(首段超长)与 seg2 均 overflow
            self.assertEqual(summary["overflow_count"], 2)
            self.assertGreater(summary["total_shift_ms"], 0)
            seg2_shift = next(d["shift_ms"] for d in report["delay_details"] if d["index"] == 2)
            self.assertEqual(seg2_shift, 100)

    def test_first_segment_pinned_to_cue_start(self) -> None:
        """首段无前序 → 贴 cue 起点居中(window_start=cue_start)。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seg = root / "seg.wav"
            _write_wav(seg, [1000] * 800, sample_rate=8000)  # 100ms
            report = align_and_merge_segments_window(
                cues=[_cue(1, 500, 1500)],
                segments=[_segment(1, 500, 1500, str(seg), duration_ms=100)],
                output_wav=root / "narration.wav",
                output_mp3=root / "narration.mp3",
                config=_config(root),
            )
            self.assertEqual(report["placements"][0]["start_ms"], 500)
            self.assertFalse(report["placements"][0]["shifted"])

    def test_failed_segment_skipped_with_warning(self) -> None:
        """失败片段跳过,不更新 prev_end_ms。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seg1 = root / "seg1.wav"
            seg3 = root / "seg3.wav"
            _write_wav(seg1, [1000] * 800, sample_rate=8000)
            _write_wav(seg3, [3000] * 800, sample_rate=8000)
            report = align_and_merge_segments_window(
                cues=[_cue(1, 0, 100), _cue(2, 100, 200), _cue(3, 200, 300)],
                segments=[
                    _segment(1, 0, 100, str(seg1), duration_ms=100),
                    _segment(2, 100, 200, str(root / "missing.wav"), duration_ms=100, success=False),
                    _segment(3, 200, 300, str(seg3), duration_ms=100),
                ],
                output_wav=root / "narration.wav",
                output_mp3=root / "narration.mp3",
                config=_config(root),
            )
            self.assertEqual(len(report["placements"]), 2)
            self.assertTrue(report["warnings"])
            self.assertTrue(any("2" in w for w in report["warnings"]))

    def test_canvas_extends_on_overflow(self) -> None:
        """末段超长溢出 → 画布自动延长,duration_ms 超过 max_cue_end。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seg1 = root / "seg1.wav"
            _write_wav(seg1, [1000] * 8000, sample_rate=8000)  # 1000ms
            # cue 0-500, dur 1000 → 溢出到 1000, max_cue_end=500
            report = align_and_merge_segments_window(
                cues=[_cue(1, 0, 500)],
                segments=[_segment(1, 0, 500, str(seg1), duration_ms=1000)],
                output_wav=root / "narration.wav",
                output_mp3=root / "narration.mp3",
                config=_config(root),
            )
            self.assertGreater(report["duration_ms"], 500)
            samples = _read_wav_samples(root / "narration.wav")
            self.assertTrue(any(s != 0 for s in samples[4000:]))  # 500ms 之后仍有非零


if __name__ == "__main__":
    unittest.main()
