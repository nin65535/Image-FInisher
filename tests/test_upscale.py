import time
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from backend.app.main import create_app
from backend.app.services.upscale import UpscaleConfig


class FakeUpscaleClient:
    def __init__(self, *, wrong_size: bool = False) -> None:
        self.config = UpscaleConfig(Path("unused"), "1", "image", "4", "filename_prefix", "ImageFinisher/upscale", 10)
        self.wrong_size = wrong_size
        self.prefixes: list[str] = []

    def upscale(self, source: Path, destination: Path, output_prefix: str) -> None:
        self.prefixes.append(output_prefix)
        with Image.open(source) as image:
            size = image.size if self.wrong_size else (image.width * 2, image.height * 2)
            image.resize(size, Image.Resampling.LANCZOS).save(destination, format="PNG")


def _wait(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_upscale_job_outputs_exact_double_dimensions_for_mixed_aspect_ratios(tmp_path: Path) -> None:
    inputs = tmp_path / "input"
    inputs.mkdir()
    Image.new("RGB", (8, 8), "red").save(inputs / "square_1_.png")
    Image.new("RGB", (7, 11), "blue").save(inputs / "portrait_1_.png")
    originals = {path.name: path.read_bytes() for path in inputs.iterdir()}
    fake = FakeUpscaleClient()
    app = create_app(frontend_dist=Path("missing"), data_dir=tmp_path / "data", upscale_client=fake)  # type: ignore[arg-type]

    with TestClient(app) as client:
        created = client.post("/api/jobs/upscale", json={"input_folder": str(inputs)})
        assert created.status_code == 201
        job = _wait(client, created.json()["id"])

    assert job["status"] == "completed"
    assert job["enabled_steps"] == ["rename", "upscale"]
    expected = {"square_0001.png": (16, 16), "portrait_0001.png": (14, 22)}
    for name, size in expected.items():
        with Image.open(tmp_path / "finished" / name) as image:
            assert image.size == size
    assert {path.name: path.read_bytes() for path in inputs.iterdir()} == originals
    assert len(fake.prefixes) == 2
    assert not (tmp_path / ".imagefinisher-tmp").exists()


def test_upscale_dimension_mismatch_fails_without_committing_output(tmp_path: Path) -> None:
    inputs = tmp_path / "input"
    inputs.mkdir()
    Image.new("RGB", (9, 5), "green").save(inputs / "scene_1_.png")
    app = create_app(frontend_dist=Path("missing"), data_dir=tmp_path / "data",
                     upscale_client=FakeUpscaleClient(wrong_size=True))  # type: ignore[arg-type]

    with TestClient(app) as client:
        created = client.post("/api/jobs/upscale", json={"input_folder": str(inputs)})
        job = _wait(client, created.json()["id"])

    assert job["status"] == "failed"
    assert "expected=18x10" in job["images"][0]["error"]
    assert not (tmp_path / "finished" / "scene_0001.png").exists()
    assert job["images"][0]["steps"][1]["status"] == "failed"
