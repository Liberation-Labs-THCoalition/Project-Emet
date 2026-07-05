"""Evidence-chain tracking for investigation reports.

Binds every factual claim in a report to the sources that support it,
computes a defensible 0-1 confidence score from that evidence, and
flags claims that are not actually supported so they cannot slip into
a published report as settled fact.

Typical flow:

    chain = EvidenceChain()
    chain.add_claim(
        "Acme Holdings was incorporated in Delaware in 2019.",
        sources=[SourceRef.from_provenance(entity["_provenance"])],
    )
    markdown = chain.to_markdown()
    unresolved = chain.unsupported_claims()  # must be resolved before publication

This module deliberately mirrors the ``_provenance`` shape produced by
``emet.ftm.external.converters`` (``source``, ``source_id``, ``source_url``,
``confidence``, ``retrieved_at``) so ``SourceRef`` objects can be built
directly from converted FtM entities.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Source references
# ---------------------------------------------------------------------------


@dataclass
class SourceRef:
    """A single piece of supporting (or contradicting) evidence.

    Mirrors the shape of an FtM entity's ``_provenance`` dict.
    """

    source: str
    source_id: str = ""
    source_url: str = ""
    confidence: float = 1.0  # the source's own reliability, 0-1
    retrieved_at: str = ""

    @classmethod
    def from_provenance(cls, provenance: dict[str, Any]) -> "SourceRef":
        """Build a ``SourceRef`` directly from an FtM entity's ``_provenance`` dict.

        Missing keys default sanely. Notably, ``confidence`` defaults to 0.5
        when entirely absent — an entity with no stated confidence shouldn't
        be treated as fully trusted by default.
        """
        return cls(
            source=provenance.get("source", ""),
            source_id=provenance.get("source_id", ""),
            source_url=provenance.get("source_url", ""),
            confidence=provenance.get("confidence", 0.5),
            retrieved_at=provenance.get("retrieved_at", ""),
        )


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


@dataclass
class Claim:
    """A single factual assertion made in a report, and the evidence for it."""

    statement: str
    sources: list[SourceRef] = field(default_factory=list)
    contradicted_by: list[SourceRef] = field(default_factory=list)
    confidence: float = 0.0
    id: str = ""  # short stable id for footnote linking, e.g. "c1" — set by EvidenceChain.add_claim


def score_confidence(claim: Claim) -> float:
    """Aggregate a defensible 0-1 confidence score for ``claim``.

    Rules (see module docstring for the reasoning):

    1. No sources at all -> 0.0. An unsupported claim has zero confidence,
       full stop.
    2. Base score = the single highest-confidence source's ``confidence``.
       The strongest individual piece of evidence sets the floor/ceiling
       for how sure we can be.
    3. Corroboration bonus: each *additional distinct* source (distinct by
       the ``source`` field — two ``SourceRef``s from the same source name
       don't independently corroborate each other) beyond the first adds a
       diminishing-returns bonus, capped so ``base + bonus`` never exceeds
       1.0 before the contradiction penalty is applied.
    4. Contradiction penalty: multiplicative, not additive. Each
       contradicting source multiplies the running score by
       ``(1 - contradicting_source.confidence * 0.5)``, applied after the
       corroboration bonus. The final result is clamped to [0.0, 1.0].

    This is pure arithmetic — no randomness, no wall-clock — so it produces
    the same output every time given the same inputs.
    """
    if not claim.sources:
        return 0.0

    # Step 2: base score is the strongest individual source.
    base = max(source.confidence for source in claim.sources)

    # Step 3: corroboration bonus for additional *distinct* sources.
    distinct_source_names = {source.source for source in claim.sources}
    distinct_count = len(distinct_source_names)
    bonus = sum(0.5**i * 0.1 for i in range(1, distinct_count))
    score = min(base + bonus, 1.0)

    # Step 4: multiplicative contradiction penalty.
    for contradiction in claim.contradicted_by:
        score *= 1 - contradiction.confidence * 0.5

    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Evidence chain
# ---------------------------------------------------------------------------


class EvidenceChain:
    """Accumulates claims for one report/investigation and renders them.

    Every claim added is scored immediately via :func:`score_confidence`, so
    the chain always reflects the current, defensible confidence for each
    assertion — and can report which claims are not yet fit to publish.
    """

    def __init__(self) -> None:
        self._claims: list[Claim] = []

    @property
    def claims(self) -> list[Claim]:
        """All claims recorded so far, in insertion order."""
        return list(self._claims)

    def add_claim(
        self,
        statement: str,
        sources: list[SourceRef],
        contradicted_by: list[SourceRef] | None = None,
    ) -> Claim:
        """Record a new claim, score it, and return it.

        Auto-assigns ``claim.id`` (``c1``, ``c2``, ...) and computes
        ``claim.confidence`` via :func:`score_confidence`.
        """
        claim = Claim(
            statement=statement,
            sources=list(sources),
            contradicted_by=list(contradicted_by) if contradicted_by else [],
        )
        claim.id = f"c{len(self._claims) + 1}"
        claim.confidence = score_confidence(claim)
        self._claims.append(claim)
        return claim

    def unsupported_claims(self, threshold: float = 0.3) -> list[Claim]:
        """Claims with confidence below ``threshold`` or zero sources.

        These are the claims that must NOT be published as settled fact
        without further corroboration.
        """
        return [
            claim
            for claim in self._claims
            if not claim.sources or claim.confidence < threshold
        ]

    def to_markdown(self) -> str:
        """Render all claims as footnoted Markdown.

        Produces a numbered list of claims (each with an inline footnote
        marker, e.g. ``... corporate registry filing.[^c1]``), a footnotes
        section mapping each claim id to its sources (name, url if present,
        confidence), and — when applicable — an explicit
        "Unsupported / low-confidence claims" section so those claims can
        never accidentally read as verified fact in a rendered report.
        """
        if not self._claims:
            return "## Evidence Chain\n\nNo claims recorded.\n"

        lines: list[str] = ["## Evidence Chain\n"]

        lines.append("### Claims\n")
        for i, claim in enumerate(self._claims, 1):
            lines.append(
                f"{i}. {claim.statement}[^{claim.id}] "
                f"(confidence: {claim.confidence:.2f})"
            )
        lines.append("")

        lines.append("### Footnotes\n")
        for claim in self._claims:
            lines.append(f"[^{claim.id}]:")
            if not claim.sources:
                lines.append("    - *No supporting sources.*")
            for src in claim.sources:
                detail = f"    - {src.source}"
                if src.source_url:
                    detail += f" ({src.source_url})"
                detail += f" — confidence {src.confidence:.2f}"
                lines.append(detail)
            for src in claim.contradicted_by:
                detail = f"    - *Contradicted by* {src.source}"
                if src.source_url:
                    detail += f" ({src.source_url})"
                detail += f" — confidence {src.confidence:.2f}"
                lines.append(detail)
        lines.append("")

        unsupported = self.unsupported_claims()
        if unsupported:
            lines.append("### Unsupported / low-confidence claims\n")
            lines.append(
                "The following claims are not adequately supported and "
                "must not be published as verified fact without further "
                "corroboration:\n"
            )
            for claim in unsupported:
                lines.append(
                    f"- [^{claim.id}] **{claim.statement}** "
                    f"(confidence: {claim.confidence:.2f})"
                )
            lines.append("")

        return "\n".join(lines)

    def to_jsonld(self) -> dict[str, Any]:
        """Lightweight JSON-LD-ish serialization of claims + sources.

        Uses schema.org's ``Claim``/``CreativeWork`` vocabulary loosely.
        This is separate from — and much simpler than — the full FtM
        JSON-LD exporter used for the entity graph; it exists only to make
        the evidence chain itself machine-readable.
        """
        graph: list[dict[str, Any]] = []
        for claim in self._claims:
            node: dict[str, Any] = {
                "@type": "Claim",
                "identifier": claim.id,
                "text": claim.statement,
                "confidence": claim.confidence,
                "citation": [self._source_to_jsonld(src) for src in claim.sources],
            }
            if claim.contradicted_by:
                node["disputed"] = True
                node["contradictingCitation"] = [
                    self._source_to_jsonld(src) for src in claim.contradicted_by
                ]
            graph.append(node)

        return {"@context": "https://schema.org", "@graph": graph}

    @staticmethod
    def _source_to_jsonld(src: SourceRef) -> dict[str, Any]:
        node: dict[str, Any] = {
            "@type": "CreativeWork",
            "name": src.source,
            "confidence": src.confidence,
        }
        if src.source_id:
            node["identifier"] = src.source_id
        if src.source_url:
            node["url"] = src.source_url
        if src.retrieved_at:
            node["dateRetrieved"] = src.retrieved_at
        return node
