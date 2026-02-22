"""End-to-end integration tests for the full investigation pipeline.

Tests the complete flow: goal → agent → tools → findings → scrub → report
in a single execution, verifying that all layers work together.

These are integration tests, not unit tests — they exercise real code
paths across multiple packages without mocking internal boundaries.
"""

from __future__ import annotations

import asyncio
import json
import pytest
from typing import Any
from unittest.mock import AsyncMock

from emet.agent import InvestigationAgent, AgentConfig
from emet.agent.session import Session, Finding, Lead
from emet.agent.safety_harness import SafetyHarness, PreCheckVerdict, PostCheckResult
from emet.agent.persistence import save_session, load_session
from emet.adapters.investigation_bridge import InvestigationBridge, BridgeConfig, InvestigationResult


# ---------------------------------------------------------------------------
# Full pipeline: investigate → analyze → scrub → report
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """End-to-end: goal → agent → tools → findings → scrub → report."""

    @pytest.mark.asyncio
    async def test_investigation_produces_findings(self):
        """Agent should find entities and produce findings from a goal."""
        config = AgentConfig(max_turns=5, enable_safety=True, generate_graph=True)
        agent = InvestigationAgent(config=config)

        session = await agent.investigate("Acme Corp shell companies")

        assert isinstance(session, Session)
        assert session.goal == "Acme Corp shell companies"
        assert session.turn_count >= 1
        assert len(session.reasoning_trace) > 0
        # Should have attempted tool use
        assert len(session.tool_history) > 0

    @pytest.mark.asyncio
    async def test_safety_observes_but_does_not_block(self):
        """Safety harness observes during investigation, doesn't interfere."""
        config = AgentConfig(max_turns=3, enable_safety=True)
        agent = InvestigationAgent(config=config)

        session = await agent.investigate("John Smith sanctions check")

        # Safety audit should be attached
        audit = getattr(session, "_safety_audit", {})
        assert isinstance(audit, dict)
        assert audit.get("total_checks", 0) > 0
        # No blocks during investigation (observe-only mode)
        assert audit.get("blocks", 0) == 0

    @pytest.mark.asyncio
    async def test_pii_preserved_in_session_scrubbed_in_report(self):
        """PII is preserved in raw session but scrubbed at publication boundary."""
        config = AgentConfig(max_turns=2, enable_safety=True)
        agent = InvestigationAgent(config=config)

        session = await agent.investigate("Entity search test")

        # Inject PII into a finding to test scrubbing
        session.add_finding(Finding(
            source="test",
            summary="Contact john@example.com or call 555-123-4567",
            confidence=0.9,
        ))

        # Raw session should have PII
        finding_text = session.findings[-1].summary
        assert "john@example.com" in finding_text

        # Publication scrub should redact
        harness = SafetyHarness.from_defaults()
        scrubbed = harness.scrub_for_publication(finding_text)
        assert "john@example.com" not in scrubbed.scrubbed_text
        assert scrubbed.pii_found > 0

    @pytest.mark.asyncio
    async def test_persistence_roundtrip(self, tmp_path):
        """Investigation can be saved and loaded with full fidelity."""
        config = AgentConfig(max_turns=3)
        agent = InvestigationAgent(config=config)

        session = await agent.investigate("Persistence test target")

        # Save
        path = tmp_path / "test_session.json"
        save_session(session, path)

        # Load
        loaded = load_session(path)

        assert loaded.goal == session.goal
        assert loaded.turn_count == session.turn_count
        assert len(loaded.reasoning_trace) == len(session.reasoning_trace)
        assert len(loaded.findings) == len(session.findings)
        assert len(loaded.entities) == len(session.entities)

    @pytest.mark.asyncio
    async def test_graph_generation(self):
        """Investigation should produce a relationship graph."""
        config = AgentConfig(max_turns=3, generate_graph=True)
        agent = InvestigationAgent(config=config)

        session = await agent.investigate("Graph test Acme Corp")

        # Graph should be attached (may be None if no entities found)
        graph = getattr(session, "_investigation_graph", None)
        # At minimum, the attribute should exist
        assert hasattr(session, "_investigation_graph")


