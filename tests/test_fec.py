"""Tests for the FEC campaign-finance adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from emet.ftm.external.fec import (
    FECClient,
    FECConfig,
    candidate_to_ftm,
    committee_to_ftm,
    contribution_to_ftm,
)


class TestConverters:
    def test_candidate_to_ftm(self):
        e = candidate_to_ftm(
            {
                "candidate_id": "P001",
                "name": "SMITH, JANE",
                "office_full": "President",
                "party_full": "Independent",
                "state": "CA",
            }
        )
        assert e["schema"] == "Person"
        assert e["id"] == "fec:candidate:P001"
        assert "Candidate for President" in e["properties"]["position"][0]

    def test_committee_to_ftm(self):
        e = committee_to_ftm(
            {
                "committee_id": "C01",
                "name": "SUPER PAC",
                "committee_type_full": "Super PAC",
                "treasurer_name": "Bob",
            }
        )
        assert e["schema"] == "Organization"
        assert e["id"] == "fec:committee:C01"
        assert "Treasurer: Bob" in e["properties"]["summary"][0]

    def test_org_contribution_emits_payment(self):
        ents = contribution_to_ftm(
            {
                "entity_type": "ORG",
                "contributor_name": "MEGA CORP PAC",
                "committee_id": "C01",
                "sub_id": "S1",
                "contribution_receipt_amount": 5000,
                "contribution_receipt_date": "2026-01-01",
            }
        )
        schemas = [e["schema"] for e in ents]
        assert "Organization" in schemas and "Payment" in schemas
        payment = [e for e in ents if e["schema"] == "Payment"][0]
        assert payment["_relationship"]["beneficiary"] == "fec:committee:C01"
        assert payment["properties"]["amount"] == ["5000"]

    def test_individual_donor_skipped_by_default(self):
        ents = contribution_to_ftm(
            {"entity_type": "IND", "contributor_name": "JOHN DOE", "committee_id": "C01"}
        )
        assert ents == []

    def test_individual_donor_included_when_enabled(self):
        ents = contribution_to_ftm(
            {"entity_type": "IND", "contributor_name": "JOHN DOE",
             "committee_id": "C01", "sub_id": "S2"},
            include_individual=True,
        )
        assert any(e["schema"] == "Person" for e in ents)


class TestClient:
    def test_config_from_env_defaults_demo(self, monkeypatch):
        monkeypatch.delenv("FEC_API_KEY", raising=False)
        assert FECConfig.from_env().api_key == "DEMO_KEY"

    @pytest.mark.asyncio
    async def test_search_entities_ftm_merges(self):
        client = FECClient(FECConfig())
        with patch.object(
            client, "search_candidates_ftm", new=AsyncMock(
                return_value={"entities": [{"id": "fec:candidate:P1", "schema": "Person"}]}
            )
        ), patch.object(
            client, "search_committees_ftm", new=AsyncMock(
                return_value={"entities": [{"id": "fec:committee:C1", "schema": "Organization"}]}
            )
        ):
            result = await client.search_entities_ftm("test")
        assert result["entity_count"] == 2
