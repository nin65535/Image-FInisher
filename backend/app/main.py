from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.health import router as health_router
from backend.app.core.errors import register_exception_handlers
from backend.app.core.logging import configure_logging, register_request_logging


def create_app(frontend_dist: Path | None = None) -> FastAPI:
    app = FastAPI(title="Image Finisher API", version="0.1.0")
    logger = configure_logging()
    app.state.logger = logger
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
