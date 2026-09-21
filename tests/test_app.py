from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.api.lifecycle import router as lifecycle_router
from backend.app.main import create_app


def test_health_check(tmp_path: Path) -> None:
    with TestClient(create_app(frontend_dist=Path("missing"), data_dir=tmp_path)) as client:
        response = client.get("/api/health", headers={"X-Request-ID": "test-request"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "application": "image-finisher"}
    assert response.headers["X-Request-ID"] == "test-request"


def test_unknown_api_uses_common_error_response(tmp_path: Path) -> None:
    with TestClient(create_app(frontend_dist=Path("missing"), data_dir=tmp_path)) as client:
        response = client.get("/api/missing")
    assert response.status_code == 404
    body = response.json()["error"]
    assert body["code"] == "http_404"
    assert body["message"] == "API route not found: /api/missing"
    assert body["details"] is None
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_built_frontend_is_served(tmp_path: Path) -> None:
    dist = Path(__file__).parent / "fixtures" / "frontend_dist"
    with TestClient(create_app(frontend_dist=dist, data_dir=tmp_path)) as client:
        response = client.get("/some/client/route")
    assert response.status_code == 200
    assert "Image Finisher" in response.text


def test_lifecycle_stream_route_is_registered(tmp_path: Path) -> None:
    app = create_app(frontend_dist=Path("missing"), data_dir=tmp_path)
    assert any(
        getattr(route, "original_router", None) is lifecycle_router
        and route.include_context.prefix == "/api"
        for route in app.routes
    )
