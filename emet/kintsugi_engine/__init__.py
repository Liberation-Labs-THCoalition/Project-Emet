"""Kintsugi Engine -- shadow verification and safe self-modification.

Re-exports all public symbols from the engine sub-modules.
"""

from emet.kintsugi_engine.shadow_fork import (
    ShadowConfig,
    ShadowFork,
    ShadowState,
    ShadowStatus,
)
from emet.kintsugi_engine.verifier import (
    VerificationResult,
    Verifier,
    VerifierConfig,
    VerifierVerdict,
)
from emet.kintsugi_engine.promoter import (
    GoldenTrace,
    PromotionAction,
    Promoter,
    PromoterConfig,
)
from emet.kintsugi_engine.evolution import (
    EvolutionConfig,
    EvolutionManager,
    ModificationProposal,
    ModificationScope,
)
from emet.kintsugi_engine.calibration import (
    CalibrationConfig,
    CalibrationEngine,
    CalibrationRecord,
    CalibrationReport,
    DriftDirection,
)
from emet.kintsugi_engine.bloom_adapter import (
    AdversarialScenario,
    BloomAdapter,
    BloomConfig,
    BloomResult,
    ScenarioType,
)
from emet.kintsugi_engine.drift import (
    DriftCategory,
    DriftConfig,
    DriftDetector,
    DriftEvent,
)

__all__ = [
    # Stream 3A
    "ShadowConfig",
    "ShadowFork",
    "ShadowState",
    "ShadowStatus",
    "VerificationResult",
    "Verifier",
    "VerifierConfig",
    "VerifierVerdict",
    "GoldenTrace",
    "PromotionAction",
    "Promoter",
    "PromoterConfig",
    # Stream 3B
    "EvolutionConfig",
    "EvolutionManager",
    "ModificationProposal",
    "ModificationScope",
    "CalibrationConfig",
    "CalibrationEngine",
    "CalibrationRecord",
    "CalibrationReport",
    "DriftDirection",
    # Stream 3C
    "AdversarialScenario",
    "BloomAdapter",
    "BloomConfig",
    "BloomResult",
    "ScenarioType",
    "DriftCategory",
    "DriftConfig",
    "DriftDetector",
    "DriftEvent",
]