# ---------------------------------------------------------------------------
# Adapter bridge integration
# ---------------------------------------------------------------------------


class TestBridgeIntegration:
    """Integration tests for the adapter bridge."""

    @pytest.mark.asyncio
    async def test_bridge_runs_investigation(self):
        """Bridge should run a full investigation and return results."""
        bridge = InvestigationBridge(BridgeConfig(max_turns=3))

        result = await bridge.run_investigation("Bridge test Acme Corp")

        assert isinstance(result, InvestigationResult)
        assert isinstance(result.session, Session)
        assert result.session.goal == "Bridge test Acme Corp"
        assert isinstance(result.summary, dict)
        assert len(result.report_text) > 0

    @pytest.mark.asyncio
    async def test_bridge_handle_command(self):
        """Bridge command handler sends progress and results."""
        bridge = InvestigationBridge(BridgeConfig(max_turns=2))

        messages_sent: list[str] = []

        async def mock_send(text: str) -> None:
            messages_sent.append(text)

        result = await bridge.handle_investigate_command(
            goal="Command test",
            channel_id="test-channel",
            send_fn=mock_send,
        )

        assert isinstance(result, InvestigationResult)
        # Should have sent at least "Starting investigation" and the report
        assert len(messages_sent) >= 2
        assert any("Starting investigation" in m for m in messages_sent)

    @pytest.mark.asyncio
    async def test_bridge_prevents_duplicate(self):
        """Bridge should prevent duplicate investigations in same channel."""
        bridge = InvestigationBridge(BridgeConfig(max_turns=2))

        messages: list[str] = []
        async def mock_send(text: str) -> None:
            messages.append(text)

        # Fake an active investigation
        bridge._active["busy-channel"] = Session(goal="already running")

        result = await bridge.handle_investigate_command(
            goal="Should not start",
            channel_id="busy-channel",
            send_fn=mock_send,
        )

        assert result.error
        assert "already running" in messages[0].lower()

        # Clean up
        bridge._active.clear()

    @pytest.mark.asyncio
    async def test_bridge_cleans_up_on_error(self):
        """Bridge should clean up active state even on failure."""
        bridge = InvestigationBridge(BridgeConfig(max_turns=1))

        messages: list[str] = []
        async def mock_send(text: str) -> None:
            messages.append(text)

        await bridge.handle_investigate_command(
            goal="Cleanup test",
            channel_id="error-channel",
            send_fn=mock_send,
        )

        # Channel should be cleaned up regardless of result
        assert "error-channel" not in bridge._active

    def test_format_for_slack(self):
        """Slack formatting should produce valid blocks."""
        bridge = InvestigationBridge()
        session = Session(goal="Slack test")
        session.add_finding(Finding(
            source="search", summary="Found 3 entities", confidence=0.8
        ))

        result = InvestigationResult(
            session=session,
            summary={"entity_count": 3, "finding_count": 1, "turns": 2, "leads_open": 0},
            report_text="Test report",
            scrubbed_report_text="Test report (scrubbed)",
        )

        slack_msg = bridge.format_for_slack(result)
        assert "blocks" in slack_msg
        assert "text" in slack_msg
        assert len(slack_msg["blocks"]) >= 2  # header + summary at minimum

    def test_format_for_discord(self):
        """Discord formatting should produce valid embed."""
        bridge = InvestigationBridge()
        session = Session(goal="Discord test")

        result = InvestigationResult(
            session=session,
            summary={"entity_count": 5, "finding_count": 2, "turns": 3, "leads_open": 1},
            report_text="Discord report",
            scrubbed_report_text="Discord report (scrubbed)",
        )

        embed = bridge.format_for_discord(result)
        assert "title" in embed
        assert "fields" in embed
        assert embed["color"] == 0x2ECC71

    def test_format_for_discord_error(self):
        """Discord error formatting should be red."""
        bridge = InvestigationBridge()
        result = InvestigationResult(
            session=Session(goal="fail"),
            summary={},
            error="Connection refused",
        )

        embed = bridge.format_for_discord(result)
        assert embed["color"] == 0xFF0000
        assert "Connection refused" in embed["description"]


