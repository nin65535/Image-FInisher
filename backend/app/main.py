from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.health import router as health_router
from backend.app.api.folders import router as folders_router
from backend.app.api.jobs import router as jobs_router
from backend.app.core.errors import register_exception_handlers
from backend.app.core.logging import configure_logging, register_request_logging


from backend.app.services.jobs import JobManager, JobStore
from backend.app.services.mosaic import MosaicClient, PersonalSettings, load_mosaic_config
from backend.app.services.upscale import ComfyUIClient, load_upscale_config


def create_app(frontend_dist: Path | None = None, data_dir: Path | None = None,
               upscale_client: ComfyUIClient | None = None,
               mosaic_client: MosaicClient | None = None) -> FastAPI:
    resolved_data = data_dir or Path.home() / "AppData" / "Local" / "ImageFinisher"
    app_root = Path(__file__).resolve().parents[2]
    store = JobStore(resolved_data / "jobs.sqlite3")
    mosaic_config = load_mosaic_config(app_root)
    personal_settings = PersonalSettings(resolved_data / "settings.json", mosaic_config.default)
    manager = JobManager(store, upscale_client or ComfyUIClient(load_upscale_config(app_root)),
                         mosaic_client or MosaicClient(mosaic_config))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await manager.start()
        try:
            yield
        finally:
            await manager.stop()

    app = FastAPI(title="Image Finisher API", version="0.1.0", lifespan=lifespan)
    logger = configure_logging()
    app.state.logger = logger
    app.state.app_root = app_root
    app.state.job_store = store
    app.state.job_manager = manager
    app.state.mosaic_config = mosaic_config
    app.state.personal_settings = personal_settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_request_logging(app, logger)
    register_exception_handlers(app)
    app.include_router(health_router, prefix="/api")
    app.include_router(folders_router, prefix="/api")
    app.include_router(jobs_router, prefix="/api")

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def api_not_found(path: str) -> None:
        raise HTTPException(status_code=404, detail=f"API route not found: /api/{path}")

    resolved_dist = frontend_dist or Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if resolved_dist.is_dir() and (resolved_dist / "index.html").is_file():
        assets = resolved_dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            candidate = (resolved_dist / path).resolve()
            if candidate.is_relative_to(resolved_dist.resolve()) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(resolved_dist / "index.html")

    return app


app = create_app()
