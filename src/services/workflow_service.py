from __future__ import annotations

import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.graph import build_workflow, get_exception_node, unwrap_workflow_node_error
from src.services.job_service import JobService
from src.services.media_service import MediaService
from src.services.separation_service import SeparationService
from src.services.state_persistence import (
    clear_state_snapshot,
    detect_last_completed_node,
    get_resume_node,
    load_state_snapshot,
    save_state_snapshot,
)
from src.state import WorkflowState
from src.tools.asr_tools import transcribe_mp3_to_srt, write_asr_report
from src.tools.asr_words import cues_from_asr_words_file
from src.tools.file_tools import ensure_dir, write_json
from src.tools.tts_tools import FatalTtsError
from src.tools.srt_tools import parse_srt
from src.video_types import (
    DEFAULT_VIDEO_TYPE,
    VIDEO_TYPE_MANJU,
    VIDEO_TYPE_MOVIE_COMMENTARY,
    normalize_video_type,
)
from src.workflow_pause import WorkflowPauseRequired

logger = logging.getLogger(__name__)


PREPROCESS_STEPS = [
    {"node": "extract_audio", "label": "提取音频"},
    {"node": "separate_audio", "label": "分离人声与背景音"},
]

WORKFLOW_STEPS = [
    {"node": "merge_zh_asr_srt", "label": "ASR 字幕智能合并"},
    {"node": "restitch_merge_cuts", "label": "合并切点重整"},
    {"node": "clean_srt", "label": "字幕清洗"},
    {"node": "critic_srt", "label": "字幕校对"},
    {"node": "summarize_plot", "label": "剧情摘要"},
    {"node": "translate_to_english", "label": "英文翻译"},
    {"node": "tts_generate_and_detect", "label": "TTS 合成与时长检测"},
    {"node": "reflect_duration_issues", "label": "时长反思修正"},
    {"node": "align_and_merge_audio", "label": "音频对齐与合并"},
]
WORKFLOW_STEP_INDEX = {step["node"]: index for index, step in enumerate(WORKFLOW_STEPS, start=1)}


