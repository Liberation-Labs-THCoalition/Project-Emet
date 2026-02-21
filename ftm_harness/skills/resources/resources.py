"""Resources Skill Chip — training, documentation, and methodology guides.

Provides investigators with access to training materials, methodology
guides, tool documentation, and best practices for investigative journalism.

This chip is unique in that it requires no external API access and no
consensus — it's purely informational and always available.

Modeled after the journalism wrapper's /help, /training, and /methodology commands.
"""

from __future__ import annotations
from typing import Any

from ftm_harness.skills.base import (
    BaseSkillChip, EFEWeights, SkillCapability,
    SkillContext, SkillDomain, SkillRequest, SkillResponse,
)


class ResourcesChip(BaseSkillChip):
    name = "resources"
    description = "Training materials, methodology guides, and tool documentation"
    version = "1.0.0"
    domain = SkillDomain.RESOURCES
    efe_weights = EFEWeights(
        accuracy=0.20, source_protection=0.10, public_interest=0.20,
        proportionality=0.20, transparency=0.30,
    )
    capabilities = []
    consensus_actions = []

    METHODOLOGY_GUIDES = {
        "aleph_basics": {
            "title": "Getting Started with Aleph",
            "topics": [
                "Creating investigations (collections)",
                "Uploading documents (ingest pipeline)",
                "Entity search (ElasticSearch query syntax)",
                "Cross-referencing between collections",
                "Entity mapping (diagrams and timelines)",
            ],
        },
        "ftm_data_model": {
            "title": "Understanding the FollowTheMoney Data Model",
            "topics": [
                "Entity schemas (Person, Company, Document, etc.)",
                "Relationship entities (Ownership, Directorship, Payment)",
                "Properties and property types",
                "Entity IDs and deterministic generation",
                "Schema inheritance and mixins",
            ],
        },
        "osint_techniques": {
            "title": "OSINT Investigation Techniques",
            "topics": [
                "Corporate registry research (OpenCorporates, national registries)",
                "Sanctions and watchlist screening (OpenSanctions/yente)",
                "Offshore entity research (ICIJ Offshore Leaks)",
                "Beneficial ownership tracing (GLEIF LEI)",
                "Document analysis and OCR workflows",
                "Network analysis and visualization",
            ],
        },
        "financial_investigation": {
            "title": "Financial Investigation Methodology",
            "topics": [
                "Following the money trail",
                "Shell company identification",
                "Beneficial ownership tracing",
                "Sanctions exposure analysis",
                "Transaction pattern analysis (structuring, layering)",
                "Tax haven jurisdictional analysis",
            ],
        },
        "source_protection": {
            "title": "Source Protection and Digital Security",
            "topics": [
                "Operational security (OpSec) for journalists",
                "Secure communication channels",
                "Document metadata scrubbing",
                "Source anonymization in publications",
                "Threat modeling for investigations",
                "Legal protections for journalists and sources",
            ],
        },
        "verification": {
            "title": "Verification and Fact-Checking",
            "topics": [
                "Multi-source corroboration requirements",
                "Document authenticity verification",
                "Source reliability assessment framework",
                "AI-assisted finding verification",
                "Pre-publication legal review checklist",
                "Right of reply procedures",
            ],
        },
        "government_accountability": {
            "title": "Government Accountability Investigation",
            "topics": [
                "FOIA request strategies",
                "Campaign finance analysis",
                "Lobbying disclosure research",
                "Procurement fraud detection",
                "Public official asset disclosure analysis",
                "Revolving door tracking",
            ],
        },
    }

    TOOL_REFERENCE = {
        "search_syntax": {
            "title": "Aleph Search Syntax Reference",
            "examples": [
                'Simple: putin',
                'Boolean: oligarch AND (sanctions OR pep)',
                'Exact phrase: "shell company"',
                'Wildcard: gazprom*',
                'Fuzzy: Газпром~',
                'Field: schema:Company',
                'Exclude: company NOT dissolved',
                'Proximity: "money laundering"~3',
            ],
        },
        "ftm_schemas": {
            "title": "Common FtM Schemas",
            "node_schemas": [
                "Person", "Company", "Organization", "PublicBody",
                "Vehicle", "Vessel", "Airplane", "RealEstate",
                "Document", "BankAccount", "Address",
            ],
            "relationship_schemas": [
                "Ownership", "Directorship", "Membership", "Employment",
                "Family", "Associate", "Payment", "Debt", "Sanction",
            ],
        },
    }

    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        intent = request.intent.lower()
        dispatch = {
            "methodology": self._methodology,
            "guide": self._methodology,
            "training": self._training,
            "tool_reference": self._tool_reference,
            "search_syntax": self._search_syntax,
            "list_skills": self._list_skills,
            "help": self._help,
        }
        handler = dispatch.get(intent, self._help)
        return await handler(request, context)

    async def _help(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        return SkillResponse(
            content="FtM Harness — Investigative Journalism Agent Framework",
            success=True,
            data={
                "available_guides": list(self.METHODOLOGY_GUIDES.keys()),
                "available_tools": list(self.TOOL_REFERENCE.keys()),
                "skill_domains": [
                    "entity_search", "cross_reference", "document_analysis",
                    "nlp_extraction", "network_analysis", "data_quality",
                    "financial_investigation", "government_accountability",
                    "environmental_investigation", "labor_investigation",
                    "corporate_research", "monitoring", "verification",
                    "story_development", "resources",
                ],
            },
            result_confidence=1.0,
        )

    async def _methodology(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        topic = request.parameters.get("topic", "")
        if topic in self.METHODOLOGY_GUIDES:
            guide = self.METHODOLOGY_GUIDES[topic]
            return SkillResponse(
                content=f"Methodology guide: {guide['title']}",
                success=True,
                data={"guide": guide},
                result_confidence=1.0,
            )
        return SkillResponse(
            content="Available methodology guides.",
            success=True,
            data={
                "guides": {k: v["title"] for k, v in self.METHODOLOGY_GUIDES.items()},
            },
            result_confidence=1.0,
        )

    async def _training(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        return SkillResponse(
            content="Training materials for investigative journalism with the FtM Harness.",
            success=True,
            data={
                "training_tracks": {
                    "beginner": ["aleph_basics", "ftm_data_model", "source_protection"],
                    "intermediate": ["osint_techniques", "verification", "government_accountability"],
                    "advanced": ["financial_investigation", "network_analysis", "cross_border"],
                },
            },
            result_confidence=1.0,
        )

    async def _tool_reference(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        tool = request.parameters.get("tool", "")
        if tool in self.TOOL_REFERENCE:
            return SkillResponse(
                content=f"Tool reference: {self.TOOL_REFERENCE[tool]['title']}",
                success=True,
                data={"reference": self.TOOL_REFERENCE[tool]},
                result_confidence=1.0,
            )
        return SkillResponse(
            content="Available tool references.",
            success=True,
            data={"tools": {k: v["title"] for k, v in self.TOOL_REFERENCE.items()}},
            result_confidence=1.0,
        )

    async def _search_syntax(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        ref = self.TOOL_REFERENCE["search_syntax"]
        return SkillResponse(
            content="Aleph Search Syntax Reference",
            success=True,
            data={"reference": ref},
            result_confidence=1.0,
        )

    async def _list_skills(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        return SkillResponse(
            content="All registered skill chips.",
            success=True,
            data={
                "investigation": [
                    "entity_search", "cross_reference", "document_analysis",
                    "nlp_extraction", "network_analysis", "data_quality",
                ],
                "specialized": [
                    "financial_investigation", "government_accountability",
                    "environmental_investigation", "labor_investigation",
                    "corporate_research",
                ],
                "monitoring": ["monitoring"],
                "publication": ["verification", "story_development"],
                "resources": ["resources"],
            },
            result_confidence=1.0,
        )
