"""Live integration tests for external data source federation.

Requires real API keys. Run with: pytest -m live tests/live/
"""

from __future__ import annotations

import pytest
from tests.test_ftm_roundtrip import _validate_ftm_entity


# ---------------------------------------------------------------------------
# OpenSanctions / Yente
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestYenteLive:

    @pytest.mark.asyncio
    async def test_search_known_entity(self, require_opensanctions, live_config):
        """Search for a well-known sanctioned individual."""
        from emet.ftm.external.adapters import YenteClient, YenteConfig

        config = YenteConfig(base_url=live_config.opensanctions_url)
        client = YenteClient(config)
        results = await client.search("Gaddafi", limit=5, entity_type="Person")

        assert len(results) >= 1, "Should find at least one Gaddafi entity"
        for entity in results:
            errors = _validate_ftm_entity(entity, "yente-live")
            assert not errors, errors

    @pytest.mark.asyncio
    async def test_empty_result_no_crash(self, require_opensanctions, live_config):
        """Gibberish query should return empty results, not crash."""
        from emet.ftm.external.adapters import YenteClient, YenteConfig

        config = YenteConfig(base_url=live_config.opensanctions_url)
        client = YenteClient(config)
        results = await client.search("xyzzyplugh99999fakename", limit=5, entity_type="Any")

        assert isinstance(results, list)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# OpenCorporates
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestOpenCorporatesLive:

    @pytest.mark.asyncio
    async def test_search_known_company(self, require_opencorporates, live_config):
        """Search for a well-known company."""
        from emet.ftm.external.adapters import OpenCorporatesClient, OpenCorporatesConfig

        config = OpenCorporatesConfig(api_key=live_config.opencorporates_key)
        client = OpenCorporatesClient(config)
        results = await client.search("Deutsche Bank", limit=5, entity_type="Company")

        assert len(results) >= 1
        for entity in results:
            errors = _validate_ftm_entity(entity, "oc-live")
            assert not errors, errors
            assert entity.get("id"), "Must have id for graph operations"


# ---------------------------------------------------------------------------
# Companies House
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestCompaniesHouseLive:

    @pytest.mark.asyncio
    async def test_search_company(self, require_companies_house, live_config):
        """Search UK Companies House for a well-known company."""
        from emet.ftm.external.companies_house import CompaniesHouseClient, CompaniesHouseConfig

        config = CompaniesHouseConfig(api_key=live_config.companies_house_key)
        client = CompaniesHouseClient(config)
        result = await client.search("Tesco")

        entities = result.get("entities", [])
        assert len(entities) >= 1
        for entity in entities:
            errors = _validate_ftm_entity(entity, "ch-live")
            assert not errors, errors

    @pytest.mark.asyncio
    async def test_get_officers(self, require_companies_house, live_config):
        """Get officers for a known company number (Tesco: 00445790)."""
        from emet.ftm.external.companies_house import CompaniesHouseClient, CompaniesHouseConfig

        config = CompaniesHouseConfig(api_key=live_config.companies_house_key)
        client = CompaniesHouseClient(config)
        result = await client.get_company_details("00445790")

        entities = result.get("entities", [])
        persons = [e for e in entities if e.get("schema") == "Person"]
        directorships = [e for e in entities if e.get("schema") == "Directorship"]

        assert len(persons) >= 1, "Tesco should have at least one officer"
        assert len(directorships) >= 1, "Should have directorship relationships"


# ---------------------------------------------------------------------------
# GLEIF
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestGLEIFLive:

    @pytest.mark.asyncio
    async def test_search_by_name(self, require_any_source):
        """Search GLEIF for a major bank (no API key required)."""
        from emet.ftm.external.adapters import GLEIFClient, GLEIFConfig

        client = GLEIFClient(GLEIFConfig())
        results = await client.search("Apple Inc", limit=5, entity_type="Company")

        assert len(results) >= 1
        # GLEIF LEI should be 20 characters
        for entity in results:
            lei = entity.get("_provenance", {}).get("source_id", "")
            assert len(lei) == 20, f"LEI should be 20 chars, got {len(lei)}: {lei}"


