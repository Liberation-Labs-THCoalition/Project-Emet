"""Expected Free Energy (EFE) calculation for investigative journalism.

Implements a lightweight EFE scorer used by the orchestrator to rank
candidate investigation policies. Lower total EFE indicates the preferred
policy (least expected surprise / best alignment with desired outcomes).

Journalism-specific weight profiles bias decisions toward:
- High epistemic value for entity search (prefer gathering more data)
- High risk aversion for publication decisions (minimize false positives)
- Balanced profiles for cross-referencing (weigh evidence carefully)
"""

from __future__ import annotations

import math
from dataclasses import dataclass


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


# --- Investigation-specific weight profiles ---

# Entity search: heavily favor information gathering over premature action.
# Journalists should always prefer to search more before concluding.
ENTITY_SEARCH_WEIGHTS = EFEWeights(risk=0.2, ambiguity=0.3, epistemic=0.5)

# Cross-referencing: balanced — evidence quality matters as much as discovery.
# False positive entity matches can derail investigations.
CROSS_REFERENCE_WEIGHTS = EFEWeights(risk=0.35, ambiguity=0.30, epistemic=0.35)

# Document analysis: moderate risk aversion, high curiosity.
# OCR/NLP errors propagate — but unexplored documents are lost leads.
DOCUMENT_ANALYSIS_WEIGHTS = EFEWeights(risk=0.25, ambiguity=0.30, epistemic=0.45)

# NLP extraction: moderate risk (false entities contaminate collections),
# high epistemic (new entity discoveries are the core value).
NLP_EXTRACTION_WEIGHTS = EFEWeights(risk=0.30, ambiguity=0.25, epistemic=0.45)

# Network analysis: balanced — structural insights vs overinterpretation.
NETWORK_ANALYSIS_WEIGHTS = EFEWeights(risk=0.30, ambiguity=0.35, epistemic=0.35)

# Financial investigation: high risk aversion (money trail errors are
# defamation risks), moderate curiosity.
FINANCIAL_INVESTIGATION_WEIGHTS = EFEWeights(risk=0.45, ambiguity=0.25, epistemic=0.30)

# Government accountability: moderate across all — FOIA research is
# iterative, but false claims about officials carry legal risk.
GOVERNMENT_ACCOUNTABILITY_WEIGHTS = EFEWeights(risk=0.35, ambiguity=0.30, epistemic=0.35)

# Monitoring: low risk (alerting is non-destructive), high epistemic
# (the whole point is catching new information early).
MONITORING_WEIGHTS = EFEWeights(risk=0.15, ambiguity=0.25, epistemic=0.60)

# Verification: highest risk aversion in the system — the purpose of
# verification is to catch errors before publication.
VERIFICATION_WEIGHTS = EFEWeights(risk=0.55, ambiguity=0.25, epistemic=0.20)

# Publication/story development: very high risk aversion.
# Publication decisions are irreversible and carry legal exposure.
PUBLICATION_WEIGHTS = EFEWeights(risk=0.50, ambiguity=0.30, epistemic=0.20)

# Data quality: high risk (bad data propagates), moderate epistemic.
DATA_QUALITY_WEIGHTS = EFEWeights(risk=0.40, ambiguity=0.30, epistemic=0.30)

# Digital security: extremely high risk aversion — security failures
# can endanger sources and compromise investigations.
DIGITAL_SECURITY_WEIGHTS = EFEWeights(risk=0.60, ambiguity=0.25, epistemic=0.15)

# Default fallback for unclassified domains.
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
    """Compute Expected Free Energy for candidate investigation policies.

    Parameters
    ----------
    default_weights:
        Fallback weights when none are provided per call.
    """

    def __init__(self, default_weights: EFEWeights | None = None) -> None:
        self._default_weights = default_weights or DEFAULT_WEIGHTS

    # -- public API ---------------------------------------------------------

    def calculate_efe(
        self,
        policy_id: str,
        predicted_outcome: dict,
        desired_outcome: dict,
        uncertainty: float,
        information_gain: float,
        weights: EFEWeights | None = None,
    ) -> EFEScore:
        """Score a single policy.

        Parameters
        ----------
        policy_id:
            Unique identifier for the candidate policy.
        predicted_outcome:
            Dict of predicted state variables after executing the policy.
        desired_outcome:
            Dict of target / goal state variables.
        uncertainty:
            Scalar representing outcome uncertainty (0 = certain).
        information_gain:
            Expected information gain from executing this policy.
        weights:
            Per-call weight override; uses *default_weights* when *None*.

        Returns
        -------
        EFEScore
            Decomposed score with total and per-component values.
        """
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

    def select_policy(self, scores: list[EFEScore]) -> EFEScore:
        """Return the policy with the lowest total EFE.

        Raises ``ValueError`` if *scores* is empty.
        """
        if not scores:
            raise ValueError("Cannot select from an empty score list")
        return min(scores, key=lambda s: s.total)

    @staticmethod
    def compute_divergence(predicted: dict, desired: dict) -> float:
        """Normalised symmetric difference between two outcome dicts.

        For overlapping keys with numeric values the divergence is the mean
        absolute difference normalised by the max absolute value (per key).
        Keys present in only one dict contribute 1.0 each.  The final value
        is averaged over the union of keys so the result lies in ``[0, 1]``.
        """
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
