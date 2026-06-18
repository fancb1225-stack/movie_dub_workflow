from __future__ import annotations

import unittest

from src.tools.merge_tools import split_cues_by_gap
from src.tools.srt_tools import make_cue


def _cue(idx: int, start: int, end: int, text: str = "") -> dict:
    return make_cue(idx, start, end, text)


class SplitCuesByGapTests(unittest.TestCase):
    def test_split_at_large_gap(self) -> None:
        """间隙 > max_gap_ms 处断开,块内连续。"""
        cues = [
            _cue(1, 0, 1000, "a"),
            _cue(2, 1100, 2000, "b"),   # gap 100
            _cue(3, 5000, 6000, "c"),   # gap 3000 > 450 → 断
            _cue(4, 6100, 7000, "d"),   # gap 100
        ]
        chunks, hard_cuts = split_cues_by_gap(cues, max_gap_ms=450, max_chunk_size=200)
        self.assertEqual(len(chunks), 2)
        self.assertEqual([c["index"] for c in chunks[0]], [1, 2])
        self.assertEqual([c["index"] for c in chunks[1]], [3, 4])
        self.assertEqual(hard_cuts, [])

    def test_no_gap_single_chunk(self) -> None:
        """全连续 → 1 块,无硬切。"""
        cues = [
            _cue(1, 0, 1000, "a"),
            _cue(2, 1000, 2000, "b"),
            _cue(3, 2000, 3000, "c"),
        ]
        chunks, hard_cuts = split_cues_by_gap(cues, max_gap_ms=450, max_chunk_size=200)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(len(chunks[0]), 3)
        self.assertEqual(hard_cuts, [])

    def test_all_gaps_split_into_singles(self) -> None:
        """每条间隙都 > max_gap_ms → N 块各 1 条。"""
        cues = [
            _cue(1, 0, 1000, "a"),
            _cue(2, 5000, 6000, "b"),
            _cue(3, 10000, 11000, "c"),
        ]
        chunks, hard_cuts = split_cues_by_gap(cues, max_gap_ms=450, max_chunk_size=200)
        self.assertEqual(len(chunks), 3)
        for chunk in chunks:
            self.assertEqual(len(chunk), 1)
        self.assertEqual(hard_cuts, [])

    def test_hard_cut_when_block_exceeds_max_size(self) -> None:
        """连续块超 max_chunk_size → 硬切,记录 hard_cut 时间边界。"""
        # 5 条全连续, max_chunk_size=2 → 切成 [1,2],[3,4],[5],2 个硬切点
        cues = [_cue(i, (i - 1) * 1000, i * 1000, str(i)) for i in range(1, 6)]
        chunks, hard_cuts = split_cues_by_gap(cues, max_gap_ms=450, max_chunk_size=2)
        self.assertEqual(len(chunks), 3)
        self.assertEqual([c["index"] for c in chunks[0]], [1, 2])
        self.assertEqual([c["index"] for c in chunks[1]], [3, 4])
        self.assertEqual([c["index"] for c in chunks[2]], [5])
        # 2 个硬切点:chunk0↔chunk1 (cut_end=2000, cut_start=2000),
        #            chunk1↔chunk2 (cut_end=4000, cut_start=4000)
        self.assertEqual(len(hard_cuts), 2)
        self.assertEqual(hard_cuts[0], {"cut_end_ms": 2000, "cut_start_ms": 2000})
        self.assertEqual(hard_cuts[1], {"cut_end_ms": 4000, "cut_start_ms": 4000})

    def test_empty_cues(self) -> None:
        chunks, hard_cuts = split_cues_by_gap([], max_gap_ms=450, max_chunk_size=200)
        self.assertEqual(chunks, [])
        self.assertEqual(hard_cuts, [])

    def test_hard_cut_only_between_adjacent_chunks(self) -> None:
        """硬切点仅记录相邻 chunk 间,首块无前驱不算。"""
        # 4 条连续, max_chunk_size=2 → [1,2],[3,4],1 个硬切点
        cues = [_cue(i, (i - 1) * 1000, i * 1000, str(i)) for i in range(1, 5)]
        chunks, hard_cuts = split_cues_by_gap(cues, max_gap_ms=450, max_chunk_size=2)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(len(hard_cuts), 1)
        self.assertEqual(hard_cuts[0], {"cut_end_ms": 2000, "cut_start_ms": 2000})


if __name__ == "__main__":
    unittest.main()
