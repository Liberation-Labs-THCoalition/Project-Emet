"""Workflow registry with built-in investigation templates.

Manages workflow definitions: loading from YAML files, registering
custom workflows, and providing the 5 starter templates that ship
with Emet.

Built-in templates:
  1. corporate_ownership — Trace ownership, screen sanctions, generate report
  2. person_investigation — Search, OSINT recon, sanctions, graph analysis
  3. sanctions_screening — Batch screen entities against watchlists
  4. domain_investigation — Domain OSINT, entity extraction, monitoring
  5. due_diligence — Full KYC/AML: search, sanctions, blockchain, report
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from emet.workflows.schema import (
    WorkflowDef,
    WorkflowParam,
    WorkflowStep,
    StepCondition,
)

logger = logging.getLogger(__name__)


class WorkflowRegistry:
    """Registry of available investigation workflow templates."""

    def __init__(self) -> None:
        self._workflows: dict[str, WorkflowDef] = {}

    def register(self, workflow: WorkflowDef) -> None:
        """Register a workflow definition."""
        errors = workflow.validate()
        if errors:
            raise ValueError(f"Invalid workflow '{workflow.name}': {errors}")
        self._workflows[workflow.name] = workflow

    def unregister(self, name: str) -> None:
        self._workflows.pop(name, None)

    def get(self, name: str) -> WorkflowDef | None:
        return self._workflows.get(name)

    def list_workflows(self) -> list[dict[str, Any]]:
        """List all registered workflows with metadata."""
        return [
            {
                "name": w.name,
                "description": w.description,
                "version": w.version,
                "category": w.category,
                "tags": w.tags,
                "step_count": len(w.steps),
                "parameters": [
                    {"name": p.name, "required": p.required, "description": p.description}
                    for p in w.parameters
                ],
            }
            for w in self._workflows.values()
        ]

    def load_from_yaml(self, path: str | Path) -> None:
        """Load a workflow from a YAML file."""
        try:
            import yaml
        except ImportError:
            raise ImportError("PyYAML required for YAML workflow loading")

        path = Path(path)
        with open(path) as f:
            data = yaml.safe_load(f)

        workflow = WorkflowDef.from_dict(data)
        self.register(workflow)
        logger.info("Loaded workflow '%s' from %s", workflow.name, path)

    def load_from_directory(self, directory: str | Path) -> int:
        """Load all .yaml/.yml workflow files from a directory."""
        directory = Path(directory)
        count = 0
        if not directory.exists():
            return 0

        for path in sorted(directory.glob("*.y*ml")):
            try:
                self.load_from_yaml(path)
                count += 1
            except Exception as exc:
                logger.warning("Failed to load workflow %s: %s", path, exc)

        return count

    def load_builtins(self) -> None:
        """Register the 5 built-in investigation workflow templates."""
        for workflow in BUILTIN_WORKFLOWS:
            self.register(workflow)
        logger.info("Loaded %d built-in workflows", len(BUILTIN_WORKFLOWS))


# ---------------------------------------------------------------------------
# Built-in workflow templates
# ---------------------------------------------------------------------------


BUILTIN_WORKFLOWS: list[WorkflowDef] = [
    # --- 1. Corporate Ownership Investigation ---
    WorkflowDef(
        name="corporate_ownership",
        description=(
            "Trace corporate ownership chains, screen entities against "
            "sanctions lists, analyze the ownership graph, and generate "
            "a comprehensive report."
        ),
        version="1.0",
        author="Emet",
        category="corporate",
        tags=["ownership", "sanctions", "graph", "report"],
        parameters=[
            WorkflowParam(
                name="target",
                type="string",
                required=True,
                description="Company name to investigate",
            ),
            WorkflowParam(
                name="max_depth",
                type="integer",
                required=False,
                default=3,
                description="Ownership chain depth",
            ),
        ],
        steps=[
            WorkflowStep(
                id="search",
                tool="search_entities",
                description="Search for the target company across all sources",
                params={
                    "query": "{{ target }}",
                    "entity_type": "Company",
                },
            ),
            WorkflowStep(
                id="ownership",
                tool="trace_ownership",
                description="Trace ownership chains from the target",
                params={
                    "entity_name": "{{ target }}",
                    "max_depth": "{{ max_depth }}",
                    "include_officers": True,
                },
            ),
            WorkflowStep(
                id="sanctions",
                tool="screen_sanctions",
                description="Screen discovered entities against sanctions lists",
                params={
                    "entities": "{{ search.entities }}",
                    "threshold": 0.7,
                },
                condition=StepCondition(
                    if_expr="{{ search.result_count > 0 }}",
                    skip_message="No entities found to screen",
                ),
            ),
            WorkflowStep(
                id="graph",
                tool="analyze_graph",
                description="Analyze the ownership network structure",
                params={
                    "algorithm": "community_detection",
                },
                condition=StepCondition(
                    if_expr="{{ search.result_count > 0 }}",
                    skip_message="No entities for graph analysis",
                ),
            ),
            WorkflowStep(
                id="report",
                tool="generate_report",
                description="Generate comprehensive ownership report",
                params={
                    "title": "Corporate Ownership: {{ target }}",
                    "include_graph": True,
                    "include_timeline": True,
                },
            ),
        ],
    ),

    # --- 2. Person Investigation ---
    WorkflowDef(
        name="person_investigation",
        description=(
            "Full investigation of an individual: database search, "
            "OSINT reconnaissance, sanctions screening, and network "
            "analysis of connections."
        ),
        version="1.0",
        author="Emet",
        category="person",
        tags=["person", "osint", "sanctions", "network"],
        parameters=[
            WorkflowParam(
                name="target_name",
                type="string",
                required=True,
                description="Full name of the person to investigate",
            ),
            WorkflowParam(
                name="target_email",
                type="string",
                required=False,
                default="",
                description="Email address (optional, improves OSINT results)",
            ),
        ],
        steps=[
            WorkflowStep(
                id="search",
                tool="search_entities",
                description="Search databases for the target person",
                params={
                    "query": "{{ target_name }}",
                    "entity_type": "Person",
                },
            ),
            WorkflowStep(
                id="osint",
                tool="osint_recon",
                description="Run passive OSINT reconnaissance",
                params={
                    "target": "{{ target_email }}",
                    "scan_type": "passive",
                },
                condition=StepCondition(
                    if_expr="{{ target_email != '' }}",
                    skip_message="No email provided for OSINT",
                ),
            ),
            WorkflowStep(
                id="sanctions",
                tool="screen_sanctions",
                description="Screen against sanctions and PEP lists",
                params={
                    "entities": [{"name": "{{ target_name }}", "schema": "Person"}],
                    "threshold": 0.65,
                },
            ),
            WorkflowStep(
                id="graph",
                tool="analyze_graph",
                description="Analyze connection network",
                params={
                    "algorithm": "centrality",
                },
                condition=StepCondition(
                    if_expr="{{ search.result_count > 2 }}",
                    skip_message="Not enough connections for network analysis",
                ),
            ),
            WorkflowStep(
                id="report",
                tool="generate_report",
                description="Generate person investigation report",
                params={
                    "title": "Person Investigation: {{ target_name }}",
                    "include_graph": True,
                },
            ),
        ],
    ),

    # --- 3. Sanctions Screening ---
    WorkflowDef(
        name="sanctions_screening",
        description=(
            "Batch sanctions screening: search for entities, screen "
            "against 325+ watchlists, generate compliance report."
        ),
        version="1.0",
        author="Emet",
        category="compliance",
        tags=["sanctions", "compliance", "screening", "aml"],
        parameters=[
            WorkflowParam(
                name="entity_name",
                type="string",
                required=True,
                description="Entity name to screen",
            ),
            WorkflowParam(
                name="entity_type",
                type="string",
                required=False,
                default="Any",
                description="Person, Company, or Any",
            ),
            WorkflowParam(
                name="threshold",
                type="number",
                required=False,
                default=0.7,
                description="Match threshold (0-1)",
            ),
        ],
        steps=[
            WorkflowStep(
                id="search",
                tool="search_entities",
                description="Look up entity in databases",
                params={
                    "query": "{{ entity_name }}",
                    "entity_type": "{{ entity_type }}",
                    "sources": ["opensanctions"],
                },
            ),
            WorkflowStep(
                id="screen",
                tool="screen_sanctions",
                description="Screen against all watchlists",
                params={
                    "entities": [{"name": "{{ entity_name }}"}],
                    "threshold": "{{ threshold }}",
                },
            ),
            WorkflowStep(
                id="monitor",
                tool="monitor_entity",
                description="Set up ongoing monitoring",
                params={
                    "entity_name": "{{ entity_name }}",
                    "entity_type": "{{ entity_type }}",
                    "alert_types": ["new_sanction"],
                },
            ),
            WorkflowStep(
                id="report",
                tool="generate_report",
                description="Generate compliance report",
                params={
                    "title": "Sanctions Screening: {{ entity_name }}",
                },
            ),
        ],
    ),

    # --- 4. Domain Investigation ---
    WorkflowDef(
        name="domain_investigation",
        description=(
            "Investigate a domain: OSINT reconnaissance, extract entities "
            "from associated data, set up monitoring for changes."
        ),
        version="1.0",
        author="Emet",
        category="technical",
        tags=["domain", "osint", "dns", "monitoring"],
        parameters=[
            WorkflowParam(
                name="domain",
                type="string",
                required=True,
                description="Domain to investigate (e.g. example.com)",
            ),
        ],
        steps=[
            WorkflowStep(
                id="osint",
                tool="osint_recon",
                description="Run domain OSINT reconnaissance",
                params={
                    "target": "{{ domain }}",
                    "scan_type": "passive",
                },
            ),
            WorkflowStep(
                id="search",
                tool="search_entities",
                description="Search databases for domain-associated entities",
                params={
                    "query": "{{ domain }}",
                    "entity_type": "Any",
                },
            ),
            WorkflowStep(
                id="monitor",
                tool="monitor_entity",
                description="Monitor for domain changes",
                params={
                    "entity_name": "{{ domain }}",
                },
            ),
            WorkflowStep(
                id="report",
                tool="generate_report",
                description="Generate domain investigation report",
                params={
                    "title": "Domain Investigation: {{ domain }}",
                },
            ),
        ],
    ),

    # --- 5. Due Diligence (KYC/AML) ---
    WorkflowDef(
        name="due_diligence",
        description=(
            "Full KYC/AML due diligence: entity search, ownership tracing, "
            "sanctions screening, blockchain check (if crypto address "
            "provided), and comprehensive report generation."
        ),
        version="1.0",
        author="Emet",
        category="compliance",
        tags=["kyc", "aml", "due_diligence", "compliance", "blockchain"],
        parameters=[
            WorkflowParam(
                name="entity_name",
                type="string",
                required=True,
                description="Entity name for due diligence",
            ),
            WorkflowParam(
                name="entity_type",
                type="string",
                required=False,
                default="Any",
                description="Person, Company, or Any",
            ),
            WorkflowParam(
                name="crypto_address",
                type="string",
                required=False,
                default="",
                description="Blockchain address to check (optional)",
            ),
        ],
        steps=[
            WorkflowStep(
                id="search",
                tool="search_entities",
                description="Comprehensive entity search",
                params={
                    "query": "{{ entity_name }}",
                    "entity_type": "{{ entity_type }}",
                },
            ),
            WorkflowStep(
                id="ownership",
                tool="trace_ownership",
                description="Trace ownership structures",
                params={
                    "entity_name": "{{ entity_name }}",
                    "max_depth": 3,
                },
                condition=StepCondition(
                    if_expr="{{ entity_type != 'Person' }}",
                    skip_message="Ownership tracing not applicable for persons",
                ),
            ),
            WorkflowStep(
                id="sanctions",
                tool="screen_sanctions",
                description="Full sanctions and PEP screening",
                params={
                    "entities": [{"name": "{{ entity_name }}"}],
                    "threshold": 0.6,
                },
            ),
            WorkflowStep(
                id="blockchain",
                tool="investigate_blockchain",
                description="Check blockchain address",
                params={
                    "address": "{{ crypto_address }}",
                    "chain": "ethereum",
                },
                condition=StepCondition(
                    if_expr="{{ crypto_address != '' }}",
                    skip_message="No crypto address provided",
                ),
            ),
            WorkflowStep(
                id="graph",
                tool="analyze_graph",
                description="Analyze entity network",
                params={
                    "algorithm": "community_detection",
                },
                condition=StepCondition(
                    if_expr="{{ search.result_count > 0 }}",
                    skip_message="No entities for graph analysis",
                ),
            ),
            WorkflowStep(
                id="monitor",
                tool="monitor_entity",
                description="Set up ongoing monitoring",
                params={
                    "entity_name": "{{ entity_name }}",
                    "alert_types": ["new_sanction", "changed_property"],
                },
            ),
            WorkflowStep(
                id="report",
                tool="generate_report",
                description="Generate due diligence report",
                params={
                    "title": "Due Diligence Report: {{ entity_name }}",
                    "include_graph": True,
                    "include_timeline": True,
                },
            ),
        ],
    ),
]
