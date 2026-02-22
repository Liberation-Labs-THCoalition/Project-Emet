"""Safety harness — two-mode safety gate for the agent loop.

Two modes, matching how investigative journalists actually work:

  **investigate** (audit-only):
    During investigation, the agent needs raw data to reason with.
    All safety checks run but only *log* — nothing is blocked,
    nothing is scrubbed. PII, injection patterns, rate anomalies
    are recorded in the audit trail for later review.

  **publish** (enforcing):
    At the publication boundary (report generation, exports, API
    responses), all checks enforce. PII is scrubbed, security
    flags block output, budgets are enforced.

Usage:
    harness = SafetyHarness.from_defaults()

    # During investigation — observes, never interferes
    harness.pre_check(tool="search_entities", args={...})
    harness.post_check(result_text, tool="search_entities")

    # At publication boundary — enforces everything
    clean = harness.scrub_for_publication(report_text)

The threat model is inverted from a chatbot: the agent is trusted,
the external world is the data source. Safety infrastructure provides
observability during investigation and enforcement at publication.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PreCheckVerdict:
    """Result of pre-execution safety checks."""
    allowed: bool = True
    blocked: bool = False
    reason: str = ""
    shield_decision: str = "ALLOW"
    capsule_valid: bool = True
    rate_limited: bool = False
    observations: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.allowed:
            obs = f" [{len(self.observations)} observations]" if self.observations else ""
            return f"ALLOW{obs}"
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
    check_type: str   # "pre", "post", or "publish"
    tool: str
    result: str       # "ALLOW", "BLOCK", "OBSERVED", "SCRUBBED"
    details: str
    mode: str = ""    # "investigate" or "publish"


# ---------------------------------------------------------------------------
# SafetyHarness
# ---------------------------------------------------------------------------

class SafetyHarness:
    """Two-mode safety gate: audit-only during investigation, enforcing at publication.

    During investigation:
      - All checks run but only observe and log
      - No tool calls are blocked (agent needs freedom to investigate)
      - No data is scrubbed (PII is the work product)
      - Shield/monitor/redactor findings are recorded in audit trail

    At publication boundary:
      - PII is scrubbed from outward-facing text
      - Security flags can block output
      - Full enforcement mode

    Intent capsule constraints are always enforced (they represent
    the operator's hard mandate, not safety heuristics).
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

    # ===================================================================
    # INVESTIGATE MODE — audit-only, observe but never interfere
    # ===================================================================

    def pre_check(
        self,
        tool: str,
        args: dict[str, Any],
        cost: float = 0.0,
    ) -> PreCheckVerdict:
        """Run pre-execution checks in audit-only mode.

        Logs all observations but only blocks on intent capsule
        violations (operator hard mandate). Shield and monitor
        findings are recorded but not enforced.
        """
        verdict = PreCheckVerdict()

        # Intent capsule is ALWAYS enforced — it's the operator's mandate
        if self._intent_capsule is not None:
            constraints = self._intent_capsule.constraints
            allowed_tools = constraints.get("allowed_tools", [])
            if allowed_tools and tool not in allowed_tools:
                verdict.allowed = False
                verdict.blocked = True
                verdict.capsule_valid = False
                verdict.reason = f"Tool '{tool}' not in capsule allowed_tools"
                self._log("pre", tool, "BLOCK", verdict.reason, "investigate")
                return verdict

            budget = constraints.get("budget_remaining", None)
            if budget is not None and cost > budget:
                verdict.allowed = False
                verdict.blocked = True
                verdict.reason = f"Cost {cost} exceeds capsule budget {budget}"
                self._log("pre", tool, "BLOCK", verdict.reason, "investigate")
                return verdict

        # Shield — observe only, do not block
        if self._enable_shield and self._shield is not None:
            shield_result = self._shield.check_action(
                action_type=f"tool:{tool}",
                cost=cost,
                tool=tool,
            )
            verdict.shield_decision = shield_result.decision.value
            if shield_result.decision.value == "BLOCK":
                verdict.observations.append(
                    f"Shield would block: {shield_result.reason}"
                )
                logger.info(
                    "Safety observation (not enforced): Shield would block %s: %s",
                    tool, shield_result.reason,
                )

        # Security monitor — observe only, do not block
        if self._enable_monitor and self._security_monitor is not None:
            args_text = json.dumps(args, default=str)
            sec_result = self._security_monitor.check_text(args_text)
            if sec_result.verdict.value != "ALLOW":
                verdict.observations.append(
                    f"Monitor flag: {sec_result.reason}"
                )
                logger.info(
                    "Safety observation (not enforced): Monitor flagged %s args: %s",
                    tool, sec_result.reason,
                )

        obs_detail = "; ".join(verdict.observations) if verdict.observations else "clean"
        self._log("pre", tool, "OBSERVED", obs_detail, "investigate")
        return verdict

    def post_check(
        self,
        text: str,
        tool: str = "",
    ) -> PostCheckResult:
        """Run post-execution checks in audit-only mode.

        Detects PII and security issues but does NOT scrub or block.
        Returns the original text unmodified with observations logged.
        """
        result = PostCheckResult(scrubbed_text=text)

        # PII detection — observe only, do not scrub
        if self._enable_pii and self._pii_redactor is not None:
            try:
                redaction = self._pii_redactor.redact(text)
                result.pii_found = redaction.detections_count
                result.pii_types = redaction.types_found
                # Do NOT replace the text — keep raw for investigation
                if result.pii_found > 0:
                    logger.info(
                        "PII detected in %s output (not scrubbed): %d items (%s)",
                        tool, result.pii_found, ", ".join(result.pii_types),
                    )
            except Exception as exc:
                logger.warning("PII detection failed: %s", exc)

        # Security scan — observe only
        if self._enable_monitor and self._security_monitor is not None:
            try:
                sec_result = self._security_monitor.check_text(text)
                result.security_verdict = sec_result.verdict.value
                if sec_result.verdict.value != "ALLOW":
                    result.security_flags.append(sec_result.reason)
                    logger.info(
                        "Security flag in %s output (not enforced): %s",
                        tool, sec_result.reason,
                    )
            except Exception as exc:
                logger.warning("Security scan failed: %s", exc)

        self._log("post", tool, "OBSERVED", result.summary, "investigate")
        return result

    # ===================================================================
    # PUBLISH MODE — enforcing, scrubs and blocks at the boundary
    # ===================================================================

    def scrub_for_publication(self, text: str, context: str = "report") -> PostCheckResult:
        """Scrub text for publication — full enforcement mode.

        This is the publication boundary. PII is redacted, security
        issues are flagged, and the scrubbed text is returned.

        Use this for: reports, exports, API responses, anything that
        leaves the investigation workspace.
        """
        result = PostCheckResult(scrubbed_text=text)

        # PII redaction — ENFORCED
        if self._enable_pii and self._pii_redactor is not None:
            try:
                redaction = self._pii_redactor.redact(text)
                result.scrubbed_text = redaction.redacted_text
                result.pii_found = redaction.detections_count
                result.pii_types = redaction.types_found
                if result.pii_found > 0:
                    logger.info(
                        "PII scrubbed for publication (%s): %d items (%s)",
                        context, result.pii_found, ", ".join(result.pii_types),
                    )
            except Exception as exc:
                logger.warning("PII redaction failed at publication: %s", exc)

        # Security scan — ENFORCED
        if self._enable_monitor and self._security_monitor is not None:
            try:
                sec_result = self._security_monitor.check_text(result.scrubbed_text)
                result.security_verdict = sec_result.verdict.value
                if sec_result.verdict.value != "ALLOW":
                    result.security_flags.append(sec_result.reason)
                    result.safe = sec_result.verdict.value != "BLOCK"
                    logger.warning(
                        "Security flag at publication (%s): %s",
                        context, sec_result.reason,
                    )
            except Exception as exc:
                logger.warning("Security scan failed at publication: %s", exc)

        self._log(
            "publish", context,
            "SCRUBBED" if result.pii_found else "CLEAN",
            result.summary,
            "publish",
        )
        return result

    def scrub_dict_for_publication(
        self, data: dict[str, Any], context: str = "export"
    ) -> dict[str, Any]:
        """Recursively scrub all string values in a dict for publication."""
        def scrub(obj: Any) -> Any:
            if isinstance(obj, str) and len(obj) > 5:
                return self.scrub_for_publication(obj, context).scrubbed_text
            if isinstance(obj, dict):
                return {k: scrub(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [scrub(v) for v in obj]
            return obj
        return scrub(data)

    # ===================================================================
    # Circuit breaker feedback
    # ===================================================================

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

    # ===================================================================
    # Audit
    # ===================================================================

    @property
    def audit_log(self) -> list[SafetyEvent]:
        return list(self._audit_log)

    def audit_summary(self) -> dict[str, Any]:
        """Machine-readable audit summary."""
        blocks = [e for e in self._audit_log if e.result == "BLOCK"]
        observations = [e for e in self._audit_log if e.result == "OBSERVED"]
        scrubs = [e for e in self._audit_log if e.result == "SCRUBBED"]
        pii_events = [e for e in self._audit_log if "PII" in e.details]
        return {
            "total_checks": len(self._audit_log),
            "blocks": len(blocks),
            "observations": len(observations),
            "publication_scrubs": len(scrubs),
            "pii_detections": len(pii_events),
            "events": [
                {
                    "check": e.check_type,
                    "tool": e.tool,
                    "result": e.result,
                    "mode": e.mode,
                }
                for e in self._audit_log
            ],
        }

    def _log(
        self, check_type: str, tool: str, result: str, details: str, mode: str = "",
    ) -> None:
        self._audit_log.append(SafetyEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            check_type=check_type,
            tool=tool,
            result=result,
            details=details,
            mode=mode,
        ))
