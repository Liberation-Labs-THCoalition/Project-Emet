"""Kintsugi Governance Layer -- Phase 2.

Consensus gating and observability for agent actions.
"""

from ftm_harness.governance.consensus import (
    ConsensusPriority,
    ConsentCategory,
    ConsentItem,
    ConsentStatus,
    ConsensusConfig,
    ConsensusGate,
)
from ftm_harness.governance.otel import (
    KintsugiTracer,
    OTelConfig,
    SpanContext,
)

__all__ = [
    # consensus
    "ConsensusPriority",
    "ConsentCategory",
    "ConsentItem",
    "ConsentStatus",
    "ConsensusConfig",
    "ConsensusGate",
    # otel
    "KintsugiTracer",
    "OTelConfig",
    "SpanContext",
]
