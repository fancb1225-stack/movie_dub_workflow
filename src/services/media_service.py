from __future__ import annotations

from pathlib import Path
from typing import Any

from src.services.job_service import JobService
from src.tools.ffmpeg_tools import probe_media
from src.tools.file_tools import write_json
from src.tools.media_tools import (
    extract_audio,
    has_audio_stream,
    has_video_stream,
    media_duration_ms,
)


class MediaService:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.jobs = JobService(config)

    def probe_job(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get_job(job_id)
        input_path = Path(job["paths"]["input"])
        probe = probe_media(input_path, self.config)
        report = self._build_probe_report(job_id, input_path, probe)
        report_path = Path(job["paths"]["reports_dir"]) / "media_report.json"
        write_json(report_path, report)
        self.jobs.update_job(
            job_id,
            reports={"media_report": str(report_path)},
            extra={"media_report": report},
        )
        return report

    def extract_audio_for_job(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get_job(job_id)
        input_path = Path(job["paths"]["input"])
        probe = probe_media(input_path, self.config)
        if not has_audio_stream(probe):
            raise RuntimeError(f"Input has no audio stream: {input_path}")
        output_path = Path(job["paths"]["media_dir"]) / "source_audio.wav"
        sample_rate = int(self.config.get("media", {}).get("audio_sample_rate", 16000))
        extract_audio(input_path, output_path, sample_rate, self.config)
        report = self._build_probe_report(job_id, input_path, probe)
        report.update(
            {
                "status": "extracted",
                "source_audio_wav": str(output_path),
                "audio_sample_rate": sample_rate,
            }
        )
        report_path = Path(job["paths"]["reports_dir"]) / "media_report.json"
        write_json(report_path, report)
        self.jobs.update_job(
            job_id,
            status="audio_extracted",
            artifacts={"source_audio_wav": str(output_path)},
            reports={"media_report": str(report_path)},
            extra={"media_report": report},
        )
        return report

    def _build_probe_report(
        self, job_id: str, input_path: Path, probe: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "job_id": job_id,
            "input_path": str(input_path),
            "has_audio": has_audio_stream(probe),
            "has_video": has_video_stream(probe),
            "duration_ms": media_duration_ms(probe),
            "stream_count": len(probe.get("streams", [])),
            "format": probe.get("format", {}).get("format_name", ""),
            "probe": probe,
        }

