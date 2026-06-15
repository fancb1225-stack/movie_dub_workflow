from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from src.graph import build_workflow
from src.services.job_service import JobService
from src.state import WorkflowState
from src.tools.file_tools import ensure_dir, write_json


class WorkflowService:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.jobs = JobService(config)

    def run_job_langgraph_workflow(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get_job(job_id)
        report_path = Path(job["paths"]["reports_dir"]) / "langgraph_workflow_report.json"
        input_audio = _resolve_vocals_audio(job)
        background_audio = _resolve_background_audio(job)
        if input_audio is None:
            report = _failure_report(
                job_id,
                None,
                "Missing separated vocals audio for LangGraph workflow.",
                "请先执行“分离人声与背景音”，生成 media/separation/vocals.wav 后再运行翻译与配音工作流。",
                report_path,
            )
            self.jobs.update_job(
                job_id,
                status="langgraph_failed",
                reports={"langgraph_workflow_report": str(report_path)},
                extra={"langgraph_workflow_report": report},
            )
            return report

        job_config: dict[str, Any] | None = None
        try:
            job_config = _job_workflow_config(self.config, job, input_audio, background_audio)
            state: WorkflowState = {
                "config": job_config,
                "reports": {},
                "errors": [],
                "reflection_rounds": 0,
            }
            final_state = build_workflow(job_config).invoke(state)
            report = _success_report(job_id, input_audio, background_audio, final_state, report_path)
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
                input_audio,
                str(exc),
                _workflow_hint(str(exc)),
                report_path,
                workflow_dir=_workflow_dir_from_config(job_config),
                asr_provider=_asr_provider_from_config(job_config),
            )
            self.jobs.update_job(
                job_id,
                status="langgraph_failed",
                reports={"langgraph_workflow_report": str(report_path)},
                extra={"langgraph_workflow_report": report},
            )
            return report


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
    input_audio: Path,
    background_audio: Path | None,
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
            "input_mp3": str(input_audio),
            "outputs_dir": str(workflow_dir),
            "asr_srt": str(workflow_dir / "asr" / "zh_raw.srt"),
            "cleaned_srt": str(workflow_dir / "cleaned" / "zh_cleaned.srt"),
            "merged_before_critic_srt": str(
                workflow_dir / "merged" / "zh_merged_before_critic.srt"
            ),
            "corrected_srt": str(workflow_dir / "critic" / "zh_corrected.srt"),
            "merged_after_critic_srt": str(
                workflow_dir / "merged" / "zh_merged_after_critic.srt"
            ),
            "translated_srt": str(workflow_dir / "translated" / "en_translated.srt"),
            "final_srt": str(workflow_dir / "final" / "en_final.srt"),
            "tts_segments_dir": str(workflow_dir / "tts_segments"),
            "reports_dir": str(Path(job["paths"]["reports_dir"])),
            "audio_dir": str(workflow_dir / "audio"),
            "narration_wav": str(workflow_dir / "audio" / "narration_en.wav"),
            "narration_mp3": str(workflow_dir / "audio" / "narration_en.mp3"),
        }
    )
    if background_audio is not None:
        job_config.setdefault("audio", {})["background_mp3"] = str(background_audio)
        job_config.setdefault("audio", {})["background_wav"] = str(background_audio)
        job_config["paths"]["background_mp3"] = str(background_audio)
    _configure_job_asr(job_config)
    return job_config


def _configure_job_asr(job_config: dict[str, Any]) -> None:
    """Keep Web-triggered job workflows from silently reusing mock ASR."""
    workflow_config = job_config.get("workflow", {})
    allow_mock = bool(workflow_config.get("allow_mock_asr_for_jobs", False))
    asr_config = job_config.setdefault("asr", {})
    provider = str(asr_config.get("provider", "mock")).lower()
    if provider == "mock" and not allow_mock:
        asr_config["provider"] = str(
            workflow_config.get("force_job_asr_provider", "faster_whisper")
        )
        provider = str(asr_config["provider"]).lower()
    if provider == "faster_whisper":
        asr_config.setdefault("device", "cpu")
        asr_config.setdefault("compute_type", "int8")
        asr_config.setdefault("vad_filter", True)
    asr_config["mock_when_missing_input"] = False


def _success_report(
    job_id: str,
    input_audio: Path,
    background_audio: Path | None,
    state: WorkflowState,
    report_path: Path,
) -> dict[str, Any]:
    config = state["config"]
    asr_provider = str(config.get("asr", {}).get("provider", "mock"))
    workflow_dir = str(Path(config["paths"]["outputs_dir"]))
    report = {
        "job_id": job_id,
        "status": "success",
        "source": "job_vocals",
        "workflow_dir": workflow_dir,
        "asr_provider": asr_provider,
        "used_mock_asr": asr_provider.lower() == "mock",
        "input_audio": str(input_audio),
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
    input_audio: Path | None,
    error: str,
    hint: str,
    report_path: Path,
    *,
    workflow_dir: str | None = None,
    asr_provider: str | None = None,
) -> dict[str, Any]:
    report = {
        "job_id": job_id,
        "status": "failed",
        "source": "job_vocals" if input_audio else None,
        "workflow_dir": workflow_dir,
        "asr_provider": asr_provider,
        "used_mock_asr": asr_provider.lower() == "mock" if asr_provider else None,
        "input_audio": str(input_audio) if input_audio else None,
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


def _asr_provider_from_config(config: dict[str, Any] | None) -> str | None:
    if not config:
        return None
    provider = config.get("asr", {}).get("provider")
    return str(provider) if provider else None


def _workflow_artifacts(config: dict[str, Any]) -> dict[str, str]:
    paths = config["paths"]
    candidates = {
        "raw_srt": paths["asr_srt"],
        "cleaned_srt": paths["cleaned_srt"],
        "merged_before_critic_srt": paths["merged_before_critic_srt"],
        "corrected_srt": paths["corrected_srt"],
        "merged_after_critic_srt": paths["merged_after_critic_srt"],
        "translated_srt": paths["translated_srt"],
        "final_srt": paths["final_srt"],
        "narration_wav": paths["narration_wav"],
        "narration_mp3": paths["narration_mp3"],
        "langgraph_input_audio": paths["input_mp3"],
    }
    return {key: value for key, value in candidates.items() if Path(value).exists()}


def _workflow_reports(state: WorkflowState, report_path: Path) -> dict[str, Any]:
    reports = dict(state.get("reports", {}))
    reports["langgraph_workflow_report"] = str(report_path)
    return reports


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
    if "edge_tts" in lowered or "tts" in lowered:
        return "TTS 依赖或配置不可用。请检查 tts.provider/voice 配置，或先使用 mock TTS 验证流程。"
    if "access_denied" in lowered or "ip" in lowered and "允许访问" in error:
        return "LLM 服务拒绝访问。请检查 LLM 服务的 IP 白名单、API Key 权限和 LLM_BASE_URL。"
    if "llm" in lowered or "http" in lowered or "api" in lowered:
        return "LLM 校对/翻译请求失败。请检查 LLM_API_KEY、LLM_BASE_URL、LLM_MODEL 或将 llm.model 设为 mock。"
    return "请查看 outputs/jobs/<job_id>/reports/langgraph_workflow_report.json，并确认已完成人声分离。"
