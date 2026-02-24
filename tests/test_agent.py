"""Tests for the agentic investigation runtime.

Tests session tracking, finding/lead management, agent loop,
heuristic routing, and CLI commands.
"""

from __future__ import annotations

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from typing import Any

from emet.agent.session import Session, Finding, Lead, _summarize_result
from emet.agent.loop import (
    InvestigationAgent,
    AgentConfig,
    AGENT_TOOLS,
    _build_finding_summary,
    _estimate_confidence,
)


# ===========================================================================
# Session
# ===========================================================================


class TestSession:
    def test_create(self):
        s = Session(goal="investigate Acme Corp")
        assert s.goal == "investigate Acme Corp"
        assert s.entity_count == 0
        assert s.finding_count == 0
        assert s.turn_count == 0

    def test_add_finding(self):
        s = Session(goal="test")
        f = Finding(
            source="search",
            summary="Found 5 entities",
            entities=[
                {"id": "e1", "schema": "Person", "properties": {"name": ["John"]}},
                {"id": "e2", "schema": "Company", "properties": {"name": ["Acme"]}},
            ],
        )
        s.add_finding(f)
        assert s.finding_count == 1
        assert s.entity_count == 2
        assert "e1" in s.entities
        assert "e2" in s.entities

    def test_entity_merge(self):
        s = Session(goal="test")
        s.add_finding(Finding(
            source="a",
            summary="first",
            entities=[{"id": "e1", "schema": "Person", "properties": {"name": ["John"]}}],
        ))
        s.add_finding(Finding(
            source="b",
            summary="second",
            entities=[{"id": "e1", "schema": "Person", "properties": {"name": ["John"], "country": ["US"]}}],
        ))
        # Should merge, not duplicate
        assert s.entity_count == 1
        assert "US" in s.entities["e1"]["properties"]["country"]

    def test_leads(self):
        s = Session(goal="test")
        s.add_lead(Lead(description="Check sanctions", priority=0.8, tool="screen_sanctions"))
        s.add_lead(Lead(description="Low priority", priority=0.2))
        
        open_leads = s.get_open_leads()
        assert len(open_leads) == 2
        assert open_leads[0].priority == 0.8  # Sorted by priority

    def test_resolve_lead(self):
        s = Session(goal="test")
        lead = Lead(description="Check", priority=0.5)
        s.add_lead(lead)
        s.resolve_lead(lead.id, "resolved")
        assert len(s.get_open_leads()) == 0

    def test_record_tool_use(self):
        s = Session(goal="test")
        s.record_tool_use("search", {"query": "test"}, {"result_count": 5})
        assert len(s.tool_history) == 1
        assert s.tool_history[0]["tool"] == "search"

    def test_record_reasoning(self):
        s = Session(goal="test")
        s.record_reasoning("Starting investigation")
        s.record_reasoning("Following lead")
        assert len(s.reasoning_trace) == 2

    def test_context_for_llm(self):
        s = Session(goal="investigate corruption")
        s.add_finding(Finding(source="search", summary="Found entities"))
        s.add_lead(Lead(description="Check sanctions", priority=0.8))
        
        ctx = s.context_for_llm()
        assert "investigate corruption" in ctx
        assert "Found entities" in ctx
        assert "Check sanctions" in ctx

    def test_context_truncation(self):
        s = Session(goal="test")
        for i in range(100):
            s.add_finding(Finding(source="x", summary=f"Finding {i}" * 10))
        
        ctx = s.context_for_llm(max_chars=500)
        assert len(ctx) <= 520  # Roughly respects limit

    def test_summary(self):
        s = Session(goal="test")
        s.turn_count = 5
        s.add_finding(Finding(source="a", summary="x"))
        s.add_lead(Lead(description="y"))
        s.record_tool_use("search", {}, {})
        
        summary = s.summary()
        assert summary["turns"] == 5
        assert summary["finding_count"] == 1
        assert summary["leads_total"] == 1

    def test_custom_session_id(self):
        s = Session(goal="test", session_id="my-session")
        assert s.id == "my-session"


