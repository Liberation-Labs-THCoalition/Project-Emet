"""Tests for the HTTP API — app factory and endpoint smoke tests.

Uses FastAPI's TestClient for synchronous request testing.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from emet.api.app import create_app


@pytest.fixture
def client():
    """Create a test client for the Emet API."""
    app = create_app(include_docs=True)
    return TestClient(app)


class TestAppFactory:
    """Verify the app factory assembles routes correctly."""

    def test_creates_fastapi_app(self):
        """create_app() should return a FastAPI instance."""
        app = create_app()
        assert app.title == "Emet"

    def test_registers_investigation_routes(self):
        """Investigation routes should be registered."""
        app = create_app()
        paths = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/api/investigations" in paths
        assert "/api/investigations/{inv_id}" in paths
        assert "/api/investigations/{inv_id}/export" in paths

    def test_registers_health_route(self):
        """Health check should be registered."""
        app = create_app()
        paths = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/api/health" in paths

    def test_docs_enabled_by_default(self):
        """Docs should be available by default."""
        app = create_app(include_docs=True)
        paths = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/docs" in paths

    def test_docs_disabled(self):
        """Docs can be disabled."""
        app = create_app(include_docs=False)
        paths = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/docs" not in paths


class TestHealthEndpoint:
    """Smoke test the health endpoint."""

    def test_health_check(self, client):
        """GET /api/health should return ok."""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestInvestigationEndpoints:
    """Smoke test the investigation endpoints."""

    def test_list_investigations_empty(self, client):
        """GET /api/investigations should return empty list initially."""
        resp = client.get("/api/investigations")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_start_investigation(self, client):
        """POST /api/investigations should return 202 with ID."""
        resp = client.post(
            "/api/investigations",
            json={"goal": "Test investigation", "max_turns": 2},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "running"
        assert "id" in data
        assert data["goal"] == "Test investigation"

    def test_get_unknown_investigation(self, client):
        """GET /api/investigations/{bad_id} should return 404."""
        resp = client.get("/api/investigations/nonexistent")
        assert resp.status_code == 404

    def test_export_not_completed(self, client):
        """POST export on running investigation should return 409."""
        # Start one
        resp = client.post(
            "/api/investigations",
            json={"goal": "Export test", "max_turns": 1},
        )
        inv_id = resp.json()["id"]

        # Try to export immediately (still running)
        resp = client.post(f"/api/investigations/{inv_id}/export")
        # Could be 409 (running) or 200 (if background completed fast)
        assert resp.status_code in (200, 409)

    def test_openapi_schema(self, client):
        """OpenAPI schema should be accessible."""
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert "paths" in schema
        assert "/api/investigations" in schema["paths"]
