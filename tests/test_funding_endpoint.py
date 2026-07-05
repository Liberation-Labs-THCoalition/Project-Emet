"""Tests for the funding API — "who funds this outlet?" (TruthStrike integration).

Covers the framework-agnostic ``lookup_funding()`` core logic directly
(dependency-injected federation + audit, no network/filesystem needed) and
the HTTP route wiring via FastAPI's TestClient.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from emet.api.app import create_app
from emet.api.routes.funding import lookup_funding
from emet.agent.audit import AuditArchive
from emet.ftm.external.federation import FederatedResult
from emet.security.target_policy import PublicInterestOverride


def _target_entity(schema="Company", provenance=None) -> dict:
    return {
        "id": "target-co",
        "schema": schema,
        "properties": {"name": ["Target Media Co"]},
        "_provenance": provenance or {"source": "opencorporates"},
    }


def _fake_federation(entities, ownership_chain=None, sanctions=None):
    fed = MagicMock()
    fed.search_entity = AsyncMock(return_value=FederatedResult(
        query="Target Media Co", entity_type="Company", entities=entities,
        source_stats={}, errors={}, cache_hits=0, total_time_ms=0, queried_at="",
    ))
    fed.enrich_entity = AsyncMock(return_value={
        "entity": entities[0] if entities else None,
        "sanctions_matches": sanctions or [],
        "offshore_connections": [],
        "ownership_chain": ownership_chain or [],
        "sources_checked": [],
    })
    return fed


class TestLookupFundingCore:
    @pytest.mark.asyncio
    async def test_not_found(self):
        fed = _fake_federation([])
        result = await lookup_funding("Nobody Media", fed)
        assert result["found"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_organization_allowed_with_owners(self):
        owner = {"id": "owner-co", "schema": "Company", "properties": {"name": ["Owner Holdco"]}}
        ownership_rel = {
            "id": "own-1", "schema": "Ownership",
            "properties": {"owner": ["owner-co"], "asset": ["target-co"], "percentage": ["60%"]},
        }
        fed = _fake_federation([_target_entity()], ownership_chain=[owner, ownership_rel])

        result = await lookup_funding("Target Media Co", fed, max_depth=3)

        assert result["found"] is True
        assert result["allowed"] is True
        assert result["target_type"] == "organization"
        assert len(result["owners"]) == 1
        assert result["owners"][0]["entity_id"] == "owner-co"
        assert result["owners"][0]["effective_pct"] == pytest.approx(0.6)
        assert "Owner Holdco" in result["evidence_markdown"]

    @pytest.mark.asyncio
    async def test_private_individual_denied_without_override(self):
        bare_person = {
            "id": "person-1", "schema": "Person",
            "properties": {"name": ["Jane Q. Public"]},
        }
        fed = _fake_federation([bare_person])

        result = await lookup_funding("Jane Q. Public", fed)

        assert result["found"] is True
        assert result["allowed"] is False
        assert result["target_type"] == "unknown"
        fed.enrich_entity.assert_not_awaited()  # denied before enrichment/tracing

    @pytest.mark.asyncio
    async def test_private_individual_allowed_with_override(self):
        bare_person = {
            "id": "person-1", "schema": "Person",
            "properties": {"name": ["Jane Q. Public"]},
        }
        fed = _fake_federation([bare_person])
        override = PublicInterestOverride(reason="Named in a public corruption probe", authorized_by="editor-1")

        result = await lookup_funding("Jane Q. Public", fed, override=override)

        assert result["allowed"] is True
        fed.enrich_entity.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_records_to_audit_trail_with_actor(self, tmp_path):
        fed = _fake_federation([_target_entity()])
        archive = AuditArchive(base_dir=str(tmp_path))
        archive.open("test-funding-session", actor={"id": "truthstrike", "type": "service"})

        await lookup_funding("Target Media Co", fed, audit=archive, requester="truthstrike")

        manifest = archive.close()
        from emet.agent.audit import read_archive
        events = read_archive(manifest.path)
        assert any(e["type"] == "funding_lookup" for e in events)
        assert all(e["actor"]["id"] == "truthstrike" for e in events if e["type"] != "session_start" or True)


class TestFundingRoute:
    @pytest.fixture
    def client(self):
        app = create_app()
        return TestClient(app)

    def test_route_registered(self, client):
        app = create_app()
        paths = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/api/funding/{entity}" in paths
        assert "/api/funding" in paths

    def test_get_funding_success(self, client):
        fed = _fake_federation([_target_entity()])
        with patch("emet.api.routes.funding._get_federation", return_value=fed), \
             patch("emet.api.routes.funding._open_audit") as mock_open_audit:
            mock_open_audit.return_value = MagicMock(record_event=MagicMock(), close=MagicMock())
            resp = client.get("/api/funding/Target Media Co", params={"requester": "truthstrike"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["allowed"] is True
        assert data["entity_id"] == "target-co"

    def test_get_funding_not_found(self, client):
        fed = _fake_federation([])
        with patch("emet.api.routes.funding._get_federation", return_value=fed), \
             patch("emet.api.routes.funding._open_audit") as mock_open_audit:
            mock_open_audit.return_value = MagicMock(record_event=MagicMock(), close=MagicMock())
            resp = client.get("/api/funding/Nobody Media")

        assert resp.status_code == 404

    def test_get_funding_denied_private_individual(self, client):
        bare_person = {"id": "p1", "schema": "Person", "properties": {"name": ["Jane Q. Public"]}}
        fed = _fake_federation([bare_person])
        with patch("emet.api.routes.funding._get_federation", return_value=fed), \
             patch("emet.api.routes.funding._open_audit") as mock_open_audit:
            mock_open_audit.return_value = MagicMock(record_event=MagicMock(), close=MagicMock())
            resp = client.get("/api/funding/Jane Q. Public")

        assert resp.status_code == 403

    def test_post_funding_with_override(self, client):
        bare_person = {"id": "p1", "schema": "Person", "properties": {"name": ["Jane Q. Public"]}}
        fed = _fake_federation([bare_person])
        with patch("emet.api.routes.funding._get_federation", return_value=fed), \
             patch("emet.api.routes.funding._open_audit") as mock_open_audit:
            mock_open_audit.return_value = MagicMock(record_event=MagicMock(), close=MagicMock())
            resp = client.post("/api/funding", json={
                "entity": "Jane Q. Public",
                "requester": "truthstrike",
                "override_reason": "Public corruption probe",
                "override_authorized_by": "editor-1",
            })

        assert resp.status_code == 200
        assert resp.json()["allowed"] is True
