"""Live integration tests for the investigation agent pipeline.

Tests the full investigation loop with real API data, real LLM decisions,
audit archives, cross-session memory, and report generation.

Run with: pytest -m live tests/live/
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Heuristic-driven investigation (no LLM key needed)
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.live_slow
class TestHeuristicInvestigation:

    @pytest.mark.asyncio
    async def test_known_sanctioned_entity(self, require_opensanctions, tmp_dir):
        """Full investigation of a known sanctioned entity with heuristics."""
        from emet.agent.loop import InvestigationAgent, AgentConfig

        config = AgentConfig(
            max_turns=8,
            llm_provider="stub",
            tool_timeout_seconds=30.0,
            memory_dir=tmp_dir,
        )
        agent = InvestigationAgent(config=config)
        session = await agent.investigate("Viktor Bout arms trafficking network")

        assert session.finding_count >= 1, "Should find something about Viktor Bout"
        assert session.turn_count >= 2
        tools_used = {t["tool"] for t in session.tool_history}
        assert "search_entities" in tools_used

    @pytest.mark.asyncio
    async def test_clean_entity_low_sanctions_confidence(self, require_any_source, tmp_dir):
        """Non-sanctioned entity should not produce high-confidence sanctions hits."""
        from emet.agent.loop import InvestigationAgent, AgentConfig

        config = AgentConfig(
            max_turns=5,
            llm_provider="stub",
            tool_timeout_seconds=30.0,
            memory_dir=tmp_dir,
        )
        agent = InvestigationAgent(config=config)
        session = await agent.investigate("Microsoft Corporation")

        sanctions_findings = [
            f for f in session.findings
            if "sanction" in f.source.lower() and f.entities
        ]
        for f in sanctions_findings:
            assert f.confidence < 0.8, \
                f"Microsoft should not have high-confidence sanctions hit: {f}"

    @pytest.mark.asyncio
    async def test_investigation_produces_report(self, require_any_source, tmp_dir):
        """Investigation should produce a text report."""
        from emet.agent.loop import InvestigationAgent, AgentConfig

        config = AgentConfig(
            max_turns=6,
            llm_provider="stub",
            tool_timeout_seconds=30.0,
            memory_dir=tmp_dir,
        )
        agent = InvestigationAgent(config=config)
        session = await agent.investigate("Gazprom corporate structure")

        assert session.report, "Should generate a report"
        assert len(session.report) > 100, "Report should be substantive"


# ---------------------------------------------------------------------------
# LLM-driven investigation (requires Anthropic key)
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.live_llm
@pytest.mark.live_slow
class TestLLMInvestigation:

    @pytest.mark.asyncio
    async def test_llm_decides_next_actions(self, require_anthropic, require_any_source, tmp_dir):
        """Real Claude decides investigation strategy."""
        from emet.agent.loop import InvestigationAgent, AgentConfig

        config = AgentConfig(
            max_turns=6,
            llm_provider="anthropic",
            tool_timeout_seconds=30.0,
            memory_dir=tmp_dir,
        )
        agent = InvestigationAgent(config=config)
        session = await agent.investigate("Wirecard AG accounting fraud network")

        # LLM should have made at least some decisions
        summary = session.summary()
        llm_decisions = summary.get("decisions_llm", 0)
        assert llm_decisions >= 1, "Claude should have made at least 1 decision"

        tools_used = {t["tool"] for t in session.tool_history}
        assert "search_entities" in tools_used
        assert session.finding_count >= 1

    @pytest.mark.asyncio
    async def test_llm_reasoning_in_trace(self, require_anthropic, require_any_source, tmp_dir):
        """LLM reasoning should appear in session trace."""
        from emet.agent.loop import InvestigationAgent, AgentConfig

        config = AgentConfig(
            max_turns=4,
            llm_provider="anthropic",
            tool_timeout_seconds=30.0,
            memory_dir=tmp_dir,
        )
        agent = InvestigationAgent(config=config)
        session = await agent.investigate("Roman Abramovich sanctions exposure")

        # Reasoning trace should include [llm] tagged entries
        llm_traces = [t for t in session.reasoning_trace if "[llm]" in t]
        assert len(llm_traces) >= 1, "Should have LLM-tagged reasoning entries"


# ---------------------------------------------------------------------------
# Audit archive (requires any data source)
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestAuditArchiveLive:

    @pytest.mark.asyncio
    async def test_audit_captures_live_tool_results(self, require_any_source, tmp_dir):
        """Audit archive should contain full tool results from real APIs."""
        from emet.agent.loop import InvestigationAgent, AgentConfig
        from emet.agent.audit import read_archive, verify_archive

        config = AgentConfig(
            max_turns=4,
            llm_provider="stub",
            tool_timeout_seconds=30.0,
            memory_dir=tmp_dir,
        )
        agent = InvestigationAgent(config=config)
        session = await agent.investigate("Deutsche Bank")

        # Find audit files
        audit_dir = Path(tmp_dir) / "audit"
        archives = list(audit_dir.glob("*.jsonl.gz"))
        assert len(archives) == 1, "Should produce exactly 1 audit archive"

        # Verify integrity
        valid, manifest = verify_archive(archives[0])
        assert valid, "SHA-256 integrity check should pass"

        # Read events
        events = read_archive(archives[0])
        tool_calls = [e for e in events if e["type"] == "tool_call"]

        # Real tool calls should have substantive results
        assert len(tool_calls) >= 2, "Should have at least search + one more tool"
        for tc in tool_calls:
            assert "result" in tc["data"], f"Tool call {tc['data']['tool']} missing result"
            assert "duration_ms" in tc["data"], "Should have timing"

        # Session should reference audit manifest
        assert hasattr(session, "_audit_manifest")
        assert session._audit_manifest["sha256"] == manifest.sha256

    @pytest.mark.asyncio
    async def test_audit_captures_llm_exchanges(self, require_anthropic, require_any_source, tmp_dir):
        """Audit should capture full LLM prompt/response when using Claude."""
        from emet.agent.loop import InvestigationAgent, AgentConfig
        from emet.agent.audit import read_archive

        config = AgentConfig(
            max_turns=3,
            llm_provider="anthropic",
            tool_timeout_seconds=30.0,
            memory_dir=tmp_dir,
        )
        agent = InvestigationAgent(config=config)
        session = await agent.investigate("Oleg Deripaska business network")

        audit_dir = Path(tmp_dir) / "audit"
        archives = list(audit_dir.glob("*.jsonl.gz"))
        events = read_archive(archives[0])

        llm_events = [e for e in events if e["type"] == "llm_exchange"]
        assert len(llm_events) >= 1, "Should capture at least 1 LLM exchange"

        for le in llm_events:
            assert le["data"]["system_prompt"], "Should have system prompt"
            assert le["data"]["user_prompt"], "Should have user prompt"
            assert le["data"]["raw_response"], "Should have raw response"


# ---------------------------------------------------------------------------
# Cross-session memory (requires any data source)
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.live_slow
class TestCrossSessionMemory:

    @pytest.mark.asyncio
    async def test_second_investigation_recalls_first(self, require_any_source, tmp_dir):
        """Second investigation about same entity should recall prior findings."""
        from emet.agent.loop import InvestigationAgent, AgentConfig

        config = AgentConfig(
            max_turns=4,
            llm_provider="stub",
            tool_timeout_seconds=30.0,
            memory_dir=tmp_dir,
        )

        # Investigation 1: initial search
        agent1 = InvestigationAgent(config=config)
        session1 = await agent1.investigate("Gazprom corporate ownership")

        # Verify session was saved
        session_files = list(Path(tmp_dir).glob("*.json"))
        assert len(session_files) >= 1, "Session should be saved to memory_dir"

        # Investigation 2: related query — should recall
        agent2 = InvestigationAgent(config=config)
        session2 = await agent2.investigate("Gazprom sanctions exposure")

        # Prior intelligence should be present
        prior = getattr(session2, "_prior_intelligence", [])
        assert len(prior) >= 1, \
            "Second investigation should recall findings from first"


# ---------------------------------------------------------------------------
# PDF report generation (requires any data source)
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestPDFReportLive:

    @pytest.mark.asyncio
    async def test_pdf_from_live_investigation(self, require_any_source, tmp_dir):
        """Generate a PDF report from a real investigation."""
        from emet.agent.loop import InvestigationAgent, AgentConfig
        from emet.export.pdf import PDFReport
        from emet.export.markdown import InvestigationReport

        config = AgentConfig(
            max_turns=5,
            llm_provider="stub",
            tool_timeout_seconds=30.0,
            memory_dir=tmp_dir,
        )
        agent = InvestigationAgent(config=config)
        session = await agent.investigate("HSBC money laundering")

        # Build InvestigationReport from session
        all_entities = []
        for f in session.findings:
            all_entities.extend(f.entities)

        report_data = InvestigationReport(
            title=session.goal,
            summary=session.report or f"Investigation: {session.goal}",
            entities=all_entities,
            data_sources=[
                {"name": t["tool"], "query": str(t.get("args", {}))}
                for t in session.tool_history
            ],
        )

        # Generate PDF
        pdf_path = Path(tmp_dir) / "report.pdf"
        report = PDFReport()
        report.generate(
            report=report_data,
            output_path=str(pdf_path),
        )

        assert pdf_path.exists(), "PDF file should exist"
        assert pdf_path.stat().st_size > 1000, "PDF should be substantive"

        # Verify it's a valid PDF
        header = pdf_path.read_bytes()[:5]
        assert header == b"%PDF-", "Should be a valid PDF file"


# ---------------------------------------------------------------------------
# Blockchain (requires Etherscan key)
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.live_blockchain
class TestBlockchainLive:

    @pytest.mark.asyncio
    async def test_ethereum_address_lookup(self, require_blockchain):
        """Query a well-known Ethereum address via MCP tool."""
        from emet.mcp.tools import EmetToolExecutor

        executor = EmetToolExecutor()
        # Vitalik's public address
        result = await executor.execute_raw("investigate_blockchain", {
            "address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
            "chain": "ethereum",
        })

        assert "data" in result
        assert result["chain"] == "ethereum"


# ---------------------------------------------------------------------------
# MCP tool dispatch (validates param fixes)
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestMCPToolDispatch:

    @pytest.mark.asyncio
    async def test_screen_sanctions_llm_params(self, require_opensanctions):
        """Sanctions screening with LLM-style params (entity_name string)."""
        from emet.mcp.tools import EmetToolExecutor

        executor = EmetToolExecutor()
        result = await executor.execute_raw("screen_sanctions", {
            "entity_name": "Gaddafi",
            "entity_type": "Person",
        })

        assert "matches" in result or "results" in result or "error" not in result

    @pytest.mark.asyncio
    async def test_analyze_graph_llm_params(self, require_any_source):
        """Graph analysis with LLM-style params (analysis_type alias)."""
        from emet.mcp.tools import EmetToolExecutor

        executor = EmetToolExecutor()
        # First get some entities
        search = await executor.execute_raw("search_entities", {
            "query": "Shell companies BVI",
            "limit": 10,
        })

        entities = search.get("entities", [])
        if not entities:
            pytest.skip("No entities returned for graph analysis test")

        result = await executor.execute_raw("analyze_graph", {
            "analysis_type": "key_players",
            "entities": entities,
        })

        assert "error" not in result

    @pytest.mark.asyncio
    async def test_trace_ownership(self, require_any_source):
        """Ownership tracing through MCP tool."""
        from emet.mcp.tools import EmetToolExecutor

        executor = EmetToolExecutor()
        result = await executor.execute_raw("trace_ownership", {
            "entity_name": "Shell plc",
            "max_depth": 2,
        })

        assert "entities_found" in result
        assert result["target"] == "Shell plc"

    @pytest.mark.asyncio
    async def test_monitor_entity(self):
        """News monitoring via GDELT (no key needed)."""
        from emet.mcp.tools import EmetToolExecutor

        executor = EmetToolExecutor()
        result = await executor.execute_raw("monitor_entity", {
            "entity_name": "Elon Musk",
            "timespan": "7d",
        })

        # GDELT should find news about Elon Musk
        assert "article_count" in result
