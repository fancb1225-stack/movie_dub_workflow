from __future__ import annotations

import tempfile
import unittest
import wave
from array import array
from pathlib import Path

from src.tools.audio_tools import align_and_merge_segments_simple


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
            "mode": "simple",
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


class SimpleAlignTests(unittest.TestCase):
    def test_short_segment_pads_trailing_silence(self) -> None:
        """片段比时间轴短 → 对齐到 cue 起点补尾静音。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            segment = root / "segment.wav"
            # 50ms @ 8kHz = 400 samples of non-silence
            _write_wav(segment, [1000] * 400, sample_rate=8000)
            out_wav = root / "narration.wav"
            out_mp3 = root / "narration.mp3"

            report = align_and_merge_segments_simple(
                cues=[_cue(1, 0, 1000)],
                segments=[_segment(1, 0, 1000, str(segment), duration_ms=50)],
                output_wav=out_wav,
                output_mp3=out_mp3,
                config=_config(root),
            )

            samples = _read_wav_samples(out_wav)
            # 前 50ms (400 samples) 非静音
            self.assertTrue(any(s != 0 for s in samples[:400]))
            # 50ms 之后到 1000ms 之间应是静音
            tail = samples[400:8000]
            self.assertTrue(all(s == 0 for s in tail), "trailing region should be silent")
            self.assertEqual(report["alignment_mode"], "simple")
            self.assertEqual(report["placements"][0]["start_ms"], 0)
            self.assertFalse(report["placements"][0]["shifted"])

    def test_long_segment_shifts_forward_without_overlap(self) -> None:
        """长片段与上一个重叠 → 顺延到上一个结束点,保证不重叠。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seg1 = root / "seg1.wav"
            seg2 = root / "seg2.wav"
            # seg1: 100ms 音频
            _write_wav(seg1, [1000] * 800, sample_rate=8000)
            # seg2: 100ms 音频
            _write_wav(seg2, [2000] * 800, sample_rate=8000)

            # seg1 cue 0-100, dur 100 → ends at 100
            # seg2 cue 80-200, dur 100 → cue_start(80) < prev_end(100), 重叠
            # 新公式: max(0, max(cue_start-1000, prev_end)) = max(0, max(-920,100)) = 100
            # seg2 顺延到 100,紧贴 seg1 结束,不重叠
            report = align_and_merge_segments_simple(
                cues=[_cue(1, 0, 100), _cue(2, 80, 200)],
                segments=[
                    _segment(1, 0, 100, str(seg1), duration_ms=100),
                    _segment(2, 80, 200, str(seg2), duration_ms=100),
                ],
                output_wav=root / "narration.wav",
                output_mp3=root / "narration.mp3",
                config=_config(root),
            )
            self.assertEqual(report["placements"][1]["start_ms"], 100)
            self.assertTrue(report["placements"][1]["shifted"])
            # 验证不重叠:seg2 start == seg1 end
            self.assertEqual(
                report["placements"][1]["start_ms"],
                report["placements"][0]["start_ms"] + report["placements"][0]["duration_ms"],
            )

    def test_non_overlapping_segment_not_shifted(self) -> None:
        """不重叠的片段保持原位(cue_start >= prev_end)。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seg1 = root / "seg1.wav"
            seg2 = root / "seg2.wav"
            _write_wav(seg1, [1000] * 800, sample_rate=8000)
            _write_wav(seg2, [2000] * 800, sample_rate=8000)

            # seg1 cue 0-100, dur 100 → ends 100
            # seg2 cue 200-300, dur 100 → cue_start(200) >= prev_end(100), 不重叠,不前移
            report = align_and_merge_segments_simple(
                cues=[_cue(1, 0, 100), _cue(2, 200, 300)],
                segments=[
                    _segment(1, 0, 100, str(seg1), duration_ms=100),
                    _segment(2, 200, 300, str(seg2), duration_ms=100),
                ],
                output_wav=root / "narration.wav",
                output_mp3=root / "narration.mp3",
                config=_config(root),
            )
            self.assertEqual(report["placements"][1]["start_ms"], 200)
            self.assertFalse(report["placements"][1]["shifted"])

    def test_shift_uses_prev_end_when_one_second_insufficient(self) -> None:
        """严重重叠:往前1s仍不够 → 顺延到 prev_end(不重叠下限)。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seg1 = root / "seg1.wav"
            seg2 = root / "seg2.wav"
            _write_wav(seg1, [1000] * 800, sample_rate=8000)
            _write_wav(seg2, [2000] * 800, sample_rate=8000)

            # seg1 cue 0-4000, dur 4000 → ends 4000
            # seg2 cue 3000-3100, dur 100 → cue_start(3000) < prev_end(4000), 重叠
            # 新公式: max(0, max(3000-1000, 4000)) = max(0, max(2000,4000)) = 4000
            # seg2 顺延到 4000,紧贴 seg1 结束
            report = align_and_merge_segments_simple(
                cues=[_cue(1, 0, 4000), _cue(2, 3000, 3100)],
                segments=[
                    _segment(1, 0, 4000, str(seg1), duration_ms=4000),
                    _segment(2, 3000, 3100, str(seg2), duration_ms=100),
                ],
                output_wav=root / "narration.wav",
                output_mp3=root / "narration.mp3",
                config=_config(root),
            )
            self.assertEqual(report["placements"][1]["start_ms"], 4000)
            self.assertTrue(report["placements"][1]["shifted"])

    def test_first_segment_not_shifted(self) -> None:
        """首片段无前序 → 不前移,start==cue_start。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seg1 = root / "seg1.wav"
            _write_wav(seg1, [1000] * 800, sample_rate=8000)
            report = align_and_merge_segments_simple(
                cues=[_cue(1, 500, 1500)],
                segments=[_segment(1, 500, 1500, str(seg1), duration_ms=100)],
                output_wav=root / "narration.wav",
                output_mp3=root / "narration.mp3",
                config=_config(root),
            )
            self.assertEqual(report["placements"][0]["start_ms"], 500)
            self.assertFalse(report["placements"][0]["shifted"])

    def test_failed_segment_skipped_with_warning(self) -> None:
        """失败片段跳过,不更新 prev_end_ms,产出 warning。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seg1 = root / "seg1.wav"
            seg3 = root / "seg3.wav"
            _write_wav(seg1, [1000] * 800, sample_rate=8000)
            _write_wav(seg3, [3000] * 800, sample_rate=8000)

            report = align_and_merge_segments_simple(
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
        """前移后仍溢出 → 画布自动延长,duration_ms 超过 max_cue_end。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seg1 = root / "seg1.wav"
            seg2 = root / "seg2.wav"
            _write_wav(seg1, [1000] * 8000, sample_rate=8000)  # 1000ms
            _write_wav(seg2, [2000] * 8000, sample_rate=8000)  # 1000ms

            # seg1 cue 0-500, dur 1000 → 溢出到 1000, prev_end=1000
            # seg2 cue 300-800, dur 1000 → cue_start(300) < prev_end(1000), 重叠
            # 新公式: max(0, max(300-1000, 1000)) = 1000, 顺延到 1000, 溢出到 2000
            # max_cue_end=800, 实际音频延伸到 2000
            report = align_and_merge_segments_simple(
                cues=[_cue(1, 0, 500), _cue(2, 300, 800)],
                segments=[
                    _segment(1, 0, 500, str(seg1), duration_ms=1000),
                    _segment(2, 300, 800, str(seg2), duration_ms=1000),
                ],
                output_wav=root / "narration.wav",
                output_mp3=root / "narration.mp3",
                config=_config(root),
            )
            self.assertGreater(report["duration_ms"], 800)
            samples = _read_wav_samples(root / "narration.wav")
            # 末尾(800ms=6400sample 附近)仍有非零样本
            self.assertTrue(any(s != 0 for s in samples[6400:]))


if __name__ == "__main__":
    unittest.main()
