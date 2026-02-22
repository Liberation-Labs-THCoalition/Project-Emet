"""Investigation workflow engine for Project Emet.

Provides YAML-defined investigation templates that chain Emet's
capabilities into automated, repeatable workflows.

Workflows orchestrate the MCP tool layer — each step maps to a
tool call with parameter passing between steps.

Usage::

    from emet.workflows import WorkflowEngine, WorkflowRegistry

    registry = WorkflowRegistry()
    registry.load_builtins()

    engine = WorkflowEngine(registry=registry)
    result = await engine.run("corporate_ownership", {
        "target": "Acme Holdings Ltd",
    })
"""

from emet.workflows.schema import (
    WorkflowDef,
    WorkflowStep,
    StepCondition,
    WorkflowParam,
)
from emet.workflows.engine import WorkflowEngine, WorkflowRun, StepResult
from emet.workflows.registry import WorkflowRegistry

__all__ = [
    "WorkflowDef",
    "WorkflowStep",
    "StepCondition",
    "WorkflowParam",
    "WorkflowEngine",
    "WorkflowRun",
    "StepResult",
    "WorkflowRegistry",
]
