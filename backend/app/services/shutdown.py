import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable

from backend.app.services.jobs import JobStore


ShutdownCallback = Callable[[], None | Awaitable[None]]


class ShutdownService:
    """ブラウザ接続終了後、実行中ジョブを保護しつつサーバーを停止する。"""

    def __init__(
        self,
        store: JobStore,
        request_shutdown: ShutdownCallback,
        grace_seconds: float = 10.0,
        poll_seconds: float = 0.25,
    ) -> None:
        self.store = store
        self.request_shutdown = request_shutdown
        self.grace_seconds = grace_seconds
        self.poll_seconds = poll_seconds
        self.connection_count = 0
        self.shutdown_triggered = False
        self._disconnected_at = 0.0
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self._disconnected_at = time.monotonic()
        self._task = asyncio.create_task(self._monitor(), name="shutdown-monitor")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def connected(self) -> None:
        async with self._lock:
            self.connection_count += 1
            self._disconnected_at = 0.0

    async def disconnected(self) -> None:
        async with self._lock:
            self.connection_count = max(0, self.connection_count - 1)
            if self.connection_count == 0:
                self._disconnected_at = time.monotonic()

    async def evaluate(self) -> None:
        async with self._lock:
            if self.shutdown_triggered or self.connection_count > 0:
                return
            if self._disconnected_at == 0.0:
                self._disconnected_at = time.monotonic()
            if time.monotonic() - self._disconnected_at < self.grace_seconds:
                return
            if self.store.has_active_jobs():
                return
            self.shutdown_triggered = True

        result = self.request_shutdown()
        if inspect.isawaitable(result):
            await result

    async def _monitor(self) -> None:
        while True:
            await asyncio.sleep(self.poll_seconds)
            await self.evaluate()
