import json
import time
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from backend.app.main import create_app
from backend.app.services.mosaic import MosaicConfig, PersonalSettings


class FakeMosaicClient:
    def __init__(self, *, wrong_size: bool = False) -> None:
        self.config = MosaicConfig(Path("unused"), "2", "image", "1", "factor", "3",
                                   "filename_prefix", "ImageFinisher/mosaic", 10, 10, None, 200)
        self.wrong_size = wrong_size
        self.strengths: list[int] = []

    def mosaic(self, source: Path, destination: Path, output_prefix: str, strength: int) -> None:
        self.strengths.append(strength)
        with Image.open(source) as image:
            size = (image.width + 1, image.height) if self.wrong_size else image.size
            image.resize(size).save(destination, format="PNG")


def _wait(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_mosaic_job_applies_strength_preserves_dimensions_and_saves_setting(tmp_path: Path) -> None:
    inputs = tmp_path / "input"
    inputs.mkdir()
    Image.new("RGB", (9, 5), "purple").save(inputs / "scene_1_.png")
    fake = FakeMosaicClient()
    app = create_app(frontend_dist=Path("missing"), data_dir=tmp_path / "data",
                     mosaic_client=fake)  # type: ignore[arg-type]

    with TestClient(app) as client:
        defaults = client.get("/api/jobs/mosaic/settings")
        assert defaults.json()["value"] == 200
        created = client.post("/api/jobs/mosaic", json={"input_folder": str(inputs), "mosaic_strength": 125})
        assert created.status_code == 201
        job = _wait(client, created.json()["id"])

    assert job["status"] == "completed"
    assert job["enabled_steps"] == ["rename", "mosaic"]
    assert job["settings"]["mosaic_strength"] == 125
    assert fake.strengths == [125]
    with Image.open(tmp_path / "finished" / "scene_0001.png") as output:
        assert output.size == (9, 5)
    assert json.loads((tmp_path / "data" / "settings.json").read_text(encoding="utf-8"))["mosaic_strength"] == 125


def test_mosaic_rejects_strength_below_workflow_minimum(tmp_path: Path) -> None:
    inputs = tmp_path / "input"
    inputs.mkdir()
    Image.new("RGB", (4, 4)).save(inputs / "scene_1_.png")
    app = create_app(frontend_dist=Path("missing"), data_dir=tmp_path / "data",
                     mosaic_client=FakeMosaicClient())  # type: ignore[arg-type]
    with TestClient(app) as client:
        response = client.post("/api/jobs/mosaic", json={"input_folder": str(inputs), "mosaic_strength": 9})
    assert response.status_code == 422
    assert not (tmp_path / "data" / "settings.json").exists()


def test_mosaic_dimension_mismatch_fails_without_output(tmp_path: Path) -> None:
    inputs = tmp_path / "input"
    inputs.mkdir()
    Image.new("RGB", (6, 7)).save(inputs / "scene_1_.png")
    app = create_app(frontend_dist=Path("missing"), data_dir=tmp_path / "data",
                     mosaic_client=FakeMosaicClient(wrong_size=True))  # type: ignore[arg-type]
    with TestClient(app) as client:
        created = client.post("/api/jobs/mosaic", json={"input_folder": str(inputs), "mosaic_strength": 200})
        job = _wait(client, created.json()["id"])
    assert job["status"] == "failed"
    assert "expected=6x7" in job["images"][0]["error"]
    assert not (tmp_path / "finished" / "scene_0001.png").exists()


def test_personal_setting_is_restored(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    settings = PersonalSettings(path, 200)
    settings.save_mosaic_strength(333)
    assert PersonalSettings(path, 200).mosaic_strength() == 333