class WorkflowService:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.jobs = JobService(config)

    def run_job_preprocess_streaming(self, job_id: str):
        """Run extract → separate → ASR with SSE progress events."""
        job = self.jobs.get_job(job_id)
        yield {"event": "start", "steps": PREPROCESS_STEPS}

        # Step 1: Extract audio
        try:
            self.jobs.update_job(job_id, status="preprocessing")
            extract_result = MediaService(self.config).extract_audio_for_job(job_id)
            if extract_result.get("status") != "extracted" and extract_result.get("status") != "success":
                yield {"event": "error", "error": extract_result.get("error", "提取音频失败。"), "hint": extract_result.get("hint", "提取音频失败。请检查输入文件是否有音频轨。")}
                return
            yield {"event": "progress", "node": "extract_audio", "label": "提取音频", "status": "done", "index": 1, "total": len(PREPROCESS_STEPS)}
        except Exception as exc:
            yield {"event": "error", "error": str(exc), "hint": "提取音频失败。请检查输入文件。"}
            return

        # Step 2: Separate vocals and background
        job = self.jobs.get_job(job_id)
        try:
            separate_result = SeparationService(self.config).separate_job_audio(job_id)
            if separate_result.get("status") != "success":
                yield {"event": "error", "error": separate_result.get("error", "人声分离失败。"), "hint": separate_result.get("hint", "人声分离失败。请检查 Demucs 配置。")}
                return
            yield {"event": "progress", "node": "separate_audio", "label": "分离人声与背景音", "status": "done", "index": 2, "total": len(PREPROCESS_STEPS)}
        except Exception as exc:
            yield {"event": "error", "error": str(exc), "hint": "人声分离失败。请检查 Demucs 安装和配置。"}
            return

        self.jobs.update_job(job_id, status="preprocessed")
        yield {"event": "done", "hint": "预处理完成。可以执行 ASR 语音识别。"}

    def run_job_asr(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get_job(job_id)
        background_audio = _resolve_background_audio(job)
        job_config = _job_workflow_config(self.config, job, background_audio)
        raw_asr = _run_job_asr(job_id, job, job_config, self.jobs)
        return _asr_response(job_id, raw_asr, self.jobs.get_job(job_id))

    def run_job_langgraph_workflow(self, job_id: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        job = self.jobs.get_job(job_id)
        report_path = Path(job["paths"]["reports_dir"]) / "langgraph_workflow_report.json"
        raw_asr = _resolve_raw_asr(job)
        if raw_asr is None:
            report = _failure_report(
                job_id,
                "Missing raw ASR for LangGraph workflow.",
                "请先执行 ASR 语音识别，生成字幕后再运行翻译与配音工作流。",
                report_path,
            )
            self.jobs.update_job(
                job_id,
                status="langgraph_failed",
                reports={"langgraph_workflow_report": str(report_path)},
                extra={"langgraph_workflow_report": report},
            )
            return report

        background_audio = _resolve_background_audio(job)
        job_config: dict[str, Any] | None = None
        try:
            job_config = _job_workflow_config(self.config, job, background_audio)
            _apply_overrides(job_config, overrides)
            raw_srt_text, raw_cues = _load_raw_asr_state(raw_asr)
            state: WorkflowState = {
                "config": job_config,
                "raw_srt": raw_srt_text,
                "raw_cues": raw_cues,
                "reports": {},
                "errors": [],
                "reflection_rounds": 0,
                "input_video_path": job.get("paths", {}).get("input", ""),
            }
            final_state = build_workflow(job_config).invoke(state)
            report = _success_report(job_id, background_audio, final_state, report_path)
            self.jobs.update_job(
                job_id,
                status="langgraph_completed",
                artifacts=_workflow_artifacts(job_config),
                reports=_workflow_reports(final_state, report_path),
                extra={"langgraph_workflow_report": report},
            )
            return report
        except Exception as exc:
            report = _failure_report(
                job_id,
                str(exc),
                _workflow_hint(str(exc)),
                report_path,
                workflow_dir=_workflow_dir_from_config(job_config),
            )
            self.jobs.update_job(
                job_id,
                status="langgraph_failed",
                reports={"langgraph_workflow_report": str(report_path)},
                extra={"langgraph_workflow_report": report},
            )
            return report

    def run_job_langgraph_workflow_streaming(self, job_id: str, overrides: dict[str, Any] | None = None):
        job = self.jobs.get_job(job_id)
        report_path = Path(job["paths"]["reports_dir"]) / "langgraph_workflow_report.json"
        background_audio = _resolve_background_audio(job)
        yield {"event": "start", "steps": WORKFLOW_STEPS}
        raw_asr = _resolve_raw_asr(job)
        if raw_asr is None:
            report = _failure_report(
                job_id,
                "Missing raw ASR for LangGraph workflow.",
                "请先执行 ASR 语音识别，生成字幕后再运行翻译与配音工作流。",
                report_path,
            )
            self.jobs.update_job(
                job_id,
                status="langgraph_failed",
                reports={"langgraph_workflow_report": str(report_path)},
                extra={"langgraph_workflow_report": report, "langgraph_progress": {"event": "error", "report": report}},
            )
            yield {"event": "error", "report": report}
            return

        job_config: dict[str, Any] | None = None
        try:
            self.jobs.update_job(
                job_id,
                status="langgraph_running",
                extra={"langgraph_progress": {"event": "start", "steps": WORKFLOW_STEPS}},
            )
            job_config = _job_workflow_config(self.config, job, background_audio)
            _apply_overrides(job_config, overrides)
            raw_srt_text, raw_cues = _load_raw_asr_state(raw_asr)
            state: WorkflowState = {
                "config": job_config,
                "raw_srt": raw_srt_text,
                "raw_cues": raw_cues,
                "reports": {},
                "errors": [],
                "reflection_rounds": 0,
                "input_video_path": job.get("paths", {}).get("input", ""),
            }
            final_state = state
            workflow = build_workflow(job_config)
            logger.info("Streaming workflow: built %s for job %s", type(workflow).__name__, job_id)
            for chunk in workflow.stream(state):
                if not chunk:
                    logger.warning("Streaming workflow: got empty chunk")
                    continue
                node_name, node_state = next(iter(chunk.items()))
                logger.info("Streaming workflow: node '%s' completed", node_name)
                final_state = node_state
                progress = _progress_event(node_name, node_state)
                # Save state snapshot after each node completes
                save_state_snapshot(job["paths"]["job_dir"], node_state, node_name)
                self.jobs.update_job(job_id, extra={"langgraph_progress": progress})
                yield progress
            report = _success_report(job_id, background_audio, final_state, report_path)
            self.jobs.update_job(
                job_id,
                status="langgraph_completed",
                artifacts=_workflow_artifacts(job_config),
                reports=_workflow_reports(final_state, report_path),
                extra={"langgraph_workflow_report": report, "langgraph_progress": {"event": "done", "report": report}},
            )
            # Clear snapshot on successful completion
            clear_state_snapshot(job["paths"]["job_dir"])
            yield {"event": "done", "report": report}
        except WorkflowPauseRequired as pause:
            payload = dict(pause.payload)
            report = {
                "job_id": job_id,
                "status": "paused",
                "error": str(pause),
                "hint": "请在前端为每个说话人配置 TTS 音色、语速等参数后恢复工作流。",
                **payload,
            }
            self.jobs.update_job(
                job_id,
                status="langgraph_paused",
                extra={"langgraph_workflow_report": report, "langgraph_progress": report},
            )
            yield report
        except Exception as exc:
            report = _failure_report(
                job_id,
                str(exc),
                _workflow_hint(str(exc)),
                report_path,
                workflow_dir=_workflow_dir_from_config(job_config),
            )
            progress = _workflow_error_progress(exc, report)
            self.jobs.update_job(
                job_id,
                status="langgraph_failed",
                reports={"langgraph_workflow_report": str(report_path)},
                extra={"langgraph_workflow_report": report, "langgraph_progress": progress},
            )
            yield progress

    def resume_job_langgraph_workflow_streaming(self, job_id: str, overrides: dict[str, Any] | None = None):
        """Resume a failed workflow from the last completed node."""
        job = self.jobs.get_job(job_id)
        report_path = Path(job["paths"]["reports_dir"]) / "langgraph_workflow_report.json"
        background_audio = _resolve_background_audio(job)
        yield {"event": "start", "steps": WORKFLOW_STEPS}

        snapshot = load_state_snapshot(Path(job["paths"]["job_dir"]))
        if snapshot is None:
            # Fallback: detect last completed node from artifact files on disk
            last_completed = detect_last_completed_node(job["paths"]["job_dir"])
            if last_completed is None:
                report = _failure_report(
                    job_id,
                    "No state snapshot found for resume.",
                    "无法恢复：未找到工作流快照。请重新运行完整工作流。",
                    report_path,
                )
                self.jobs.update_job(
                    job_id,
                    status="langgraph_failed",
                    reports={"langgraph_workflow_report": str(report_path)},
                    extra={"langgraph_workflow_report": report, "langgraph_progress": {"event": "error", "report": report}},
                )
                yield {"event": "error", "report": report}
                return

            # Rebuild state from artifact files
            resume_node = get_resume_node(last_completed)
            if resume_node is None:
                report = _failure_report(
                    job_id,
                    "Workflow already completed, nothing to resume.",
                    "工作流已完成，无需恢复。",
                    report_path,
                )
                yield {"event": "error", "report": report}
                return

            job_config = _job_workflow_config(self.config, job, background_audio)
            _apply_overrides(job_config, overrides)
            raw_asr = _resolve_raw_asr(job)
            if raw_asr is None:
                report = _failure_report(
                    job_id,
                    "Missing raw ASR for resume.",
                    "无法恢复：缺少原始 ASR 文件。",
                    report_path,
                )
                yield {"event": "error", "report": report}
                return
            raw_srt_text, raw_cues = _load_raw_asr_state(raw_asr)
            state: WorkflowState = {
                "config": job_config,
                "raw_srt": raw_srt_text,
                "raw_cues": raw_cues,
                "reports": {},
                "errors": [],
                "reflection_rounds": 0,
                "input_video_path": job.get("paths", {}).get("input", ""),
            }
            last_completed_node = last_completed
        else:
            state, last_completed_node = snapshot

        resume_node = get_resume_node(last_completed_node)
        if resume_node is None:
            report = _failure_report(
                job_id,
                "Workflow already completed, nothing to resume.",
                "工作流已完成，无需恢复。",
                report_path,
            )
            yield {"event": "error", "report": report}
            return

        job_config: dict[str, Any] | None = None
        try:
            self.jobs.update_job(
                job_id,
                status="langgraph_running",
                extra={"langgraph_progress": {"event": "start", "steps": WORKFLOW_STEPS}},
            )
            job_config = state.get("config", {})
            _ensure_job_config_metadata(job_config, job, overwrite=False)
            _apply_overrides(job_config, overrides)
            job_config.setdefault("workflow", {})["reuse_existing_tts_segments"] = True
            state["config"] = job_config
            final_state = state
            workflow = build_workflow(job_config, resume_from=resume_node)
            for chunk in workflow.stream(state):
                if not chunk:
                    continue
                node_name, node_state = next(iter(chunk.items()))
                final_state = node_state
                progress = _progress_event(node_name, node_state)
                save_state_snapshot(job["paths"]["job_dir"], node_state, node_name)
                self.jobs.update_job(job_id, extra={"langgraph_progress": progress})
                yield progress
            report = _success_report(job_id, background_audio, final_state, report_path)
            self.jobs.update_job(
                job_id,
                status="langgraph_completed",
                artifacts=_workflow_artifacts(job_config),
                reports=_workflow_reports(final_state, report_path),
                extra={"langgraph_workflow_report": report, "langgraph_progress": {"event": "done", "report": report}},
            )
            clear_state_snapshot(job["paths"]["job_dir"])
            yield {"event": "done", "report": report}
        except Exception as exc:
            report = _failure_report(
                job_id,
                str(exc),
                _workflow_hint(str(exc)),
                report_path,
                workflow_dir=_workflow_dir_from_config(job_config),
            )
            progress = _workflow_error_progress(exc, report)
            self.jobs.update_job(
                job_id,
                status="langgraph_failed",
                reports={"langgraph_workflow_report": str(report_path)},
                extra={"langgraph_workflow_report": report, "langgraph_progress": progress},
            )
            yield progress


def _progress_event(node_name: str, state: WorkflowState) -> dict[str, Any]:
    step = next((item for item in WORKFLOW_STEPS if item["node"] == node_name), None)
    label = step["label"] if step else node_name
    index = WORKFLOW_STEP_INDEX.get(node_name, len(WORKFLOW_STEPS))
    event: dict[str, Any] = {
        "event": "progress",
        "node": node_name,
        "label": label,
        "status": "done",
        "index": index,
        "total": len(WORKFLOW_STEPS),
    }
    if node_name in {"tts_generate_and_detect", "reflect_duration_issues"}:
        event["reflection_rounds"] = int(state.get("reflection_rounds", 0))
    return event


def _workflow_error_progress(exc: Exception, report: dict[str, Any]) -> dict[str, Any]:
    cause = unwrap_workflow_node_error(exc)
    message = str(cause)
    event: dict[str, Any] = {"event": "error", "report": report}
    if isinstance(cause, FatalTtsError):
        event.update(
            {
                "node": "tts_generate_and_detect",
                "status": "error",
                "message": message,
                "error": message,
            }
        )
        return event

    node = get_exception_node(exc)
    if node:
        event.update(
            {
                "node": node,
                "status": "error",
                "message": message,
                "error": message,
            }
        )
    return event


def _run_job_asr(
    job_id: str,
    job: dict[str, Any],
    job_config: dict[str, Any],
    jobs: JobService,
) -> tuple[Path, str]:
    vocals_path = _resolve_vocals_audio(job)
    if vocals_path is None:
        raise RuntimeError("找不到人声音频文件。请先执行预处理完成人声/背景分离。")
    _apply_video_type_asr_provider(job_config)
    _ensure_job_mock_asr_allowed(job_config)
    job_config["paths"]["input_mp3"] = str(vocals_path)
    output_words_json = Path(job_config["paths"]["asr_words"])
    ensure_dir(output_words_json.parent)
    asr_result = transcribe_mp3_to_srt(vocals_path, output_words_json, job_config)
    output_srt = Path(job_config["paths"]["asr_srt"])
    ensure_dir(output_srt.parent)
    output_srt.write_text(str(asr_result["srt"]), encoding="utf-8")
    report_path = Path(job["paths"]["reports_dir"]) / "asr_report.json"
    write_asr_report(report_path, asr_result)
    artifacts = {
        "vocals_wav": str(vocals_path),
        "raw_srt": str(output_srt),
        "asr_report": str(report_path),
    }
    words_json = asr_result.get("words_json")
    raw_asr: tuple[Path, str] = (output_srt, "srt")
    if words_json and Path(str(words_json)).exists():
        artifacts["raw_words"] = str(words_json)
        raw_asr = (Path(str(words_json)), "words")
    jobs.update_job(
        job_id,
        status="asr_completed",
        artifacts=artifacts,
        extra={"asr_result": {k: v for k, v in asr_result.items() if k not in {"cues", "srt", "words"}}},
    )
    return raw_asr


def _asr_response(job_id: str, raw_asr: tuple[Path, str], job: dict[str, Any]) -> dict[str, Any]:
    asr_result = job.get("asr_result", {})
    artifacts = job.get("artifacts", {})
    return {
        "job_id": job_id,
        "status": "done",
        "input_audio": str(_resolve_vocals_audio(job) or ""),
        "raw_words": str(raw_asr[0]),
        "asr_report": str(artifacts.get("asr_report", "")),
        "provider": asr_result.get("provider"),
        "subtitle_count": asr_result.get("subtitle_count"),
        "speakers": asr_result.get("speakers", []),
    }


def _resolve_raw_srt(job: dict[str, Any]) -> Path | None:
    """Find the raw ASR SRT file for a job (from artifacts or workflow dir)."""
    artifact = job.get("artifacts", {}).get("raw_srt")
    candidates = []
    if artifact:
        candidates.append(Path(str(artifact)))
    candidates.append(Path(job["paths"]["job_dir"]) / "workflow" / "asr" / "zh_raw.srt")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _resolve_raw_asr(job: dict[str, Any]) -> tuple[Path, str] | None:
    """Find raw ASR artifact: prefer词级 words.json,回退 srt(兼容老 job)。

    返回 (path, kind),kind ∈ {"words", "srt"}。
    """
    job_dir = Path(job["paths"]["job_dir"])
    asr_dir = job_dir / "workflow" / "asr"
    words_artifact = job.get("artifacts", {}).get("raw_words")
    words_candidates: list[Path] = []
    if words_artifact:
        words_candidates.append(Path(str(words_artifact)))
    words_candidates.append(asr_dir / "zh_raw.words.json")
    for candidate in words_candidates:
        if candidate.exists():
            return candidate, "words"
    # 回退到 srt(老 job 或测试造数)
    srt_path = _resolve_raw_srt(job)
    if srt_path is not None:
        return srt_path, "srt"
    return None


def _load_raw_asr_state(raw_asr: tuple[Path, str]) -> tuple[str, list]:
    """从原始 ASR 产物重建 (raw_srt_text, raw_cues)。

    words.json:切短句 cues + 派生 srt 文本。
    srt:维持 parse_srt。
    """
    path, kind = raw_asr
    if kind == "words":
        from src.tools.srt_tools import format_srt

        raw_cues = cues_from_asr_words_file(path)
        write_json(path.with_name("zh_raw.cues.json"), raw_cues)
        return format_srt(raw_cues), raw_cues
    raw_srt_text = path.read_text(encoding="utf-8")
    return raw_srt_text, parse_srt(raw_srt_text)


def _resolve_vocals_audio(job: dict[str, Any]) -> Path | None:
    artifact = job.get("artifacts", {}).get("vocals_wav")
    candidates = []
    if artifact:
        candidates.append(Path(str(artifact)))
    candidates.append(Path(job["paths"]["media_dir"]) / "separation" / "vocals.wav")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _resolve_background_audio(job: dict[str, Any]) -> Path | None:
    artifact = job.get("artifacts", {}).get("background_wav")
    candidates = []
    if artifact:
        candidates.append(Path(str(artifact)))
    candidates.append(Path(job["paths"]["media_dir"]) / "separation" / "background.wav")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _job_workflow_config(
    config: dict[str, Any],
    job: dict[str, Any],
    background_audio: Path | None = None,
) -> dict[str, Any]:
    job_config = deepcopy(config)
    job_dir = Path(job["paths"]["job_dir"])
    workflow_dir = ensure_dir(job_dir / "workflow")
    ensure_dir(workflow_dir / "asr")
    ensure_dir(workflow_dir / "cleaned")
    ensure_dir(workflow_dir / "merged")
    ensure_dir(workflow_dir / "critic")
    ensure_dir(workflow_dir / "translated")
    ensure_dir(workflow_dir / "final")
    ensure_dir(workflow_dir / "tts_segments")
    ensure_dir(workflow_dir / "audio")
    ensure_dir(Path(job["paths"]["reports_dir"]))

    job_config["paths"] = deepcopy(job_config.get("paths", {}))
    job_config["paths"].update(
        {
            "outputs_dir": str(workflow_dir),
            "asr_srt": str(workflow_dir / "asr" / "zh_raw.srt"),
            "asr_words": str(workflow_dir / "asr" / "zh_raw.words.json"),
            "merged_asr_srt": str(workflow_dir / "merged" / "zh_asr_merged.srt"),
            "cleaned_srt": str(workflow_dir / "cleaned" / "zh_cleaned.srt"),
            "corrected_srt": str(workflow_dir / "critic" / "zh_corrected.srt"),
            "translated_srt": str(workflow_dir / "translated" / "en_translated.srt"),
            "final_srt": str(workflow_dir / "final" / "en_final.srt"),
            "tts_segments_dir": str(workflow_dir / "tts_segments"),
            "reports_dir": str(Path(job["paths"]["reports_dir"])),
            "audio_dir": str(workflow_dir / "audio"),
            "narration_wav": str(workflow_dir / "audio" / "narration_en.wav"),
            "narration_mp3": str(workflow_dir / "audio" / "narration_en.mp3"),
            "input_video": str(Path(job["paths"]["job_dir"]) / "input" / job.get("original_filename", "")),
        }
    )
    if background_audio is not None:
        job_config.setdefault("audio", {})["background_mp3"] = str(background_audio)
        job_config.setdefault("audio", {})["background_wav"] = str(background_audio)
        job_config["paths"]["background_mp3"] = str(background_audio)
    _ensure_job_config_metadata(job_config, job, overwrite=True)
    return job_config


def _ensure_job_config_metadata(
    config: dict[str, Any], job: dict[str, Any], *, overwrite: bool = False
) -> None:
    """Populate config["job"] with job metadata for prompt selection.

    New workflow builds pass overwrite=True to write current job metadata.
    Resume from snapshot passes overwrite=False so an existing video_type is
    preserved, avoiding mid-workflow prompt style switches.
    """
    config.setdefault("job", {})
    metadata = {
        "job_id": job.get("job_id", ""),
        "video_type": normalize_video_type(job.get("video_type", DEFAULT_VIDEO_TYPE)),
        "original_filename": job.get("original_filename", ""),
        "input_kind": job.get("input_kind", ""),
    }
    for key, value in metadata.items():
        if overwrite or key not in config["job"]:
            config["job"][key] = value


def _apply_video_type_asr_provider(config: dict[str, Any]) -> None:
    video_type = normalize_video_type(config.get("job", {}).get("video_type", DEFAULT_VIDEO_TYPE))
    workflow_config = config.get("workflow", {})
    asr_config = config.setdefault("asr", {})
    if video_type == VIDEO_TYPE_MANJU:
        asr_config["provider"] = str(workflow_config.get("manju_asr_provider", "whisperx"))
        asr_config.pop("default_speaker_id", None)
    elif video_type == VIDEO_TYPE_MOVIE_COMMENTARY:
        asr_config["provider"] = str(workflow_config.get("movie_commentary_asr_provider", "faster_whisper"))
        asr_config["default_speaker_id"] = str(workflow_config.get("movie_commentary_default_speaker_id", "speaker_0"))


def _ensure_job_mock_asr_allowed(config: dict[str, Any]) -> None:
    provider = str(config.get("asr", {}).get("provider", "mock")).lower()
    allow_mock = bool(config.get("workflow", {}).get("allow_mock_asr_for_jobs", False))
    if provider == "mock" and not allow_mock:
        raise RuntimeError(
            "Job preprocessing would use mock ASR, but "
            "workflow.allow_mock_asr_for_jobs is false."
        )


def _success_report(
    job_id: str,
    background_audio: Path | None,
    state: WorkflowState,
    report_path: Path,
) -> dict[str, Any]:
    config = state["config"]
    workflow_dir = str(Path(config["paths"]["outputs_dir"]))
    report = {
        "job_id": job_id,
        "status": "success",
        "source": "job_vocals",
        "workflow_dir": workflow_dir,
        "background_audio": str(background_audio) if background_audio else None,
        "raw_srt": config["paths"].get("asr_srt"),
        "final_srt": config["paths"].get("final_srt"),
        "narration_wav": state.get("narration_wav_path") or config["paths"].get("narration_wav"),
        "narration_mp3": state.get("narration_mp3_path") or config["paths"].get("narration_mp3"),
        "pipeline_report": state.get("reports", {}).get("pipeline_report"),
        "report": str(report_path),
        "subtitle_count": len(state.get("final_cues", [])),
        "reflection_rounds": int(state.get("reflection_rounds", 0)),
        "remaining_duration_issues": len(state.get("duration_issues", [])),
        "error": None,
        "hint": None,
    }
    write_json(report_path, report)
    return report


def _failure_report(
    job_id: str,
    error: str,
    hint: str,
    report_path: Path,
    *,
    workflow_dir: str | None = None,
) -> dict[str, Any]:
    report = {
        "job_id": job_id,
        "status": "failed",
        "source": None,
        "workflow_dir": workflow_dir,
        "background_audio": None,
        "raw_srt": None,
        "final_srt": None,
        "narration_wav": None,
        "narration_mp3": None,
        "pipeline_report": None,
        "report": str(report_path),
        "error": error,
        "hint": hint,
    }
    write_json(report_path, report)
    return report


def _workflow_dir_from_config(config: dict[str, Any] | None) -> str | None:
    if not config:
        return None
    return str(config.get("paths", {}).get("outputs_dir") or "") or None


def _workflow_artifacts(config: dict[str, Any]) -> dict[str, str]:
    paths = config["paths"]
    candidates = {
        "raw_srt": paths["asr_srt"],
        "raw_cues": str(Path(paths["asr_srt"]).with_suffix(".cues.json")),
        "merged_asr_srt": paths["merged_asr_srt"],
        "merged_asr_cues": str(Path(paths["merged_asr_srt"]).with_suffix(".cues.json")),
        "cleaned_srt": paths["cleaned_srt"],
        "corrected_srt": paths["corrected_srt"],
        "corrected_cues": str(Path(paths["corrected_srt"]).with_suffix(".cues.json")),
        "translated_srt": paths["translated_srt"],
        "translated_cues": str(Path(paths["translated_srt"]).with_suffix(".cues.json")),
        "final_srt": paths["final_srt"],
        "final_cues": str(Path(paths["final_srt"]).with_suffix(".cues.json")),
        "narration_wav": paths["narration_wav"],
        "narration_mp3": paths["narration_mp3"],
    }
    return {key: value for key, value in candidates.items() if Path(value).exists()}


def _workflow_reports(state: WorkflowState, report_path: Path) -> dict[str, Any]:
    reports = dict(state.get("reports", {}))
    reports["langgraph_workflow_report"] = str(report_path)
    return reports


def _apply_overrides(config: dict[str, Any], overrides: dict[str, Any] | None) -> None:
    """Apply runtime overrides to a job config using dot-notation keys."""
    if not overrides:
        return
    for dotted_key, value in overrides.items():
        parts = dotted_key.split(".")
        target: Any = config
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value


def _workflow_hint(error: str) -> str:
    lowered = error.lower()
    if "cublas" in lowered or "cuda" in lowered or "cudnn" in lowered:
        return (
            "faster-whisper 正在尝试使用 CUDA，但当前 Windows 环境缺少 CUDA/CUBLAS DLL。"
            "请将 config.yaml 的 asr.device 设为 cpu、asr.compute_type 设为 int8，"
            "然后重启 API 后重试。"
        )
    if "faster_whisper" in lowered or "whisper" in lowered:
        return (
            "页面触发的 job 工作流默认不再使用 mock ASR。请安装 faster-whisper，"
            "或在 config.yaml 中将 workflow.allow_mock_asr_for_jobs 设为 true 仅用于测试。"
        )
    if "access_denied" in lowered or "ip" in lowered and "允许访问" in error:
        if "minimax" in lowered or "tts" in lowered:
            return (
                "MiniMax TTS 服务拒绝访问。请检查 MiniMax/TTS 服务的 IP 白名单、"
                "LLM_API_KEY、MINIMAX_GROUP_ID、TTS_MODEL 和 base_url 配置。"
            )
        return "LLM 服务拒绝访问。请检查 LLM 服务的 IP 白名单、API Key 权限和 LLM_BASE_URL。"
    if "edge_tts" in lowered or "tts" in lowered:
        return "TTS 依赖或配置不可用。请检查 tts.provider/voice 配置，或先使用 mock TTS 验证流程。"
    if "llm" in lowered or "http" in lowered or "api" in lowered:
        return "LLM 校对/翻译请求失败。请检查 LLM_API_KEY、LLM_BASE_URL、LLM_MODEL 或将 llm.model 设为 mock。"
    return "请查看 outputs/jobs/<job_id>/reports/langgraph_workflow_report.json，并确认已完成人声分离。"
