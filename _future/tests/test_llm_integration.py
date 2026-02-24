"""Tests for emet.skills.llm_integration — LLM integration for skill chips.

Tests cover:
  - parse_json_response: code fence stripping, embedded JSON extraction
  - SkillLLMHelper: analyze, analyze_structured, extract_entities,
    classify_risk, generate_narrative, verify_claims
  - TokenUsage: tracking and summary
  - Evidence formatting

All tests use StubClient — no external LLM required.
"""

import json
import pytest

from emet.cognition.llm_base import LLMProvider, LLMResponse
from emet.cognition.llm_stub import StubClient
from emet.skills.llm_integration import (
    SkillLLMHelper,
    TokenUsage,
    parse_json_response,
    SYSTEM_PROMPTS,
)


# ---------------------------------------------------------------------------
# parse_json_response tests
# ---------------------------------------------------------------------------


class TestParseJsonResponse:
    def test_clean_json(self):
        result = parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_array(self):
        result = parse_json_response('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_code_fenced_json(self):
        result = parse_json_response('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_code_fenced_no_language(self):
        result = parse_json_response('```\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_json_with_preamble(self):
        text = 'Here is the analysis:\n{"risk": "high", "score": 0.8}'
        result = parse_json_response(text)
        assert result == {"risk": "high", "score": 0.8}

    def test_json_with_postamble(self):
        text = '{"risk": "high"}\nLet me know if you need more.'
        result = parse_json_response(text)
        assert result == {"risk": "high"}

    def test_invalid_json_returns_none(self):
        result = parse_json_response("This is not JSON at all")
        assert result is None

    def test_empty_string(self):
        result = parse_json_response("")
        assert result is None

    def test_nested_json(self):
        text = '{"entities": [{"name": "Alice", "type": "PERSON"}]}'
        result = parse_json_response(text)
        assert result["entities"][0]["name"] == "Alice"

    def test_whitespace_handling(self):
        result = parse_json_response('  \n  {"key": "value"}  \n  ')
        assert result == {"key": "value"}


# ---------------------------------------------------------------------------
# TokenUsage tests
# ---------------------------------------------------------------------------


class TestTokenUsage:
    def test_empty_usage(self):
        usage = TokenUsage()
        assert usage.total_tokens == 0
        assert usage.call_count == 0
        assert usage.total_cost_usd == 0.0

    def test_record_usage(self):
        usage = TokenUsage()
        response = LLMResponse(
            text="test", model="stub/fast", provider=LLMProvider.STUB,
            input_tokens=100, output_tokens=50, cost_usd=0.001,
        )
        usage.record(response, "test_call")

        assert usage.input_tokens == 100
        assert usage.output_tokens == 50
        assert usage.total_tokens == 150
        assert usage.call_count == 1
        assert usage.total_cost_usd == 0.001

    def test_multiple_records(self):
        usage = TokenUsage()
        for i in range(3):
            response = LLMResponse(
                text="test", model="stub", provider=LLMProvider.STUB,
                input_tokens=100, output_tokens=50, cost_usd=0.01,
            )
            usage.record(response, f"call_{i}")

        assert usage.call_count == 3
        assert usage.total_tokens == 450
        assert len(usage.calls) == 3

    def test_summary(self):
        usage = TokenUsage()
        response = LLMResponse(
            text="test", model="stub", provider=LLMProvider.STUB,
            input_tokens=200, output_tokens=100, cost_usd=0.005,
        )
        usage.record(response)

        summary = usage.summary()
        assert summary["total_tokens"] == 300
        assert summary["call_count"] == 1
        assert summary["total_cost_usd"] == 0.005


# ---------------------------------------------------------------------------
# System prompts tests
# ---------------------------------------------------------------------------


class TestSystemPrompts:
    def test_all_domains_have_prompts(self):
        expected_domains = [
            "investigative_base", "entity_extraction", "corporate_analysis",
            "story_development", "verification", "financial_analysis",
        ]
        for domain in expected_domains:
            assert domain in SYSTEM_PROMPTS, f"Missing system prompt for {domain}"
            assert len(SYSTEM_PROMPTS[domain]) > 50, f"System prompt for {domain} too short"

    def test_investigative_base_includes_key_principles(self):
        prompt = SYSTEM_PROMPTS["investigative_base"]
        assert "evidence" in prompt.lower()
        assert "confidence" in prompt.lower()
        assert "fabricate" in prompt.lower()  # "Never fabricate"


# ---------------------------------------------------------------------------
# SkillLLMHelper tests (using StubClient)
# ---------------------------------------------------------------------------


class TestSkillLLMHelper:
    @pytest.fixture
    def stub_client(self):
        return StubClient(default_response='{"result": "analyzed", "confidence": 0.8}')

    @pytest.fixture
    def helper(self, stub_client):
        return SkillLLMHelper(stub_client, domain="investigative_base")

    @pytest.mark.asyncio
    async def test_analyze_basic(self, helper, stub_client):
        result = await helper.analyze("Analyze this entity")
        assert isinstance(result, str)
        assert len(result) > 0
        assert stub_client.call_log[-1]["method"] == "complete"

    @pytest.mark.asyncio
    async def test_analyze_with_evidence(self, helper, stub_client):
        evidence = [
            {"id": "e1", "schema": "Person", "properties": {"name": ["Alice"], "country": ["UK"]}},
        ]
        result = await helper.analyze("Analyze this", evidence=evidence)
        # Evidence should have been included in the prompt
        last_call = stub_client.call_log[-1]
        assert "Alice" in last_call["prompt"] or "evidence" in last_call["prompt"].lower()

    @pytest.mark.asyncio
    async def test_analyze_structured(self, helper):
        result = await helper.analyze_structured(
            "Assess risk",
            output_schema={"risk_level": "str", "explanation": "str"},
        )
        # StubClient returns default response which may not parse as our schema
        # but the method should not crash
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_token_tracking(self, helper):
        await helper.analyze("Test prompt", purpose="test_purpose")
        assert helper.usage.call_count == 1
        assert helper.usage.calls[0]["purpose"] == "test_purpose"

    @pytest.mark.asyncio
    async def test_multiple_calls_tracked(self, helper):
        await helper.analyze("First call")
        await helper.analyze("Second call")
        await helper.analyze("Third call")
        assert helper.usage.call_count == 3

    @pytest.mark.asyncio
    async def test_shared_usage_tracker(self, stub_client):
        tracker = TokenUsage()
        h1 = SkillLLMHelper(stub_client, usage_tracker=tracker)
        h2 = SkillLLMHelper(stub_client, usage_tracker=tracker)

        await h1.analyze("Call from h1")
        await h2.analyze("Call from h2")

        assert tracker.call_count == 2  # Both contribute to shared tracker

    @pytest.mark.asyncio
    async def test_extract_entities_returns_list(self):
        # Use a client that returns entity-like JSON
        client = StubClient(
            default_response='[{"name": "Alice", "type": "PERSON", "confidence": 0.9}]'
        )
        helper = SkillLLMHelper(client)
        entities = await helper.extract_entities("Alice went to London")
        assert isinstance(entities, list)

    @pytest.mark.asyncio
    async def test_classify_risk_returns_dict(self, helper):
        result = await helper.classify_risk(
            entity_data={"name": "Shell Corp", "country": "VG"},
            risk_factors=["Offshore jurisdiction", "No directors"],
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_generate_narrative_returns_dict(self, helper):
        result = await helper.generate_narrative(
            findings={"key_players": [{"name": "Viktor"}]},
            angle="corruption",
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_verify_claims_returns_list(self):
        client = StubClient(
            default_response='[{"claim": "test", "status": "unverifiable", "confidence": 0.3}]'
        )
        helper = SkillLLMHelper(client)
        results = await helper.verify_claims(
            claims=["Entity X is connected to Entity Y"],
            evidence=[{"id": "e1", "schema": "Person", "properties": {"name": ["Entity X"]}}],
        )
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Evidence formatting tests
# ---------------------------------------------------------------------------


class TestEvidenceFormatting:
    def test_format_entities(self):
        entities = [
            {
                "id": "e1", "schema": "Company",
                "properties": {"name": ["Acme Corp"], "country": ["VG"]},
                "_provenance": {"source": "opencorporates"},
            },
        ]
        text = SkillLLMHelper._format_evidence(entities)
        assert "Acme Corp" in text
        assert "Company" in text
        assert "VG" in text
        assert "opencorporates" in text

    def test_format_empty(self):
        text = SkillLLMHelper._format_evidence([])
        assert "No evidence" in text

    def test_format_truncates_large_lists(self):
        entities = [
            {"id": f"e{i}", "schema": "Person", "properties": {"name": [f"Person {i}"]}}
            for i in range(50)
        ]
        text = SkillLLMHelper._format_evidence(entities, max_entities=10)
        assert "40 more entities" in text

    def test_format_handles_missing_props(self):
        entities = [
            {"id": "e1", "schema": "Unknown", "properties": {}},
        ]
        text = SkillLLMHelper._format_evidence(entities)
        assert "Unknown" in text
        # Should not crash on missing name
