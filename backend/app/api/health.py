from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel


router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    application: Literal["image-finisher"]


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", application="image-finisher")
