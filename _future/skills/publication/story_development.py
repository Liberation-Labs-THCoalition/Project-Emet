"""Story Development Skill Chip — narrative construction and impact tracking.

Helps journalists organize investigation findings into publishable narratives:
timeline construction, key finding synthesis, impact measurement, and
structured story outlines.

Not a content generator — this chip organizes and structures findings
that human journalists have verified. It never fabricates quotes,
invents sources, or generates fictional narrative elements.

Modeled after the journalism wrapper's /story, /timeline, and /impact commands.
"""

from __future__ import annotations
import logging
from typing import Any

from emet.skills.base import (
    BaseSkillChip, EFEWeights, SkillCapability,
    SkillContext, SkillDomain, SkillRequest, SkillResponse,
)

logger = logging.getLogger(__name__)


class StoryDevelopmentChip(BaseSkillChip):
    name = "story_development"
    description = "Organize investigation findings into structured narratives and timelines"
    version = "1.0.0"
    domain = SkillDomain.PUBLICATION
    efe_weights = EFEWeights(
        accuracy=0.30, source_protection=0.25, public_interest=0.20,
        proportionality=0.15, transparency=0.10,
    )
    capabilities = [SkillCapability.READ_ALEPH]
    consensus_actions = ["publish_story", "share_findings"]

    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        intent = request.intent.lower()
        dispatch = {
            "build_timeline": self._build_timeline,
            "timeline": self._build_timeline,
            "synthesize_findings": self._synthesize_findings,
            "story_outline": self._story_outline,
            "outline": self._story_outline,
            "key_findings": self._key_findings,
            "impact_assessment": self._impact_assessment,
            "methodology_doc": self._methodology_doc,
            "data_appendix": self._data_appendix,
        }
        handler = dispatch.get(intent, self._story_outline)
        return await handler(request, context)

    async def _build_timeline(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Build a chronological timeline from investigation events."""
        events = request.parameters.get("events", [])
        collection_id = request.parameters.get("collection_id", "")
        return SkillResponse(
            content=f"Timeline construction from {len(events)} events.",
            success=True,
            data={
                "events_count": len(events),
                "timeline_elements": [
                    "Date-stamped events from FtM entities",
                    "Document dates from ingest metadata",
                    "Relationship start/end dates",
                    "Corporate filing dates",
                    "Transaction dates",
                ],
                "output_formats": ["Aleph entity set (timeline)", "HTML timeline", "Structured JSON"],
            },
            result_confidence=0.7,
        )

    async def _synthesize_findings(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Synthesize investigation findings into structured summary."""
        return SkillResponse(
            content="Findings synthesis.",
            success=True,
            data={
                "synthesis_structure": [
                    "Core finding (one sentence)",
                    "Key supporting evidence (bullet points with source citations)",
                    "Network/relationship summary",
                    "Financial flow summary (if applicable)",
                    "Open questions remaining",
                    "Confidence assessment per finding",
                ],
                "important": "All synthesized content must be traceable to verified source material.",
            },
            result_confidence=0.7,
        )

    async def _story_outline(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Generate a structured story outline from investigation data."""
        return SkillResponse(
            content="Story outline template.",
            success=True,
            data={
                "outline_template": [
                    "1. Lead: Core revelation (what happened, who is involved)",
                    "2. Nut graf: Why this matters (public interest justification)",
                    "3. Key characters: Entity profiles with verified details",
                    "4. The evidence: Document-by-document walkthrough",
                    "5. The money trail: Financial connections (if applicable)",
                    "6. The network: Relationship map with explanations",
                    "7. The response: Right of reply from named parties",
                    "8. Impact: What should change / what has changed",
                    "9. Methodology: How the investigation was conducted",
                ],
            },
            result_confidence=0.8,
        )

    async def _key_findings(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Extract and rank key findings from investigation context."""
        return SkillResponse(
            content="Key findings extraction from investigation BDI state.",
            success=True,
            data={
                "finding_categories": [
                    "Confirmed facts (strong evidence)",
                    "Probable findings (moderate evidence)",
                    "Working hypotheses (circumstantial evidence)",
                    "Unresolved questions",
                ],
                "ranking_criteria": [
                    "Evidence strength", "Public interest significance",
                    "Novelty (not previously reported)", "Actionability",
                ],
            },
            result_confidence=0.7,
        )

    async def _impact_assessment(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Assess potential and actual impact of investigation."""
        return SkillResponse(
            content="Impact assessment framework.",
            success=True,
            data={
                "impact_categories": [
                    "Accountability: Officials/executives held responsible",
                    "Policy change: Laws/regulations modified",
                    "Institutional reform: Organizational changes",
                    "Legal action: Investigations, indictments, lawsuits",
                    "Public awareness: Measurable change in public knowledge",
                    "Financial impact: Fines, settlements, market effects",
                ],
            },
            result_confidence=0.7,
        )

    async def _methodology_doc(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Generate methodology documentation for the investigation."""
        return SkillResponse(
            content="Methodology documentation template.",
            success=True,
            data={
                "sections": [
                    "Data sources used (with access dates)",
                    "Tools and methods applied",
                    "AI/automated analysis disclosure",
                    "Human verification steps",
                    "Limitations and caveats",
                    "Data handling and security measures",
                    "Ethical considerations",
                ],
                "important": "Required for transparency and reproducibility. "
                             "Also serves as legal defense documentation.",
            },
            result_confidence=0.8,
        )

    async def _data_appendix(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Generate data appendix for publication."""
        return SkillResponse(
            content="Data appendix generation.",
            success=True,
            data={
                "appendix_elements": [
                    "Entity list with key properties",
                    "Relationship table",
                    "Timeline of key events",
                    "Financial flow summary",
                    "Document inventory",
                    "Source reliability assessments",
                ],
                "formats": ["PDF", "Excel", "Interactive web appendix"],
            },
            result_confidence=0.8,
        )
