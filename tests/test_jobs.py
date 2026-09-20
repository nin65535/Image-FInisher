import asyncio
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from backend.app.main import create_app
from backend.app.services.folder_scan import scan_folder
from backend.app.services.jobs import JobManager, JobStore


def _input_folder(root: Path, count: int = 2) -> Path:
    folder = root / "input"
    folder.mkdir()
    for number in range(1, count + 1):
        Image.new("RGB", (8, 6), "navy").save(folder / f"scene_{number}_.png")
    return folder


def test_job_api_persists_images_steps_and_clears_terminal_history(tmp_path: Path) -> None:
    input_folder = _input_folder(tmp_path)
    app = create_app(frontend_dist=Path("missing"), data_dir=tmp_path / "data")
    with TestClient(app) as client:
        created = client.post("/api/jobs/test", json={"input_folder": str(input_folder)})
        assert created.status_code == 201
        job_id = created.json()["id"]

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] == "completed":
                break
            time.sleep(0.01)

        assert job["status"] == "completed"
        assert job["processed_count"] == 2
        assert [image["output_name"] for image in job["images"]] == ["scene_0001.png", "scene_0002.png"]
        assert all([step["status"] for step in image["steps"]] == ["completed"] * 3 for image in job["images"])
        assert not (tmp_path / "finished").exists()

        assert client.delete("/api/jobs").json() == {"deleted_count": 1}
        assert client.get("/api/jobs").json() == []


def test_startup_marks_interrupted_job_failed(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    store._initialize()
    scan = scan_folder(_input_folder(tmp_path), app_root=tmp_path / "app")
    job_id = store.create(scan, ["rename"], {})
    store.set_job_status(job_id, "running")
    image_id = store.image_ids(job_id)[0]
    with store._connect() as db:
        db.execute("UPDATE images SET status='running' WHERE id=?", (image_id,))
        db.execute("UPDATE image_steps SET status='running' WHERE image_id=?", (image_id,))

    assert store.recover_interrupted() == 1
    recovered = store.snapshot(job_id)
    assert recovered is not None
    assert recovered["status"] == "failed"
    assert recovered["images"][0]["status"] == "failed"
    assert recovered["images"][0]["steps"][0]["status"] == "failed"


def test_clear_history_keeps_active_jobs(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    store._initialize()
    scan = scan_folder(_input_folder(tmp_path), app_root=tmp_path / "app")
    queued_id = store.create(scan, ["rename"], {})
    completed_id = store.create(scan, ["rename"], {})
    store.set_job_status(completed_id, "completed")

    assert store.clear_terminal() == 1
    assert store.snapshot(queued_id) is not None
    assert store.snapshot(completed_id) is None


def test_sse_starts_with_persisted_snapshot(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    store._initialize()
    scan = scan_folder(_input_folder(tmp_path), app_root=tmp_path / "app")
    job_id = store.create(scan, ["rename"], {})
    manager = JobManager(store)

    async def first_event() -> str:
        events = manager.events(job_id)
        try:
            return await anext(events)
        finally:
            await events.aclose()

    event = asyncio.run(first_event())
    assert event.startswith("event: job\ndata: ")
    payload = json.loads(event.split("data: ", 1)[1])
    assert payload["id"] == job_id
    assert payload["status"] == "queued"
