from __future__ import annotations

from pathlib import Path
from typing import Any

from src.services.job_service import JobService
from src.tools.file_tools import write_json
from src.tools.video_tools import package_video_with_audio


class VideoService:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.jobs = JobService(config)

    def package_job_video(
        self,
        job_id: str,
        audio_path: str | None = None,
        output_filename: str = "final_en.mp4",
    ) -> dict[str, Any]:
        job = self.jobs.get_job(job_id)
        input_path = Path(job["paths"]["input"])
        if input_path.suffix.lower() != ".mp4":
            raise RuntimeError("Video packaging requires an uploaded MP4 job input.")
        replacement_audio = self._resolve_audio_path(job, audio_path)
        output_path = Path(job["paths"]["video_dir"]) / output_filename
        final_video = package_video_with_audio(
            input_path, replacement_audio, output_path, self.config
        )
        report = {
            "job_id": job_id,
            "status": "success",
            "input_video": str(input_path),
            "replacement_audio": str(replacement_audio),
            "final_video": final_video,
            "subtitles": "none",
        }
        report_path = Path(job["paths"]["reports_dir"]) / "video_report.json"
        write_json(report_path, report)
        self.jobs.update_job(
            job_id,
            status="video_packaged",
            artifacts={"final_video_mp4": final_video},
            reports={"video_report": str(report_path)},
            extra={"video_report": report},
        )
        return report

    def _resolve_audio_path(self, job: dict[str, Any], audio_path: str | None) -> Path:
        if audio_path:
            candidate = Path(audio_path)
            if not candidate.is_absolute():
                candidate = Path(job["paths"]["job_dir"]) / candidate
        else:
            candidate = Path(
                job.get("artifacts", {}).get(
                    "mixed_audio_wav",
                    job.get("artifacts", {}).get("source_audio_wav", ""),
                )
            )
        if not candidate.exists():
            raise FileNotFoundError(f"Replacement audio does not exist: {candidate}")
        return candidate