# ---------------------------------------------------------------------------
# API integration
# ---------------------------------------------------------------------------


class TestAPIIntegration:
    """Tests for the investigation API routes."""

    @pytest.mark.asyncio
    async def test_api_models_serialize(self):
        """API models should serialize cleanly."""
        from emet.api.routes.investigation import (
            InvestigationRequest,
            InvestigationStatus,
            InvestigationListItem,
            ExportResponse,
        )

        req = InvestigationRequest(goal="API test")
        assert req.goal == "API test"
        assert req.max_turns == 15

        status = InvestigationStatus(
            id="abc123",
            goal="test",
            status="running",
            started_at="2026-01-01T00:00:00Z",
        )
        data = status.model_dump()
        assert data["id"] == "abc123"
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_api_run_investigation_task(self):
        """The background investigation task should complete."""
        from emet.api.routes.investigation import (
            _run_investigation, _investigations, InvestigationRequest,
        )

        inv_id = "test_run_001"
        _investigations[inv_id] = {
            "id": inv_id,
            "goal": "API background test",
            "status": "running",
            "started_at": "2026-01-01T00:00:00Z",
            "config": {},
            "session": None,
            "error": None,
        }

        req = InvestigationRequest(goal="API background test", max_turns=2)
        await _run_investigation(inv_id, req)

        assert _investigations[inv_id]["status"] == "completed"
        assert _investigations[inv_id]["session"] is not None
        assert _investigations[inv_id]["completed_at"] is not None

        # Cleanup
        del _investigations[inv_id]

    @pytest.mark.asyncio
    async def test_api_export_scrubs_pii(self):
        """Export endpoint should scrub PII from results."""
        from emet.api.routes.investigation import _investigations

        # Create a completed investigation with PII in findings
        session = Session(goal="Export PII test")
        session.add_finding(Finding(
            source="test",
            summary="Director email: john@badcorp.com, SSN: 123-45-6789",
            confidence=0.9,
        ))

        inv_id = "test_export_001"
        _investigations[inv_id] = {
            "id": inv_id,
            "goal": "Export PII test",
            "status": "completed",
            "started_at": "2026-01-01T00:00:00Z",
            "completed_at": "2026-01-01T00:01:00Z",
            "session": session,
            "summary": session.summary(),
            "error": None,
        }

        from emet.api.routes.investigation import export_investigation
        response = await export_investigation(inv_id)

        # PII should be scrubbed from the export
        report_str = json.dumps(response.report)
        assert "john@badcorp.com" not in report_str
        assert "123-45-6789" not in report_str

        # Cleanup
        del _investigations[inv_id]


# ---------------------------------------------------------------------------
# Safety harness two-mode verification
# ---------------------------------------------------------------------------


