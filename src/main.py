from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from src.config import config_path, load_config, resolve_path
from src.graph import build_workflow
from src.llm_client import LLMClient, load_dotenv_if_present
from src.state import WorkflowState
from src.tools.file_tools import ensure_dir
from src.trace_collector import TraceCollector, set_active_collector, clear_active_collector


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the movie dub workflow.")
    parser.add_argument("--trace", action="store_true", help="Collect LLM call traces into an eval case.")
    parser.add_argument("--run-id", default=None, help="Run/case id used for the trace output directory.")
    args = parser.parse_args()

    load_dotenv_if_present()
    config = load_config("config.yaml")
    _ensure_base_dirs(config)
    state: WorkflowState = {
        "config": config,
        "reports": {},
        "errors": [],
        "reflection_rounds": 0,
    }

    trace_enabled = bool(args.trace or config.get("trace", {}).get("enabled", False))
    llm_enabled = LLMClient.from_config(config).enabled()
    collector: TraceCollector | None = None
    if trace_enabled:
        if not llm_enabled:
            print("WARNING: --trace requested but LLM is disabled (mock mode); trace collection skipped.", file=sys.stderr)
        else:
            collector = TraceCollector()
            set_active_collector(collector)

    workflow = build_workflow(config)
    run_error: str | None = None
    try:
        final_state = workflow.invoke(state)
    except Exception as exc:
        run_error = str(exc)
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        raise
    finally:
        if collector is not None:
            run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
            cases_dir = resolve_path(config, str(config.get("trace", {}).get("cases_dir", "eval/cases")))
            try:
                case_dir = collector.write_case(cases_dir, run_id, run_error)
                print(f"Trace case written to {case_dir}")
            except Exception as trace_exc:
                print(f"WARNING: failed to write trace case: {trace_exc}", file=sys.stderr)
            clear_active_collector()

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
