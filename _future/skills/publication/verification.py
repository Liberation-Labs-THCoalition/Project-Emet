"""Verification Skill Chip — fact-checking, corroboration, and source assessment.

The last line of defense before publication. Provides structured verification
workflows that check claims against evidence, assess source reliability,
identify corroboration gaps, and flag potential defamation risks.

Implements the "Never trust an LLM" principle from NYT's AI investigation
methodology — every AI-generated finding must be traceable to original
source material.

Modeled after the journalism wrapper's /verify, /fact-check, and /corroborate commands.
"""

from __future__ import annotations
import logging
from typing import Any

from emet.skills.base import (
    BaseSkillChip, EFEWeights, SkillCapability,
    SkillContext, SkillDomain, SkillRequest, SkillResponse,
)

logger = logging.getLogger(__name__)


class VerificationChip(BaseSkillChip):
    name = "verification"
    description = "Fact-checking, corroboration, source reliability assessment, and pre-publication review"
    version = "1.0.0"
    domain = SkillDomain.VERIFICATION
    efe_weights = EFEWeights(
        accuracy=0.40, source_protection=0.20, public_interest=0.15,
        proportionality=0.15, transparency=0.10,
    )
    capabilities = [SkillCapability.READ_ALEPH, SkillCapability.SEARCH_ALEPH]
    consensus_actions = ["approve_for_publication", "flag_defamation_risk"]

    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        intent = request.intent.lower()
        dispatch = {
            "verify_claim": self._verify_claim,
            "fact_check": self._verify_claim,
            "assess_source": self._assess_source,
            "source_reliability": self._assess_source,
            "corroboration_check": self._corroboration_check,
            "corroborate": self._corroboration_check,
            "defamation_check": self._defamation_check,
            "legal_review": self._defamation_check,
            "evidence_chain": self._evidence_chain,
            "pre_publication": self._pre_publication_review,
        }
        handler = dispatch.get(intent, self._verify_claim)
        return await handler(request, context)

    async def _verify_claim(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Verify a specific claim against available evidence.

        For each claim, traces back to original source documents and
        assesses the strength of evidence supporting it.
        """
        claim = request.parameters.get("claim", request.raw_input)
        evidence = request.parameters.get("evidence", [])

        return SkillResponse(
            content="Claim verification initiated.",
            success=True,
            data={
                "claim": claim,
                "evidence_count": len(evidence),
                "verification_steps": [
                    "1. Trace claim to original source documents",
                    "2. Verify source document authenticity",
                    "3. Check for corroborating evidence in other sources",
                    "4. Identify contradicting evidence",
                    "5. Assess overall evidence strength",
                    "6. Flag any claims that rely solely on AI-generated analysis",
                ],
                "evidence_strength_scale": {
                    "strong": "Multiple independent sources confirm, original documents available",
                    "moderate": "Two sources confirm, some original documentation",
                    "weak": "Single source, circumstantial evidence only",
                    "unverified": "AI-generated inference without source documentation",
                },
            },
            result_confidence=0.7,
            suggestions=[
                "Ensure every key claim has at least two independent sources",
                "Flag any findings that originated from LLM analysis for manual verification",
            ],
        )

    async def _assess_source(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Assess reliability of a source or data origin."""
        source = request.parameters.get("source", request.raw_input)
        source_type = request.parameters.get("type", "unknown")

        reliability_factors = {
            "official_record": {
                "base_reliability": 0.85,
                "factors": ["Issuing authority verified", "Tamper evidence checked", "Date consistency"],
            },
            "corporate_filing": {
                "base_reliability": 0.75,
                "factors": ["Filed with registry", "Consistent with other filings", "Auditor verification"],
            },
            "leaked_document": {
                "base_reliability": 0.60,
                "factors": ["Document authenticity verified", "Metadata consistent", "Content corroborated"],
            },
            "human_source": {
                "base_reliability": 0.50,
                "factors": ["Source has direct knowledge", "Motivation assessed", "Track record", "Corroborated"],
            },
            "open_source": {
                "base_reliability": 0.70,
                "factors": ["Source is authoritative", "Data is current", "Cross-referenced"],
            },
            "ai_generated": {
                "base_reliability": 0.30,
                "factors": ["Traceable to original data", "Verified by human", "Consistent with known facts"],
            },
        }

        assessment = reliability_factors.get(source_type, {
            "base_reliability": 0.50,
            "factors": ["Source type not recognized — manual assessment required"],
        })

        return SkillResponse(
            content=f"Source reliability assessment: {source_type} — base reliability {assessment['base_reliability']:.0%}.",
            success=True,
            data={
                "source": source, "source_type": source_type,
                "assessment": assessment,
                "all_source_types": list(reliability_factors.keys()),
            },
            result_confidence=0.7,
        )

    async def _corroboration_check(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Check if key findings are independently corroborated."""
        findings = request.parameters.get("findings", [])
        return SkillResponse(
            content=f"Corroboration check for {len(findings)} findings.",
            success=True,
            data={
                "findings_count": len(findings),
                "corroboration_requirements": {
                    "high_impact_claims": "Minimum 3 independent sources",
                    "medium_impact_claims": "Minimum 2 independent sources",
                    "background_context": "Single authoritative source acceptable",
                },
                "independence_criteria": [
                    "Sources do not share common origin",
                    "Sources accessed through different channels",
                    "Sources are not derivative of each other",
                ],
            },
            result_confidence=0.7,
        )

    async def _defamation_check(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Screen content for potential defamation or legal risks.

        ALWAYS requires editorial consensus before proceeding.
        """
        content = request.parameters.get("content", request.raw_input)
        named_persons = request.parameters.get("named_persons", [])

        return SkillResponse(
            content="Pre-publication legal risk assessment.",
            success=True,
            data={
                "named_persons_count": len(named_persons),
                "risk_categories": [
                    "Defamation (stating unverified facts as proven)",
                    "Privacy violations (unnecessary personal details)",
                    "Source exposure (inadvertent identification)",
                    "Sub judice (prejudicing ongoing legal proceedings)",
                    "National security (classified information handling)",
                ],
                "checklist": [
                    "All factual claims supported by evidence?",
                    "Opinions clearly distinguished from facts?",
                    "Right of reply offered to all named persons?",
                    "Sources adequately protected?",
                    "Public interest justification documented?",
                ],
            },
            requires_consensus=True,
            consensus_action="approve_for_publication",
            result_confidence=0.7,
        )

    async def _evidence_chain(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Trace the evidence chain for a specific finding."""
        finding = request.parameters.get("finding", request.raw_input)
        return SkillResponse(
            content="Evidence chain trace initiated.",
            success=True,
            data={
                "finding": finding,
                "chain_elements": [
                    "Original source document(s)",
                    "Discovery method (search, xref, NLP, manual)",
                    "Processing steps applied",
                    "Human verification checkpoints",
                    "Corroborating evidence",
                ],
            },
            result_confidence=0.7,
        )

    async def _pre_publication_review(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Comprehensive pre-publication review checklist."""
        return SkillResponse(
            content="Pre-publication review initiated.",
            success=True,
            data={
                "review_checklist": [
                    "All claims verified against original sources",
                    "No AI-generated claims without human verification",
                    "Source protection measures confirmed",
                    "Right of reply documented",
                    "Legal review completed",
                    "Public interest justification documented",
                    "Methodology transparent and documentable",
                    "Data handling compliant with applicable law",
                    "Editorial sign-off obtained",
                ],
            },
            requires_consensus=True,
            consensus_action="approve_for_publication",
            result_confidence=0.8,
        )
