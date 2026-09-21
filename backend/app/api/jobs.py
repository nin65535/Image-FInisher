from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.app.services.folder_scan import scan_folder


router = APIRouter(prefix="/jobs", tags=["jobs"])


class TestJobRequest(BaseModel):
    input_folder: str = Field(min_length=1)
    enabled_steps: list[str] = Field(default_factory=lambda: ["rename", "upscale", "mosaic"])
    settings: dict[str, Any] = Field(default_factory=dict)


@router.post("/test", status_code=status.HTTP_201_CREATED)
async def create_test_job(request: Request, body: TestJobRequest) -> dict[str, Any]:
    scan = scan_folder(Path(body.input_folder), app_root=request.app.state.app_root)
    if not scan.can_start:
        raise HTTPException(status_code=409, detail="事前検証に失敗したためジョブを登録できません。")
    allowed = {"rename", "upscale", "mosaic"}
    if not body.enabled_steps or any(step not in allowed for step in body.enabled_steps):
        raise HTTPException(status_code=422, detail="有効工程の指定が不正です。")
    settings = {**body.settings, "_test_job": True}
    return await request.app.state.job_manager.enqueue(scan, list(dict.fromkeys(body.enabled_steps)), settings)


class RenameJobRequest(BaseModel):
    input_folder: str = Field(min_length=1)


class MosaicJobRequest(RenameJobRequest):
    mosaic_strength: int


class PipelineJobRequest(RenameJobRequest):
    rename: bool = True
    upscale: bool = True
    mosaic: bool = False
    mosaic_strength: int | None = None


@router.post("/pipeline", status_code=status.HTTP_201_CREATED)
async def create_pipeline_job(request: Request, body: PipelineJobRequest) -> dict[str, Any]:
    scan = scan_folder(Path(body.input_folder), app_root=request.app.state.app_root)
    if not scan.can_start:
        raise HTTPException(status_code=409, detail="事前検証に失敗したためジョブを登録できません。")
    enabled = [name for name, selected in (("rename", body.rename), ("upscale", body.upscale), ("mosaic", body.mosaic)) if selected]
    if not enabled:
        raise HTTPException(status_code=422, detail="工程を1つ以上有効にしてください。")
    settings: dict[str, Any] = {}
    if body.upscale:
        settings.update({"model": "RealESRGAN_x4plus_anime_6B", "model_scale": 4, "lanczos_scale": 0.5})
    if body.mosaic:
        try:
            strength = request.app.state.mosaic_config.validate_strength(body.mosaic_strength)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        settings.update({"mosaic_strength": strength, "workflow": "AutoMosaic"})
        request.app.state.personal_settings.save_mosaic_strength(strength)
    return await request.app.state.job_manager.enqueue(scan, enabled, settings)


@router.post("/rename", status_code=status.HTTP_201_CREATED)
async def create_rename_job(request: Request, body: RenameJobRequest) -> dict[str, Any]:
    scan = scan_folder(Path(body.input_folder), app_root=request.app.state.app_root)
    if not scan.can_start:
        raise HTTPException(status_code=409, detail="事前検証に失敗したためジョブを登録できません。")
    return await request.app.state.job_manager.enqueue(scan, ["rename"], {})


@router.post("/upscale", status_code=status.HTTP_201_CREATED)
async def create_upscale_job(request: Request, body: RenameJobRequest) -> dict[str, Any]:
    scan = scan_folder(Path(body.input_folder), app_root=request.app.state.app_root)
    if not scan.can_start:
        raise HTTPException(status_code=409, detail="事前検証に失敗したためジョブを登録できません。")
    return await request.app.state.job_manager.enqueue(
        scan, ["rename", "upscale"],
        {"model": "RealESRGAN_x4plus_anime_6B", "model_scale": 4, "lanczos_scale": 0.5},
    )


@router.get("/mosaic/settings")
def get_mosaic_settings(request: Request) -> dict[str, int | None]:
    config = request.app.state.mosaic_config
    value = request.app.state.personal_settings.mosaic_strength()
    try:
        config.validate_strength(value)
    except Exception:
        value = config.default
    return {"value": value, "minimum": config.minimum, "maximum": config.maximum, "default": config.default}


@router.post("/mosaic", status_code=status.HTTP_201_CREATED)
async def create_mosaic_job(request: Request, body: MosaicJobRequest) -> dict[str, Any]:
    scan = scan_folder(Path(body.input_folder), app_root=request.app.state.app_root)
    if not scan.can_start:
        raise HTTPException(status_code=409, detail="事前検証に失敗したためジョブを登録できません。")
    try:
        strength = request.app.state.mosaic_config.validate_strength(body.mosaic_strength)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    request.app.state.personal_settings.save_mosaic_strength(strength)
    return await request.app.state.job_manager.enqueue(
        scan, ["rename", "mosaic"], {"mosaic_strength": strength, "workflow": "AutoMosaic"},
    )


@router.get("")
def list_jobs(request: Request) -> list[dict[str, Any]]:
    return request.app.state.job_store.list()


@router.get("/{job_id}")
def get_job(request: Request, job_id: str) -> dict[str, Any]:
    job = request.app.state.job_store.snapshot(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません。")
    return job


@router.get("/{job_id}/events")
def job_events(request: Request, job_id: str) -> StreamingResponse:
    if request.app.state.job_store.status(job_id) is None:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません。")
    return StreamingResponse(request.app.state.job_manager.events(job_id), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.post("/{job_id}/cancel")
async def cancel_job(request: Request, job_id: str) -> dict[str, Any]:
    if request.app.state.job_store.status(job_id) is None:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません。")
    if not await request.app.state.job_manager.cancel(job_id):
        raise HTTPException(status_code=409, detail="この状態のジョブはキャンセルできません。")
    return request.app.state.job_store.snapshot(job_id)


@router.post("/{job_id}/retry")
async def retry_failed_images(request: Request, job_id: str) -> dict[str, Any]:
    if request.app.state.job_store.status(job_id) is None:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません。")
    job = await request.app.state.job_manager.retry_failed(job_id)
    if job is None:
        raise HTTPException(status_code=409, detail="再実行できる失敗画像がありません。")
    return job


@router.post("/{job_id}/open-output")
def open_output_folder(request: Request, job_id: str) -> dict[str, str]:
    job = request.app.state.job_store.snapshot(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません。")
    folder = Path(job["output_folder"])
    if not folder.is_dir():
        raise HTTPException(status_code=409, detail="完成フォルダがまだ存在しません。")
    try:
        import os
        os.startfile(folder)  # type: ignore[attr-defined]
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"完成フォルダを開けません: {exc}") from exc
    return {"path": str(folder)}


@router.delete("")
def clear_history(request: Request) -> dict[str, int]:
    return {"deleted_count": request.app.state.job_store.clear_terminal()}
