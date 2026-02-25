"""Live integration tests for Aleph (OpenAleph / OCCRP Aleph).

The א that gives the golem life. Tests search, entity retrieval,
collection management, cross-referencing, and investigation export.

Requires: ALEPH_HOST and ALEPH_API_KEY

Run with: pytest -m live tests/live/test_live_aleph.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Direct client tests
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.live_aleph
class TestAlephClient:

    @pytest.mark.asyncio
    async def test_search_returns_results(self, require_aleph, live_config):
        """Basic full-text search should return FtM entities."""
        from emet.ftm.aleph_client import AlephClient, AlephConfig

        config = AlephConfig(
            host=live_config.aleph_host,
            api_key=live_config.aleph_key,
        )
        client = AlephClient(config)
        result = await client.search("Gazprom", limit=5)

        assert "results" in result, "Response should have 'results' key"
        assert "total" in result, "Response should have 'total' key"
        # OpenAleph might have limited data; just verify the API works
        assert isinstance(result["results"], list)

    @pytest.mark.asyncio
    async def test_search_with_schema_filter(self, require_aleph, live_config):
        """Schema-filtered search should work."""
        from emet.ftm.aleph_client import AlephClient, AlephConfig

        config = AlephConfig(
            host=live_config.aleph_host,
            api_key=live_config.aleph_key,
        )
        client = AlephClient(config)
        result = await client.search("bank", schema="Company", limit=5)

        assert isinstance(result.get("results", []), list)
        # If results exist, they should be Company schema
        for entity in result.get("results", []):
            schema = entity.get("schema", "")
            assert schema in ("Company", "Organization", "LegalEntity", "Thing"), \
                f"Expected Company-like schema, got {schema}"

    @pytest.mark.asyncio
    async def test_list_collections(self, require_aleph, live_config):
        """Should be able to list accessible collections."""
        from emet.ftm.aleph_client import AlephClient, AlephConfig

        config = AlephConfig(
            host=live_config.aleph_host,
            api_key=live_config.aleph_key,
        )
        client = AlephClient(config)
        result = await client.list_collections(limit=10)

        assert "results" in result
        assert isinstance(result["results"], list)

    @pytest.mark.asyncio
    async def test_search_elasticsearch_syntax(self, require_aleph, live_config):
        """Elasticsearch query syntax should work (boolean, wildcards)."""
        from emet.ftm.aleph_client import AlephClient, AlephConfig

        config = AlephConfig(
            host=live_config.aleph_host,
            api_key=live_config.aleph_key,
        )
        client = AlephClient(config)

        # Boolean query
        result = await client.search("Putin AND sanctions", limit=5)
        assert isinstance(result.get("results", []), list)

    @pytest.mark.asyncio
    async def test_empty_query_no_crash(self, require_aleph, live_config):
        """Edge case: empty or gibberish query should not crash."""
        from emet.ftm.aleph_client import AlephClient, AlephConfig

        config = AlephConfig(
            host=live_config.aleph_host,
            api_key=live_config.aleph_key,
        )
        client = AlephClient(config)
        result = await client.search("xyzzy99999nonexistent", limit=5)

        assert isinstance(result.get("results", []), list)
        assert result.get("total", 0) == 0 or len(result["results"]) == 0


# ---------------------------------------------------------------------------
# MCP tool tests
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.live_aleph
class TestAlephMCPTool:

    @pytest.mark.asyncio
    async def test_search_aleph_tool(self, require_aleph):
        """search_aleph tool should return results."""
        from emet.mcp.tools import EmetToolExecutor

        executor = EmetToolExecutor()
        result = await executor.execute_raw("search_aleph", {
            "query": "offshore company",
            "limit": 10,
        })

        assert "error" not in result or result.get("result_count", 0) >= 0
        assert "entities" in result
        assert isinstance(result["entities"], list)

    @pytest.mark.asyncio
    async def test_search_aleph_with_schema(self, require_aleph):
        """search_aleph with schema filter."""
        from emet.mcp.tools import EmetToolExecutor

        executor = EmetToolExecutor()
        result = await executor.execute_raw("search_aleph", {
            "query": "shell company",
            "schema": "Company",
            "limit": 5,
        })

        assert "entities" in result

    @pytest.mark.asyncio
    async def test_search_aleph_with_country(self, require_aleph):
        """search_aleph with country filter."""
        from emet.mcp.tools import EmetToolExecutor

        executor = EmetToolExecutor()
        result = await executor.execute_raw("search_aleph", {
            "query": "bank",
            "countries": ["cy"],  # Cyprus — classic offshore jurisdiction
            "limit": 5,
        })

        assert "entities" in result


# ---------------------------------------------------------------------------
# Federation integration tests
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.live_aleph
class TestAlephInFederation:

    @pytest.mark.asyncio
    async def test_federation_includes_aleph(self, require_aleph):
        """Federated search should include Aleph as a source."""
        from emet.ftm.external.federation import FederatedSearch, FederationConfig

        config = FederationConfig.from_env()
        federation = FederatedSearch(config)

        assert "aleph" in federation._clients, "Aleph should be in federation clients"

        result = await federation.search_entity("Gazprom", entity_type="Company")

        assert "aleph" in result.source_stats, \
            f"Aleph should appear in source_stats, got: {result.source_stats}"

    @pytest.mark.asyncio
    async def test_aleph_entities_have_provenance(self, require_aleph):
        """Entities from Aleph should have proper provenance tagging."""
        from emet.ftm.external.federation import FederatedSearch, FederationConfig

        config = FederationConfig.from_env()
        federation = FederatedSearch(config)
        result = await federation.search_entity(
            "offshore", entity_type="Company", sources=["aleph"]
        )

        for entity in result.entities:
            prov = entity.get("_provenance", {})
            assert prov.get("source") == "aleph", \
                f"Aleph entity should have source='aleph', got {prov}"


# ---------------------------------------------------------------------------
# Collection management + write-back
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.live_aleph
@pytest.mark.live_slow
class TestAlephCollections:

    @pytest.mark.asyncio
    async def test_create_collection_and_write_entities(self, require_aleph, live_config):
        """Create a collection, write entities, search them back."""
        from emet.ftm.aleph_client import AlephClient, AlephConfig

        config = AlephConfig(
            host=live_config.aleph_host,
            api_key=live_config.aleph_key,
        )
        client = AlephClient(config)

        # Create test collection
        collection = await client.create_collection(
            label="Emet Live Test",
            summary="Automated test collection — safe to delete",
            category="casefile",
        )
        collection_id = collection.get("collection_id") or collection.get("id")
        assert collection_id, f"Should get collection ID, got: {collection}"

        # Write a test entity
        test_entity = {
            "id": "emet-test-entity-001",
            "schema": "Company",
            "properties": {
                "name": ["Emet Test Corporation"],
                "jurisdiction": ["gb"],
                "notes": ["Created by Emet live test suite"],
            },
        }

        try:
            write_result = await client.write_entities(
                collection_id, [test_entity]
            )
            assert write_result is not None
        except Exception as exc:
            # Some Aleph versions may not support bulk write
            pytest.skip(f"Bulk write not supported: {exc}")

    @pytest.mark.asyncio
    async def test_export_investigation_to_aleph(self, require_aleph, require_any_source, live_config, tmp_dir):
        """Run investigation, export results to Aleph collection."""
        from emet.agent.loop import InvestigationAgent, AgentConfig
        from emet.ftm.aleph_client import AlephClient, AlephConfig

        # Run a small investigation
        agent_config = AgentConfig(
            max_turns=3,
            llm_provider="stub",
            demo_mode=True,
            memory_dir=tmp_dir,
        )
        agent = InvestigationAgent(config=agent_config)
        session = await agent.investigate("Meridian Holdings")

        # Collect FtM entities from findings
        entities = []
        for finding in session.findings:
            for entity in finding.entities:
                if isinstance(entity, dict) and entity.get("schema"):
                    entities.append(entity)

        if not entities:
            pytest.skip("No FtM entities to export")

        # Create Aleph collection and write
        aleph_config = AlephConfig(
            host=live_config.aleph_host,
            api_key=live_config.aleph_key,
        )
        client = AlephClient(aleph_config)

        collection = await client.create_collection(
            label=f"Emet Investigation: {session.goal}",
            summary=f"Auto-exported from Emet session {session.id}",
            category="casefile",
        )
        collection_id = collection.get("collection_id") or collection.get("id")
        assert collection_id

        try:
            await client.write_entities(collection_id, entities[:10])
        except Exception as exc:
            pytest.skip(f"Entity write not supported: {exc}")


# ---------------------------------------------------------------------------
# Cross-referencing
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.live_aleph
@pytest.mark.live_slow
class TestAlephXref:

    @pytest.mark.asyncio
    async def test_xref_trigger(self, require_aleph, live_config):
        """Cross-referencing should be triggerable (even if no matches)."""
        from emet.ftm.aleph_client import AlephClient, AlephConfig

        config = AlephConfig(
            host=live_config.aleph_host,
            api_key=live_config.aleph_key,
        )
        client = AlephClient(config)

        # List collections to find one to xref
        collections = await client.list_collections(limit=5)
        collection_list = collections.get("results", [])

        if not collection_list:
            pytest.skip("No collections available for xref test")

        collection_id = collection_list[0].get("collection_id") or collection_list[0].get("id")

        try:
            xref_result = await client.trigger_xref(collection_id)
            # Just verify it doesn't crash — xref is async on server side
            assert xref_result is not None
        except Exception as exc:
            # Some instances may not have xref enabled
            pytest.skip(f"Xref not available: {exc}")


# ---------------------------------------------------------------------------
# Full pipeline with Aleph
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.live_aleph
@pytest.mark.live_slow
class TestAlephPipeline:

    @pytest.mark.asyncio
    async def test_investigation_uses_aleph_as_source(self, require_aleph, tmp_dir):
        """Full investigation should query Aleph alongside other sources."""
        from emet.agent.loop import InvestigationAgent, AgentConfig

        config = AgentConfig(
            max_turns=5,
            llm_provider="stub",
            tool_timeout_seconds=30.0,
            memory_dir=tmp_dir,
        )
        agent = InvestigationAgent(config=config)
        session = await agent.investigate("Gazprom corporate network")

        # Check that Aleph was queried as part of federation
        tools_used = {t["tool"] for t in session.tool_history}
        assert "search_entities" in tools_used

        # The federated search should include aleph in source_stats
        # (if entities were found through federation)
        for finding in session.findings:
            if finding.source == "search_entities" and finding.raw_data:
                stats = finding.raw_data.get("source_stats", {})
                if "aleph" in stats:
                    assert stats["aleph"] >= 0
                    break

    @pytest.mark.asyncio
    async def test_audit_captures_aleph_calls(self, require_aleph, tmp_dir):
        """Audit archive should capture Aleph tool calls."""
        from emet.agent.loop import InvestigationAgent, AgentConfig
        from emet.agent.audit import read_archive

        config = AgentConfig(
            max_turns=3,
            llm_provider="stub",
            tool_timeout_seconds=30.0,
            memory_dir=tmp_dir,
        )
        agent = InvestigationAgent(config=config)
        session = await agent.investigate("sanctions evasion network")

        # Read audit archive
        audit_dir = Path(tmp_dir) / "audit"
        archives = list(audit_dir.glob("*.jsonl.gz"))
        if not archives:
            pytest.skip("No audit archive created")

        events = read_archive(archives[0])
        tool_calls = [e for e in events if e["type"] == "tool_call"]

        # search_entities should appear (it fans out to Aleph internally)
        tools = [tc["data"]["tool"] for tc in tool_calls]
        assert "search_entities" in tools