# ---------------------------------------------------------------------------
# Blockchain
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.live_blockchain
class TestBlockchainLive:

    @pytest.mark.asyncio
    async def test_etherscan_known_address(self, require_blockchain, live_config):
        """Query a well-known Ethereum address (Vitalik's public address)."""
        from emet.ftm.external.blockchain import EtherscanClient, EtherscanConfig

        config = EtherscanConfig(api_key=live_config.etherscan_key)
        client = EtherscanClient(config)
        # Vitalik's known address
        result = await client.get_address_summary(
            "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
        )

        assert "balance" in result or "balance_eth" in result
        assert result.get("transaction_count", result.get("tx_count", 0)) > 0


# ---------------------------------------------------------------------------
# Federated Search (end-to-end)
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.live_slow
class TestFederatedSearchLive:

    @pytest.mark.asyncio
    async def test_multi_source_search(self, require_any_source, live_config):
        """Fan out a search to all available sources."""
        from emet.ftm.external.federation import FederatedSearch, FederationConfig

        config = FederationConfig(
            opensanctions_url=live_config.opensanctions_url,
            opencorporates_api_key=live_config.opencorporates_key,
            companies_house_api_key=live_config.companies_house_key,
        )
        federation = FederatedSearch(config)
        result = await federation.search("Deutsche Bank", entity_type="Company")

        assert len(result.entities) >= 1, "Should find Deutsche Bank in at least one source"
        assert len(result.source_stats) >= 1, "Should have stats from at least one source"
        assert result.queried_at, "Should have queried_at timestamp"

        # Validate all returned entities
        for entity in result.entities:
            errors = _validate_ftm_entity(entity, "federation-live")
            assert not errors, errors

    @pytest.mark.asyncio
    async def test_cache_hits_on_repeat(self, require_any_source, live_config):
        """Second identical search should hit cache."""
        from emet.ftm.external.federation import FederatedSearch, FederationConfig

        config = FederationConfig(
            opensanctions_url=live_config.opensanctions_url,
            opencorporates_api_key=live_config.opencorporates_key,
        )
        federation = FederatedSearch(config)

        # First search — cold
        result1 = await federation.search("Test Corp Cache", entity_type="Company")
        # Second search — should hit cache
        result2 = await federation.search("Test Corp Cache", entity_type="Company")

        assert result2.cache_hits > result1.cache_hits, \
            "Second search should have more cache hits"
        assert result2.total_time_ms < result1.total_time_ms * 2, \
            "Cached search should not be dramatically slower"


# ---------------------------------------------------------------------------
# Full Investigation Pipeline
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.live_slow
class TestInvestigationPipelineLive:

    @pytest.mark.asyncio
    async def test_known_sanctioned_entity(self, require_opensanctions, live_config):
        """Full investigation of a known sanctioned entity."""
        from emet.agent.loop import InvestigationAgent, AgentConfig

        config = AgentConfig(
            max_turns=8,
            llm_provider="stub",  # Use heuristic routing, no LLM needed
            tool_timeout_seconds=30.0,
        )
        agent = InvestigationAgent(config=config)
        session = await agent.investigate("Viktor Bout arms trafficking")

        assert session.finding_count >= 1, "Should find something about Viktor Bout"
        assert session.turn_count >= 2, "Should do more than just the initial search"
        # Should have used sanctions screening
        tools_used = {t["tool"] for t in session.tool_history}
        assert "search_entities" in tools_used

    @pytest.mark.asyncio
    async def test_clean_entity_no_false_positives(self, require_any_source, live_config):
        """Investigation of a non-sanctioned entity should not produce false sanctions hits."""
        from emet.agent.loop import InvestigationAgent, AgentConfig

        config = AgentConfig(
            max_turns=5,
            llm_provider="stub",
            tool_timeout_seconds=30.0,
        )
        agent = InvestigationAgent(config=config)
        session = await agent.investigate("Microsoft Corporation")

        # Should NOT have sanctions findings
        sanctions_findings = [
            f for f in session.findings
            if "sanction" in f.source.lower() and f.entities
        ]
        # If sanctions hits exist, they should be low confidence
        for f in sanctions_findings:
            assert f.confidence < 0.8, \
                f"Microsoft should not have high-confidence sanctions hit: {f}"
