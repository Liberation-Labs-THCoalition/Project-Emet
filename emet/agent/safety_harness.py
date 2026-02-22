"""Safety harness — unified pre/post gate for the agent loop.

Composes the Kintsugi safety infrastructure into a single interface
the agent loop can call before and after every tool invocation:

    harness = SafetyHarness.from_config(config)

    # Before tool call
    verdict = harness.pre_check(tool="search_entities", args={...})
    if verdict.blocked:
        skip the call

    # After tool call
    result = harness.post_check(result_text, session_context)
    # result.scrubbed_text has PII redacted
    # result.security_flags has any injection/traversal warnings

This is the wiring layer between emet.agent and emet.security/kintsugi_engine.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class PreCheckVerdict:
    """Result of pre-execution safety checks."""
    allowed: bool = True
    blocked: bool = False
    reason: str = ""
    shield_decision: str = "ALLOW"
    capsule_valid: bool = True
    rate_limited: bool = False

    @property
    def summary(self) -> str:
        if self.allowed:
            return "ALLOW"
        return f"BLOCK: {self.reason}"


@dataclass
class PostCheckResult:
    """Result of post-execution safety checks."""
    scrubbed_text: str = ""
    pii_found: int = 0
    pii_types: list[str] = field(default_factory=list)
    security_flags: list[str] = field(default_factory=list)
    security_verdict: str = "ALLOW"
    safe: bool = True

    @property
    def summary(self) -> str:
        parts = []
        if self.pii_found:
            parts.append(f"PII: {self.pii_found} ({', '.join(self.pii_types)})")
        if self.security_flags:
            parts.append(f"Security: {', '.join(self.security_flags)}")
        return "; ".join(parts) if parts else "clean"


@dataclass
class SafetyEvent:
    """Audit log entry for a safety check."""
    timestamp: str
    check_type: str  # "pre" or "post"
    tool: str
    result: str      # "ALLOW" or "BLOCK"
    details: str


class SafetyHarness:
    """Unified safety gate composing Shield, PIIRedactor, and SecurityMonitor.

    Wraps all Kintsugi safety infrastructure into pre_check / post_check
    calls that the agent loop invokes around every tool execution.
    """

    def __init__(
        self,
        shield: Any = None,
        pii_redactor: Any = None,
        security_monitor: Any = None,
        intent_capsule: Any = None,
        enable_pii_redaction: bool = True,
        enable_shield: bool = True,
        enable_security_monitor: bool = True,
    ) -> None:
        self._shield = shield
        self._pii_redactor = pii_redactor
        self._security_monitor = security_monitor
        self._intent_capsule = intent_capsule
        self._enable_pii = enable_pii_redaction
        self._enable_shield = enable_shield
        self._enable_monitor = enable_security_monitor
        self._audit_log: list[SafetyEvent] = []

    @classmethod
    def from_defaults(cls) -> SafetyHarness:
        """Create a harness with default safety components."""
        try:
            from emet.security.shield import Shield, ShieldConfig
            shield = Shield(ShieldConfig())
        except Exception as exc:
            logger.warning("Shield unavailable: %s", exc)
            shield = None

        try:
            from emet.security.pii import PIIRedactor
            pii = PIIRedactor()
        except Exception as exc:
            logger.warning("PIIRedactor unavailable: %s", exc)
            pii = None

        try:
            from emet.security.monitor import SecurityMonitor
            monitor = SecurityMonitor()
        except Exception as exc:
            logger.warning("SecurityMonitor unavailable: %s", exc)
            monitor = None

        return cls(
            shield=shield,
            pii_redactor=pii,
            security_monitor=monitor,
        )

    @classmethod
    def disabled(cls) -> SafetyHarness:
        """Create a no-op harness (all checks pass, nothing scrubbed)."""
        return cls(
            enable_pii_redaction=False,
            enable_shield=False,
            enable_security_monitor=False,
        )

    # -------------------------------------------------------------------
    # Pre-execution checks
    # -------------------------------------------------------------------

    def pre_check(
        self,
        tool: str,
        args: dict[str, Any],
        cost: float = 0.0,
    ) -> PreCheckVerdict:
        """Run all pre-execution safety checks.

        Called before every tool invocation. Returns a verdict that
        the agent loop uses to decide whether to proceed.
        """
        verdict = PreCheckVerdict()

        # 1. Intent capsule constraint check
        if self._intent_capsule is not None:
            constraints = self._intent_capsule.constraints
            allowed_tools = constraints.get("allowed_tools", [])
            if allowed_tools and tool not in allowed_tools:
                verdict.allowed = False
                verdict.blocked = True
                verdict.capsule_valid = False
                verdict.reason = f"Tool '{tool}' not in capsule allowed_tools"
                self._log("pre", tool, "BLOCK", verdict.reason)
                return verdict

            budget = constraints.get("budget_remaining", None)
            if budget is not None and cost > budget:
                verdict.allowed = False
                verdict.blocked = True
                verdict.reason = f"Cost {cost} exceeds capsule budget {budget}"
                self._log("pre", tool, "BLOCK", verdict.reason)
                return verdict

        # 2. Shield checks (budget, rate limit, circuit breaker)
        if self._enable_shield and self._shield is not None:
            shield_result = self._shield.check_action(
                action_type=f"tool:{tool}",
                cost=cost,
                tool=tool,
            )
            verdict.shield_decision = shield_result.decision.value
            if shield_result.decision.value == "BLOCK":
                verdict.allowed = False
                verdict.blocked = True
                verdict.rate_limited = "rate limit" in shield_result.reason.lower()
                verdict.reason = shield_result.reason
                self._log("pre", tool, "BLOCK", verdict.reason)
                return verdict

        # 3. Security monitor — scan args for injection
        if self._enable_monitor and self._security_monitor is not None:
            args_text = json.dumps(args, default=str)
            sec_result = self._security_monitor.check_text(args_text)
            if sec_result.verdict.value == "BLOCK":
                verdict.allowed = False
                verdict.blocked = True
                verdict.reason = f"Security monitor: {sec_result.reason}"
                self._log("pre", tool, "BLOCK", verdict.reason)
                return verdict

        self._log("pre", tool, "ALLOW", "all checks passed")
        return verdict

    # -------------------------------------------------------------------
    # Post-execution checks
    # -------------------------------------------------------------------

    def post_check(
        self,
        text: str,
        tool: str = "",
    ) -> PostCheckResult:
        """Run all post-execution safety checks.

        Called after tool execution. Scrubs PII from output and
        scans for security concerns in returned data.
        """
        result = PostCheckResult(scrubbed_text=text)

        # 1. PII redaction
        if self._enable_pii and self._pii_redactor is not None:
            try:
                redaction = self._pii_redactor.redact(text)
                result.scrubbed_text = redaction.redacted_text
                result.pii_found = redaction.detections_count
                result.pii_types = redaction.types_found
                if result.pii_found > 0:
                    logger.info(
                        "PII redacted from %s output: %d items (%s)",
                        tool, result.pii_found, ", ".join(result.pii_types),
                    )
            except Exception as exc:
                logger.warning("PII redaction failed: %s", exc)

        # 2. Security scan of output
        if self._enable_monitor and self._security_monitor is not None:
            try:
                sec_result = self._security_monitor.check_text(result.scrubbed_text)
                result.security_verdict = sec_result.verdict.value
                if sec_result.verdict.value != "ALLOW":
                    result.security_flags.append(sec_result.reason)
                    result.safe = sec_result.verdict.value != "BLOCK"
                    logger.warning(
                        "Security flag in %s output: %s",
                        tool, sec_result.reason,
                    )
            except Exception as exc:
                logger.warning("Security scan failed: %s", exc)

        self._log(
            "post", tool,
            "CLEAN" if result.safe else "FLAGGED",
            result.summary,
        )
        return result

    # -------------------------------------------------------------------
    # Shield feedback (for circuit breaker)
    # -------------------------------------------------------------------

    def report_tool_success(self, tool: str) -> None:
        """Tell the shield a tool call succeeded (resets circuit breaker)."""
        if self._shield is not None:
            try:
                self._shield.circuit_breaker.record_result(tool, success=True)
            except Exception:
                pass

    def report_tool_failure(self, tool: str) -> None:
        """Tell the shield a tool call failed (increments circuit breaker)."""
        if self._shield is not None:
            try:
                self._shield.circuit_breaker.record_result(tool, success=False)
            except Exception:
                pass

    def record_spend(self, cost: float) -> None:
        """Record actual spend after a successful tool call."""
        if self._shield is not None:
            try:
                self._shield.budget.record_spend(cost)
            except Exception:
                pass

    # -------------------------------------------------------------------
    # Audit
    # -------------------------------------------------------------------

    @property
    def audit_log(self) -> list[SafetyEvent]:
        return list(self._audit_log)

    def audit_summary(self) -> dict[str, Any]:
        """Machine-readable audit summary."""
        blocks = [e for e in self._audit_log if "BLOCK" in e.result]
        pii_events = [e for e in self._audit_log if "PII" in e.details]
        return {
            "total_checks": len(self._audit_log),
            "blocks": len(blocks),
            "pii_redactions": len(pii_events),
            "events": [
                {"check": e.check_type, "tool": e.tool, "result": e.result}
                for e in self._audit_log
            ],
        }

    def _log(self, check_type: str, tool: str, result: str, details: str) -> None:
        self._audit_log.append(SafetyEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            check_type=check_type,
            tool=tool,
            result=result,
            details=details,
        ))