class TestTwoModeSafety:
    """Verify investigate vs publish modes across the pipeline."""

    def test_investigate_mode_preserves_all_data(self):
        """During investigation, nothing is blocked or scrubbed."""
        harness = SafetyHarness.from_defaults()

        # Pre-check: SQL-like query should pass through
        verdict = harness.pre_check(
            tool="search_entities",
            args={"query": "O'Brien & Associates DROP TABLE"},
        )
        assert verdict.allowed
        assert not verdict.blocked

        # Post-check: PII should be detected but not scrubbed
        result = harness.post_check(
            "Found: john@example.com, SSN: 999-88-7777, Phone: 555-0123",
            tool="search_entities",
        )
        assert "john@example.com" in result.scrubbed_text
        assert "999-88-7777" in result.scrubbed_text
        assert result.pii_found > 0

    def test_publish_mode_scrubs_all_pii(self):
        """At publication boundary, PII is fully scrubbed."""
        harness = SafetyHarness.from_defaults()

        result = harness.scrub_for_publication(
            "Found: john@example.com, SSN: 999-88-7777, Phone: 555-0123"
        )
        assert "john@example.com" not in result.scrubbed_text
        assert "999-88-7777" not in result.scrubbed_text
        assert result.pii_found > 0

    def test_same_harness_both_modes(self):
        """Same harness instance handles both modes correctly."""
        harness = SafetyHarness.from_defaults()
        text = "Contact: jane@shell.co, ID: 987-65-4321"

        # Investigate: preserve
        inv = harness.post_check(text, tool="search")
        assert "jane@shell.co" in inv.scrubbed_text

        # Publish: scrub
        pub = harness.scrub_for_publication(text)
        assert "jane@shell.co" not in pub.scrubbed_text

        # Audit should show both modes
        audit = harness.audit_summary()
        events = audit["events"]
        modes = {e["mode"] for e in events}
        assert "investigate" in modes
        assert "publish" in modes


# ---------------------------------------------------------------------------
# Cross-package smoke tests
# ---------------------------------------------------------------------------


class TestCrossPackageIntegration:
    """Verify key packages work together."""

    def test_agent_uses_mcp_tools(self):
        """Agent's tool executor should have all tools registered."""
        from emet.mcp.tools import EmetToolExecutor, EMET_TOOLS

        executor = EmetToolExecutor()
        tools = executor.list_tools()
        assert len(tools) == len(EMET_TOOLS)
        tool_names = {t["name"] for t in tools}
        assert "search_entities" in tool_names
        assert "trace_ownership" in tool_names
        assert "screen_sanctions" in tool_names

    def test_tool_executor_pool_reuses_instances(self):
        """Connection pool should return same instance on repeated calls."""
        from emet.mcp.tools import EmetToolExecutor
        from emet.graph.engine import GraphEngine

        executor = EmetToolExecutor()
        e1 = executor._get_or_create("test_engine", GraphEngine)
        e2 = executor._get_or_create("test_engine", GraphEngine)
        assert e1 is e2

    def test_safety_harness_creates_from_defaults(self):
        """Harness should create with all safety components."""
        harness = SafetyHarness.from_defaults()
        assert harness._pii_redactor is not None
        assert harness._security_monitor is not None
        # Shield may or may not be available depending on config

    def test_session_context_for_llm(self):
        """Session should produce context string for LLM decision-making."""
        session = Session(goal="Cross-package test")
        session.add_finding(Finding(
            source="test",
            summary="Found suspicious entity",
            confidence=0.8,
        ))
        session.add_lead(Lead(
            description="Investigate further",
            priority=0.9,
            query="suspicious entity",
            tool="search_entities",
        ))

        context = session.context_for_llm()
        assert "Cross-package test" in context
        assert "suspicious entity" in context

    def test_bridge_and_api_models_compatible(self):
        """Bridge results should be convertible to API response models."""
        from emet.api.routes.investigation import InvestigationStatus

        session = Session(goal="Compatibility test")
        session.add_finding(Finding(
            source="test", summary="Compatible finding", confidence=0.7
        ))
        summary = session.summary()

        # Should be able to construct API model from bridge data
        status = InvestigationStatus(
            id="compat-001",
            goal=session.goal,
            status="completed",
            started_at=session.started_at,
            turns=summary["turns"],
            entity_count=summary["entity_count"],
            finding_count=summary["finding_count"],
            findings=[{"source": f.source, "summary": f.summary, "confidence": f.confidence}
                      for f in session.findings],
        )
        assert status.finding_count == 1
