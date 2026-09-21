import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from backend.app.main import create_app
from backend.app.services.mosaic import MosaicConfig
from backend.app.services.upscale import UpscaleConfig


class FakeUpscale:
    def __init__(self, started: threading.Event | None = None, release: threading.Event | None = None) -> None:
        self.config = UpscaleConfig(Path("unused"), "1", "image", "4", "prefix", "ImageFinisher/upscale", 10)
        self.started, self.release = started, release

    def upscale(self, source: Path, destination: Path, output_prefix: str) -> None:
        if self.started:
            self.started.set()
        if self.release:
            assert self.release.wait(2)
        with Image.open(source) as image:
            image.resize((image.width * 2, image.height * 2), Image.Resampling.LANCZOS).save(destination, "PNG")


class FakeMosaic:
    def __init__(self, fail: bool = False) -> None:
        self.config = MosaicConfig(Path("unused"), "2", "image", "1", "factor", "3", "prefix",
                                   "ImageFinisher/mosaic", 10, 10, None, 200)
        self.fail = fail
        self.sizes: list[tuple[int, int]] = []

    def mosaic(self, source: Path, destination: Path, output_prefix: str, strength: int) -> None:
        if self.fail:
            raise RuntimeError("mosaic failed")
        with Image.open(source) as image:
            self.sizes.append(image.size)
            image.save(destination, "PNG")


def _inputs(root: Path, count: int = 1) -> Path:
    folder = root / "input"
    folder.mkdir()
    for index in range(1, count + 1):
        Image.new("RGB", (7, 5), "navy").save(folder / f"scene_{index}_.png")
    return folder


def _wait(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_pipeline_runs_fixed_order_and_commits_only_final_image(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    mosaic = FakeMosaic()
    app = create_app(Path("missing"), tmp_path / "data", FakeUpscale(), mosaic)  # type: ignore[arg-type]
    with TestClient(app) as client:
        response = client.post("/api/jobs/pipeline", json={
            "input_folder": str(inputs), "rename": True, "upscale": True,
            "mosaic": True, "mosaic_strength": 150,
        })
        assert response.status_code == 201
        job = _wait(client, response.json()["id"])
    assert job["status"] == "completed"
    assert job["enabled_steps"] == ["rename", "upscale", "mosaic"]
    assert [step["status"] for step in job["images"][0]["steps"]] == ["completed"] * 3
    assert mosaic.sizes == [(14, 10)]
    with Image.open(tmp_path / "finished" / "scene_0001.png") as image:
        assert image.size == (14, 10)
    assert not (tmp_path / ".imagefinisher-tmp").exists()


def test_pipeline_failure_does_not_commit_intermediate_image(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    app = create_app(Path("missing"), tmp_path / "data", FakeUpscale(), FakeMosaic(fail=True))  # type: ignore[arg-type]
    with TestClient(app) as client:
        response = client.post("/api/jobs/pipeline", json={
            "input_folder": str(inputs), "rename": True, "upscale": True,
            "mosaic": True, "mosaic_strength": 200,
        })
        job = _wait(client, response.json()["id"])
    assert job["status"] == "failed"
    assert [step["status"] for step in job["images"][0]["steps"]] == ["completed", "completed", "failed"]
    assert not (tmp_path / "finished" / "scene_0001.png").exists()


def test_cancel_finishes_current_image_then_cancels_remaining_images(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, 2)
    started, release = threading.Event(), threading.Event()
    app = create_app(Path("missing"), tmp_path / "data", FakeUpscale(started, release), FakeMosaic())  # type: ignore[arg-type]
    with TestClient(app) as client:
        response = client.post("/api/jobs/pipeline", json={
            "input_folder": str(inputs), "rename": True, "upscale": True, "mosaic": False,
        })
        job_id = response.json()["id"]
        assert started.wait(2)
        assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 200
        release.set()
        job = _wait(client, job_id)
    assert job["status"] == "cancelled"
    assert [image["status"] for image in job["images"]] == ["completed", "cancelled"]
    assert (tmp_path / "finished" / "scene_0001.png").is_file()
    assert not (tmp_path / "finished" / "scene_0002.png").exists()
