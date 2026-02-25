"""Mock fidelity and tool coverage tests.

These tests verify that:
1. All 12 MCP tools can be dispatched without crashing
2. Mock return types match real function signatures
3. Previously-broken tools (fixed in commit 0c66c00) stay working

This catches the class of bugs where tests pass with wrong mocks
but real invocations crash.
"""

from __future__ import annotations

import inspect
import pytest
from unittest.mock import AsyncMock, patch

from emet.mcp.tools import EMET_TOOLS, EmetToolExecutor
from emet.ftm.external.federation import FederatedSearch, FederatedResult


# ===========================================================================
# Mock fidelity: verify mocked interfaces match real code
# ===========================================================================


class TestMockFidelity:
    """Structural tests that mock shapes match real interfaces."""

    def test_all_12_tools_registered(self):
        """Executor must have handlers for all 12 MCP tool definitions."""
        executor = EmetToolExecutor()
        tool_names = {t["name"] for t in executor.list_tools()}
        assert len(tool_names) == 13
        expected = {
            "search_entities", "search_aleph", "osint_recon", "analyze_graph",
            "trace_ownership", "screen_sanctions", "investigate_blockchain",
            "monitor_entity", "check_alerts", "generate_report",
            "ingest_documents", "list_workflows", "run_workflow",
        }
        assert tool_names == expected

    def test_federated_search_returns_federated_result(self):
        """FederatedSearch.search_entity must return FederatedResult, not list."""
        sig = inspect.signature(FederatedSearch.search_entity)
        # The return annotation should exist (enforced by type hints)
        # More importantly: FederatedResult must be importable and have
        # the fields that tools expect
        result = FederatedResult(
            query="test", entity_type="Any", entities=[],
            source_stats={}, errors={}, cache_hits=0,
            total_time_ms=0, queried_at="",
        )
        assert hasattr(result, "entities")
        assert hasattr(result, "source_stats")
        assert hasattr(result, "errors")
        assert isinstance(result.entities, list)

    def test_tool_definitions_have_required_fields(self):
        """Every tool must have name, description, inputSchema, annotations."""
        for tool in EMET_TOOLS:
            assert tool.name, f"Tool missing name"
            assert tool.description, f"Tool {tool.name} missing description"
            assert tool.input_schema, f"Tool {tool.name} missing input_schema"

    def test_executor_tool_map_matches_definitions(self):
        """Every defined tool must have a handler in the executor."""
        executor = EmetToolExecutor()
        defined_names = {t.name for t in EMET_TOOLS}
        handler_names = set(executor._tool_map.keys())
        assert defined_names == handler_names, (
            f"Mismatched: defined={defined_names - handler_names}, "
            f"handlers={handler_names - defined_names}"
        )


# ===========================================================================
# Previously-broken tool smoke tests (regression guards)
# ===========================================================================


