import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse


router = APIRouter(prefix="/lifecycle", tags=["lifecycle"])


@router.get("/events")
def lifecycle_events(request: Request) -> StreamingResponse:
    async def stream():
        shutdown_service = request.app.state.shutdown_service
        if shutdown_service is not None:
            await shutdown_service.connected()
        try:
            yield "event: connected\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                await asyncio.sleep(15)
                yield ": keep-alive\n\n"
        finally:
            if shutdown_service is not None:
                await shutdown_service.disconnected()

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
