#!/usr/bin/env python3
"""一次性脚本：对 bd787ec8023e40daad084fec8aebd1c3 任务的 TTS 片段
使用新的重叠对齐算法重新合并，输出文件以 _v2 后缀命名。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.config import load_config
from src.tools.audio_tools import align_and_merge_segments
from src.tools.srt_tools import parse_srt


def main() -> None:
    job_id = "bd787ec8023e40daad084fec8aebd1c3"
    config = load_config()
    job_dir = Path(config["project_root"]) / "outputs" / "jobs" / job_id

    # 1. 读取 final SRT → cues
    final_srt_path = job_dir / "workflow" / "final" / "en_final.srt"
    srt_text = final_srt_path.read_text(encoding="utf-8")
    cues = parse_srt(srt_text)
    print(f"读取 {len(cues)} 条 SRT cue")

    # 2. 构建 TTS segments 列表（从文件系统和 duration report 恢复）
    tts_dir = job_dir / "workflow" / "tts_segments"
    duration_report_path = job_dir / "reports" / "tts_duration_report.json"
    duration_report = json.loads(duration_report_path.read_text(encoding="utf-8"))

    # 从 report 的 issues 中提取 duration 信息；其余 segment 用 ffprobe 测
    from src.tools.duration_tools import get_audio_duration_ms

    segments: list[dict] = []
    for cue in cues:
        idx = cue["index"]
        seg_path = tts_dir / f"segment_{idx:04d}.mp3"
        if not seg_path.exists():
            segments.append({
                "index": idx,
                "start_ms": cue["start_ms"],
                "end_ms": cue["end_ms"],
                "duration_ms": 0,
                "path": str(seg_path),
                "success": False,
                "text": cue["text"],
            })
            continue
        try:
            dur = get_audio_duration_ms(str(seg_path), config)
        except Exception:
            dur = 0
        segments.append({
            "index": idx,
            "start_ms": cue["start_ms"],
            "end_ms": cue["end_ms"],
            "duration_ms": dur,
            "path": str(seg_path),
            "success": True,
            "text": cue["text"],
        })
    success_count = sum(1 for s in segments if s["success"])
    print(f"构建 {len(segments)} 个 TTS segment，{success_count} 个成功")

    # 3. 使用新的重叠对齐算法合并
    out_wav = job_dir / "workflow" / "audio" / "narration_en_v2.wav"
    out_mp3 = job_dir / "workflow" / "audio" / "narration_en_v2.mp3"

    report = align_and_merge_segments(cues, segments, out_wav, out_mp3, config)

    # 4. 输出报告
    print(f"\n=== 合并完成 ===")
    print(f"输出 WAV: {report['narration_wav']}")
    print(f"输出 MP3: {report['narration_mp3']}")
    print(f"采样率: {report['sample_rate']}")
    print(f"总时长: {report['duration_ms']}ms ({report['duration_ms']/1000:.1f}s)")
    print(f"片段数: {report['segment_count']}")
    print(f"MP3 生成方式: {report['mp3_created_with']}")

    if "alignment_summary" in report:
        summary = report["alignment_summary"]
        print(f"\n=== 对齐摘要 ===")
        print(f"检测到重叠: {summary['total_overlaps_detected']} 个片段")
        print(f"  顺延解决 (delay): {summary['resolved_by_delay']}")
        print(f"  前移解决 (shift_back): {summary['resolved_by_shift_back']}")
        print(f"  无重叠 (none): {summary['no_overlap']}")
        print(f"  未解决 (fallback): {summary['fallback_overlap']}")
        print(f"  最大前移量: {summary['max_forward_shift_ms']}ms")
        print(f"  最大后移量: {summary['max_backward_shift_ms']}ms")

    if report.get("warnings"):
        print(f"\n警告: {report['warnings']}")

    # 5. 保存详细报告
    report_path = job_dir / "reports" / "audio_alignment_v2_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n详细报告已保存: {report_path}")


if __name__ == "__main__":
    main()
