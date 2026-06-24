from __future__ import annotations

from src.config import config_path
from src.state import WorkflowState
from src.tools.asr_tools import transcribe_mp3_to_srt, write_asr_report


def asr_mp3_to_srt(state: WorkflowState) -> WorkflowState:
    config = state["config"]
    input_mp3 = config_path(config, "paths.input_mp3")
    output_words_json = config_path(config, "paths.asr_words")
    asr_result = transcribe_mp3_to_srt(input_mp3, output_words_json, config)
    report_path = config_path(config, "paths.reports_dir") / "asr_report.json"
    write_asr_report(report_path, asr_result)
    state["asr_result"] = {
        key: value for key, value in asr_result.items() if key not in {"cues", "srt", "words"}
    }
    state["raw_srt"] = str(asr_result["srt"])
    state["raw_cues"] = asr_result["cues"]
    state["raw_words"] = asr_result["words"]
    state.setdefault("reports", {})["asr_report"] = str(report_path)
    return state

