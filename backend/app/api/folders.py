from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.app.services.folder_picker import pick_folder
from backend.app.services.folder_scan import ScanResult, scan_folder


router = APIRouter(prefix="/folders", tags=["folders"])


class ScanRequest(BaseModel):
    path: str = Field(min_length=1)


class FolderSelection(BaseModel):
    path: str | None


@router.post("/select", response_model=FolderSelection)
def select_folder() -> FolderSelection:
    try:
        return FolderSelection(path=pick_folder())
    except Exception as exc:
        raise HTTPException(status_code=503, detail="フォルダ選択ダイアログを開けませんでした。") from exc


@router.post("/scan", response_model=ScanResult)
def scan(request: Request, body: ScanRequest) -> ScanResult:
    return scan_folder(Path(body.path), app_root=request.app.state.app_root)
