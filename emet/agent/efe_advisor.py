"""EFE-powered investigation advisor.

Scores candidate actions using Expected Free Energy with journalism-
weighted profiles. Replaces priority-only lead ordering with
information-theoretic decision-making.

The advisor answers: "Given what we know, what we want to know,
and the risks of each action — what should we do next?"
"""
from __future__ import annotations

from typing import Any

from emet.agent.session import Session, Lead
from emet.cognition.efe import (
    EFECalculator,
    EFEScore,
    EFEWeights,
    ENTITY_SEARCH_WEIGHTS,
    CROSS_REFERENCE_WEIGHTS,
    FINANCIAL_INVESTIGATION_WEIGHTS,
    NETWORK_ANALYSIS_WEIGHTS,
    MONITORING_WEIGHTS,
    VERIFICATION_WEIGHTS,
    DIGITAL_SECURITY_WEIGHTS,
    DEFAULT_WEIGHTS,
)

# Map tools to their journalism-appropriate EFE weight profiles
TOOL_WEIGHTS: dict[str, EFEWeights] = {
    "search_entities": ENTITY_SEARCH_WEIGHTS,
    "search_aleph": ENTITY_SEARCH_WEIGHTS,
    "screen_sanctions": VERIFICATION_WEIGHTS,
    "trace_ownership": FINANCIAL_INVESTIGATION_WEIGHTS,
    "osint_recon": DIGITAL_SECURITY_WEIGHTS,
    "investigate_blockchain": FINANCIAL_INVESTIGATION_WEIGHTS,
    "analyze_graph": NETWORK_ANALYSIS_WEIGHTS,
    "monitor_entity": MONITORING_WEIGHTS,
    "generate_report": VERIFICATION_WEIGHTS,
}


class EFEAdvisor:
    """Scores candidate investigation actions using EFE.

    Wraps the EFECalculator with investigation-specific logic:
    - Estimates information gain from session context
    - Estimates risk from tool type and investigation phase
    - Estimates uncertainty from evidence coverage
    """

    def __init__(self) -> None:
        self._calc = EFECalculator()

    def score_lead(self, lead: Lead, session: Session) -> EFEScore:
        """Score a lead using EFE with journalism weights."""
        weights = TOOL_WEIGHTS.get(lead.tool, DEFAULT_WEIGHTS)

        predicted = self._predict_outcome(lead, session)
        desired = self._desired_outcome(session)
        uncertainty = self._estimate_uncertainty(lead, session)
        info_gain = self._estimate_information_gain(lead, session)

        return self._calc.calculate_efe(
            policy_id=lead.id,
            predicted_outcome=predicted,
            desired_outcome=desired,
            uncertainty=uncertainty,
            information_gain=info_gain,
            weights=weights,
        )

    def rank_leads(self, session: Session) -> list[tuple[Lead, EFEScore]]:
        """Rank all open leads by EFE (lowest = best)."""
        leads = session.get_open_leads()
        if not leads:
            return []

        scored = [(lead, self.score_lead(lead, session)) for lead in leads]
        scored.sort(key=lambda x: x[1].total)
        return scored

    def best_lead(self, session: Session) -> Lead | None:
        """Return the lead with the lowest EFE, or None."""
        ranked = self.rank_leads(session)
        return ranked[0][0] if ranked else None

    def score_action(self, action: dict[str, Any], session: Session) -> EFEScore:
        """Score an arbitrary action dict (from LLM or heuristic)."""
        tool = action.get("tool", "search_entities")
        weights = TOOL_WEIGHTS.get(tool, DEFAULT_WEIGHTS)

        lead = Lead(
            description=action.get("reasoning", ""),
            query=action.get("args", {}).get("query",
                   action.get("args", {}).get("entity_name", "")),
            tool=tool,
        )

        return self.score_lead(lead, session)

    def _predict_outcome(self, lead: Lead, session: Session) -> dict:
        """Predict what executing this lead will produce."""
        tool = lead.tool

        if tool in ("search_entities", "search_aleph"):
            return {
                "new_entities": 3.0 if session.entity_count < 5 else 1.0,
                "new_leads": 2.0,
                "evidence_coverage": min(1.0, session.entity_count / 20 + 0.2),
            }
        elif tool == "screen_sanctions":
            return {
                "new_entities": 0.5,
                "new_leads": 1.0,
                "evidence_coverage": min(1.0, session.entity_count / 20 + 0.3),
                "risk_identified": 0.3,
            }
        elif tool == "trace_ownership":
            return {
                "new_entities": 4.0,
                "new_leads": 3.0,
                "evidence_coverage": min(1.0, session.entity_count / 20 + 0.4),
                "structural_insight": 0.7,
            }
        elif tool == "analyze_graph":
            return {
                "new_entities": 0.0,
                "new_leads": 2.0,
                "evidence_coverage": min(1.0, session.entity_count / 20 + 0.3),
                "structural_insight": 0.8,
            }
        elif tool == "investigate_blockchain":
            return {
                "new_entities": 2.0,
                "new_leads": 2.0,
                "evidence_coverage": min(1.0, session.entity_count / 20 + 0.3),
                "financial_evidence": 0.6,
            }
        else:
            return {
                "new_entities": 1.0,
                "new_leads": 1.0,
                "evidence_coverage": min(1.0, session.entity_count / 20 + 0.1),
            }

    def _desired_outcome(self, session: Session) -> dict:
        """What does a successful investigation look like?"""
        return {
            "new_entities": 0.0,
            "new_leads": 0.0,
            "evidence_coverage": 1.0,
            "risk_identified": 1.0 if session.entity_count > 0 else 0.0,
            "structural_insight": 1.0 if session.entity_count >= 5 else 0.0,
            "financial_evidence": 0.5,
        }

    def _estimate_uncertainty(self, lead: Lead, session: Session) -> float:
        """How uncertain are we about the outcome of this action?"""
        tool = lead.tool

        # Already searched for this entity? Lower uncertainty
        query = lead.query.lower() if lead.query else ""
        prior_searches = sum(
            1 for t in session.tool_history
            if query and query in str(t.get("args", {})).lower()
        )
        familiarity_discount = min(0.3, prior_searches * 0.1)

        base_uncertainty = {
            "search_entities": 0.6,
            "search_aleph": 0.7,
            "screen_sanctions": 0.3,
            "trace_ownership": 0.5,
            "osint_recon": 0.8,
            "investigate_blockchain": 0.7,
            "analyze_graph": 0.2,
            "monitor_entity": 0.5,
        }.get(tool, 0.5)

        return max(0.1, base_uncertainty - familiarity_discount)

    def _estimate_information_gain(self, lead: Lead, session: Session) -> float:
        """How much new information will this action provide?"""
        tool = lead.tool

        # Diminishing returns: more entities = less info gain from search
        search_saturation = min(1.0, session.entity_count / 30)

        base_gain = {
            "search_entities": 0.8 * (1.0 - search_saturation),
            "search_aleph": 0.9 * (1.0 - search_saturation * 0.5),
            "screen_sanctions": 0.6,
            "trace_ownership": 0.9 * (1.0 - search_saturation * 0.3),
            "osint_recon": 0.5,
            "investigate_blockchain": 0.7,
            "analyze_graph": 0.8 if not any(
                t.get("tool") == "analyze_graph" for t in session.tool_history
            ) else 0.2,
            "monitor_entity": 0.4,
        }.get(tool, 0.3)

        # High-priority leads have more expected information gain
        priority_boost = lead.priority * 0.2

        return min(1.0, base_gain + priority_boost)