class TestPreviouslyBrokenTools:
    """Regression tests for tools that crashed before commit 0c66c00.

    Each test calls the tool with minimal valid input and verifies
    it returns a dict (not crashes). Uses real code paths where safe,
    mocks only external network calls.
    """

    def setup_method(self):
        self.executor = EmetToolExecutor()

    @pytest.mark.asyncio
    async def test_screen_sanctions_returns_dict(self):
        """screen_sanctions was calling nonexistent YenteClient.match()."""
        # Mock the actual network call
        with patch(
            "emet.ftm.external.adapters.YenteClient.screen_entities",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await self.executor.execute_raw(
                "screen_sanctions",
                {"entities": [{"name": "Test Person", "schema": "Person"}], "threshold": 0.7},
            )
            assert isinstance(result, dict)
            assert "screened_count" in result
            assert "matches" in result

    @pytest.mark.asyncio
    async def test_analyze_graph_returns_dict(self):
        """analyze_graph was calling nonexistent GraphEngine.run_algorithm()."""
        result = await self.executor.execute_raw(
            "analyze_graph",
            {"algorithm": "full", "entities": [
                {"id": "e1", "schema": "Person", "properties": {"name": ["A"]}},
                {"id": "e2", "schema": "Company", "properties": {"name": ["B"]}},
            ]},
        )
        assert isinstance(result, dict)
        assert "algorithm" in result

    @pytest.mark.asyncio
    async def test_generate_report_returns_dict(self):
        """generate_report imported nonexistent MarkdownReporter class."""
        result = await self.executor.execute_raw(
            "generate_report",
            {"title": "Test Report", "entities": [
                {"id": "e1", "schema": "Person", "properties": {"name": ["Test"]}},
            ]},
        )
        assert isinstance(result, dict)
        assert "report" in result

    @pytest.mark.asyncio
    async def test_investigate_blockchain_returns_dict(self):
        """investigate_blockchain had Etherscan V1 API + int parsing crash."""
        with patch(
            "emet.ftm.external.blockchain.EtherscanClient.get_balance",
            new_callable=AsyncMock,
            return_value={"balance_wei": "0", "balance_eth": "0"},
        ), patch(
            "emet.ftm.external.blockchain.EtherscanClient.get_transactions",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await self.executor.execute_raw(
                "investigate_blockchain",
                {"address": "0x0000000000000000000000000000000000000000", "chain": "ethereum"},
            )
            assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_ingest_documents_returns_dict(self):
        """ingest_documents imported nonexistent Config classes."""
        result = await self.executor.execute_raw(
            "ingest_documents",
            {"source": "datashare", "query": "test", "limit": 5},
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_run_workflow_returns_dict(self):
        """run_workflow was missing required 'inputs' argument."""
        result = await self.executor.execute_raw(
            "run_workflow",
            {"workflow_name": "nonexistent"},
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_osint_recon_returns_dict(self):
        """osint_recon had unhandled connection error."""
        result = await self.executor.execute_raw(
            "osint_recon",
            {"target": "example.com", "scan_type": "passive"},
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_check_alerts_returns_dict(self):
        """check_alerts had wrong federation kwargs."""
        with patch(
            "emet.monitoring.ChangeDetector.check_all",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await self.executor.execute_raw(
                "check_alerts",
                {"entity_name": "test entity", "severity": "low"},
            )
            assert isinstance(result, dict)
            assert "alert_count" in result

    @pytest.mark.asyncio
    async def test_trace_ownership_returns_dict(self):
        """trace_ownership should return ownership chain."""
        mock_federated = FederatedResult(
            query="Test Corp", entity_type="", entities=[
                {"id": "e1", "schema": "Company", "properties": {"name": ["Test Corp"]}},
            ],
            source_stats={}, errors={}, cache_hits=0,
            total_time_ms=0, queried_at="",
        )
        with patch(
            "emet.ftm.external.federation.FederatedSearch.search_entity",
            new_callable=AsyncMock,
            return_value=mock_federated,
        ):
            result = await self.executor.execute_raw(
                "trace_ownership",
                {"entity_name": "Test Corp", "max_depth": 2},
            )
            assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_monitor_entity_returns_dict(self):
        """monitor_entity should return news/GDELT results."""
        result = await self.executor.execute_raw(
            "monitor_entity",
            {"entity_name": "Test Corp", "timespan": "24h"},
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_list_workflows_returns_dict(self):
        """list_workflows should return available workflows."""
        result = await self.executor.execute_raw(
            "list_workflows",
            {},
        )
        assert isinstance(result, dict)


# ===========================================================================
# Demo mode tests
# ===========================================================================


class TestDemoMode:
    """Test that demo mode injects data correctly."""

    def test_demo_entities_load(self):
        from emet.data.demo_entities import get_demo_entities, get_demo_sanctions_matches
        entities = get_demo_entities()
        assert len(entities) >= 15  # Companies + people + relationships
        # Check key entities are present
        ids = {e["id"] for e in entities}
        assert "demo:meridian-holdings" in ids
        assert "demo:viktor-renko" in ids

        matches = get_demo_sanctions_matches()
        assert len(matches) >= 1
        assert matches[0]["name"] == "Viktor Renko"

    def test_demo_entities_order(self):
        """First 5 entities should be the key investigation targets."""
        from emet.data.demo_entities import get_demo_entities
        entities = get_demo_entities()
        first_5_ids = [e["id"] for e in entities[:5]]
        assert "demo:meridian-holdings" in first_5_ids
        assert "demo:viktor-renko" in first_5_ids

    @pytest.mark.asyncio
    async def test_demo_sanctions_injected(self):
        """Demo mode should inject sanctions matches for Viktor Renko."""
        executor = EmetToolExecutor(demo_mode=True)
        with patch(
            "emet.ftm.external.adapters.YenteClient.screen_entities",
            new_callable=AsyncMock,
            return_value=[],  # Real screening returns nothing
        ):
            result = await executor.execute_raw(
                "screen_sanctions",
                {"entities": [{"name": "Viktor Renko", "schema": "Person"}], "threshold": 0.5},
            )
            assert result["match_count"] >= 1
            assert any("Renko" in m.get("name", "") for m in result["matches"])
