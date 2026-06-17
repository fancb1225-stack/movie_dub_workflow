from __future__ import annotations

import logging

from src.config import config_path
from src.state import WorkflowState
from src.tools.duration_tools import build_tts_duration_report, detect_duration_issues
from src.tools.file_tools import write_json
from src.tools.tts_tools import generate_tts_segments

logger = logging.getLogger(__name__)


def tts_generate_and_detect(state: WorkflowState) -> WorkflowState:
    config = state["config"]
    cues = state.get("final_cues", [])
    logger.info("tts_generate_and_detect: %d cues, provider=%s", len(cues), config.get("tts", {}).get("provider"))
    segments = generate_tts_segments(cues, config_path(config, "paths.tts_segments_dir"), config)
    duration_config = config.get("duration", {})
    issues = detect_duration_issues(
        cues,
        segments,
        int(duration_config.get("max_overrun_ms", 350)),
        float(duration_config.get("max_ratio", 1.12)),
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

