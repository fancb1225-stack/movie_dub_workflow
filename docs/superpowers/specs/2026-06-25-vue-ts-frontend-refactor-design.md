# Vue TypeScript Frontend Refactor Design

## Goal

Refactor the current `web/index.html` media console into a maintainable Vue 3 + TypeScript single page app while preserving the existing FastAPI media workflows and keeping the LangGraph CLI flow untouched.

## Scope

The refactor covers only the browser UI and the app/static serving path. It does not add new media processing behavior, does not expose tools to LLMs, and does not modify `src/graph.py`.

## Architecture

The frontend will live under `web/` as a Vite application. Vue owns the browser UI, TypeScript owns the API contracts used by the browser, and FastAPI continues to own `/api/*` and `/health`.

Production FastAPI serving will prefer `web/dist/index.html` and mounted Vite assets. During development, `npm run dev` in `web/` will proxy `/api` and `/health` to the FastAPI server.

## Frontend Structure

- `web/package.json`: npm scripts for dev, build, preview, and type checking.
- `web/vite.config.ts`: Vue plugin, dev server proxy, and build settings.
- `web/index.html`: Vite shell with the Vue mount point.
- `web/src/main.ts`: Vue bootstrap.
- `web/src/App.vue`: top-level layout and workflow composition.
- `web/src/api/client.ts`: JSON, upload, stream, and download helpers.
- `web/src/types/api.ts`: job, file, workflow event, settings, and response types.
- `web/src/composables/useJobs.ts`: selected job, job refresh, upload, list, files, and output state.
- `web/src/composables/useWorkflow.ts`: preprocessing, LangGraph streaming, resume flow, speaker profile settings, and workflow logs.
- `web/src/components/*`: focused Vue components for the header, upload panel, job status, operation controls, files, output, job picker modal, and workflow settings modal.
- `web/src/styles.css`: design tokens and responsive layout derived from the existing console.

## UI Behavior

The Vue app will preserve the current user-facing workflows:

- Configure API base URL and check `/health`.
- Upload MP4/MP3 and create a job.
- Open an existing job from the job list.
- Refresh job status and files.
- Probe media, run preprocessing stream, run/resume LangGraph stream, download artifacts, open job directory, and package video.
- Show messages, JSON output, workflow logs, substep states, file downloads, and speaker voice settings.

The layout remains an operational console rather than a marketing page. The design should be dense, scannable, and stable on desktop and mobile.

## FastAPI Serving

`src/api/app.py` will mount built frontend assets when `web/dist` exists. The root route will return `web/dist/index.html` in production, with a fallback to `web/index.html` for local development before the frontend is built.

## Docker

The Docker image will install Node.js, build the Vite frontend during image build, then run the existing FastAPI command. Compose continues to expose port `8000`, load `.env`, and mount `outputs`.

## Testing

Backend tests will cover the static-root selection behavior without requiring a browser. Frontend verification will include `npm run build`, which runs TypeScript checking and Vite build. Project verification will include:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_unit_*.py"
.\.venv\Scripts\python.exe -m compileall src tests
```

If frontend dependencies are installed successfully, also run:

```powershell
npm --prefix web run build
```

If pytest dependencies are available, also run:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Non-Goals

- No real multi-role downstream speaker propagation changes.
- No subtitle burn-in or subtitle track packaging.
- No media Prompt additions.
- No ReAct Agent or LLM-based media processing.
- No LangGraph node-order changes.
