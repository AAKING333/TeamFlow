from __future__ import annotations

from app.extensions import db


def test_health_endpoint_returns_expected_status(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.is_json
    assert response.get_json() == {"status": "ok", "service": "TeamFlow API"}


def test_health_ready_returns_healthy_response_when_database_is_reachable(client):
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["service"] == "TeamFlow API"
    assert payload["checks"]["database"] == "ready"


def test_health_ready_handles_database_failures_safely(client, monkeypatch):
    def raise_runtime_error(*_args, **_kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(db.session, "execute", raise_runtime_error)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    payload = response.get_json()
    assert payload["status"] == "error"
    assert payload["error"] == "database_unavailable"
    assert "Traceback" not in response.get_data(as_text=True)
    assert "database_url" not in response.get_data(as_text=True).lower()


def test_invalid_routes_return_safe_json_error_payload(client):
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    payload = response.get_json()
    assert payload["error"] == "not_found"
    assert "Traceback" not in response.get_data(as_text=True)
    assert "DATABASE_URL" not in response.get_data(as_text=True)
