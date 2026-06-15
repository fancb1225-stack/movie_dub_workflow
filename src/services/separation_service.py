from __future__ import annotations

from pathlib import Path
from typing import Any

from src.services.job_service import JobService
from src.services.media_service import MediaService
from src.tools.file_tools import write_json
from src.tools.separation_tools import separate_with_demucs


class SeparationService:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.jobs = JobService(config)
        self.media = MediaService(config)

    def separate_job_audio(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get_job(job_id)
        source_audio = job.get("artifacts", {}).get("source_audio_wav")
        if not source_audio:
            source_audio = self.media.extract_audio_for_job(job_id)["source_audio_wav"]
            job = self.jobs.get_job(job_id)
        output_dir = Path(job["paths"]["media_dir"]) / "separation"
        report_path = Path(job["paths"]["reports_dir"]) / "separation_report.json"
        try:
            result = separate_with_demucs(source_audio, output_dir, self.config)
            report = {"job_id": job_id, "status": "success", **result}
            self.jobs.update_job(
                job_id,
                status="audio_separated",
                artifacts={
                    "vocals_wav": result["vocals_wav"],
                    "background_wav": result["background_wav"],
                },
                reports={"separation_report": str(report_path)},
                extra={"separation_report": report},
            )
        except Exception as exc:
            report = {
                "job_id": job_id,
                "status": "failed",
                "source_audio": str(source_audio),
                "error": str(exc),
                "hint": _separation_hint(str(exc)),
                "vocals_wav": None,
                "background_wav": None,
            }
            self.jobs.update_job(
                job_id,
                status="separation_failed",
                reports={"separation_report": str(report_path)},
                extra={"separation_report": report},
            )
        write_json(report_path, report)
        return report

    def get_or_create_background(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get_job(job_id)
        background = job.get("artifacts", {}).get("background_wav")
        if background and Path(background).exists():
            return {
                "job_id": job_id,
                "status": "available",
                "background_wav": background,
                "source": "separation",
            }
        report = self.separate_job_audio(job_id)
        if report.get("status") == "success":
            return {
                "job_id": job_id,
                "status": "available",
                "background_wav": report.get("background_wav"),
                "source": "separation",
            }
        return {
            "job_id": job_id,
            "status": "unavailable",
            "background_wav": None,
            "source": "separation",
            "error": report.get("error", "Background extraction failed."),
            "hint": report.get("hint"),
        }


def _separation_hint(error: str) -> str:
    lowered = error.lower()
    if "keyboardinterrupt" in lowered or "3221225786" in lowered:
        return "Demucs 在完成前被中断。CPU 分离可能需要几分钟，请保持 API/终端进程运行，或在 config.yaml 中调低 separation.segment/shifts。"
    if "torchcodec" in lowered:
        return "Demucs CLI 的保存逻辑触发了 torchcodec 兼容问题。请重启 API，确认 config.yaml 中 separation.method=python，并确认 ffmpeg/bin 可用。"
    if "no module named demucs" in lowered or ("demucs" in lowered and "not installed" in lowered):
        return "当前 venv 未安装 Demucs。请运行：.venv\\Scripts\\python.exe -m pip install demucs"
    if "connection" in lowered or "download" in lowered or "http" in lowered:
        return "Demucs 可能正在下载模型。请检查网络访问，或提前缓存 config.yaml 中配置的模型。"
    if "cuda" in lowered or "out of memory" in lowered:
        return "分离模型可能需要更多显存。请改用 CPU、缩短输入文件，或调低 separation.segment。"
    return "请查看 outputs/jobs/<job_id>/reports/separation_report.json，并确认输入音频可读。"
