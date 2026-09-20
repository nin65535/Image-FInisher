from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from backend.app.main import create_app
from backend.app.services.folder_scan import scan_folder


def _png(path: Path, size: tuple[int, int] = (8, 6)) -> None:
    Image.new("RGB", size, "navy").save(path)


def test_scan_plans_sorted_names_per_group_without_writing(tmp_path: Path) -> None:
    input_folder = tmp_path / "input"
    input_folder.mkdir()
    _png(input_folder / "scene_19_.png", (11, 7))
    _png(input_folder / "scene_4_.PNG", (9, 5))
    _png(input_folder / "other_1_.png")
    (input_folder / "notes.txt").write_text("keep", encoding="utf-8")
    (input_folder / "nested").mkdir()

    before = sorted(path.relative_to(input_folder) for path in input_folder.rglob("*"))
    result = scan_folder(input_folder, app_root=tmp_path / "application")
    after = sorted(path.relative_to(input_folder) for path in input_folder.rglob("*"))

    assert result.can_start is True
    assert result.target_count == 3
    assert result.excluded_count == 2
    assert [(group.name, group.count) for group in result.groups] == [("other", 1), ("scene", 2)]
    assert [(image.source_name, image.output_name) for image in result.images] == [
        ("other_1_.png", "other_0001.png"),
        ("scene_19_.png", "scene_0001.png"),
        ("scene_4_.PNG", "scene_0002.png"),
    ]
    assert result.images[1].width == 11
    assert result.images[1].height == 7
    assert not (tmp_path / "finished").exists()
    assert before == after


def test_scan_collects_filename_decode_and_collision_errors(tmp_path: Path) -> None:
    input_folder = tmp_path / "input"
    output_folder = tmp_path / "finished"
    input_folder.mkdir()
    output_folder.mkdir()
    _png(input_folder / "valid_1_.png")
    _png(input_folder / "bad.png")
    (input_folder / "broken_2_.png").write_bytes(b"not a png")
    _png(output_folder / "valid_0001.png")

    result = scan_folder(input_folder, app_root=tmp_path / "application")
    codes = {error.code for error in result.errors}

    assert result.can_start is False
    assert {"invalid_filename", "unreadable_png", "output_exists"} <= codes


def test_scan_detects_case_insensitive_duplicate_output(tmp_path: Path) -> None:
    input_folder = tmp_path / "input"
    input_folder.mkdir()
    _png(input_folder / "Group_1_.png")
    _png(input_folder / "group_2_.png")

    result = scan_folder(input_folder, app_root=tmp_path / "application")

    assert "duplicate_output" in {error.code for error in result.errors}
    assert result.can_start is False


def test_scan_rejects_group_over_limit(tmp_path: Path, monkeypatch) -> None:
    input_folder = tmp_path / "input"
    input_folder.mkdir()
    _png(input_folder / "large_1_.png")
    _png(input_folder / "large_2_.png")
    monkeypatch.setattr("backend.app.services.folder_scan.MAX_GROUP_SIZE", 1)

    result = scan_folder(input_folder, app_root=tmp_path / "application")

    assert "group_too_large" in {error.code for error in result.errors}
    assert result.can_start is False


def test_scan_rejects_app_root_and_empty_folder(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    empty_result = scan_folder(empty, app_root=tmp_path / "application")
    app_result = scan_folder(tmp_path, app_root=tmp_path)

    assert "no_target_png" in {error.code for error in empty_result.errors}
    assert "unsafe_input_path" in {error.code for error in app_result.errors}


def test_scan_api_returns_complete_plan(tmp_path: Path) -> None:
    input_folder = tmp_path / "input"
    input_folder.mkdir()
    _png(input_folder / "sample_123_.png")

    with TestClient(create_app(frontend_dist=Path("missing"))) as client:
        response = client.post("/api/folders/scan", json={"path": str(input_folder)})

    assert response.status_code == 200
    body = response.json()
    assert body["can_start"] is True
    assert body["images"][0]["output_name"] == "sample_0001.png"


def test_folder_select_endpoint_can_be_cancelled(monkeypatch) -> None:
    monkeypatch.setattr("backend.app.api.folders.pick_folder", lambda: None)
    with TestClient(create_app(frontend_dist=Path("missing"))) as client:
        response = client.post("/api/folders/select")
    assert response.status_code == 200
    assert response.json() == {"path": None}
