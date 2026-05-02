"""BDI layer — structured reasoning lens on investigation sessions.

Maps Session concepts to BDI:
  - Findings → Beliefs (what we think is true, with confidence)
  - Investigation goal → Desire (what we want to prove)
  - Leads → Intentions (what we're going to do about it)

The BDI layer doesn't replace the Session — it provides structured
reasoning on top of it. Coherence checking detects when the
investigation drifts from its goal. The audit trail gets explicit
BDI annotations.

Moved from _future/bdi/ and wired into the live agent loop.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from emet.agent.session import Session, Finding, Lead

# Import the BDI models from _future (promoted to active use)
import sys
from pathlib import Path
_future = str(Path(__file__).resolve().parent.parent.parent / "_future")
if _future not in sys.path:
    sys.path.insert(0, _future)

from bdi.models import (
    BDIBelief, BDIDesire, BDIIntention, BDISnapshot,
    BeliefStatus, DesireStatus, IntentionStatus,
)
from bdi.store import BDIStore
from bdi.coherence import CoherenceChecker, CoherenceScore


class InvestigationBDI:
    """BDI reasoning layer for investigations.

    Wraps a Session with structured belief-desire-intention tracking.
    Updated after each agent turn to maintain a coherent picture of
    the investigation's epistemic state.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._store = BDIStore(org_id=session.id)
        self._checker = CoherenceChecker()
        self._initialized = False

    def initialize(self) -> None:
        """Create the initial BDI state from the investigation goal."""
        now = datetime.now(timezone.utc)

        self._store.add_desire(BDIDesire(
            id="goal",
            content=self._session.goal,
            priority=1.0,
            status=DesireStatus.ACTIVE,
            related_tags=self._extract_tags(self._session.goal),
            measurable=True,
            metric="evidence_coverage",
            created_at=now,
        ))

        self._store.add_intention(BDIIntention(
            id="investigate",
            goal=f"Investigate: {self._session.goal}",
            status=IntentionStatus.ACTIVE,
            belief_ids=[],
            desire_ids=["goal"],
            created_at=now,
        ))

        self._initialized = True

    def update_from_finding(self, finding: Finding) -> BDIBelief:
        """Convert a new finding into a belief."""
        now = datetime.now(timezone.utc)
        belief_id = f"finding_{finding.id}"

        tags = self._extract_tags(finding.summary)
        for entity in finding.entities:
            name = entity.get("name", entity.get("caption", ""))
            if name:
                tags.append(name.lower())

        belief = BDIBelief(
            id=belief_id,
            content=finding.summary,
            confidence=finding.confidence,
            status=BeliefStatus.ACTIVE,
            source=finding.source,
            tags=tags,
            created_at=now,
            evidence=[finding.id],
        )
        self._store.add_belief(belief)

        # Update the investigation intention with the new belief
        intention = self._store.get_intention("investigate")
        if intention:
            intention.belief_ids.append(belief_id)
            progress = min(1.0, len(intention.belief_ids) / 10)
            self._store.update_intention(
                "investigate", progress=progress,
            )

        return belief

    def update_from_lead(self, lead: Lead) -> BDIIntention:
        """Convert a new lead into an intention."""
        now = datetime.now(timezone.utc)
        intention_id = f"lead_{lead.id}"

        intention = BDIIntention(
            id=intention_id,
            goal=lead.description,
            status=IntentionStatus.ACTIVE,
            belief_ids=[],
            desire_ids=["goal"],
            created_at=now,
        )
        self._store.add_intention(intention)
        return intention

    def resolve_lead(self, lead_id: str, outcome: str) -> None:
        """Update intention when a lead is resolved."""
        intention_id = f"lead_{lead_id}"
        intention = self._store.get_intention(intention_id)
        if intention:
            if outcome in ("resolved", "completed"):
                self._store.complete_intention(intention_id)
            else:
                self._store.update_intention(
                    intention_id, status=IntentionStatus.FAILED,
                )

    def check_coherence(self) -> CoherenceScore:
        """Check if beliefs, desires, and intentions are aligned."""
        snapshot = self._store.get_snapshot()
        return self._checker.check_coherence(snapshot)

    def get_summary(self) -> dict[str, Any]:
        """Human-readable summary of the BDI state."""
        beliefs = self._store.list_beliefs(BeliefStatus.ACTIVE)
        desires = self._store.list_desires(DesireStatus.ACTIVE)
        intentions = self._store.list_intentions(IntentionStatus.ACTIVE)

        coherence = self.check_coherence()

        return {
            "beliefs": len(beliefs),
            "desires": len(desires),
            "intentions": len(intentions),
            "coherence": coherence.overall,
            "coherence_issues": list(coherence.issues),
            "investigation_progress": self._store.get_intention("investigate").progress
                if self._store.get_intention("investigate") else 0.0,
            "top_beliefs": [
                {"content": b.content[:80], "confidence": b.confidence}
                for b in sorted(beliefs, key=lambda b: -b.confidence)[:5]
            ],
        }

    def should_refocus(self) -> tuple[bool, str]:
        """Check if the investigation needs to refocus.

        Returns (should_refocus, reason).
        """
        coherence = self.check_coherence()

        if coherence.overall < 0.3:
            return True, (
                f"Investigation coherence is low ({coherence.overall:.2f}). "
                f"Issues: {'; '.join(coherence.issues[:3])}"
            )

        beliefs = self._store.list_beliefs(BeliefStatus.ACTIVE)
        if len(beliefs) > 5:
            high_conf = [b for b in beliefs if b.confidence >= 0.7]
            if not high_conf:
                return True, (
                    f"Many findings ({len(beliefs)}) but none with high confidence. "
                    "Consider verifying existing evidence before pursuing new leads."
                )

        return False, ""

    @staticmethod
    def _extract_tags(text: str) -> list[str]:
        """Extract simple keyword tags from text."""
        stop_words = {"the", "a", "an", "is", "are", "was", "were", "in",
                      "on", "at", "to", "for", "of", "and", "or", "not",
                      "this", "that", "with", "from", "by", "as", "it"}
        words = text.lower().split()
        return [w.strip(".,;:!?\"'()") for w in words
                if len(w) > 3 and w.lower() not in stop_words][:10]

    @property
    def store(self) -> BDIStore:
        return self._store
