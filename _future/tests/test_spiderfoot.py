"""Tests for SpiderFoot OSINT adapter — Sprint 10b.

Tests the SpiderFoot client, FtM converter, event type mapping,
relationship building, and the OSINT recon skill chip.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from emet.ftm.external.spiderfoot import (
    SpiderFootClient,
    SpiderFootConfig,
    SpiderFootFtMConverter,
    EVENT_TYPE_MAP,
    _stable_hash,
    _event_confidence,
    _count_by_schema,
)
from emet.skills.investigation.osint_recon import OSINTReconChip
from emet.skills.base import SkillContext, SkillRequest, SkillDomain


# ===========================================================================
# Configuration
# ===========================================================================


class TestSpiderFootConfig:
    """Test SpiderFoot configuration defaults."""

    def test_defaults(self):
        config = SpiderFootConfig()
        assert config.host == "http://localhost:5001"
        assert config.username == "admin"
        assert config.timeout_seconds == 30.0
        assert config.poll_interval_seconds == 5.0
        assert config.default_scan_type == "passive"

    def test_passive_modules_populated(self):
        config = SpiderFootConfig()
        assert len(config.passive_modules) > 0
        assert "sfp_dnsresolve" in config.passive_modules
        assert "sfp_whois" in config.passive_modules

    def test_custom_config(self):
        config = SpiderFootConfig(
            host="http://sf.internal:5001",
            password="secret",
            timeout_seconds=60.0,
        )
        assert config.host == "http://sf.internal:5001"
        assert config.password == "secret"


# ===========================================================================
# Event type mapping
# ===========================================================================


class TestEventTypeMap:
    """Test SpiderFoot event → FtM schema mapping."""

    def test_all_mappings_have_schema(self):
        for event_type, mapping in EVENT_TYPE_MAP.items():
            assert "schema" in mapping, f"{event_type} missing schema"
            assert "property" in mapping, f"{event_type} missing property"

    def test_core_mappings(self):
        assert EVENT_TYPE_MAP["INTERNET_NAME"]["schema"] == "Domain"
        assert EVENT_TYPE_MAP["EMAILADDR"]["schema"] == "Email"
        assert EVENT_TYPE_MAP["IP_ADDRESS"]["schema"] == "Address"
        assert EVENT_TYPE_MAP["PHONE_NUMBER"]["schema"] == "Phone"
        assert EVENT_TYPE_MAP["HUMAN_NAME"]["schema"] == "Person"
        assert EVENT_TYPE_MAP["COMPANY_NAME"]["schema"] == "Organization"
        assert EVENT_TYPE_MAP["SOCIAL_MEDIA"]["schema"] == "Mention"

    def test_technical_mappings_are_notes(self):
        note_types = [
            "SSL_CERTIFICATE_RAW",
            "DOMAIN_WHOIS",
            "WEBSERVER_BANNER",
            "DATA_BREACH",
            "DARKNET_MENTION_URL",
        ]
        for event_type in note_types:
            assert EVENT_TYPE_MAP[event_type]["schema"] == "Note"
            assert "prefix" in EVENT_TYPE_MAP[event_type]

    def test_affiliate_mappings(self):
        assert EVENT_TYPE_MAP["AFFILIATE_INTERNET_NAME"]["schema"] == "Domain"
        assert EVENT_TYPE_MAP["AFFILIATE_EMAILADDR"]["schema"] == "Email"


# ===========================================================================
# FtM Converter
# ===========================================================================


class TestSpiderFootFtMConverter:
    """Test SpiderFoot event to FtM entity conversion."""

    def setup_method(self):
        self.converter = SpiderFootFtMConverter(scan_target="example.com")

    def test_convert_domain_event(self):
        events = [
            {"type": "INTERNET_NAME", "data": "example.com", "module": "sfp_dnsresolve"},
        ]
        entities = self.converter.convert_events(events)
        assert len(entities) == 1
        entity = entities[0]
        assert entity["schema"] == "Domain"
        assert entity["properties"]["name"] == ["example.com"]
        assert entity["_provenance"]["source"] == "spiderfoot"
        assert entity["_provenance"]["module"] == "sfp_dnsresolve"

    def test_convert_email_event(self):
        events = [
            {"type": "EMAILADDR", "data": "admin@example.com", "module": "sfp_emailformat"},
        ]
        entities = self.converter.convert_events(events)
        assert len(entities) == 1
        assert entities[0]["schema"] == "Email"
        assert entities[0]["properties"]["address"] == ["admin@example.com"]

    def test_convert_person_event(self):
        events = [
            {"type": "HUMAN_NAME", "data": "John Smith", "module": "sfp_fullcontact"},
        ]
        entities = self.converter.convert_events(events)
        assert len(entities) == 1
        assert entities[0]["schema"] == "Person"
        assert entities[0]["properties"]["name"] == ["John Smith"]

    def test_convert_company_event(self):
        events = [
            {"type": "COMPANY_NAME", "data": "Acme Corp", "module": "sfp_whois"},
        ]
        entities = self.converter.convert_events(events)
        assert len(entities) == 1
        assert entities[0]["schema"] == "Organization"
        assert entities[0]["properties"]["name"] == ["Acme Corp"]

    def test_convert_note_with_prefix(self):
        events = [
            {"type": "DATA_BREACH", "data": "LinkedIn 2024", "module": "sfp_haveibeenpwned"},
        ]
        entities = self.converter.convert_events(events)
        assert len(entities) == 1
        assert entities[0]["schema"] == "Note"
        assert entities[0]["properties"]["title"] == ["Data Breach: LinkedIn 2024"]

    def test_convert_deduplicates(self):
        events = [
            {"type": "EMAILADDR", "data": "test@example.com", "module": "sfp_emailformat"},
            {"type": "EMAILADDR", "data": "test@example.com", "module": "sfp_hunter"},
        ]
        entities = self.converter.convert_events(events)
        assert len(entities) == 1  # Same data = same ID = deduplicated

    def test_convert_skips_empty_data(self):
        events = [
            {"type": "EMAILADDR", "data": "", "module": "sfp_emailformat"},
            {"type": "EMAILADDR", "data": "   ", "module": "sfp_emailformat"},
        ]
        entities = self.converter.convert_events(events)
        assert len(entities) == 0

    def test_convert_skips_unknown_types(self):
        events = [
            {"type": "UNKNOWN_EVENT_TYPE_XYZ", "data": "something", "module": "sfp_test"},
        ]
        entities = self.converter.convert_events(events)
        assert len(entities) == 0

    def test_entity_ids_are_stable(self):
        """Same data should produce same ID across invocations."""
        conv1 = SpiderFootFtMConverter()
        conv2 = SpiderFootFtMConverter()
        events = [{"type": "EMAILADDR", "data": "test@example.com", "module": "sfp_test"}]
        e1 = conv1.convert_events(events)
        e2 = conv2.convert_events(events)
        assert e1[0]["id"] == e2[0]["id"]

    def test_provenance_tracking(self):
        events = [
            {
                "type": "INTERNET_NAME",
                "data": "sub.example.com",
                "module": "sfp_dnsbrute",
                "id": "evt-123",
            },
        ]
        entities = self.converter.convert_events(events)
        prov = entities[0]["_provenance"]
        assert prov["source"] == "spiderfoot"
        assert prov["source_id"] == "evt-123"
        assert prov["module"] == "sfp_dnsbrute"
        assert prov["scan_target"] == "example.com"
        assert prov["event_type"] == "INTERNET_NAME"
        assert "retrieved_at" in prov

    def test_multiple_event_types(self):
        events = [
            {"type": "INTERNET_NAME", "data": "example.com", "module": "sfp_dns"},
            {"type": "EMAILADDR", "data": "admin@example.com", "module": "sfp_email"},
            {"type": "HUMAN_NAME", "data": "John Doe", "module": "sfp_fullcontact"},
            {"type": "COMPANY_NAME", "data": "Example Inc", "module": "sfp_whois"},
            {"type": "IP_ADDRESS", "data": "93.184.216.34", "module": "sfp_dns"},
        ]
        entities = self.converter.convert_events(events)
        assert len(entities) == 5
        schemas = {e["schema"] for e in entities}
        assert schemas == {"Domain", "Email", "Person", "Organization", "Address"}

    def test_build_relationships(self):
        entities = [
            {"id": "p1", "schema": "Person", "properties": {"name": ["John"]}},
            {"id": "e1", "schema": "Email", "properties": {"address": ["john@example.com"]}},
            {"id": "d1", "schema": "Domain", "properties": {"name": ["example.com"]}},
            {"id": "o1", "schema": "Organization", "properties": {"name": ["Example Inc"]}},
        ]
        relationships = self.converter.build_relationships(entities)
        assert len(relationships) >= 2  # At least email→person and domain→company

        # Check relationship structure
        for rel in relationships:
            assert "id" in rel
            assert rel["schema"] == "UnknownLink"
            assert "subject" in rel["properties"]
            assert "object" in rel["properties"]
            assert rel["_provenance"]["source"] == "spiderfoot"

    def test_build_relationships_no_persons(self):
        """No person entities = no email relationships."""
        entities = [
            {"id": "e1", "schema": "Email", "properties": {"address": ["test@test.com"]}},
        ]
        relationships = self.converter.build_relationships(entities)
        assert len(relationships) == 0


# ===========================================================================
# Helper functions
# ===========================================================================


class TestHelpers:
    """Test helper functions."""

    def test_stable_hash(self):
        assert _stable_hash("test") == _stable_hash("test")
        assert _stable_hash("a") != _stable_hash("b")
        assert len(_stable_hash("test")) == 12

    def test_event_confidence_levels(self):
        assert _event_confidence("EMAILADDR") == 0.9  # High
        assert _event_confidence("HUMAN_NAME") == 0.7  # Medium
        assert _event_confidence("SOME_UNKNOWN") == 0.5  # Default

    def test_count_by_schema(self):
        entities = [
            {"schema": "Person"},
            {"schema": "Person"},
            {"schema": "Company"},
        ]
        counts = _count_by_schema(entities)
        assert counts == {"Person": 2, "Company": 1}


# ===========================================================================
# SpiderFoot Client (mocked HTTP)
# ===========================================================================


class TestSpiderFootClient:
    """Test SpiderFoot API client with mocked HTTP."""

    def setup_method(self):
        self.client = SpiderFootClient(SpiderFootConfig())

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_get.return_value = mock_resp

            result = await self.client.health_check()
            assert result["status"] == "ok"
            assert result["reachable"] is True

    @pytest.mark.asyncio
    async def test_health_check_unreachable(self):
        with patch("httpx.AsyncClient.get", side_effect=Exception("Connection refused")):
            result = await self.client.health_check()
            assert result["status"] == "error"
            assert result["reachable"] is False

    @pytest.mark.asyncio
    async def test_scan_full_flow(self):
        """Test complete scan flow: start → poll → results → convert."""
        # Mock start scan
        mock_start = MagicMock()
        mock_start.status_code = 200
        mock_start.json.return_value = "scan-001"
        mock_start.raise_for_status = MagicMock()

        # Mock status check
        mock_status = MagicMock()
        mock_status.status_code = 200
        mock_status.json.return_value = {"status": "FINISHED"}
        mock_status.raise_for_status = MagicMock()

        # Mock results
        mock_results = MagicMock()
        mock_results.status_code = 200
        mock_results.json.return_value = [
            {"type": "INTERNET_NAME", "data": "example.com", "module": "sfp_dns", "id": "1"},
            {"type": "EMAILADDR", "data": "admin@example.com", "module": "sfp_email", "id": "2"},
            {"type": "HUMAN_NAME", "data": "John Doe", "module": "sfp_fc", "id": "3"},
        ]
        mock_results.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_start):
            with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
                mock_get.side_effect = [mock_status, mock_results]

                result = await self.client.scan(
                    target="example.com",
                    scan_type="passive",
                    wait=True,
                )

                assert result["scan_id"] == "scan-001"
                assert result["target"] == "example.com"
                assert result["status"] == "FINISHED"
                assert result["entity_count"] == 3
                assert result["event_count"] == 3

                # Check converted entities
                schemas = {e["schema"] for e in result["entities"]}
                assert "Domain" in schemas
                assert "Email" in schemas
                assert "Person" in schemas

    @pytest.mark.asyncio
    async def test_scan_no_wait(self):
        """Test scan with wait=False returns immediately."""
        mock_start = MagicMock()
        mock_start.status_code = 200
        mock_start.json.return_value = "scan-002"
        mock_start.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_start):
            result = await self.client.scan(
                target="example.com",
                wait=False,
            )
            assert result["status"] == "started"
            assert result["scan_id"] == "scan-002"
            assert result["entities"] == []


# ===========================================================================
# OSINT Recon Skill Chip
# ===========================================================================


class TestOSINTReconChip:
    """Test the OSINT recon skill chip."""

    def setup_method(self):
        self.chip = OSINTReconChip()
        self.context = SkillContext(
            investigation_id="inv-001",
            user_id="user-001",
        )

    def test_chip_metadata(self):
        assert self.chip.name == "osint_recon"
        assert self.chip.domain == SkillDomain.ENTITY_SEARCH
        assert self.chip.version == "1.0.0"

    def test_chip_capabilities(self):
        from emet.skills.base import SkillCapability
        assert SkillCapability.EXTERNAL_API in self.chip.capabilities
        assert SkillCapability.WEB_SCRAPING in self.chip.capabilities

    def test_chip_consensus_on_active_scan(self):
        assert self.chip.requires_consensus("active_scan") is True

    def test_chip_info(self):
        info = self.chip.get_info()
        assert info["name"] == "osint_recon"
        assert "efe_weights" in info

    @pytest.mark.asyncio
    async def test_active_scan_requires_consensus(self):
        request = SkillRequest(
            intent="osint_recon",
            parameters={"target": "example.com", "scan_type": "active"},
        )
        response = await self.chip.handle(request, self.context)
        assert response.requires_consensus is True
        assert response.consensus_action == "active_scan"
        assert response.success is False

    @pytest.mark.asyncio
    async def test_missing_target(self):
        request = SkillRequest(intent="osint_recon", parameters={})
        response = await self.chip.handle(request, self.context)
        assert response.success is False
        assert "target" in response.content.lower()

    @pytest.mark.asyncio
    async def test_successful_recon(self):
        mock_result = {
            "scan_id": "sf-test",
            "target": "example.com",
            "status": "FINISHED",
            "event_count": 10,
            "entities": [
                {"id": "e1", "schema": "Domain", "properties": {"name": ["example.com"]}},
                {"id": "e2", "schema": "Email", "properties": {"address": ["admin@example.com"]}},
            ],
            "relationships": [],
            "entities_by_schema": {"Domain": 1, "Email": 1},
        }

        with patch(
            "emet.ftm.external.spiderfoot.SpiderFootClient.health_check",
            new_callable=AsyncMock,
            return_value={"status": "ok", "reachable": True},
        ):
            with patch(
                "emet.ftm.external.spiderfoot.SpiderFootClient.scan",
                new_callable=AsyncMock,
                return_value=mock_result,
            ):
                request = SkillRequest(
                    intent="investigate_domain",
                    parameters={"target": "example.com"},
                )
                response = await self.chip.handle(request, self.context)

                assert response.success is True
                assert "example.com" in response.content
                assert len(response.produced_entities) == 2
                assert response.result_confidence == 0.8
                assert len(response.suggestions) > 0

    @pytest.mark.asyncio
    async def test_spiderfoot_unreachable(self):
        with patch(
            "emet.ftm.external.spiderfoot.SpiderFootClient.health_check",
            new_callable=AsyncMock,
            return_value={"status": "error", "reachable": False},
        ):
            request = SkillRequest(
                intent="osint_recon",
                parameters={"target": "example.com"},
            )
            response = await self.chip.handle(request, self.context)
            assert response.success is False
            assert "not reachable" in response.content