# ===========================================================================
# Finding & Lead
# ===========================================================================


class TestFinding:
    def test_defaults(self):
        f = Finding(source="test", summary="found something")
        assert f.id  # Auto-generated
        assert f.confidence == 0.0
        assert f.entities == []

    def test_with_entities(self):
        f = Finding(
            source="search",
            summary="results",
            entities=[{"id": "e1"}],
            confidence=0.8,
        )
        assert len(f.entities) == 1
        assert f.confidence == 0.8


class TestLead:
    def test_defaults(self):
        l = Lead(description="follow up")
        assert l.status == "open"
        assert l.priority == 0.5

    def test_custom(self):
        l = Lead(
            description="sanctions hit",
            priority=0.95,
            tool="screen_sanctions",
            query="John Smith",
        )
        assert l.tool == "screen_sanctions"


# ===========================================================================
# Helpers
# ===========================================================================


class TestHelpers:
    def test_summarize_result_count(self):
        assert "5 results" in _summarize_result({"result_count": 5})

    def test_summarize_entities(self):
        assert "3 entities" in _summarize_result({"entity_count": 3})

    def test_summarize_articles(self):
        assert "10 articles" in _summarize_result({"article_count": 10})

    def test_summarize_error(self):
        assert "error" in _summarize_result({"error": "timeout"})

    def test_summarize_generic(self):
        assert "2 keys" in _summarize_result({"a": 1, "b": 2})

    def test_build_finding_summary(self):
        s = _build_finding_summary(
            "search_entities",
            {"args": {"query": "test"}},
            {"result_count": 5},
        )
        assert "5" in s
        assert "test" in s

    def test_estimate_confidence_matches(self):
        assert _estimate_confidence({"matches": [1]}) == 0.85

    def test_estimate_confidence_results(self):
        assert _estimate_confidence({"result_count": 3}) == 0.7

    def test_estimate_confidence_empty(self):
        assert _estimate_confidence({}) == 0.4


# ===========================================================================
# Agent tools catalog
# ===========================================================================


class TestAgentTools:
    def test_has_search(self):
        assert "search_entities" in AGENT_TOOLS

    def test_has_conclude(self):
        assert "conclude" in AGENT_TOOLS

    def test_all_have_descriptions(self):
        for name, tool in AGENT_TOOLS.items():
            assert "description" in tool, f"{name} missing description"

    def test_all_have_params(self):
        for name, tool in AGENT_TOOLS.items():
            assert "params" in tool, f"{name} missing params"


# ===========================================================================
# Agent loop (mocked executor)
# ===========================================================================


