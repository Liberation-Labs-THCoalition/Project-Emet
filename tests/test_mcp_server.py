"""Tests for MCP server — Sprint 10a.

Tests the MCP protocol layer, tool definitions, resource provider,
and investigation session state management.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from emet.mcp.server import (
    EmetMCPServer,
    _jsonrpc_response,
    _jsonrpc_error,
    MCP_PROTOCOL_VERSION,
    SERVER_INFO,
    PARSE_ERROR,
    METHOD_NOT_FOUND,
)
from emet.mcp.tools import EMET_TOOLS, EmetToolExecutor, MCPToolDef
from emet.mcp.resources import (
    EmetResourceProvider,
    InvestigationSession,
    EMET_RESOURCES,
    MCPResource,
)


# ===========================================================================
# JSON-RPC helpers
# ===========================================================================


class TestJsonRpc:
    """Test JSON-RPC 2.0 message formatting."""

    def test_response_format(self):
        resp = _jsonrpc_response(1, {"tools": []})
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        assert resp["result"] == {"tools": []}

    def test_error_format(self):
        resp = _jsonrpc_error(2, -32601, "Method not found")
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 2
        assert resp["error"]["code"] == -32601
        assert resp["error"]["message"] == "Method not found"

    def test_error_with_data(self):
        resp = _jsonrpc_error(3, -32603, "Internal error", {"detail": "oops"})
        assert resp["error"]["data"] == {"detail": "oops"}


# ===========================================================================
# Tool definitions
# ===========================================================================


class TestToolDefinitions:
    """Test MCP tool definitions are well-formed."""

    def test_tool_count(self):
        """We should have 10 tools defined."""
        assert len(EMET_TOOLS) == 12

    def test_all_tools_have_names(self):
        for tool in EMET_TOOLS:
            assert tool.name, f"Tool missing name: {tool}"
            assert tool.description, f"Tool {tool.name} missing description"

    def test_all_tools_have_schemas(self):
        for tool in EMET_TOOLS:
            schema = tool.input_schema
            assert schema.get("type") == "object", f"Tool {tool.name} schema not object"
            assert "properties" in schema, f"Tool {tool.name} missing properties"

    def test_required_fields_are_valid(self):
        for tool in EMET_TOOLS:
            schema = tool.input_schema
            required = schema.get("required", [])
            properties = schema.get("properties", {})
            for field_name in required:
                assert field_name in properties, (
                    f"Tool {tool.name}: required field '{field_name}' "
                    f"not in properties"
                )

    def test_search_entities_tool(self):
        tool = next(t for t in EMET_TOOLS if t.name == "search_entities")
        assert "query" in tool.input_schema["required"]
        assert tool.category == "search"
        assert tool.read_only is True

    def test_osint_recon_tool(self):
        tool = next(t for t in EMET_TOOLS if t.name == "osint_recon")
        assert "target" in tool.input_schema["required"]
        props = tool.input_schema["properties"]
        assert "passive" in props["scan_type"]["enum"]

    def test_monitor_entity_not_readonly(self):
        tool = next(t for t in EMET_TOOLS if t.name == "monitor_entity")
        assert tool.read_only is False

    def test_generate_report_not_readonly(self):
        tool = next(t for t in EMET_TOOLS if t.name == "generate_report")
        assert tool.read_only is False

    def test_tool_categories(self):
        categories = {t.category for t in EMET_TOOLS}
        assert "search" in categories
        assert "analysis" in categories
        assert "monitoring" in categories
        assert "export" in categories
        assert "workflows" in categories

    def test_unique_tool_names(self):
        names = [t.name for t in EMET_TOOLS]
        assert len(names) == len(set(names)), "Duplicate tool names"


# ===========================================================================
# Tool executor
# ===========================================================================


class TestToolExecutor:
    """Test tool execution dispatch."""

    def setup_method(self):
        self.executor = EmetToolExecutor()

    def test_list_tools_format(self):
        tools = self.executor.list_tools()
        assert len(tools) == 12
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool
            assert "annotations" in tool

    def test_list_tools_annotations(self):
        tools = self.executor.list_tools()
        for tool in tools:
            annotations = tool["annotations"]
            assert "readOnlyHint" in annotations
            assert "destructiveHint" in annotations
            assert annotations["destructiveHint"] is False

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        result = await self.executor.execute("nonexistent_tool", {})
        assert result["isError"] is True
        assert "Unknown tool" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_search_entities_dispatches(self):
        """Test that search_entities calls FederatedSearch."""
        mock_results = [
            {"id": "e1", "schema": "Person", "properties": {"name": ["Test"]}},
        ]
        with patch(
            "emet.ftm.external.federation.FederatedSearch.search_entity",
            new_callable=AsyncMock,
            return_value=mock_results,
        ):
            result = await self.executor.execute(
                "search_entities", {"query": "Test Person"}
            )
            assert result["isError"] is False
            raw = result["_raw"]
            assert raw["query"] == "Test Person"
            assert raw["result_count"] == 1

    @pytest.mark.asyncio
    async def test_search_entities_with_source_filter(self):
        """Test source filtering in federated search."""
        with patch(
            "emet.ftm.external.federation.FederatedSearch.search_entity",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_search:
            await self.executor.execute(
                "search_entities",
                {"query": "Test", "sources": ["opensanctions"]},
            )
            mock_search.assert_called_once()

    @pytest.mark.asyncio
    async def test_osint_recon_dispatches(self):
        """Test that osint_recon calls SpiderFootClient."""
        mock_result = {
            "scan_id": "sf-test",
            "target": "example.com",
            "status": "FINISHED",
            "entities": [],
            "relationships": [],
        }
        with patch(
            "emet.ftm.external.spiderfoot.SpiderFootClient.scan",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.executor.execute(
                "osint_recon", {"target": "example.com"}
            )
            assert result["isError"] is False

    @pytest.mark.asyncio
    async def test_tool_error_handling(self):
        """Test that exceptions are caught and returned as errors."""
        with patch(
            "emet.ftm.external.federation.FederatedSearch.search_entity",
            new_callable=AsyncMock,
            side_effect=Exception("Network error"),
        ):
            result = await self.executor.execute(
                "search_entities", {"query": "Test"}
            )
            assert result["isError"] is True
            assert "Network error" in result["content"][0]["text"]


# ===========================================================================
# Resources
# ===========================================================================


class TestResources:
    """Test MCP resource definitions and provider."""

    def test_resource_count(self):
        assert len(EMET_RESOURCES) == 5

    def test_resource_uris(self):
        uris = {r.uri for r in EMET_RESOURCES}
        assert "investigation://state" in uris
        assert "investigation://entities" in uris
        assert "investigation://graph" in uris
        assert "investigation://alerts" in uris
        assert "investigation://config" in uris

    def test_provider_list_resources(self):
        provider = EmetResourceProvider()
        resources = provider.list_resources()
        assert len(resources) == 5
        for r in resources:
            assert "uri" in r
            assert "name" in r
            assert "description" in r
            assert "mimeType" in r

    @pytest.mark.asyncio
    async def test_read_state_resource(self):
        provider = EmetResourceProvider()
        result = await provider.read_resource("investigation://state")
        contents = result["contents"]
        assert len(contents) == 1
        assert contents[0]["uri"] == "investigation://state"
        data = json.loads(contents[0]["text"])
        assert "entity_count" in data
        assert "query_count" in data

    @pytest.mark.asyncio
    async def test_read_entities_resource(self):
        provider = EmetResourceProvider()
        provider.session.entities = [
            {"id": "e1", "schema": "Person", "properties": {"name": ["Test"]}},
        ]
        result = await provider.read_resource("investigation://entities")
        data = json.loads(result["contents"][0]["text"])
        assert data["count"] == 1

    @pytest.mark.asyncio
    async def test_read_graph_resource(self):
        provider = EmetResourceProvider()
        provider.session.entities = [
            {"id": "e1", "schema": "Person", "properties": {"name": ["Test"]}},
        ]
        result = await provider.read_resource("investigation://graph")
        data = json.loads(result["contents"][0]["text"])
        assert data["node_count"] == 1
        assert data["elements"]["nodes"][0]["data"]["id"] == "e1"

    @pytest.mark.asyncio
    async def test_read_unknown_resource(self):
        provider = EmetResourceProvider()
        result = await provider.read_resource("investigation://nonexistent")
        assert "Unknown resource" in result["contents"][0]["text"]


# ===========================================================================
# Investigation session
# ===========================================================================


class TestInvestigationSession:
    """Test investigation session state management."""

    def test_initial_state(self):
        session = InvestigationSession()
        assert session.entity_count == 0
        assert session.query_count == 0

    def test_record_query(self):
        session = InvestigationSession()
        session.record_query("search_entities", {"query": "test"}, 5)
        assert session.query_count == 1
        assert session.tool_calls[0]["tool"] == "search_entities"
        assert session.tool_calls[0]["result_count"] == 5

    def test_add_entities_deduplicates(self):
        session = InvestigationSession()
        entities = [
            {"id": "e1", "schema": "Person"},
            {"id": "e2", "schema": "Company"},
            {"id": "e1", "schema": "Person"},  # Duplicate
        ]
        session.add_entities(entities)
        assert session.entity_count == 2

    def test_add_alerts(self):
        session = InvestigationSession()
        session.add_alerts([{"type": "new_sanction", "entity": "Test"}])
        assert len(session.alerts) == 1

    def test_summary(self):
        session = InvestigationSession(session_id="test-123")
        session.add_entities([
            {"id": "e1", "schema": "Person", "_provenance": {"source": "opensanctions"}},
            {"id": "e2", "schema": "Company", "_provenance": {"source": "opencorporates"}},
        ])
        session.record_query("search_entities", {"query": "test"}, 2)

        summary = session.summary()
        assert summary["session_id"] == "test-123"
        assert summary["entity_count"] == 2
        assert summary["query_count"] == 1
        assert summary["entities_by_schema"]["Person"] == 1
        assert summary["entities_by_source"]["opensanctions"] == 1


# ===========================================================================
# MCP Server (protocol layer)
# ===========================================================================


class TestMCPServer:
    """Test MCP server message handling."""

    def setup_method(self):
        self.server = EmetMCPServer()

    @pytest.mark.asyncio
    async def test_initialize(self):
        msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "clientInfo": {"name": "test-client", "version": "1.0"},
                "capabilities": {},
            },
        }
        response = await self.server.handle_message(msg)
        assert response["id"] == 1
        result = response["result"]
        assert result["protocolVersion"] == MCP_PROTOCOL_VERSION
        assert result["serverInfo"]["name"] == "emet-investigative-server"
        assert "tools" in result["capabilities"]

    @pytest.mark.asyncio
    async def test_initialized_notification(self):
        """Initialized is a notification — no response."""
        msg = {
            "jsonrpc": "2.0",
            "method": "initialized",
            "params": {},
        }
        response = await self.server.handle_message(msg)
        assert response is None

    @pytest.mark.asyncio
    async def test_ping(self):
        msg = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "ping",
            "params": {},
        }
        response = await self.server.handle_message(msg)
        assert response["id"] == 2
        assert response["result"] == {}

    @pytest.mark.asyncio
    async def test_tools_list(self):
        msg = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/list",
            "params": {},
        }
        response = await self.server.handle_message(msg)
        tools = response["result"]["tools"]
        assert len(tools) == 12
        names = {t["name"] for t in tools}
        assert "search_entities" in names
        assert "osint_recon" in names

    @pytest.mark.asyncio
    async def test_tools_call(self):
        """Test tool call via MCP protocol."""
        mock_results = [
            {"id": "e1", "schema": "Person", "properties": {"name": ["Alice"]}},
        ]
        with patch(
            "emet.ftm.external.federation.FederatedSearch.search_entity",
            new_callable=AsyncMock,
            return_value=mock_results,
        ):
            msg = {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "search_entities",
                    "arguments": {"query": "Alice"},
                },
            }
            response = await self.server.handle_message(msg)
            result = response["result"]
            assert result["isError"] is False
            assert len(result["content"]) > 0

    @pytest.mark.asyncio
    async def test_tools_call_updates_session(self):
        """Tool calls should update investigation session state."""
        mock_results = [
            {"id": "e1", "schema": "Person", "properties": {"name": ["Bob"]}},
        ]
        with patch(
            "emet.ftm.external.federation.FederatedSearch.search_entity",
            new_callable=AsyncMock,
            return_value=mock_results,
        ):
            msg = {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "search_entities",
                    "arguments": {"query": "Bob"},
                },
            }
            await self.server.handle_message(msg)

            # Session should now have the entity
            assert self.server.resources.session.entity_count == 1
            assert self.server.resources.session.query_count == 1

    @pytest.mark.asyncio
    async def test_resources_list(self):
        msg = {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "resources/list",
            "params": {},
        }
        response = await self.server.handle_message(msg)
        resources = response["result"]["resources"]
        assert len(resources) == 5

    @pytest.mark.asyncio
    async def test_resources_read(self):
        msg = {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "resources/read",
            "params": {"uri": "investigation://state"},
        }
        response = await self.server.handle_message(msg)
        contents = response["result"]["contents"]
        assert len(contents) == 1

    @pytest.mark.asyncio
    async def test_unknown_method(self):
        msg = {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "nonexistent/method",
            "params": {},
        }
        response = await self.server.handle_message(msg)
        assert "error" in response
        assert response["error"]["code"] == METHOD_NOT_FOUND

    @pytest.mark.asyncio
    async def test_invalid_jsonrpc(self):
        msg = {"id": 9, "method": "ping", "params": {}}
        response = await self.server.handle_message(msg)
        assert "error" in response

    @pytest.mark.asyncio
    async def test_unknown_notification_ignored(self):
        """Unknown notifications should be silently ignored."""
        msg = {
            "jsonrpc": "2.0",
            "method": "unknown/notification",
            "params": {},
        }
        response = await self.server.handle_message(msg)
        assert response is None
