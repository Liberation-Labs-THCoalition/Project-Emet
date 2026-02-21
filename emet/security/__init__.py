"""Kintsugi Security Layer -- Phase 1 Stream 1B.

Exports all public classes and key functions from the security subsystem.
"""

from emet.security.intent_capsule import (
    AlignmentResult,
    CycleVerdict,
    IntentCapsule,
    mission_alignment_check,
    sign_capsule,
    verify_capsule,
    verify_cycle,
)
from emet.security.invariants import (
    InvariantChecker,
    InvariantContext,
    InvariantResult,
)
from emet.security.monitor import (
    SecurityMonitor,
    SecurityVerdict,
    Severity,
    Verdict,
)
from emet.security.pii import (
    PIIDetection,
    PIIRedactor,
    RedactionResult,
    pii_redaction_middleware,
)
from emet.security.sandbox import (
    SandboxContext,
    SandboxResult,
    ShadowSandbox,
)
from emet.security.shield import (
    BudgetEnforcer,
    CircuitBreaker,
    EgressValidator,
    RateLimiter,
    Shield,
    ShieldConfig,
    ShieldDecision,
    ShieldVerdict,
)

__all__ = [
    # intent_capsule
    "AlignmentResult",
    "CycleVerdict",
    "IntentCapsule",
    "mission_alignment_check",
    "sign_capsule",
    "verify_capsule",
    "verify_cycle",
    # shield
    "BudgetEnforcer",
    "CircuitBreaker",
    "EgressValidator",
    "RateLimiter",
    "Shield",
    "ShieldConfig",
    "ShieldDecision",
    "ShieldVerdict",
    # monitor
    "SecurityMonitor",
    "SecurityVerdict",
    "Severity",
    "Verdict",
    # sandbox
    "SandboxContext",
    "SandboxResult",
    "ShadowSandbox",
    # pii
    "PIIDetection",
    "PIIRedactor",
    "RedactionResult",
    "pii_redaction_middleware",
    # invariants
    "InvariantChecker",
    "InvariantContext",
    "InvariantResult",
]
