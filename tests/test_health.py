from fastapi.testclient import TestClient

from football_intelligence.main import app


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
        dashboard = client.get("/")
        overview = client.get("/api/v1/overview")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert dashboard.status_code == 200
    assert "Touchline Intelligence" in dashboard.text
    assert overview.status_code == 200
    assert "coverage" in overview.json()
