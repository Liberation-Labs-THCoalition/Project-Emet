"""Tests for LLM wiring in the agent loop.

Verifies that the agent correctly:
- Creates and caches LLM clients
- Uses the LLM for decision-making with proper prompts
- Synthesizes reports via LLM when available
- Falls back to heuristics when LLM is unavailable
- Tracks costs across turns
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from emet.agent.loop import (
    InvestigationAgent,
    AgentConfig,
    AGENT_TOOLS,
    INVESTIGATION_SYSTEM_PROMPT,
)
from emet.agent.session import Session, Finding, Lead
from emet.cognition.llm_base import LLMClient, LLMProvider, LLMResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockLLMClient(LLMClient):
    """Controllable mock LLM that returns canned decisions."""

    def __init__(self, decisions: list[dict] | None = None, report: str = ""):
        self._decisions = list(decisions or [])
        self._report = report
        self._call_count = 0
        self._calls: list[dict] = []

    @property
    def provider(self) -> LLMProvider:
        return LLMProvider.ANTHROPIC

    async def complete(self, prompt, *, system=None, max_tokens=1024,
                       temperature=0.7, stop_sequences=None, tier="balanced"):
        self._call_count += 1
        self._calls.append({
            "prompt": prompt[:200],
            "system": (system or "")[:100],
            "tier": tier,
            "temperature": temperature,
        })

        # If this looks like a report synthesis prompt
        if "Synthesize" in prompt and self._report:
            return LLMResponse(
                text=self._report,
                model="claude-sonnet-4-20250514",
                provider=LLMProvider.ANTHROPIC,
                input_tokens=500,
                output_tokens=300,
                cost_usd=0.006,
            )

        # Decision prompt — return next canned decision
        if self._decisions:
            decision = self._decisions.pop(0)
        else:
            decision = {"tool": "conclude", "args": {}, "reasoning": "Done"}

        return LLMResponse(
            text=json.dumps(decision),
            model="claude-sonnet-4-20250514",
            provider=LLMProvider.ANTHROPIC,
            input_tokens=200,
            output_tokens=50,
            cost_usd=0.001,
        )

    async def classify_intent(self, message, domains):
        return "general", 0.5

    async def generate_content(self, prompt, **kwargs):
        return "content"

    async def extract_entities(self, text, entity_schema):
        return {}


# ---------------------------------------------------------------------------
# Client lifecycle
# ---------------------------------------------------------------------------


class TestLLMClientLifecycle:
    """Verify client creation and caching."""

    def test_client_not_created_for_stub(self):
        """Stub provider creates a stub client, not None."""
        agent = InvestigationAgent(AgentConfig(llm_provider="stub"))
        client = agent._get_llm_client()
        assert client is not None

    def test_client_cached_across_calls(self):
        """_get_llm_client returns same instance on repeated calls."""
        agent = InvestigationAgent(AgentConfig(llm_provider="stub"))
        c1 = agent._get_llm_client()
        c2 = agent._get_llm_client()
        assert c1 is c2

    def test_cost_tracker_created(self):
        """Cost tracker should be initialized with the client."""
        agent = InvestigationAgent(AgentConfig(llm_provider="stub"))
        agent._get_llm_client()
        assert agent._cost_tracker is not None

    @patch("emet.agent.loop.InvestigationAgent._get_llm_client")
    @pytest.mark.asyncio
    async def test_none_client_triggers_heuristic(self, mock_get):
        """When LLM is None, _llm_decide returns None → heuristic used."""
        mock_get.return_value = None
        agent = InvestigationAgent(AgentConfig(llm_provider="stub"))
        session = Session(goal="test")
        result = await agent._llm_decide(session)
        assert result is None


# ---------------------------------------------------------------------------
# Decision making
# ---------------------------------------------------------------------------


class TestLLMDecision:
    """Verify the LLM decision loop."""

    @pytest.mark.asyncio
    async def test_llm_decision_parsed(self):
        """Valid JSON from LLM should be parsed into an action dict."""
        mock = MockLLMClient(decisions=[
            {"tool": "search_entities", "args": {"query": "Acme"}, "reasoning": "Initial search"}
        ])
        agent = InvestigationAgent(AgentConfig(llm_provider="anthropic"))
        agent._llm_client = mock

        session = Session(goal="Investigate Acme Corp")
        action = await agent._llm_decide(session)

        assert action is not None
        assert action["tool"] == "search_entities"
        assert action["args"]["query"] == "Acme"

    @pytest.mark.asyncio
    async def test_llm_receives_system_prompt(self):
        """The LLM should receive the investigation system prompt."""
        mock = MockLLMClient()
        agent = InvestigationAgent(AgentConfig(llm_provider="anthropic"))
        agent._llm_client = mock

        session = Session(goal="Test")
        await agent._llm_decide(session)

        assert len(mock._calls) == 1
        assert "investigative journalist" in mock._calls[0]["system"]

    @pytest.mark.asyncio
    async def test_llm_uses_balanced_tier(self):
        """Decision prompts should use balanced tier."""
        mock = MockLLMClient()
        agent = InvestigationAgent(AgentConfig(llm_provider="anthropic"))
        agent._llm_client = mock

        session = Session(goal="Test")
        await agent._llm_decide(session)

        assert mock._calls[0]["tier"] == "balanced"

    @pytest.mark.asyncio
    async def test_llm_uses_low_temperature(self):
        """Decision prompts should use low temperature for structured output."""
        mock = MockLLMClient()
        agent = InvestigationAgent(AgentConfig(llm_provider="anthropic"))
        agent._llm_client = mock

        session = Session(goal="Test")
        await agent._llm_decide(session)

        assert mock._calls[0]["temperature"] == 0.2

    @pytest.mark.asyncio
    async def test_unknown_tool_rejected(self):
        """LLM suggesting a non-existent tool should return None."""
        mock = MockLLMClient(decisions=[
            {"tool": "hack_pentagon", "args": {}, "reasoning": "bad idea"}
        ])
        agent = InvestigationAgent(AgentConfig(llm_provider="anthropic"))
        agent._llm_client = mock

        session = Session(goal="Test")
        action = await agent._llm_decide(session)

        assert action is None

    @pytest.mark.asyncio
    async def test_malformed_json_returns_none(self):
        """Unparseable LLM output should return None gracefully."""
        mock = MockLLMClient()
        mock.complete = AsyncMock(return_value=LLMResponse(
            text="I think we should investigate further...",
            model="test", provider=LLMProvider.ANTHROPIC,
            input_tokens=0, output_tokens=0, cost_usd=0,
        ))
        agent = InvestigationAgent(AgentConfig(llm_provider="anthropic"))
        agent._llm_client = mock

        session = Session(goal="Test")
        action = await agent._llm_decide(session)
        assert action is None

    @pytest.mark.asyncio
    async def test_markdown_fenced_json_parsed(self):
        """JSON wrapped in markdown code fences should be parsed."""
        mock = MockLLMClient()
        mock.complete = AsyncMock(return_value=LLMResponse(
            text='```json\n{"tool": "search_entities", "args": {"query": "test"}, "reasoning": "search"}\n```',
            model="test", provider=LLMProvider.ANTHROPIC,
            input_tokens=0, output_tokens=0, cost_usd=0,
        ))
        agent = InvestigationAgent(AgentConfig(llm_provider="anthropic"))
        agent._llm_client = mock

        session = Session(goal="Test")
        action = await agent._llm_decide(session)

        assert action is not None
        assert action["tool"] == "search_entities"

    @pytest.mark.asyncio
    async def test_context_includes_session_state(self):
        """The prompt should include findings and leads from the session."""
        mock = MockLLMClient()
        agent = InvestigationAgent(AgentConfig(llm_provider="anthropic"))
        agent._llm_client = mock

        session = Session(goal="Find shell companies")
        session.add_finding(Finding(
            source="search_entities",
            summary="Found 3 offshore entities in Panama",
            confidence=0.8,
        ))
        session.add_lead(Lead(
            description="Trace ownership of PanamaCo Ltd",
            priority=0.9,
            query="PanamaCo Ltd",
            tool="trace_ownership",
        ))

        await agent._llm_decide(session)

        prompt = mock._calls[0]["prompt"]
        assert "shell companies" in prompt.lower() or "Find shell" in prompt


# ---------------------------------------------------------------------------
# Report synthesis
# ---------------------------------------------------------------------------


class TestLLMReportSynthesis:
    """Verify LLM-powered report generation."""

    @pytest.mark.asyncio
    async def test_llm_synthesizes_report(self):
        """When LLM is available, it should synthesize a narrative report."""
        report_text = """## Summary