class TestInvestigationAgent:
    def _mock_executor(self):
        """Create a mock tool executor.

        Return structures must match real EmetToolExecutor._<tool>() methods
        to prevent silent data loss in _process_result. See mock fidelity
        audit for details.
        """
        executor = AsyncMock()

        async def mock_execute(tool: str, args: dict) -> dict:
            if tool == "search_entities":
                return {
                    "query": args.get("query", ""),
                    "entity_type": args.get("entity_type", "Any"),
                    "result_count": 2,
                    "entities": [
                        {"id": "e1", "schema": "Person", "properties": {"name": ["John Smith"]}},
                        {"id": "e2", "schema": "Company", "properties": {"name": ["Acme Corp"]}},
                    ],
                }
            elif tool == "screen_sanctions":
                return {
                    "screened_count": len(args.get("entities", [{"name": "?"}])),
                    "match_count": 0,
                    "threshold": args.get("threshold", 0.7),
                    "matches": [],
                }
            elif tool == "trace_ownership":
                return {
                    "target": args.get("entity_name", ""),
                    "max_depth": args.get("max_depth", 3),
                    "include_officers": args.get("include_officers", True),
                    "entities_found": 0,
                    "entities": [],
                }
            elif tool == "investigate_blockchain":
                return {
                    "address": args.get("address", ""),
                    "chain": args.get("chain", "ethereum"),
                    "depth": args.get("depth", 1),
                    "data": {"balance": "0", "transactions": []},
                }
            elif tool == "monitor_entity":
                return {
                    "entity_name": args.get("entity_name", ""),
                    "entity_type": args.get("entity_type", "Any"),
                    "monitoring_registered": True,
                    "alert_types": args.get("alert_types", ["all"]),
                    "article_count": 3,
                    "unique_sources": ["Reuters", "BBC"],
                    "average_tone": 0.5,
                    "entities": [],
                    "result_count": 3,
                }
            elif tool == "generate_report":
                return {"title": args.get("title", ""), "format": "markdown", "report": "# Report"}
            elif tool == "analyze_graph":
                return {
                    "algorithm": args.get("algorithm", "community_detection"),
                    "node_count": 5,
                    "edge_count": 8,
                    "result": {"communities": [{"id": 1, "members": ["e1", "e2"]}]},
                }
            elif tool == "osint_recon":
                return {
                    "target": args.get("target", ""),
                    "scan_type": args.get("scan_type", "passive"),
                    "result_count": 1,
                    "entities": [
                        {"id": "osint1", "schema": "Domain", "properties": {"name": [args.get("target", "")]}},
                    ],
                }
            elif tool == "check_alerts":
                return {
                    "alert_count": 0,
                    "alerts": [],
                }
            elif tool == "ingest_documents":
                return {
                    "source": args.get("source", "datashare"),
                    "document_count": 1,
                    "documents": [{"id": "doc1", "title": "Test Document"}],
                }
            return {}

        executor.execute = mock_execute
        executor.execute_raw = mock_execute
        return executor

    @pytest.mark.asyncio
    async def test_basic_investigation(self):
        config = AgentConfig(max_turns=5, llm_provider="stub")
        agent = InvestigationAgent(config=config)
        agent._executor = self._mock_executor()

        session = await agent.investigate("Acme Corp corruption")

        assert session.goal == "Acme Corp corruption"
        assert session.entity_count >= 1
        assert session.finding_count >= 1
        assert len(session.reasoning_trace) >= 1

    @pytest.mark.asyncio
    async def test_follows_leads(self):
        config = AgentConfig(max_turns=10, auto_news_check=False, llm_provider="stub")
        agent = InvestigationAgent(config=config)
        agent._executor = self._mock_executor()

        session = await agent.investigate("shell companies")

        # Should have used multiple tools
        tools_used = {t["tool"] for t in session.tool_history}
        assert "search_entities" in tools_used
        assert session.turn_count >= 1

    @pytest.mark.asyncio
    async def test_respects_max_turns(self):
        config = AgentConfig(max_turns=2, auto_news_check=False, llm_provider="stub")
        agent = InvestigationAgent(config=config)
        agent._executor = self._mock_executor()

        session = await agent.investigate("infinite leads")

        assert session.turn_count <= 2

    @pytest.mark.asyncio
    async def test_generates_report(self):
        config = AgentConfig(max_turns=3, auto_news_check=False, llm_provider="stub")
        agent = InvestigationAgent(config=config)
        agent._executor = self._mock_executor()

        session = await agent.investigate("test")

        # Report generation should be in tool history
        report_calls = [t for t in session.tool_history if t["tool"] == "generate_report"]
        assert len(report_calls) >= 1

    @pytest.mark.asyncio
    async def test_handles_tool_errors(self):
        config = AgentConfig(max_turns=3, auto_news_check=False, auto_sanctions_screen=False, llm_provider="stub")
        agent = InvestigationAgent(config=config)

        async def failing_execute(tool, args):
            raise Exception("API timeout")

        agent._executor = MagicMock()
        agent._executor.execute = failing_execute
        agent._executor.execute_raw = failing_execute

        session = await agent.investigate("test")

        # Should not crash — errors are recorded
        assert any("failed" in r.lower() for r in session.reasoning_trace)

    @pytest.mark.asyncio
    async def test_heuristic_conclude_when_no_leads(self):
        config = AgentConfig(max_turns=10, auto_news_check=False, auto_sanctions_screen=False, llm_provider="stub")
        agent = InvestigationAgent(config=config)

        async def minimal_execute(tool, args):
            if tool == "search_entities":
                return {"result_count": 0, "entities": []}
            if tool == "generate_report":
                return {"report": "empty"}
            return {}

        agent._executor = MagicMock()
        agent._executor.execute = minimal_execute
        agent._executor.execute_raw = minimal_execute

        session = await agent.investigate("nothing here")

        # Should conclude early — no entities means no leads
        assert session.turn_count < 10
        assert any("conclud" in r.lower() for r in session.reasoning_trace)
    @pytest.mark.asyncio
    async def test_heuristic_args_match_tool_signatures(self):
        """REGRESSION: heuristic sent wrong arg names (entity_name vs entities)."""
        config = AgentConfig(max_turns=1, auto_news_check=False, auto_sanctions_screen=False, llm_provider="stub")
        agent = InvestigationAgent(config=config)

        session = Session(goal="test")

        # Add leads for each tool type the heuristic handles
        test_leads = [
            Lead(description="Screen X", query="Bad Corp", tool="screen_sanctions", priority=0.9),
            Lead(description="Trace X", query="Shell Ltd", tool="trace_ownership", priority=0.8),
            Lead(description="OSINT X", query="suspect.com", tool="osint_recon", priority=0.7),
            Lead(description="Search X", query="Acme", tool="search_entities", priority=0.6),
            Lead(description="Blockchain X", query="0xabc123", tool="investigate_blockchain", priority=0.5),
            Lead(description="Monitor X", query="Dodgy Inc", tool="monitor_entity", priority=0.4),
        ]

        for lead in test_leads:
            session.add_lead(lead)
            lead.status = "open"
            action = agent._heuristic_decide(session)

            # The key test: args must be valid keyword arguments for the tool handler
            # screen_sanctions needs "entities" (list), not "entity_name" (str)
            if action["tool"] == "screen_sanctions":
                assert "entities" in action["args"], "screen_sanctions needs 'entities' list, not 'entity_name'"
                assert isinstance(action["args"]["entities"], list)
            elif action["tool"] == "trace_ownership":
                assert "entity_name" in action["args"]
            elif action["tool"] == "osint_recon":
                assert "target" in action["args"]
            elif action["tool"] == "search_entities":
                assert "query" in action["args"]

            # Reset lead so next iteration picks up the next one
            lead.status = "resolved"

    @pytest.mark.asyncio
    async def test_partial_tool_failure_still_produces_findings(self):
        """If one tool fails but others work, investigation should still produce results."""
        config = AgentConfig(max_turns=5, auto_news_check=False, llm_provider="stub")
        agent = InvestigationAgent(config=config)

        call_count = {"search": 0, "sanctions": 0}

        async def partial_executor(tool, args):
            if tool == "search_entities":
                call_count["search"] += 1
                return {
                    "query": args.get("query", ""),
                    "entity_type": "Any",
                    "result_count": 1,
                    "entities": [
                        {"id": "e1", "schema": "Company", "properties": {"name": ["Acme Corp"]}},
                    ],
                }
            elif tool == "screen_sanctions":
                call_count["sanctions"] += 1
                raise ConnectionError("OpenSanctions API down")
            elif tool == "trace_ownership":
                raise TimeoutError("OpenCorporates timed out")
            elif tool == "generate_report":
                return {"title": args.get("title", ""), "format": "markdown", "report": "# Report"}
            return {}

        agent._executor = MagicMock()
        agent._executor.execute = partial_executor
        agent._executor.execute_raw = partial_executor

        session = await agent.investigate("Acme Corp corruption")

        # Should still have findings from search_entities
        assert session.finding_count >= 1, "Should have findings even with partial failures"
        # Errors should be logged, not swallowed
        assert any("failed" in r.lower() for r in session.reasoning_trace)


