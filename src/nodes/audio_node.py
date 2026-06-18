from __future__ import annotations

import logging

from src.config import config_path
from src.state import WorkflowState
from src.tools.audio_tools import (
    align_and_merge_segments,
    align_and_merge_segments_simple,
    align_and_merge_segments_window,
)
from src.tools.file_tools import write_json, write_text

logger = logging.getLogger(__name__)


def align_and_merge_audio(state: WorkflowState) -> WorkflowState:
    logger.info("align_and_merge_audio: entering node")
    config = state["config"]
    final_srt = state.get("final_srt", "")
    write_text(config_path(config, "paths.final_srt"), final_srt)
    alignment_mode = str(config.get("alignment", {}).get("mode", "simple")).lower()
    if alignment_mode == "overlap_resolution":
        audio_report = align_and_merge_segments(
            state.get("final_cues", []),
            state.get("tts_segments", []),
            config_path(config, "paths.narration_wav"),
            config_path(config, "paths.narration_mp3"),
            config,
        )
    elif alignment_mode == "window":
        audio_report = align_and_merge_segments_window(
            state.get("final_cues", []),
            state.get("tts_segments", []),
            config_path(config, "paths.narration_wav"),
            config_path(config, "paths.narration_mp3"),
            config,
        )
        # 顺延明细单独写文件,便于排查超长段
        delay_details_path = config_path(config, "paths.reports_dir") / "alignment_delay_details.json"
        write_json(
            delay_details_path,
            {
                "alignment_mode": "window",
                "delay_summary": audio_report.get("delay_summary", {}),
                "delay_details": audio_report.get("delay_details", []),
            },
        )
        state.setdefault("reports", {})["alignment_delay_details"] = str(delay_details_path)
    else:
        audio_report = align_and_merge_segments_simple(
            state.get("final_cues", []),
            state.get("tts_segments", []),
            config_path(config, "paths.narration_wav"),
            config_path(config, "paths.narration_mp3"),
            config,
        )
    pipeline_report = _build_pipeline_report(state, audio_report)
    report_path = config_path(config, "paths.reports_dir") / "pipeline_report.json"
    write_json(report_path, pipeline_report)
    state["narration_wav_path"] = str(config_path(config, "paths.narration_wav"))
    state["narration_mp3_path"] = str(config_path(config, "paths.narration_mp3"))
    state.setdefault("reports", {})["audio_report"] = audio_report
    state.setdefault("reports", {})["pipeline_report"] = str(report_path)
    return state


def _build_pipeline_report(
    state: WorkflowState, audio_report: dict[str, object]
) -> dict[str, object]:
    config = state["config"]
    return {
        "input_mp3": config["paths"]["input_mp3"],
        "asr_srt": config["paths"]["asr_srt"],
        "raw_subtitle_count": len(state.get("raw_cues", [])),
        "cleaned_subtitle_count": len(state.get("cleaned_cues", [])),
        "corrected_count": len(state.get("corrected_cues", [])),
        "translated_count": len(state.get("en_translated_cues", [])),
        "reflection_rounds": int(state.get("reflection_rounds", 0)),
        "remaining_duration_issues": len(state.get("duration_issues", [])),
        "tts_segments": len(state.get("tts_segments", [])),
        "narration_wav": config["paths"]["narration_wav"],
        "narration_mp3": config["paths"]["narration_mp3"],
        "audio": audio_report,
    }