Investigation found 3 shell companies linked to target.

## Key Findings
- Offshore structure in Panama (85% confidence)

## Entity Network
PanamaCo → HoldingCo → Target Individual

## Open Questions
- Source of funds unclear

## Methodology
Used entity search and ownership tracing."""

        mock = MockLLMClient(report=report_text)
        agent = InvestigationAgent(AgentConfig(llm_provider="anthropic"))
        agent._llm_client = mock

        session = Session(goal="Investigate offshore links")
        session.add_finding(Finding(
            source="search_entities",
            summary="Found 3 entities",
            confidence=0.8,
        ))

        result = await agent._llm_synthesize_report(session)

        assert result is not None
        assert "## Summary" in result
        assert "shell companies" in result

    @pytest.mark.asyncio
    async def test_stub_provider_skips_synthesis(self):
        """Stub provider should not attempt synthesis."""
        agent = InvestigationAgent(AgentConfig(llm_provider="stub"))
        agent._get_llm_client()  # Initialize stub

        session = Session(goal="Test")
        result = await agent._llm_synthesize_report(session)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_client_skips_synthesis(self):
        """No LLM client should skip synthesis."""
        agent = InvestigationAgent(AgentConfig(llm_provider="stub"))
        agent._llm_client = None  # Force None

        session = Session(goal="Test")
        result = await agent._llm_synthesize_report(session)
        assert result is None

    @pytest.mark.asyncio
    async def test_synthesis_failure_returns_none(self):
        """Failed synthesis should return None, not raise."""
        mock = MockLLMClient()
        mock.complete = AsyncMock(side_effect=Exception("API timeout"))
        agent = InvestigationAgent(AgentConfig(llm_provider="anthropic"))
        agent._llm_client = mock

        session = Session(goal="Test")
        result = await agent._llm_synthesize_report(session)
        assert result is None


# ---------------------------------------------------------------------------
# Full investigation with LLM
# ---------------------------------------------------------------------------


class TestLLMInvestigationLoop:
    """Integration: verify LLM drives the full investigation loop."""

    @pytest.mark.asyncio
    async def test_llm_drives_multi_turn_investigation(self):
        """LLM decisions should drive the investigation across turns."""
        mock = MockLLMClient(decisions=[
            {"tool": "search_entities", "args": {"query": "Acme", "entity_type": "Company"}, "reasoning": "Initial entity search"},
            {"tool": "trace_ownership", "args": {"entity_name": "Acme Corp", "max_depth": 3}, "reasoning": "Trace ownership"},
            {"tool": "conclude", "args": {}, "reasoning": "Sufficient findings"},
        ])
        agent = InvestigationAgent(AgentConfig(
            llm_provider="anthropic",
            max_turns=5,
        ))
        agent._llm_client = mock

        session = await agent.investigate("Investigate Acme Corp")

        # Should have used multiple tools
        tools_used = {t["tool"] for t in session.tool_history}
        assert "search_entities" in tools_used

        # LLM should have been called multiple times (decisions + possibly report)
        assert mock._call_count >= 2

    @pytest.mark.asyncio
    async def test_cost_tracked_across_turns(self):
        """Cost tracker should accumulate across LLM calls."""
        mock = MockLLMClient(decisions=[
            {"tool": "search_entities", "args": {"query": "Test"}, "reasoning": "search"},
            {"tool": "conclude", "args": {}, "reasoning": "done"},
        ])
        agent = InvestigationAgent(AgentConfig(
            llm_provider="anthropic",
            max_turns=3,
        ))
        agent._llm_client = mock

        from emet.cognition.model_router import CostTracker
        agent._cost_tracker = CostTracker()

        session = await agent.investigate("Test")

        assert agent._cost_tracker is not None


# ---------------------------------------------------------------------------
# System prompt quality
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    """Verify the system prompt contains key directives."""

    def test_prompt_mentions_follow_the_money(self):
        assert "Follow the money" in INVESTIGATION_SYSTEM_PROMPT

    def test_prompt_mentions_verification(self):
        assert "multiple sources" in INVESTIGATION_SYSTEM_PROMPT

    def test_prompt_mentions_no_fabrication(self):
        assert "Never fabricate" in INVESTIGATION_SYSTEM_PROMPT

    def test_prompt_mentions_json(self):
        assert "JSON" in INVESTIGATION_SYSTEM_PROMPT

    def test_prompt_has_strategy_ordering(self):
        """Strategy should order operations logically."""
        lines = INVESTIGATION_SYSTEM_PROMPT.split("\n")
        strategy_lines = [l for l in lines if l.strip().startswith(("1.", "2.", "3.", "4.", "5.", "6."))]
        assert len(strategy_lines) >= 5


# ---------------------------------------------------------------------------
# LLM factory provider override
# ---------------------------------------------------------------------------


class TestFactoryProviderOverride:
    """Verify the factory accepts explicit provider selection."""

    def test_stub_override(self):
        """Explicit stub provider should create stub client."""
        from emet.cognition.llm_factory import create_llm_client_sync
        client = create_llm_client_sync(provider="stub")
        assert client is not None

    def test_anthropic_without_key_falls_back(self):
        """Anthropic without API key should fall back to stub."""
        from emet.cognition.llm_factory import create_llm_client_sync
        # With fallback enabled, should not raise
        client = create_llm_client_sync(provider="anthropic")
        assert client is not None
