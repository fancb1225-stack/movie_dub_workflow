from __future__ import annotations

from pathlib import Path
from typing import Any

from src.services.job_service import JobService
from src.services.media_service import MediaService
from src.tools.file_tools import write_json
from src.tools.speaker_tools import (
    assign_placeholder_speakers_from_duration,
    assign_placeholder_speakers_from_srt,
)


class SpeakerService:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.jobs = JobService(config)
        self.media = MediaService(config)

    def identify_placeholder_speakers(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get_job(job_id)
        srt_path = self._find_job_srt(job)
        if srt_path is not None:
            segments = assign_placeholder_speakers_from_srt(
                srt_path.read_text(encoding="utf-8")
            )
            source = str(srt_path)
        else:
            media_report = job.get("media_report") or self.media.probe_job(job_id)
            segments = assign_placeholder_speakers_from_duration(
                int(media_report.get("duration_ms", 0))
            )
            source = "media_duration"
        report = {
            "job_id": job_id,
            "mode": self.config.get("speaker", {}).get("mode", "placeholder"),
            "status": "success",
            "speaker_count": 1 if segments else 0,
            "segment_count": len(segments),
            "source": source,
            "segments": segments,
        }
        report_path = Path(job["paths"]["reports_dir"]) / "speaker_report.json"
        write_json(report_path, report)
        self.jobs.update_job(
            job_id,
            reports={"speaker_report": str(report_path)},
            extra={"speaker_report": report},
        )
        return report

    def _find_job_srt(self, job: dict[str, Any]) -> Path | None:
        artifact_srt = job.get("artifacts", {}).get("srt")
        candidates = []
        if artifact_srt:
            candidates.append(Path(artifact_srt))
        candidates.extend(Path(job["paths"]["media_dir"]).glob("*.srt"))
        candidates.extend(Path(job["paths"]["job_dir"]).glob("*.srt"))
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