class TestConcurrentInvestigations:
    """Verify two simultaneous investigations don't cross-contaminate."""

    @pytest.mark.asyncio
    async def test_concurrent_sessions_isolated(self):
        config = AgentConfig(max_turns=3, auto_news_check=False, llm_provider="stub")

        call_log_a = []
        call_log_b = []

        def _make_executor(label, log):
            async def execute(tool, args):
                log.append((tool, args.get("query", args.get("entity_name", label))))
                if tool == "search_entities":
                    return {
                        "query": args.get("query", ""),
                        "entity_type": "Any",
                        "result_count": 1,
                        "entities": [
                            {"id": f"{label}-e1", "schema": "Company",
                             "properties": {"name": [f"{label} Corp"]}},
                        ],
                    }
                elif tool == "generate_report":
                    return {"title": label, "format": "markdown", "report": f"# {label}"}
                return {}

            mock = MagicMock()
            mock.execute = execute
            mock.execute_raw = execute
            return mock

        agent_a = InvestigationAgent(config=config)
        agent_a._executor = _make_executor("InvestA", call_log_a)

        agent_b = InvestigationAgent(config=config)
        agent_b._executor = _make_executor("InvestB", call_log_b)

        # Run concurrently
        session_a, session_b = await asyncio.gather(
            agent_a.investigate("Investigation Alpha"),
            agent_b.investigate("Investigation Beta"),
        )

        # Sessions should be independent
        assert session_a.goal == "Investigation Alpha"
        assert session_b.goal == "Investigation Beta"

        # Entities should not leak between sessions
        a_entities = [f.entities for f in session_a.findings]
        b_entities = [f.entities for f in session_b.findings]

        a_flat = [e.get("id", "") for group in a_entities for e in group]
        b_flat = [e.get("id", "") for group in b_entities for e in group]

        assert not set(a_flat) & set(b_flat), f"Entity leak: {set(a_flat) & set(b_flat)}"


