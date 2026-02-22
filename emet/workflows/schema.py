"""Workflow definition schema.

Defines the structure of investigation workflow templates using
plain dataclasses that serialize cleanly to/from YAML.

A workflow is:
  - Metadata (name, description, version, author)
  - Parameters (user inputs required to start)
  - Steps (ordered sequence of tool calls with parameter passing)
  - Conditions (optional branching based on step results)

Example YAML::

    name: corporate_ownership
    description: Trace corporate ownership and screen for sanctions
    version: "1.0"
    parameters:
      - name: target
        type: string
        required: true
        description: Company name to investigate
    steps:
      - id: search
        tool: search_entities
        params:
          query: "{{ target }}"
          entity_type: Company
      - id: screen
        tool: screen_sanctions
        params:
          entities: "{{ search.entities }}"
        condition:
          if: "{{ search.result_count > 0 }}"
      - id: report
        tool: generate_report
        params:
          title: "Ownership Report: {{ target }}"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowParam:
    """A parameter the user must provide to start a workflow."""
    name: str
    type: str = "string"    # string, integer, boolean, list
    required: bool = True
    default: Any = None
    description: str = ""


@dataclass
class StepCondition:
    """Conditional execution for a workflow step."""
    if_expr: str = ""       # Jinja-style expression: "{{ search.result_count > 0 }}"
    skip_message: str = ""  # Message if step is skipped


@dataclass
class WorkflowStep:
    """A single step in an investigation workflow.

    Each step maps to an MCP tool call.  Parameters can reference
    outputs from previous steps using {{ step_id.field }} syntax.
    """
    id: str
    tool: str                                   # MCP tool name
    params: dict[str, Any] = field(default_factory=dict)
    condition: StepCondition | None = None
    description: str = ""
    timeout_seconds: float = 300.0
    on_error: str = "continue"                  # continue, abort, skip


@dataclass
class WorkflowDef:
    """Complete workflow definition."""
    name: str
    description: str
    version: str = "1.0"
    author: str = ""
    category: str = "investigation"
    tags: list[str] = field(default_factory=list)
    parameters: list[WorkflowParam] = field(default_factory=list)
    steps: list[WorkflowStep] = field(default_factory=list)

    def validate(self) -> list[str]:
        """Validate workflow definition.  Returns list of error messages."""
        errors: list[str] = []
        if not self.name:
            errors.append("Workflow name is required")
        if not self.steps:
            errors.append("Workflow must have at least one step")

        step_ids = set()
        for step in self.steps:
            if not step.id:
                errors.append(f"Step missing id (tool: {step.tool})")
            if step.id in step_ids:
                errors.append(f"Duplicate step id: {step.id}")
            step_ids.add(step.id)
            if not step.tool:
                errors.append(f"Step '{step.id}' missing tool name")

        # Check required parameters have no gaps
        param_names = {p.name for p in self.parameters}
        if len(param_names) != len(self.parameters):
            errors.append("Duplicate parameter names")

        return errors

    def get_required_params(self) -> list[str]:
        """Return names of required parameters."""
        return [p.name for p in self.parameters if p.required]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict (YAML-friendly)."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "category": self.category,
            "tags": self.tags,
            "parameters": [
                {
                    "name": p.name,
                    "type": p.type,
                    "required": p.required,
                    "default": p.default,
                    "description": p.description,
                }
                for p in self.parameters
            ],
            "steps": [
                {
                    "id": s.id,
                    "tool": s.tool,
                    "params": s.params,
                    "description": s.description,
                    "timeout_seconds": s.timeout_seconds,
                    "on_error": s.on_error,
                    **(
                        {"condition": {"if": s.condition.if_expr, "skip_message": s.condition.skip_message}}
                        if s.condition else {}
                    ),
                }
                for s in self.steps
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowDef":
        """Deserialize from dict (parsed YAML)."""
        params = [
            WorkflowParam(
                name=p["name"],
                type=p.get("type", "string"),
                required=p.get("required", True),
                default=p.get("default"),
                description=p.get("description", ""),
            )
            for p in data.get("parameters", [])
        ]

        steps = []
        for s in data.get("steps", []):
            condition = None
            if "condition" in s:
                cond_data = s["condition"]
                condition = StepCondition(
                    if_expr=cond_data.get("if", ""),
                    skip_message=cond_data.get("skip_message", ""),
                )
            steps.append(
                WorkflowStep(
                    id=s["id"],
                    tool=s["tool"],
                    params=s.get("params", {}),
                    condition=condition,
                    description=s.get("description", ""),
                    timeout_seconds=s.get("timeout_seconds", 300.0),
                    on_error=s.get("on_error", "continue"),
                )
            )

        return cls(
            name=data["name"],
            description=data.get("description", ""),
            version=data.get("version", "1.0"),
            author=data.get("author", ""),
            category=data.get("category", "investigation"),
            tags=data.get("tags", []),
            parameters=params,
            steps=steps,
        )
