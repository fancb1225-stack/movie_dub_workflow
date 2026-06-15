from __future__ import annotations

from src.config import config_path
from src.state import WorkflowState
from src.tools.duration_tools import build_tts_duration_report, detect_duration_issues
from src.tools.file_tools import write_json
from src.tools.tts_tools import generate_tts_segments


def tts_generate_and_detect(state: WorkflowState) -> WorkflowState:
    config = state["config"]
    cues = state.get("final_cues", [])
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
    state["tts_segments"] = segments
    state["duration_issues"] = issues
    state.setdefault("reports", {})["tts_duration_report"] = str(report_path)
    return state

