"""Investigation skill chip registry.

All skill chips are registered here for discovery by the orchestrator.
"""

from emet.skills.base import BaseSkillChip, SkillDomain

# Lazy registry — chips are imported on first access to avoid
# import-time side effects and circular dependencies.

SKILL_CHIP_REGISTRY: dict[str, str] = {
    # Investigation core
    "entity_search": "emet.skills.investigation.entity_search.EntitySearchChip",
    "cross_reference": "emet.skills.investigation.cross_reference.CrossReferenceChip",
    "document_analysis": "emet.skills.investigation.document_analysis.DocumentAnalysisChip",
    "nlp_extraction": "emet.skills.investigation.nlp_extraction.NLPExtractionChip",
    "network_analysis": "emet.skills.investigation.network_analysis.NetworkAnalysisChip",
    "data_quality": "emet.skills.investigation.data_quality.DataQualityChip",
    # Specialized
    "financial_investigation": "emet.skills.specialized.financial_investigation.FinancialInvestigationChip",
    "government_accountability": "emet.skills.specialized.government_accountability.GovernmentAccountabilityChip",
    "corporate_research": "emet.skills.specialized.corporate_research.CorporateResearchChip",
    "environmental_investigation": "emet.skills.specialized.environmental_investigation.EnvironmentalInvestigationChip",
    "labor_investigation": "emet.skills.specialized.labor_investigation.LaborInvestigationChip",
    # Monitoring
    "monitoring": "emet.skills.monitoring.monitoring.MonitoringChip",
    # Publication
    "verification": "emet.skills.publication.verification.VerificationChip",
    "story_development": "emet.skills.publication.story_development.StoryDevelopmentChip",
    # Resources
    "resources": "emet.skills.resources.resources.ResourcesChip",
}


def get_chip(name: str) -> BaseSkillChip:
    """Instantiate a skill chip by name from the registry."""
    if name not in SKILL_CHIP_REGISTRY:
        raise KeyError(f"Unknown skill chip: '{name}'. Available: {list(SKILL_CHIP_REGISTRY.keys())}")

    import importlib
    module_path, class_name = SKILL_CHIP_REGISTRY[name].rsplit(".", 1)
    module = importlib.import_module(module_path)
    chip_class = getattr(module, class_name)
    return chip_class()


def list_chips() -> list[dict]:
    """List all registered skill chips with metadata."""
    chips = []
    for name, path in SKILL_CHIP_REGISTRY.items():
        try:
            chip = get_chip(name)
            chips.append(chip.get_info())
        except Exception as e:
            chips.append({"name": name, "error": str(e)})
    return chips
