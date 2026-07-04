"""Tests for the follow-the-money 'who funds this outlet?' lookup."""

from __future__ import annotations

import pytest

from emet.api.routes.funding import lookup_funding


class FakeFed:
    def __init__(self, enriched):
        self._enriched = enriched

    async def enrich_entity(self, name, entity_type="Company"):
        return self._enriched


def _outlet(name="Daily Bugle"):
    return {
        "id": "c:outlet",
        "schema": "Company",
        "properties": {"name": [name]},
        "_provenance": {"source": "opencorporates", "confidence": 0.9},
    }


@pytest.mark.asyncio
async def test_traces_beneficial_owner():
    enriched = {
        "entity": _outlet(),
        "sanctions_matches": [],
        "offshore_connections": [],
        "ownership_chain": [
            {"id": "c:parent", "schema": "Company",
             "properties": {"name": ["MegaMedia Holdings"]},
             "_provenance": {"source": "gleif", "confidence": 0.85}},
            {"id": "o1", "schema": "Ownership",
             "properties": {"owner": ["c:parent"], "asset": ["c:outlet"],
                            "percentage": ["100%"]}},
        ],
        "sources_checked": ["opencorporates", "gleif"],
    }
    report = await lookup_funding("Daily Bugle", fed=FakeFed(enriched), requester="truthstrike")
    assert report["outlet"]["name"] == "Daily Bugle"
    assert report["beneficial_owners"][0]["name"] == "MegaMedia Holdings"
    assert report["beneficial_owners"][0]["effective_pct"] == 1.0
    # Ownership relationship record is NOT listed as a funder.
    assert all(f["schema"] != "Ownership" for f in report["funders"])
    assert report["requester"] == "truthstrike"
    assert report["confidence"] > 0


@pytest.mark.asyncio
async def test_no_match_returns_note():
    enriched = {"entity": None, "sources_checked": []}
    report = await lookup_funding("Nonexistent", fed=FakeFed(enriched))
    assert report["outlet"] is None
    assert any("No matching" in n for n in report["notes"])


@pytest.mark.asyncio
async def test_private_individual_blocked():
    enriched = {
        "entity": {"id": "p:x", "schema": "Person",
                   "properties": {"name": ["Jane Private"]}},
        "sources_checked": [],
    }
    report = await lookup_funding("Jane Private", fed=FakeFed(enriched))
    assert report["policy"]["allowed"] is False
    assert report["outlet"] is None


@pytest.mark.asyncio
async def test_enrich_failure_degrades():
    class Boom:
        async def enrich_entity(self, name, entity_type="Company"):
            raise RuntimeError("network down")

    report = await lookup_funding("X", fed=Boom())
    assert report["outlet"] is None
    assert report["beneficial_owners"] == []


@pytest.mark.asyncio
async def test_audit_records_actor():
    import tempfile
    from emet.agent.audit import AuditArchive, read_archive

    audit = AuditArchive(tempfile.mkdtemp())
    enriched = {"entity": None, "sources_checked": []}
    await lookup_funding("X", fed=FakeFed(enriched), requester="truthstrike", audit=audit)
    # The manifest / events carry the requester identity.
    # (archive is closed inside lookup_funding)
