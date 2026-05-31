"""Expected Free Energy (EFE) calculation for investigative journalism.

Implements a lightweight EFE scorer used by the orchestrator to rank
candidate investigation policies. Lower total EFE indicates the preferred
policy (least expected surprise / best alignment with desired outcomes).

v2 (May 2026): Added state factor decomposition and observation model
for proper Active Inference grounding. Reference: arXiv:2412.10425.

Journalism-specific weight profiles bias decisions toward:
- High epistemic value for entity search (prefer gathering more data)
- High risk aversion for publication decisions (minimize false positives)
- Balanced profiles for cross-referencing (weigh evidence carefully)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Weight profiles
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EFEWeights:
    """Component weights for the EFE calculation.

    Must approximately sum to 1.0 (tolerance 0.05).
    """

    risk: float
    ambiguity: float
    epistemic: float

    def __post_init__(self) -> None:
        total = self.risk + self.ambiguity + self.epistemic
        if not math.isclose(total, 1.0, abs_tol=0.05):
            raise ValueError(
                f"EFEWeights must sum to ~1.0; got {total:.4f} "
                f"(risk={self.risk}, ambiguity={self.ambiguity}, "
                f"epistemic={self.epistemic})"
            )


# ---------------------------------------------------------------------------
# Active Inference world model (v2)
# ---------------------------------------------------------------------------


class ObservationModality(str, Enum):
    """Channels through which the agent observes the environment."""
    TOOL_OUTPUT = "tool_output"
    USER_FEEDBACK = "user_feedback"
    METRIC_STREAM = "metric_stream"
    BDI_BELIEF = "bdi_belief"
    DRIFT_SIGNAL = "drift_signal"
    EXTERNAL_EVENT = "external_event"
    SOURCE_DATA = "source_data"
    FOIA_RESPONSE = "foia_response"


@dataclass
class StateFactor:
    """A single factored dimension of the environment state.

    Active Inference decomposes the world model into independent state
    factors, each observed through one or more modalities. This enables
    targeted belief updating: when an observation arrives on one modality,
    only the relevant state factors need revision.
    """
    name: str
    value: Any = None
    confidence: float = 0.5
    observation_sources: List[ObservationModality] = field(default_factory=list)
    last_updated: Optional[str] = None
    prior: Any = None

    def update_from_observation(
        self, observed_value: Any, observation_confidence: float = 0.8
    ) -> None:
        if self.value is None:
            self.value = observed_value
            self.confidence = observation_confidence
        else:
            blend = observation_confidence / (self.confidence + observation_confidence)
            try:
                old_val = float(self.value)
                new_val = float(observed_value)
                self.value = old_val * (1 - blend) + new_val * blend
            except (TypeError, ValueError):
                if observation_confidence > self.confidence:
                    self.value = observed_value
            self.confidence = min(self.confidence + observation_confidence * 0.5, 1.0)
        from datetime import datetime, timezone
        self.last_updated = datetime.now(timezone.utc).isoformat()


@dataclass
class WorldModel:
    """Factored environment model for Active Inference.

    Decomposes the agent's understanding into independent state factors,
    each with its own observation sources and confidence.
    """
    factors: Dict[str, StateFactor] = field(default_factory=dict)

    def add_factor(self, factor: StateFactor) -> None:
        self.factors[factor.name] = factor

    def get_factor(self, name: str) -> Optional[StateFactor]:
        return self.factors.get(name)

    def observe(
        self, factor_name: str, value: Any, confidence: float = 0.8,
    ) -> bool:
        factor = self.factors.get(factor_name)
        if factor is None:
            return False
        factor.update_from_observation(value, confidence)
        return True

    def get_uncertainty(self) -> float:
        if not self.factors:
            return 1.0
        return 1.0 - sum(f.confidence for f in self.factors.values()) / len(self.factors)

    def get_uncertain_factors(self, threshold: float = 0.5) -> List[StateFactor]:
        return [f for f in self.factors.values() if f.confidence < threshold]

    def to_predicted_outcome(self) -> Dict[str, Any]:
        return {f.name: f.value for f in self.factors.values() if f.value is not None}

    def information_gain_estimate(self, factor_name: str) -> float:
        factor = self.factors.get(factor_name)
        if factor is None:
            return 0.0
        return 1.0 - factor.confidence


# ---------------------------------------------------------------------------
# Investigation-specific weight profiles
# ---------------------------------------------------------------------------

ENTITY_SEARCH_WEIGHTS = EFEWeights(risk=0.2, ambiguity=0.3, epistemic=0.5)
CROSS_REFERENCE_WEIGHTS = EFEWeights(risk=0.35, ambiguity=0.30, epistemic=0.35)
DOCUMENT_ANALYSIS_WEIGHTS = EFEWeights(risk=0.25, ambiguity=0.30, epistemic=0.45)
NLP_EXTRACTION_WEIGHTS = EFEWeights(risk=0.30, ambiguity=0.25, epistemic=0.45)
NETWORK_ANALYSIS_WEIGHTS = EFEWeights(risk=0.30, ambiguity=0.35, epistemic=0.35)
FINANCIAL_INVESTIGATION_WEIGHTS = EFEWeights(risk=0.45, ambiguity=0.25, epistemic=0.30)
GOVERNMENT_ACCOUNTABILITY_WEIGHTS = EFEWeights(risk=0.35, ambiguity=0.30, epistemic=0.35)
MONITORING_WEIGHTS = EFEWeights(risk=0.15, ambiguity=0.25, epistemic=0.60)
VERIFICATION_WEIGHTS = EFEWeights(risk=0.55, ambiguity=0.25, epistemic=0.20)
PUBLICATION_WEIGHTS = EFEWeights(risk=0.50, ambiguity=0.30, epistemic=0.20)
DATA_QUALITY_WEIGHTS = EFEWeights(risk=0.40, ambiguity=0.30, epistemic=0.30)
DIGITAL_SECURITY_WEIGHTS = EFEWeights(risk=0.60, ambiguity=0.25, epistemic=0.15)
DEFAULT_WEIGHTS = EFEWeights(risk=0.33, ambiguity=0.34, epistemic=0.33)


# ---------------------------------------------------------------------------
# Score container
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EFEScore:
    """Result of an EFE evaluation for a single policy."""

    total: float
    risk_component: float
    ambiguity_component: float
    epistemic_component: float
    policy_id: str


# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------


class EFECalculator:
    """Compute Expected Free Energy for candidate investigation policies."""

    def __init__(self, default_weights: EFEWeights | None = None) -> None:
        self._default_weights = default_weights or DEFAULT_WEIGHTS

    def calculate_efe(
        self,
        policy_id: str,
        predicted_outcome: dict,
        desired_outcome: dict,
        uncertainty: float,
        information_gain: float,
        weights: EFEWeights | None = None,
    ) -> EFEScore:
        w = weights or self._default_weights
        divergence = self.compute_divergence(predicted_outcome, desired_outcome)

        risk_component = w.risk * divergence
        ambiguity_component = w.ambiguity * uncertainty
        epistemic_component = w.epistemic * (-information_gain)
        total = risk_component + ambiguity_component + epistemic_component

        return EFEScore(
            total=total,
            risk_component=risk_component,
            ambiguity_component=ambiguity_component,
            epistemic_component=epistemic_component,
            policy_id=policy_id,
        )

    def calculate_efe_from_world_model(
        self,
        policy_id: str,
        world_model: WorldModel,
        desired_outcome: dict,
        weights: EFEWeights | None = None,
    ) -> EFEScore:
        """Score a policy using the factored world model.

        Extracts predicted outcome, uncertainty, and information gain
        directly from the WorldModel's state factors.
        """
        predicted = world_model.to_predicted_outcome()
        uncertainty = world_model.get_uncertainty()
        uncertain_factors = world_model.get_uncertain_factors()
        info_gain = (
            sum(world_model.information_gain_estimate(f.name) for f in uncertain_factors)
            / max(len(world_model.factors), 1)
        )
        return self.calculate_efe(
            policy_id=policy_id,
            predicted_outcome=predicted,
            desired_outcome=desired_outcome,
            uncertainty=uncertainty,
            information_gain=info_gain,
            weights=weights,
        )

    def select_policy(self, scores: list[EFEScore]) -> EFEScore:
        if not scores:
            raise ValueError("Cannot select from an empty score list")
        return min(scores, key=lambda s: s.total)

    @staticmethod
    def compute_divergence(predicted: dict, desired: dict) -> float:
        all_keys = set(predicted) | set(desired)
        if not all_keys:
            return 0.0

        total = 0.0
        for key in all_keys:
            if key not in predicted or key not in desired:
                total += 1.0
                continue
            pv, dv = predicted[key], desired[key]
            try:
                pf, df = float(pv), float(dv)
            except (TypeError, ValueError):
                total += 0.0 if pv == dv else 1.0
                continue
            max_abs = max(abs(pf), abs(df), 1e-9)
            total += abs(pf - df) / max_abs

        return total / len(all_keys)
