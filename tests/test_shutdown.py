import asyncio
from pathlib import Path

from backend.app.services.jobs import JobStore
from backend.app.services.shutdown import ShutdownService


def test_shutdown_requires_no_browser_and_no_active_job(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = JobStore(tmp_path / "jobs.sqlite3")
        store._initialize()
        calls: list[str] = []
        service = ShutdownService(store, lambda: calls.append("shutdown"), grace_seconds=0)

        await service.connected()
        await service.evaluate()
        assert calls == []

        await service.disconnected()
        await service.evaluate()
        assert calls == ["shutdown"]

    asyncio.run(scenario())


def test_shutdown_waits_for_active_job(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = JobStore(tmp_path / "jobs.sqlite3")
        store._initialize()
        with store._connect() as db:
            db.execute(
                "INSERT INTO jobs VALUES ('job', 'running', 'now', NULL, NULL, 'input', 'output', '[]', '{}', NULL)"
            )
        calls: list[str] = []
        service = ShutdownService(store, lambda: calls.append("shutdown"), grace_seconds=0)

        await service.evaluate()
        assert calls == []

        store.set_job_status("job", "completed")
        await service.evaluate()
        assert calls == ["shutdown"]

    asyncio.run(scenario())
