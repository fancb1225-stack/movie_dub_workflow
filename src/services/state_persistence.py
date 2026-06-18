from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.state import WorkflowState

SNAPSHOT_FILENAME = "state_snapshot.json"

NODE_ORDER = [
    "merge_zh_asr_srt",
    "restitch_merge_cuts",
    "clean_srt",
    "critic_srt",
    "summarize_plot",
    "translate_to_english",
    "tts_generate_and_detect",
    "reflect_duration_issues",
    "align_and_merge_audio",
]

# Maps each node name to the file artifacts it produces.
# Used to determine the last completed node when no snapshot exists.
NODE_ARTIFACTS: dict[str, list[str]] = {
    "merge_zh_asr_srt": ["workflow/merged/zh_asr_merged.srt"],
    "clean_srt": ["workflow/cleaned/zh_cleaned.srt"],
    "critic_srt": ["workflow/critic/zh_corrected.srt"],
    "summarize_plot": ["reports/plot_summary.txt"],
    "translate_to_english": ["workflow/translated/en_translated.srt"],
    "tts_generate_and_detect": ["workflow/tts_segments/segment_*.mp3"],
    "align_and_merge_audio": ["workflow/audio/narration_en.wav"],
}

# Glob-pattern artifacts: these require glob matching, not just existence.
GLOB_ARTIFACT_NODES = {"tts_generate_and_detect"}


def _check_artifact_exists(job_path: Path, artifact: str) -> bool:
    """Check whether an artifact path exists on disk.

    For glob patterns (containing *), checks that at least one match exists.
    For regular paths, checks existence directly.
    """
    if "*" in artifact:
        return any(job_path.glob(artifact))
    return (job_path / artifact).exists()


def save_state_snapshot(
    job_dir: str | Path,
    state: WorkflowState,
    last_completed_node: str,
) -> None:
    """Serialize WorkflowState + last_completed_node to state_snapshot.json."""
    job_path = Path(job_dir)
    workflow_dir = job_path / "workflow"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = workflow_dir / SNAPSHOT_FILENAME
    snapshot_data = {
        "last_completed_node": last_completed_node,
        "state": _serialize_state(state),
    }
    snapshot_path.write_text(
        json.dumps(snapshot_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_state_snapshot(job_dir: str | Path) -> tuple[WorkflowState, str] | None:
    """Load state snapshot. Returns (state, last_completed_node) or None if no snapshot exists."""
    snapshot_path = Path(job_dir) / "workflow" / SNAPSHOT_FILENAME
    if not snapshot_path.exists():
        return None
    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        state = _deserialize_state(data["state"])
        return state, data["last_completed_node"]
    except (json.JSONDecodeError, KeyError):
        return None


def clear_state_snapshot(job_dir: str | Path) -> None:
    """Remove state snapshot after successful workflow completion."""
    snapshot_path = Path(job_dir) / "workflow" / SNAPSHOT_FILENAME
    if snapshot_path.exists():
        snapshot_path.unlink()


def get_resume_start_index(last_completed_node: str) -> int:
    """Return the index in NODE_ORDER from which to resume execution."""
    try:
        return NODE_ORDER.index(last_completed_node) + 1
    except ValueError:
        return 0


def get_resume_node(last_completed_node: str) -> str | None:
    """Return the name of the node to start from when resuming, or None if completed."""
    next_index = get_resume_start_index(last_completed_node)
    if next_index >= len(NODE_ORDER):
        return None
    return NODE_ORDER[next_index]


def detect_last_completed_node(job_dir: str | Path) -> str | None:
    """Detect the last completed node by checking which artifact files exist.

    Walks NODE_ORDER in reverse and returns the first node whose artifacts
    all exist on disk. Returns None if no artifacts are found.

    Special case: if align_and_merge_audio produced a silent WAV file
    (all TTS segments failed), returns tts_generate_and_detect so the
    workflow can be re-run from that point.
    """
    job_path = Path(job_dir)
    for node in reversed(NODE_ORDER):
        artifacts = NODE_ARTIFACTS.get(node, [])
        if not artifacts:
            continue
        all_exist = True
        for artifact in artifacts:
            if not _check_artifact_exists(job_path, artifact):
                all_exist = False
                break
        if all_exist:
            # Special case: silent narration means TTS failed
            if node == "align_and_merge_audio" and _is_narration_silent(job_path):
                return "tts_generate_and_detect"
            return node
    return None


def _is_narration_silent(job_path: Path) -> bool:
    """Check if narration_en.wav is silent (all amplitude values are 0).

    This happens when all TTS segments failed and align_and_merge_audio
    produced a silent canvas.
    """
    wav_path = job_path / "workflow" / "audio" / "narration_en.wav"
    if not wav_path.exists():
        return True
    try:
        import wave as wave_mod
        from array import array
        with wave_mod.open(str(wav_path), "rb") as reader:
            # Check first 5000 frames for non-zero samples
            raw = reader.readframes(5000)
            if not raw:
                return True
            samples = array("h")
            samples.frombytes(raw)
            return all(s == 0 for s in samples)
    except Exception:
        return True


def _serialize_state(state: WorkflowState) -> dict[str, Any]:
    """Convert WorkflowState to a JSON-compatible dict."""
    result: dict[str, Any] = {}
    for key, value in state.items():
        if key == "config":
            # Config is already JSON-compatible (dict of dicts and primitives)
            result[key] = value
        elif isinstance(value, (str, int, float, bool)):
            result[key] = value
        elif isinstance(value, list):
            result[key] = value
        elif isinstance(value, dict):
            result[key] = value
        else:
            # Skip non-serializable fields
            result[key] = str(value)
    return result


def _deserialize_state(data: dict[str, Any]) -> WorkflowState:
    """Convert a JSON dict back to WorkflowState."""
    # WorkflowState is a TypedDict total=False, so all keys are optional
    # Just return the dict as-is; missing keys are fine
    return data  # type: ignore[return-value]