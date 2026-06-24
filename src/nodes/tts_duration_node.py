from __future__ import annotations

import logging

from src.config import config_path
from src.state import WorkflowState
from src.tools.duration_tools import build_tts_duration_report, detect_duration_issues
from src.tools.file_tools import write_json
from src.tools.tts_tools import generate_tts_segments
from src.workflow_pause import WorkflowPauseRequired

logger = logging.getLogger(__name__)


def tts_generate_and_detect(state: WorkflowState) -> WorkflowState:
    config = state["config"]
    cues = state.get("final_cues", [])
    _pause_if_speaker_profiles_missing(state, cues)
    logger.info("tts_generate_and_detect: %d cues, provider=%s", len(cues), config.get("tts", {}).get("provider"))
    segments = generate_tts_segments(cues, config_path(config, "paths.tts_segments_dir"), config)
    duration_config = config.get("duration", {})
    issues = detect_duration_issues(
        cues,
        segments,
        int(duration_config.get("max_overrun_ms", 350)),
        float(duration_config.get("max_ratio", 1.12)),
        zh_cues=state.get("corrected_cues", []),
        plot_summary=state.get("plot_summary", ""),
    )
    report = build_tts_duration_report(segments, issues)
    report_path = config_path(config, "paths.reports_dir") / "tts_duration_report.json"
    write_json(report_path, report)
    logger.info("TTS report: success=%d, failed=%d, duration_issues=%d",
                report["success_segments"], report["failed_segments"], report["duration_issue_count"])
    if report["failed_segments"] > 0:
        logger.warning("Failed TTS segments: %s", report.get("failed_errors", []))
    state["tts_segments"] = segments
    state["duration_issues"] = issues
    state.setdefault("reports", {})["tts_duration_report"] = str(report_path)
    return state


def _pause_if_speaker_profiles_missing(state: WorkflowState, cues: list) -> None:
    config = state["config"]
    tts_config = config.get("tts", {})
    if not bool(tts_config.get("pause_before_tts", False)):
        return
    if state.get("tts_profiles_confirmed") or tts_config.get("profiles_confirmed"):
        return
    speakers = sorted({cue.get("speaker_id") or "default" for cue in cues})
    profiles = tts_config.get("speaker_profiles", {})
    configured = set(profiles.keys()) if isinstance(profiles, dict) else set()
    missing = [speaker for speaker in speakers if speaker not in configured]
    if missing:
        raise WorkflowPauseRequired(
            "TTS 前需要为每个说话人选择音色和语速。",
            {
                "event": "pause",
                "reason": "speaker_profiles_required",
                "node": "tts_generate_and_detect",
                "speakers": speakers,
                "missing_speakers": missing,
            },
        )

