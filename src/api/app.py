from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes import router
from src.api.schemas import HealthResponse
from src.config import load_config
from src.llm_client import load_dotenv_if_present

logging.basicConfig(
    level=logging.ERROR,
    format="%(asctime)s %(levelname)-8s %(name)-20s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def create_app() -> FastAPI:
    load_dotenv_if_present()
    app = FastAPI(title="Movie Dub Workflow Media API")
    app.state.config = load_config("config.yaml")
    app.include_router(router)
    web_dir = Path("web")
    assets_dir = web_dir / "dist" / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/health", response_model=HealthResponse)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def index() -> FileResponse:
        return FileResponse(select_frontend_index(web_dir))

    return app


def select_frontend_index(web_dir: Path) -> Path:
    built_index = web_dir / "dist" / "index.html"
    if built_index.exists():
        return built_index
    return web_dir / "index.html"


app = create_app()
