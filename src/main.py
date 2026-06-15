from __future__ import annotations

import sys
from pathlib import Path

from src.config import config_path, load_config
from src.graph import build_workflow
from src.llm_client import load_dotenv_if_present
from src.state import WorkflowState
from src.tools.file_tools import ensure_dir


def main() -> None:
    load_dotenv_if_present()
    config = load_config("config.yaml")
    _ensure_base_dirs(config)
    state: WorkflowState = {
        "config": config,
        "reports": {},
        "errors": [],
        "reflection_rounds": 0,
    }
    workflow = build_workflow(config)
    try:
        final_state = workflow.invoke(state)
    except Exception as exc:
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        raise
    _print_outputs(final_state)


def _ensure_base_dirs(config: dict) -> None:
    ensure_dir(config_path(config, "paths.outputs_dir"))
    ensure_dir(config_path(config, "paths.reports_dir"))
    ensure_dir(config_path(config, "paths.tts_segments_dir"))
    ensure_dir(Path(config["project_root"]) / "input")


def _print_outputs(state: WorkflowState) -> None:
    print("Pipeline completed.")
    print(f"Final SRT: {state.get('final_srt') and state['config']['paths']['final_srt']}")
    print(f"Narration WAV: {state.get('narration_wav_path', '')}")
    print(f"Narration MP3: {state.get('narration_mp3_path', '')}")
    print(f"Pipeline report: {state.get('reports', {}).get('pipeline_report', '')}")


if __name__ == "__main__":
    main()

