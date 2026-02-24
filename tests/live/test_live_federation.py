"""Live integration tests for external data source federation.

Requires real API keys. Run with: pytest -m live tests/live/
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# OpenSanctions
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestOpenSanctionsLive:

    @pytest.mark.asyncio
    async def test_search_known_sanctioned(self, require_opensanctions, live_config):
        """Search for a well-known sanctioned individual."""
        from emet.ftm.external.adapters import YenteClient, YenteConfig

        config = YenteConfig(api_key=live_config.opensanctions_key)
        client = YenteClient(config)
        results = await client.search("Gaddafi", limit=5, entity_type="Person")

        assert len(results) >= 1, "Should find at least one Gaddafi entity"
        assert any("gaddafi" in str(e).lower() for e in results)

    @pytest.mark.asyncio
    async def test_screen_sanctions_via_tool(self, require_opensanctions):
        """Sanctions screening through the MCP tool interface."""
        from emet.mcp.tools import EmetToolExecutor

        executor = EmetToolExecutor()
        result = await executor.execute_raw("screen_sanctions", {
            "entity_name": "Viktor Bout",
            "entity_type": "Person",
            "threshold": 0.5,
        })

        assert "matches" in result or "results" in result or "hits" in result
        # Viktor Bout is sanctioned — should have hits
        hits = result.get("matches", result.get("results", result.get("hits", [])))
        assert len(hits) >= 1, "Viktor Bout should trigger sanctions match"

    @pytest.mark.asyncio
    async def test_empty_result_no_crash(self, require_opensanctions, live_config):
        """Gibberish query should return empty results, not crash."""
        from emet.ftm.external.adapters import YenteClient, YenteConfig

        config = YenteConfig(api_key=live_config.opensanctions_key)
        client = YenteClient(config)
        results = await client.search("xyzzyplugh99999fakename", limit=5)

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

        config = OpenCorporatesConfig(api_token=live_config.opencorporates_key)
        client = OpenCorporatesClient(config)
        results = await client.search("Deutsche Bank", limit=5, entity_type="Company")

        assert len(results) >= 1
        assert any("deutsche" in str(e).lower() for e in results)


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

    @pytest.mark.asyncio
    async def test_get_officers(self, require_companies_house, live_config):
        """Get officers for a known company number (Tesco: 00445790)."""
        from emet.ftm.external.companies_house import CompaniesHouseClient, CompaniesHouseConfig

        config = CompaniesHouseConfig(api_key=live_config.companies_house_key)
        client = CompaniesHouseClient(config)
        result = await client.get_company_details("00445790")

        entities = result.get("entities", [])
        persons = [e for e in entities if e.get("schema") == "Person"]
        assert len(persons) >= 1, "Tesco should have at least one officer"


# ---------------------------------------------------------------------------
# Free sources (no API key needed)
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestFreeSources:

    @pytest.mark.asyncio
    async def test_gleif_search(self):
        """Search GLEIF for a major company (no API key required)."""
        from emet.ftm.external.adapters import GLEIFClient, GLEIFConfig

        client = GLEIFClient(GLEIFConfig())
        result = await client.search_entities("Apple Inc", limit=5)

        # GLEIF returns raw API response with "data" key
        data = result.get("data", [])
        assert len(data) >= 1, "Should find Apple Inc in GLEIF"

    @pytest.mark.asyncio
    async def test_icij_search(self):
        """Search ICIJ Offshore Leaks (no API key required)."""
        from emet.ftm.external.adapters import ICIJClient, ICIJConfig

        client = ICIJClient(ICIJConfig())
        result = await client.search("Mossack Fonseca", limit=5)

        assert isinstance(result, dict)
        # ICIJ reconciliation API returns results
        candidates = result.get("results", [])
        assert len(candidates) >= 1, "Should find Mossack Fonseca in ICIJ"


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

        config = FederationConfig.from_env()
        federation = FederatedSearch(config)
        result = await federation.search_entity("Deutsche Bank", entity_type="Company")

        assert len(result.entities) >= 1
        assert len(result.source_stats) >= 1

    @pytest.mark.asyncio
    async def test_search_via_mcp_tool(self, require_any_source):
        """Entity search through the MCP tool interface."""
        from emet.mcp.tools import EmetToolExecutor

        executor = EmetToolExecutor()
        result = await executor.execute_raw("search_entities", {
            "query": "Deutsche Bank",
            "entity_type": "Company",
            "limit": 10,
        })

        assert result.get("result_count", 0) >= 1
        assert "entities" in result
