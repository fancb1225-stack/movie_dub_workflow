# Movie Dub Workflow

This repository now has two independent capabilities:

1. The existing LangGraph CLI dubbing workflow.
2. A FastAPI media capability layer with a pure HTML console.

The media API is intentionally separate from the existing LangGraph CLI graph.

## Python Environment

Use the local venv:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install dependencies with `uv` when available, or `pip`:

```powershell
uv pip install -r requirements.txt
```

Fallback:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Docker

Build the API image:

```powershell
docker build -t movie-dub-workflow .
```

Run the FastAPI media console:

```powershell
docker run --rm -p 8000:8000 --env-file .env -v ${PWD}/outputs:/app/outputs movie-dub-workflow
```

Open:

```text
http://127.0.0.1:8000/
```

For GPU ASR/TTS workloads, install a CUDA-enabled PyTorch/WhisperX stack in a derived image and run Docker with the NVIDIA runtime.

## Existing LangGraph CLI

Run:

```powershell
.\.venv\Scripts\python.exe -m src.main
```

Main outputs:

```text
outputs/asr/zh_raw.srt
outputs/cleaned/zh_cleaned.srt
outputs/merged/zh_merged_before_critic.srt
outputs/critic/zh_corrected.srt
outputs/merged/zh_merged_after_critic.srt
outputs/translated/en_translated.srt
outputs/final/en_final.srt
outputs/tts_segments/*.mp3
outputs/audio/narration_en.wav
outputs/audio/narration_en.mp3
outputs/reports/pipeline_report.json
```

## FastAPI Media Layer

Start the API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn src.api.app:app --reload
```

Open the pure HTML console:

```text
http://127.0.0.1:8000/
```

Health check:

```text
GET /health
```

Available media endpoints:

```text
POST /api/jobs
GET  /api/jobs/{job_id}
GET  /api/jobs/{job_id}/files
GET  /api/jobs/{job_id}/files/download?path=<relative_path>
POST /api/jobs/{job_id}/open-workdir
GET  /api/jobs/{job_id}/media/probe
POST /api/jobs/{job_id}/media/extract-audio
POST /api/jobs/{job_id}/audio/separate
POST /api/jobs/{job_id}/audio/background
POST /api/jobs/{job_id}/speakers/identify
POST /api/jobs/{job_id}/workflow/langgraph
POST /api/jobs/{job_id}/video/package
```

Jobs are stored under:

```text
outputs/jobs/<job_id>/
```

## Media Policy

- MP4 and MP3 uploads are supported by the API.
- FFmpeg is resolved from `config.yaml`, then local `ffmpeg/bin`, then system `PATH`.
- Background audio comes only from separation output.
- Original Chinese narration is not treated as background audio.
- The Web/job LangGraph workflow uses the current job's separated `vocals.wav`.
- The Web/job LangGraph workflow does not silently use mock ASR by default. Install `faster-whisper`, configure a real ASR provider, or set `workflow.allow_mock_asr_for_jobs: true` only for tests.
- The translation node does not silently use template fallback by default. Configure `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL` in `.env`; set `translation.allow_mock_fallback: true` only for tests.
- Video packaging copies the original video stream and replaces the audio stream.
- This phase does not implement true speaker diarization, subtitle packaging, or real multi-voice dubbing.
