"""Evidence chain and confidence scoring for publication-safe reporting.

Every claim in an Emet report must trace to source material — this
module makes that machine-checkable. A :class:`Claim` binds a natural-
language assertion to the specific source records (their provenance)
that support it, and computes an auditable confidence score from:

    - the reliability of each source (its own ``confidence``),
    - **corroboration** — independent sources raise confidence,
    - **contradiction** — sources that dispute the claim lower it.

The :class:`EvidenceChain` aggregates claims for a whole investigation
and can emit a citation-numbered structure so the report renderer can
footnote every statement. This is the "each claim traces to a source"
guarantee the license and VALUES.json require.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Source references
# ---------------------------------------------------------------------------


@dataclass
class SourceRef:
    """A single piece of supporting (or contradicting) evidence.

    Built from an FtM entity's ``_provenance`` block, so the same
    metadata the adapters already attach flows straight into citations.
    """

    source: str  # data source name, e.g. "opencorporates"
    source_id: str = ""
    source_url: str = ""
    confidence: float = 0.5  # 0–1 reliability of this record
    retrieved_at: str = ""
    note: str = ""
    supports: bool = True  # False = this source contradicts the claim

    @classmethod
    def from_provenance(
        cls, provenance: dict[str, Any], *, supports: bool = True, note: str = ""
    ) -> "SourceRef":
        return cls(
            source=provenance.get("source", "unknown"),
            source_id=str(provenance.get("source_id", "")),
            source_url=provenance.get("source_url", ""),
            confidence=float(provenance.get("confidence", 0.5)),
            retrieved_at=provenance.get("retrieved_at", ""),
            note=note,
            supports=supports,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_id": self.source_id,
            "source_url": self.source_url,
            "confidence": self.confidence,
            "retrieved_at": self.retrieved_at,
            "note": self.note,
            "supports": self.supports,
        }


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------


def score_confidence(sources: list[SourceRef]) -> float:
    """Aggregate a 0–1 confidence from a claim's sources.

    Model (deliberately simple and explainable):

    * Start from the single most reliable *supporting* source.
    * Each additional independent supporting source closes part of the
      remaining gap to 1.0 (corroboration with diminishing returns).
    * Each contradicting source applies a multiplicative penalty scaled
      by its own reliability.

    Distinct ``source`` names count as independent; repeats from the
    same source do not double-count corroboration.
    """
    supporting = [s for s in sources if s.supports]
    contradicting = [s for s in sources if not s.supports]

    if not supporting:
        # Only contradictions (or nothing) — floor near zero.
        return 0.0 if not contradicting else max(
            0.0, 0.1 - 0.05 * len(contradicting)
        )

    # Base = best supporting source.
    base = max(s.confidence for s in supporting)

    # Corroboration from additional *distinct* sources.
    distinct_sources = {s.source for s in supporting}
    extra = max(0, len(distinct_sources) - 1)
    corroboration = base
    remaining = 1.0 - base
    for _ in range(extra):
        remaining *= 0.5
        corroboration = 1.0 - remaining

    # Contradiction penalty (multiplicative).
    for c in contradicting:
        corroboration *= (1.0 - 0.5 * c.confidence)

    return round(max(0.0, min(1.0, corroboration)), 3)


def confidence_label(score: float) -> str:
    """Map a 0–1 confidence to a journalist-facing band."""
    if score >= 0.85:
        return "high"
    if score >= 0.6:
        return "moderate"
    if score >= 0.35:
        return "low"
    return "unverified"


# ---------------------------------------------------------------------------
# Claims and the chain
# ---------------------------------------------------------------------------


@dataclass
class Claim:
    """An assertion bound to its supporting evidence."""

    text: str
    sources: list[SourceRef] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def add_source(self, source: SourceRef) -> None:
        self.sources.append(source)

    @property
    def confidence(self) -> float:
        return score_confidence(self.sources)

    @property
    def confidence_label(self) -> str:
        return confidence_label(self.confidence)

    def to_dict(self, citation_start: int = 1) -> dict[str, Any]:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "confidence_label": self.confidence_label,
            "entity_ids": self.entity_ids,
            "tags": self.tags,
            "citations": [
                {"n": citation_start + i, **s.to_dict()}
                for i, s in enumerate(self.sources)
            ],
        }


@dataclass
class EvidenceChain:
    """An ordered collection of claims for an investigation."""

    claims: list[Claim] = field(default_factory=list)

    def add_claim(
        self,
        text: str,
        sources: list[SourceRef] | None = None,
        entity_ids: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> Claim:
        claim = Claim(
            text=text,
            sources=sources or [],
            entity_ids=entity_ids or [],
            tags=tags or [],
        )
        self.claims.append(claim)
        return claim

    @property
    def overall_confidence(self) -> float:
        """Mean confidence across all claims (0 if none)."""
        if not self.claims:
            return 0.0
        return round(sum(c.confidence for c in self.claims) / len(self.claims), 3)

    def unsupported_claims(self) -> list[Claim]:
        """Claims with no supporting sources — must not be published as fact."""
        return [c for c in self.claims if not any(s.supports for s in c.sources)]

    def to_dict(self) -> dict[str, Any]:
        """Serialise with sequential, globally-unique citation numbers."""
        out_claims = []
        citation_n = 1
        for claim in self.claims:
            d = claim.to_dict(citation_start=citation_n)
            citation_n += len(claim.sources)
            out_claims.append(d)
        return {
            "overall_confidence": self.overall_confidence,
            "overall_confidence_label": confidence_label(self.overall_confidence),
            "claim_count": len(self.claims),
            "unsupported_claim_count": len(self.unsupported_claims()),
            "claims": out_claims,
        }

    def to_markdown(self) -> str:
        """Render the evidence chain as a footnoted Markdown section."""
        if not self.claims:
            return "## Evidence\n\n_No claims recorded._\n"

        lines = ["## Evidence & Confidence\n"]
        footnotes: list[str] = []
        citation_n = 1
        for claim in self.claims:
            marks = []
            for src in claim.sources:
                marks.append(f"[^{citation_n}]")
                loc = src.source_url or src.source_id or src.source
                tag = "" if src.supports else " (contradicts)"
                footnotes.append(
                    f"[^{citation_n}]: {src.source} — {loc} "
                    f"(confidence {src.confidence:.2f}){tag}"
                )
                citation_n += 1
            marks_str = "".join(marks)
            lines.append(
                f"- **[{claim.confidence_label}, {claim.confidence:.2f}]** "
                f"{claim.text} {marks_str}"
            )
        return "\n".join(lines) + "\n\n" + "\n".join(footnotes) + "\n"