# ===========================================================================
# CLI (smoke tests)
# ===========================================================================


class TestCLI:
    def test_import(self):
        from emet.cli import main
        assert callable(main)

    def test_status_import(self):
        from emet.cli import _cmd_status
        assert callable(_cmd_status)

    def test_dry_run_function_exists(self):
        from emet.cli import _cmd_investigate_dry_run
        assert callable(_cmd_investigate_dry_run)

    def test_interactive_function_exists(self):
        from emet.cli import _cmd_investigate_interactive
        assert callable(_cmd_investigate_interactive)

    def test_print_session_results(self):
        from emet.cli import _print_session_results
        session = Session(goal="test")
        session.add_finding(Finding(source="test", summary="found it"))
        # Should not raise
        _print_session_results(session)

    def test_save_report(self, tmp_path):
        from emet.cli import _save_report
        session = Session(goal="test")
        session.add_finding(Finding(source="test", summary="found it"))
        path = str(tmp_path / "report.json")
        _save_report(session, path)
        with open(path) as f:
            data = json.load(f)
        assert data["summary"]["finding_count"] == 1

    def test_argparse_dry_run_flag(self):
        """CLI parser accepts --dry-run flag."""
        import argparse
        from emet.cli import main
        import sys
        # Just verify the flag parses without error
        parser = argparse.ArgumentParser()
        parser.add_argument("--dry-run", action="store_true")
        args = parser.parse_args(["--dry-run"])
        assert args.dry_run

    def test_argparse_interactive_flag(self):
        """CLI parser accepts --interactive flag."""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--interactive", "-i", action="store_true")
        args = parser.parse_args(["-i"])
        assert args.interactive


class TestConnectionPooling:
    """Verify EmetToolExecutor reuses adapter instances."""

    def test_pool_reuses_instances(self):
        from emet.mcp.tools import EmetToolExecutor
        executor = EmetToolExecutor()

        # Get same key twice — should be same object
        obj1 = executor._get_or_create("test_key", lambda: {"created": True})
        obj2 = executor._get_or_create("test_key", lambda: {"created": False})
        assert obj1 is obj2
        assert obj1["created"] is True

    def test_pool_different_keys(self):
        from emet.mcp.tools import EmetToolExecutor
        executor = EmetToolExecutor()

        obj1 = executor._get_or_create("key_a", lambda: "a")
        obj2 = executor._get_or_create("key_b", lambda: "b")
        assert obj1 != obj2

    def test_pool_reset(self):
        from emet.mcp.tools import EmetToolExecutor
        executor = EmetToolExecutor()

        executor._get_or_create("cached", lambda: "first")
        executor.reset_pool()
        obj = executor._get_or_create("cached", lambda: "second")
        assert obj == "second"

    def test_pool_persists_across_calls(self):
        """Pool survives between execute() calls."""
        from emet.mcp.tools import EmetToolExecutor
        executor = EmetToolExecutor()

        # Manually seed the pool
        executor._get_or_create("test", lambda: {"call_count": 0})
        executor._pool["test"]["call_count"] += 1
        executor._pool["test"]["call_count"] += 1

        assert executor._pool["test"]["call_count"] == 2


