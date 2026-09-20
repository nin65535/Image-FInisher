import time
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from backend.app.main import create_app
from backend.app.services.folder_scan import scan_folder
from backend.app.services.jobs import JobStore


def _save(path: Path, color: str, size: tuple[int, int] = (11, 7)) -> bytes:
    Image.new("RGB", size, color).save(path)
    return path.read_bytes()


def _wait_for_terminal(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.01)
    raise AssertionError("job did not reach a terminal state")


def test_rename_job_keeps_originals_and_commits_multiple_groups(tmp_path: Path) -> None:
    input_folder = tmp_path / "input"
    input_folder.mkdir()
    originals = {
        "alpha_9_.png": _save(input_folder / "alpha_9_.png", "red"),
        "alpha_20_.png": _save(input_folder / "alpha_20_.png", "green"),
        "beta_1_.png": _save(input_folder / "beta_1_.png", "blue", (5, 13)),
    }
    app = create_app(frontend_dist=Path("missing"), data_dir=tmp_path / "data")

    with TestClient(app) as client:
        response = client.post("/api/jobs/rename", json={"input_folder": str(input_folder)})
        assert response.status_code == 201
        job = _wait_for_terminal(client, response.json()["id"])

    assert job["status"] == "completed"
    assert job["counts"]["completed"] == 3
    assert [path.name for path in sorted((tmp_path / "finished").iterdir())] == [
        "alpha_0001.png", "alpha_0002.png", "beta_0001.png"
    ]
    assert {name: (input_folder / name).read_bytes() for name in originals} == originals
    assert not (tmp_path / ".imagefinisher-tmp").exists()
    assert all(image["validation_result"] for image in job["images"])


def test_existing_output_is_never_overwritten_and_failed_image_can_retry(tmp_path: Path) -> None:
    input_folder = tmp_path / "input"
    input_folder.mkdir()
    _save(input_folder / "scene_1_.png", "navy")
    scan = scan_folder(input_folder, app_root=tmp_path / "app")
    store = JobStore(tmp_path / "data" / "jobs.sqlite3")
    store._initialize()
    job_id = store.create(scan, ["rename"], {})
    image_id = store.image_ids(job_id)[0]
    output = tmp_path / "finished" / "scene_0001.png"
    output.parent.mkdir()
    protected = _save(output, "yellow")

    store.run_rename_image(job_id, image_id)
    failed = store.snapshot(job_id)
    assert failed is not None
    assert failed["images"][0]["status"] == "failed"
    assert output.read_bytes() == protected

    store.set_job_status(job_id, "failed")
    output.unlink()
    assert store.prepare_failed_retry(job_id)
    assert store.snapshot(job_id)["images"][0]["retry_count"] == 1
    store.run_rename_image(job_id, image_id)
    retried = store.snapshot(job_id)
    assert retried is not None
    assert retried["images"][0]["status"] == "completed"
    assert output.is_file()


def test_retry_api_preserves_successful_outputs(tmp_path: Path) -> None:
    input_folder = tmp_path / "input"
    input_folder.mkdir()
    _save(input_folder / "scene_1_.png", "red")
    _save(input_folder / "scene_2_.png", "blue")
    app = create_app(frontend_dist=Path("missing"), data_dir=tmp_path / "data")

    with TestClient(app) as client:
        created = client.post("/api/jobs/rename", json={"input_folder": str(input_folder)})
        job = _wait_for_terminal(client, created.json()["id"])
        first_output = Path(job["images"][0]["output_path"])
        first_bytes = first_output.read_bytes()

        store = app.state.job_store
        second = job["images"][1]
        Path(second["output_path"]).unlink()
        with store._connect() as db:
            db.execute("UPDATE jobs SET status='failed' WHERE id=?", (job["id"],))
            db.execute("UPDATE images SET status='failed', error='simulated' WHERE id=?", (second["id"],))
            db.execute("UPDATE image_steps SET status='failed', error='simulated' WHERE image_id=?", (second["id"],))

        retried = client.post(f"/api/jobs/{job['id']}/retry")
        assert retried.status_code == 200
        final = _wait_for_terminal(client, job["id"])

    assert final["status"] == "completed"
    assert final["images"][0]["retry_count"] == 0
    assert final["images"][1]["retry_count"] == 1
    assert first_output.read_bytes() == first_bytes
