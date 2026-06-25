# Vue TypeScript Frontend Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-file HTML media console with a Vue 3 + TypeScript Vite app while preserving current API workflows.

**Architecture:** The Vite app lives in `web/`, compiles to `web/dist`, and talks to existing FastAPI endpoints. FastAPI serves built assets when present and falls back to the Vite shell for local development.

**Tech Stack:** Vue 3, TypeScript, Vite, FastAPI static files, Docker, Python unittest.

---

## File Structure

- Create `web/package.json`, `web/tsconfig.json`, `web/tsconfig.node.json`, and `web/vite.config.ts` for the frontend toolchain.
- Replace `web/index.html` with a Vite root shell.
- Create `web/src/main.ts`, `web/src/App.vue`, `web/src/styles.css`.
- Create `web/src/types/api.ts` for browser API contracts.
- Create `web/src/api/client.ts` for request, upload, stream, and download helpers.
- Create `web/src/composables/useJobs.ts` and `web/src/composables/useWorkflow.ts` for stateful behavior.
- Create focused components in `web/src/components/`.
- Modify `src/api/app.py` to serve `web/dist` assets when available.
- Modify `Dockerfile` to build the Vue app before running FastAPI.
- Create `tests/test_unit_api_static_app.py` for static-root selection behavior.

### Task 1: Static Serving Test and App Hook

**Files:**
- Create: `tests/test_unit_api_static_app.py`
- Modify: `src/api/app.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from src.api.app import select_frontend_index


def test_select_frontend_index_prefers_built_dist(tmp_path: Path) -> None:
    web_dir = tmp_path / "web"
    dist_dir = web_dir / "dist"
    dist_dir.mkdir(parents=True)
    source_index = web_dir / "index.html"
    built_index = dist_dir / "index.html"
    source_index.write_text("source", encoding="utf-8")
    built_index.write_text("built", encoding="utf-8")

    assert select_frontend_index(web_dir) == built_index


def test_select_frontend_index_falls_back_to_source_shell(tmp_path: Path) -> None:
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    source_index = web_dir / "index.html"
    source_index.write_text("source", encoding="utf-8")

    assert select_frontend_index(web_dir) == source_index
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_unit_api_static_app`

Expected: FAIL because `select_frontend_index` is not defined.

- [ ] **Step 3: Write minimal implementation**

Add `select_frontend_index(web_dir: Path) -> Path` to `src/api/app.py`, mount `/assets` from `web/dist/assets` if present, and return the selected index from `/`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_unit_api_static_app`

Expected: PASS.

### Task 2: Vite Vue Toolchain

**Files:**
- Create: `web/package.json`
- Create: `web/tsconfig.json`
- Create: `web/tsconfig.node.json`
- Create: `web/vite.config.ts`
- Replace: `web/index.html`

- [ ] **Step 1: Create toolchain files**

Create Vue 3 + TypeScript Vite scripts: `dev`, `build`, `preview`, and `typecheck`. Configure the dev server to proxy `/api` and `/health` to `http://127.0.0.1:8000`.

- [ ] **Step 2: Verify dependency install**

Run: `npm --prefix web install`

Expected: `web/package-lock.json` is created and dependencies install successfully.

### Task 3: Typed API Layer

**Files:**
- Create: `web/src/types/api.ts`
- Create: `web/src/api/client.ts`

- [ ] **Step 1: Implement API types**

Define `Job`, `JobFile`, `WorkflowEvent`, `WorkflowOverrides`, and response types used by the console.

- [ ] **Step 2: Implement API client**

Implement helpers for `apiBase`, `requestJson`, `uploadJob`, `postJson`, `streamEvents`, `downloadUrl`, and artifact download URL creation.

### Task 4: Vue State Composables

**Files:**
- Create: `web/src/composables/useJobs.ts`
- Create: `web/src/composables/useWorkflow.ts`

- [ ] **Step 1: Implement job state**

Move selected job, file list, messages, output JSON, health check, upload, refresh, job picker, media operations, package video, artifact download, and open-directory behavior into `useJobs`.

- [ ] **Step 2: Implement workflow state**

Move preprocessing stream, LangGraph stream, resume stream, workflow steps, log rendering, settings, and speaker profile helpers into `useWorkflow`.

### Task 5: Vue Components and Styling

**Files:**
- Create: `web/src/components/AppHeader.vue`
- Create: `web/src/components/UploadPanel.vue`
- Create: `web/src/components/JobSummary.vue`
- Create: `web/src/components/OperationPanel.vue`
- Create: `web/src/components/WorkflowPanel.vue`
- Create: `web/src/components/FileList.vue`
- Create: `web/src/components/OutputPanel.vue`
- Create: `web/src/components/JobPickerModal.vue`
- Create: `web/src/components/WorkflowSettingsModal.vue`
- Create: `web/src/App.vue`
- Create: `web/src/main.ts`
- Create: `web/src/styles.css`

- [ ] **Step 1: Build component shell**

Compose the existing console layout with Vue components and props/events.

- [ ] **Step 2: Wire interactions**

Connect buttons, forms, modals, streams, file downloads, and settings to the composables.

- [ ] **Step 3: Apply responsive styles**

Port the current console styling into `styles.css`, preserving dense operational layout and mobile behavior.

### Task 6: Docker Build Integration

**Files:**
- Modify: `Dockerfile`
- Modify: `.dockerignore`

- [ ] **Step 1: Update Dockerfile**

Install Node.js in the image build, run `npm ci` and `npm run build` in `web/`, then keep the existing FastAPI runtime command.

- [ ] **Step 2: Update Docker ignore rules**

Ignore `web/node_modules` and keep `web/dist` available for local builds if present.

### Task 7: Verification and Commit

**Files:**
- All files touched in previous tasks.

- [ ] **Step 1: Run frontend build**

Run: `npm --prefix web run build`

Expected: TypeScript and Vite build succeed, producing `web/dist`.

- [ ] **Step 2: Run backend unit tests**

Run: `.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_unit_*.py"`

Expected: all unit tests pass.

- [ ] **Step 3: Run compileall**

Run: `.\.venv\Scripts\python.exe -m compileall src tests`

Expected: compilation succeeds.

- [ ] **Step 4: Run pytest if installed**

Run: `.\.venv\Scripts\python.exe -m pytest`

Expected: pytest passes, or report if pytest/dependencies are unavailable.

- [ ] **Step 5: Commit scoped changes**

Run: `git add` only for Vue refactor files, FastAPI static serving changes, Docker changes, docs, and tests. Commit with message `Refactor web console to Vue TypeScript`.
