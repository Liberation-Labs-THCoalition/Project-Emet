"""Investigation skill chip registry.

All skill chips are registered here for discovery by the orchestrator.
"""

from ftm_harness.skills.base import BaseSkillChip, SkillDomain

# Lazy registry — chips are imported on first access to avoid
# import-time side effects and circular dependencies.

SKILL_CHIP_REGISTRY: dict[str, str] = {
    # Investigation core
    "entity_search": "ftm_harness.skills.investigation.entity_search.EntitySearchChip",
    "cross_reference": "ftm_harness.skills.investigation.cross_reference.CrossReferenceChip",
    "document_analysis": "ftm_harness.skills.investigation.document_analysis.DocumentAnalysisChip",
    "nlp_extraction": "ftm_harness.skills.investigation.nlp_extraction.NLPExtractionChip",
    "network_analysis": "ftm_harness.skills.investigation.network_analysis.NetworkAnalysisChip",
    "data_quality": "ftm_harness.skills.investigation.data_quality.DataQualityChip",
    # Specialized
    "financial_investigation": "ftm_harness.skills.specialized.financial_investigation.FinancialInvestigationChip",
    "government_accountability": "ftm_harness.skills.specialized.government_accountability.GovernmentAccountabilityChip",
    "corporate_research": "ftm_harness.skills.specialized.corporate_research.CorporateResearchChip",
    "environmental_investigation": "ftm_harness.skills.specialized.environmental_investigation.EnvironmentalInvestigationChip",
    "labor_investigation": "ftm_harness.skills.specialized.labor_investigation.LaborInvestigationChip",
    # Monitoring
    "monitoring": "ftm_harness.skills.monitoring.monitoring.MonitoringChip",
    # Publication
    "verification": "ftm_harness.skills.publication.verification.VerificationChip",
    "story_development": "ftm_harness.skills.publication.story_development.StoryDevelopmentChip",
    # Resources
    "resources": "ftm_harness.skills.resources.resources.ResourcesChip",
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
