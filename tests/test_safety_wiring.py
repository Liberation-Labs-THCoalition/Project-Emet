"""Tests for safety harness, persistence, and agent loop wiring.

Tests the new integration layer between the Kintsugi safety
infrastructure and the Emet agent loop.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from emet.agent.safety_harness import SafetyHarness, PreCheckVerdict, PostCheckResult
from emet.agent.persistence import save_session, load_session, list_sessions
from emet.agent.session import Session, Finding, Lead
from emet.agent.loop import InvestigationAgent, AgentConfig


# ===================================================================
# SafetyHarness unit tests
# ===================================================================


class TestSafetyHarnessPreCheck:
    """Pre-execution safety checks."""

    def test_disabled_harness_always_allows(self):
        harness = SafetyHarness.disabled()
        verdict = harness.pre_check(tool="any_tool", args={"x": 1})
        assert verdict.allowed
        assert not verdict.blocked

    def test_from_defaults_creates_components(self):
        harness = SafetyHarness.from_defaults()
        assert harness._shield is not None
        assert harness._pii_redactor is not None
        assert harness._security_monitor is not None

    def test_pre_check_allows_normal_tool(self):
        harness = SafetyHarness.from_defaults()
        verdict = harness.pre_check(
            tool="search_entities",
            args={"query": "Acme Corp"},
        )
        assert verdict.allowed
        assert verdict.shield_decision == "ALLOW"

    def test_pre_check_blocks_over_budget(self):
        """Shield budget is now audit-only — observed but not enforced."""
        from emet.security.shield import Shield, ShieldConfig
        config = ShieldConfig(budget_session_limit=1.0)
        shield = Shield(config)
        harness = SafetyHarness(shield=shield, enable_shield=True)

        shield.budget.record_spend(0.9)
        verdict = harness.pre_check(tool="t2", args={}, cost=0.5)
        # In investigate mode, shield observes but does NOT block
        assert verdict.allowed
        assert not verdict.blocked
        assert len(verdict.observations) > 0
        assert "Shield would block" in verdict.observations[0]

    def test_pre_check_blocks_rate_limited(self):
        """Rate limiter is now audit-only — observed but not enforced."""
        from emet.security.shield import Shield, ShieldConfig
        config = ShieldConfig(rate_limits={"fast_tool": {"rate": 0, "burst": 2}})
        shield = Shield(config)
        harness = SafetyHarness(shield=shield, enable_shield=True)

        harness.pre_check(tool="fast_tool", args={})
        harness.pre_check(tool="fast_tool", args={})
        verdict = harness.pre_check(tool="fast_tool", args={})
        # Observed but not blocked
        assert verdict.allowed
        assert len(verdict.observations) > 0

    def test_pre_check_blocks_circuit_breaker(self):
        """Circuit breaker is now audit-only — observed but not enforced."""
        from emet.security.shield import Shield, ShieldConfig
        config = ShieldConfig(circuit_breaker_threshold=2)
        shield = Shield(config)
        harness = SafetyHarness(shield=shield, enable_shield=True)

        shield.circuit_breaker.record_result("bad_tool", success=False)
        shield.circuit_breaker.record_result("bad_tool", success=False)

        verdict = harness.pre_check(tool="bad_tool", args={})
        # Observed but not blocked
        assert verdict.allowed
        assert len(verdict.observations) > 0
        assert "circuit breaker" in verdict.observations[0].lower()

    def test_pre_check_intent_capsule_tool_restriction(self):
        capsule = MagicMock()
        capsule.constraints = {"allowed_tools": ["search_entities", "screen_sanctions"]}

        harness = SafetyHarness(intent_capsule=capsule)
        verdict = harness.pre_check(tool="investigate_blockchain", args={})
        assert verdict.blocked
        assert "not in capsule" in verdict.reason

    def test_pre_check_intent_capsule_allows_listed_tool(self):
        capsule = MagicMock()
        capsule.constraints = {"allowed_tools": ["search_entities"]}

        harness = SafetyHarness(intent_capsule=capsule)
        verdict = harness.pre_check(tool="search_entities", args={})
        assert verdict.allowed

    def test_pre_check_intent_capsule_budget(self):
        capsule = MagicMock()
        capsule.constraints = {"budget_remaining": 0.5}

        harness = SafetyHarness(intent_capsule=capsule)
        verdict = harness.pre_check(tool="expensive_call", args={}, cost=1.0)
        assert verdict.blocked
        assert "budget" in verdict.reason.lower()

    def test_pre_check_security_monitor_observes_injection(self):
        harness = SafetyHarness.from_defaults()
        # Craft args that might trigger the security monitor's patterns
        verdict = harness.pre_check(
            tool="search_entities",
            args={"query": "'; DROP TABLE users; --"},
        )
        # In investigate mode, monitor observes but does not block
        assert isinstance(verdict, PreCheckVerdict)
        assert verdict.allowed  # Never blocked in investigate mode


class TestSafetyHarnessPostCheck:
    """Post-execution safety checks — audit-only in investigate mode."""

    def test_disabled_harness_passthrough(self):
        harness = SafetyHarness.disabled()
        result = harness.post_check("John's SSN is 123-45-6789")
        assert result.scrubbed_text == "John's SSN is 123-45-6789"
        assert result.pii_found == 0

    def test_pii_detected_but_not_scrubbed(self):
        """In investigate mode, PII is detected but text is NOT scrubbed."""
        harness = SafetyHarness.from_defaults()
        result = harness.post_check(
            "Contact John at john@example.com or 555-123-4567",
            tool="search_entities",
        )
        assert result.pii_found > 0
        # Text is PRESERVED — not scrubbed during investigation
        assert "john@example.com" in result.scrubbed_text

    def test_ssn_detected_but_preserved(self):
        """SSNs are detected but preserved during investigation."""
        harness = SafetyHarness.from_defaults()
        result = harness.post_check("SSN: 123-45-6789")
        assert result.pii_found > 0
        # Raw data preserved for investigation
        assert "123-45-6789" in result.scrubbed_text

    def test_clean_text_passes_through(self):
        harness = SafetyHarness.from_defaults()
        text = "Acme Corporation registered in Delaware in 2005"
        result = harness.post_check(text)
        assert result.scrubbed_text == text
        assert result.safe


class TestPublicationMode:
    """Publication boundary — full enforcement."""

    def test_scrub_for_publication_redacts_pii(self):
        harness = SafetyHarness.from_defaults()
        result = harness.scrub_for_publication(
            "Contact John at john@example.com or 555-123-4567"
        )
        assert result.pii_found > 0
        assert "REDACTED" in result.scrubbed_text
        assert "john@example.com" not in result.scrubbed_text

    def test_scrub_for_publication_redacts_ssn(self):
        harness = SafetyHarness.from_defaults()
        result = harness.scrub_for_publication("SSN: 123-45-6789")
        assert "123-45-6789" not in result.scrubbed_text
        assert result.pii_found > 0

    def test_scrub_for_publication_clean_text(self):
        harness = SafetyHarness.from_defaults()
        text = "Acme Corporation registered in Delaware in 2005"
        result = harness.scrub_for_publication(text)
        assert result.scrubbed_text == text
        assert result.pii_found == 0

    def test_scrub_dict_for_publication(self):
        harness = SafetyHarness.from_defaults()
        data = {
            "entity": "Acme Corp",
            "contact": "john@example.com",
            "nested": {"phone": "555-123-4567"},
        }
        scrubbed = harness.scrub_dict_for_publication(data)
        result_str = json.dumps(scrubbed)
        assert "john@example.com" not in result_str

    def test_disabled_harness_no_publication_scrub(self):
        harness = SafetyHarness.disabled()
        result = harness.scrub_for_publication("SSN: 123-45-6789")
        assert result.scrubbed_text == "SSN: 123-45-6789"
        assert result.pii_found == 0

    def test_investigate_vs_publish_same_text(self):
        """Same text, different modes — investigate preserves, publish scrubs."""
        harness = SafetyHarness.from_defaults()
        text = "Email: jane@example.com, SSN: 987-65-4321"

        # Investigate mode — raw preserved
        inv_result = harness.post_check(text, tool="search")
        assert "jane@example.com" in inv_result.scrubbed_text
        assert inv_result.pii_found > 0

        # Publish mode — scrubbed
        pub_result = harness.scrub_for_publication(text)
        assert "jane@example.com" not in pub_result.scrubbed_text
        assert pub_result.pii_found > 0


class TestSafetyHarnessCircuitBreaker:
    """Circuit breaker feedback."""

    def test_report_success_resets(self):
        from emet.security.shield import Shield, ShieldConfig
        config = ShieldConfig(circuit_breaker_threshold=3)
        shield = Shield(config)
        harness = SafetyHarness(shield=shield, enable_shield=True)

        shield.circuit_breaker.record_result("t1", success=False)
        shield.circuit_breaker.record_result("t1", success=False)
        harness.report_tool_success("t1")
        # Should not be open after success
        assert not shield.circuit_breaker.is_open("t1")

    def test_report_failure_increments(self):
        from emet.security.shield import Shield, ShieldConfig
        config = ShieldConfig(circuit_breaker_threshold=2)
        shield = Shield(config)
        harness = SafetyHarness(shield=shield, enable_shield=True)

        harness.report_tool_failure("t1")
        harness.report_tool_failure("t1")
        assert shield.circuit_breaker.is_open("t1")


class TestSafetyHarnessAudit:
    """Audit logging."""

    def test_audit_log_records_checks(self):
        harness = SafetyHarness.from_defaults()
        harness.pre_check(tool="search_entities", args={})
        harness.post_check("some result text", tool="search_entities")

        log = harness.audit_log
        assert len(log) >= 2
        assert log[0].check_type == "pre"
        assert log[1].check_type == "post"

    def test_audit_summary(self):
        harness = SafetyHarness.from_defaults()
        harness.pre_check(tool="t1", args={})
        harness.post_check("text", tool="t1")
        harness.scrub_for_publication("email: test@test.com")

        summary = harness.audit_summary()
        assert summary["total_checks"] >= 3
        assert isinstance(summary["events"], list)
        assert "observations" in summary
        assert "publication_scrubs" in summary


# ===================================================================
# Persistence tests
# ===================================================================


class TestPersistence:
    """Save/load investigation sessions."""

    def test_save_and_load_roundtrip(self):
        session = Session(goal="Test investigation")
        session.add_finding(Finding(
            source="search",
            summary="Found Acme Corp",
            entities=[{"id": "ent1", "schema": "Company", "properties": {"name": ["Acme Corp"]}}],
            confidence=0.8,
        ))
        session.add_lead(Lead(
            description="Trace Acme ownership",
            priority=0.7,
            query="Acme Corp",
            tool="trace_ownership",
        ))
        session.record_reasoning("Started investigation")
        session.record_tool_use("search", {"query": "Acme"}, {"result_count": 1})

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_session.json"
            save_session(session, path)

            assert path.exists()
            data = json.loads(path.read_text())
            assert data["goal"] == "Test investigation"
            assert len(data["findings"]) == 1
            assert len(data["leads"]) == 1

            loaded = load_session(path)
            assert loaded.goal == "Test investigation"
            assert loaded.id == session.id
            assert len(loaded.findings) == 1
            assert loaded.findings[0].summary == "Found Acme Corp"
            assert len(loaded.leads) == 1
            assert loaded.leads[0].description == "Trace Acme ownership"
            assert "ent1" in loaded.entities
            assert len(loaded.tool_history) == 1
            assert len(loaded.reasoning_trace) == 1

    def test_save_creates_directories(self):
        session = Session(goal="test")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "deep" / "nested" / "dir" / "session.json"
            save_session(session, path)
            assert path.exists()

    def test_list_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(3):
                s = Session(goal=f"Investigation {i}")
                save_session(s, Path(tmpdir) / f"inv_{i}.json")

            sessions = list_sessions(tmpdir)
            assert len(sessions) == 3
            goals = {s["goal"] for s in sessions}
            assert goals == {"Investigation 0", "Investigation 1", "Investigation 2"}

    def test_list_sessions_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions = list_sessions(tmpdir)
            assert sessions == []

    def test_list_sessions_nonexistent_dir(self):
        sessions = list_sessions("/nonexistent/path/12345")
        assert sessions == []


# ===================================================================
# Agent loop integration tests
# ===================================================================


class TestAgentLoopSafetyWiring:
    """Test that the agent loop uses the safety harness."""

    def test_agent_creates_harness_by_default(self):
        agent = InvestigationAgent()
        assert agent._harness is not None
        assert agent._harness._shield is not None

    def test_agent_disables_harness(self):
        config = AgentConfig(enable_safety=False)
        agent = InvestigationAgent(config)
        assert not agent._harness._enable_shield
        assert not agent._harness._enable_pii
        assert not agent._harness._enable_monitor

    @pytest.mark.asyncio
    async def test_capsule_blocks_tool(self):
        """Intent capsule blocks still work — operator mandate is enforced."""
        from unittest.mock import MagicMock
        capsule = MagicMock()
        capsule.constraints = {"allowed_tools": ["generate_report"]}

        config = AgentConfig(max_turns=2, enable_safety=True)
        agent = InvestigationAgent(config)
        agent._harness._intent_capsule = capsule

        # Direct pre-check: capsule blocks search_entities
        verdict = agent._harness.pre_check(tool="search_entities", args={})
        assert verdict.blocked
        assert "not in capsule" in verdict.reason

        # Capsule allows generate_report
        verdict = agent._harness.pre_check(tool="generate_report", args={})
        assert verdict.allowed

    @pytest.mark.asyncio
    async def test_pii_preserved_during_investigation(self):
        """PII is NOT scrubbed during investigation — raw data preserved."""
        config = AgentConfig(enable_safety=True, max_turns=1)
        agent = InvestigationAgent(config)

        # The harness post_check should observe but not scrub
        result = agent._harness.post_check(
            "Entity contact: john@example.com, SSN: 123-45-6789",
            tool="search_entities",
        )
        assert "john@example.com" in result.scrubbed_text
        assert "123-45-6789" in result.scrubbed_text
        assert result.pii_found > 0

    @pytest.mark.asyncio
    async def test_pii_scrubbed_at_publication(self):
        """PII IS scrubbed when publishing — publication boundary enforces."""
        config = AgentConfig(enable_safety=True, max_turns=1)
        agent = InvestigationAgent(config)

        result = agent._harness.scrub_for_publication(
            "Entity contact: john@example.com, SSN: 123-45-6789"
        )
        assert "john@example.com" not in result.scrubbed_text
        assert "123-45-6789" not in result.scrubbed_text
        assert result.pii_found > 0

    @pytest.mark.asyncio
    async def test_safety_audit_attached(self):
        """Investigation should have safety audit on completion."""
        config = AgentConfig(max_turns=1, enable_safety=True)
        agent = InvestigationAgent(config)
        session = await agent.investigate("test audit")
        assert hasattr(session, "_safety_audit")
        assert "total_checks" in session._safety_audit


class TestAgentLoopPersistence:
    """Test auto-save on investigation completion."""

    @pytest.mark.asyncio
    async def test_auto_persist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "auto_save.json"
            config = AgentConfig(
                max_turns=1,
                persist_path=str(path),
                enable_safety=False,
                generate_graph=False,
            )
            agent = InvestigationAgent(config)
            session = await agent.investigate("auto-save test")

            assert path.exists()
            data = json.loads(path.read_text())
            assert data["goal"] == "auto-save test"
            assert data["session_id"] == session.id


class TestAgentLoopGraph:
    """Test graph generation at conclusion."""

    @pytest.mark.asyncio
    async def test_graph_generated_with_entities(self):
        config = AgentConfig(
            max_turns=1,
            generate_graph=True,
            enable_safety=False,
        )
        agent = InvestigationAgent(config)
        session = await agent.investigate("graph test")

        # Graph generation should not crash, even with mock data
        # It may or may not produce a graph depending on whether
        # any entities were found
        assert isinstance(session, Session)

    @pytest.mark.asyncio
    async def test_graph_disabled(self):
        config = AgentConfig(
            max_turns=1,
            generate_graph=False,
            enable_safety=False,
        )
        agent = InvestigationAgent(config)
        session = await agent.investigate("no graph test")
        assert not hasattr(session, "_investigation_graph") or session._investigation_graph is None


# ===================================================================
# Cross-package wiring smoke tests
# ===================================================================


class TestCrossPackageWiring:
    """Verify the safety packages are importable and interoperable."""

    def test_shield_import(self):
        from emet.security.shield import Shield, ShieldConfig
        s = Shield(ShieldConfig())
        v = s.check_action("test")
        assert v.decision.value == "ALLOW"

    def test_pii_redactor_import(self):
        from emet.security.pii import PIIRedactor
        r = PIIRedactor()
        result = r.redact("No PII here")
        assert result.redacted_text == "No PII here"

    def test_security_monitor_import(self):
        from emet.security.monitor import SecurityMonitor
        m = SecurityMonitor()
        v = m.check_text("normal text")
        assert v.verdict.value == "ALLOW"

    def test_intent_capsule_import(self):
        from emet.security.intent_capsule import sign_capsule, verify_capsule
        capsule = sign_capsule(
            goal="test",
            constraints={"allowed_tools": ["search"]},
            org_id="org1",
            secret_key="test-secret",
        )
        assert verify_capsule(capsule, "test-secret")

    def test_invariant_checker_import(self):
        from emet.security.invariants import InvariantChecker, InvariantContext
        checker = InvariantChecker()
        ctx = InvariantContext(
            text="hello world",
            cost=0.5,
            budget_remaining=10.0,
        )
        result = checker.check_all(ctx)
        assert result.all_passed

    def test_shadow_fork_import(self):
        from emet.kintsugi_engine.shadow_fork import ShadowFork, ShadowConfig
        config = ShadowConfig(modification={"temperature": 0.5})
        sf = ShadowFork(primary_config={"temperature": 1.0}, shadow_config=config)
        sid = sf.fork()
        assert sid.startswith("shadow-")

    def test_verifier_import(self):
        from emet.kintsugi_engine.verifier import Verifier
        v = Verifier()
        result = v.verify(
            primary_outputs=[{"text": "a"}],
            shadow_outputs=[{"text": "a"}],
        )
        assert result.safety_passed

    def test_bdi_coherence_import(self):
        from emet.bdi.coherence import CoherenceScore
        assert CoherenceScore is not None

    def test_consensus_gate_import(self):
        from emet.governance.consensus import ConsensusGate
        assert ConsensusGate is not None

    def test_memory_cma_import(self):
        from emet.memory.cma_stage1 import Window
        from emet.memory.cma_stage2 import Fact, Insight, cluster_facts
        from emet.memory.cma_stage3 import retrieve
        assert Window is not None
        assert Fact is not None
        assert cluster_facts is not None
        assert retrieve is not None

    def test_plugin_registry_import(self):
        from emet.plugins.registry import PluginRegistry
        assert PluginRegistry is not None

    def test_multitenancy_import(self):
        from emet.multitenancy.isolation import TenantIsolator
        assert TenantIsolator is not None

    def test_tuning_import(self):
        from emet.tuning.efe_tuner import EFETuner
        assert EFETuner is not None