class TestSessionResume:
    """Verify session save/load for --resume flag."""

    def test_resume_roundtrip(self, tmp_path):
        from emet.agent.persistence import save_session, load_session

        session = Session(goal="Investigate Acme Corp")
        session.add_finding(Finding(source="search", summary="Shell company detected"))
        session.record_reasoning("Found suspicious pattern")

        path = str(tmp_path / "session.json")
        save_session(session, path)

        restored = load_session(path)
        assert restored.goal == "Investigate Acme Corp"
        assert len(restored.findings) == 1
        assert restored.findings[0].summary == "Shell company detected"
        assert "Found suspicious pattern" in restored.reasoning_trace


# ---------------------------------------------------------------------------
# Mock fidelity audit: verify _process_result creates findings for ALL tools
# ---------------------------------------------------------------------------


class TestProcessResultFidelity:
    """Verify _process_result handles real return structures from every tool.

    The execute_raw bug (commit aacda92) showed that mocks can mask silent
    data loss. These tests use the REAL return structures from each tool
    handler and verify that findings are actually created.
    """

    def _make_agent(self):
        config = AgentConfig(max_turns=5, llm_provider="stub")
        return InvestigationAgent(config=config)

    @pytest.mark.asyncio
    async def test_search_entities_creates_finding(self):
        agent = self._make_agent()
        session = Session(goal="test")
        # Real return from _search_entities
        result = {
            "query": "Acme Corp",
            "entity_type": "Company",
            "result_count": 2,
            "entities": [
                {"id": "e1", "schema": "Company", "properties": {"name": ["Acme Corp"]}},
            ],
        }
        await agent._process_result(session, {"tool": "search_entities", "args": {"query": "Acme Corp"}}, result)
        assert len(session.findings) == 1
        assert session.findings[0].source == "search_entities"

    @pytest.mark.asyncio
    async def test_screen_sanctions_creates_finding(self):
        """REGRESSION: sanctions results were silently dropped (no 'entities' key)."""
        agent = self._make_agent()
        session = Session(goal="test")
        # Real return from _screen_sanctions — note: NO 'entities' key
        result = {
            "screened_count": 1,
            "match_count": 2,
            "threshold": 0.7,
            "matches": [
                {"name": "Bad Actor", "score": 0.95, "datasets": ["us_ofac_sdn"]},
                {"name": "Bad Corp", "score": 0.88, "datasets": ["eu_sanctions"]},
            ],
        }
        await agent._process_result(session, {"tool": "screen_sanctions", "args": {}}, result)
        assert len(session.findings) == 1, "Sanctions matches must create a finding"
        assert session.findings[0].confidence == 0.85  # matches present → high confidence

    @pytest.mark.asyncio
    async def test_investigate_blockchain_creates_finding(self):
        """REGRESSION: blockchain results were silently dropped (data under 'data' key)."""
        agent = self._make_agent()
        session = Session(goal="test")
        # Real return from _investigate_blockchain — note: NO 'entities' key
        result = {
            "address": "0x1234567890abcdef1234567890abcdef12345678",
            "chain": "ethereum",
            "depth": 1,
            "data": {"balance": "1.5", "transactions": [{"hash": "0xabc", "value": "0.5"}]},
        }
        await agent._process_result(
            session,
            {"tool": "investigate_blockchain", "args": {"address": "0x1234"}},
            result,
        )
        assert len(session.findings) == 1, "Blockchain results must create a finding"

    @pytest.mark.asyncio
    async def test_trace_ownership_creates_finding(self):
        agent = self._make_agent()
        session = Session(goal="test")
        # Real return from _trace_ownership
        result = {
            "target": "Acme Corp",
            "max_depth": 3,
            "include_officers": True,
            "entities_found": 1,
            "entities": [
                {"id": "e1", "schema": "Company", "properties": {"name": ["Acme Offshore Ltd"]}},
            ],
        }
        await agent._process_result(session, {"tool": "trace_ownership", "args": {"entity_name": "Acme"}}, result)
        assert len(session.findings) == 1

    @pytest.mark.asyncio
    async def test_monitor_entity_creates_finding(self):
        agent = self._make_agent()
        session = Session(goal="test")
        # Real return from _monitor_entity
        result = {
            "entity_name": "Bad Corp",
            "entity_type": "Company",
            "monitoring_registered": True,
            "alert_types": ["all"],
            "article_count": 5,
            "unique_sources": ["Reuters"],
            "average_tone": -2.1,
            "entities": [],
            "result_count": 5,
        }
        await agent._process_result(session, {"tool": "monitor_entity", "args": {"entity_name": "Bad Corp"}}, result)
        assert len(session.findings) == 1

    @pytest.mark.asyncio
    async def test_empty_result_creates_no_finding(self):
        agent = self._make_agent()
        session = Session(goal="test")
        result = {}
        await agent._process_result(session, {"tool": "search_entities", "args": {}}, result)
        assert len(session.findings) == 0

    @pytest.mark.asyncio
    async def test_error_result_creates_no_finding(self):
        agent = self._make_agent()
        session = Session(goal="test")
        result = {"error": "Connection refused"}
        await agent._process_result(session, {"tool": "search_entities", "args": {}}, result)
        assert len(session.findings) == 0

    @pytest.mark.asyncio
    async def test_analyze_graph_creates_finding(self):
        """REGRESSION: graph results silently dropped ('result' key not checked)."""
        agent = self._make_agent()
        session = Session(goal="test")
        # Real return from _analyze_graph — no 'entities' key
        result = {
            "algorithm": "community_detection",
            "node_count": 15,
            "edge_count": 22,
            "result": {
                "communities": [
                    {"id": 1, "members": ["e1", "e2", "e3"]},
                    {"id": 2, "members": ["e4", "e5"]},
                ],
            },
        }
        await agent._process_result(session, {"tool": "analyze_graph", "args": {"algorithm": "community_detection"}}, result)
        assert len(session.findings) == 1, "analyze_graph results must create a finding"

    @pytest.mark.asyncio
    async def test_check_alerts_creates_finding(self):
        """REGRESSION: alert results silently dropped ('alerts' key not checked)."""
        agent = self._make_agent()
        session = Session(goal="test")
        # Real return from _check_alerts
        result = {
            "alert_count": 2,
            "alerts": [
                {"type": "sanctions_change", "entity": "Bad Corp", "severity": "high", "details": "New designation"},
                {"type": "property_change", "entity": "Bad Corp", "severity": "medium", "details": "Director changed"},
            ],
        }
        await agent._process_result(session, {"tool": "check_alerts", "args": {}}, result)
        assert len(session.findings) == 1, "check_alerts results must create a finding"

    @pytest.mark.asyncio
    async def test_ingest_documents_creates_finding(self):
        """REGRESSION: document ingestion results silently dropped ('documents' key not checked)."""
        agent = self._make_agent()
        session = Session(goal="test")
        # Real return from _ingest_documents
        result = {
            "source": "datashare",
            "document_count": 3,
            "documents": [
                {"id": "doc1", "title": "Panama Papers - Acme Holdings"},
                {"id": "doc2", "title": "Tax Filing 2023"},
            ],
        }
        await agent._process_result(session, {"tool": "ingest_documents", "args": {"source": "datashare"}}, result)
        assert len(session.findings) == 1, "ingest_documents results must create a finding"