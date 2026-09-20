from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_health_check() -> None:
    with TestClient(create_app(frontend_dist=Path("missing"))) as client:
        response = client.get("/api/health", headers={"X-Request-ID": "test-request"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "application": "image-finisher"}
    assert response.headers["X-Request-ID"] == "test-request"


def test_unknown_api_uses_common_error_response() -> None:
    with TestClient(create_app(frontend_dist=Path("missing"))) as client:
        response = client.get("/api/missing")
    assert response.status_code == 404
    body = response.json()["error"]
    assert body["code"] == "http_404"
    assert body["message"] == "API route not found: /api/missing"
    assert body["details"] is None
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_built_frontend_is_served() -> None:
    dist = Path(__file__).parent / "fixtures" / "frontend_dist"
    with TestClient(create_app(frontend_dist=dist)) as client:
        response = client.get("/some/client/route")
    assert response.status_code == 200
    assert "Image Finisher" in response.text
