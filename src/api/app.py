from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse

from src.api.routes import router
from src.api.schemas import HealthResponse
from src.config import load_config
from src.llm_client import load_dotenv_if_present


def create_app() -> FastAPI:
    load_dotenv_if_present()
    app = FastAPI(title="Movie Dub Workflow Media API")
    app.state.config = load_config("config.yaml")
    app.include_router(router)

    @app.get("/health", response_model=HealthResponse)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def index() -> FileResponse:
        return FileResponse(Path("web") / "index.html")

    return app


app = create_app()
