"""Workflow execution engine.

Runs investigation workflows by sequentially executing steps,
resolving parameter references between steps, evaluating conditions,
and tracking execution state for pause/resume/audit.

Architecture:
  - WorkflowEngine: Orchestrates execution, delegates tool calls to EmetToolExecutor
  - WorkflowRun: Tracks state of a single workflow execution
  - StepResult: Captures output of each step
  - Parameter resolution: {{ step_id.field }} syntax, nested dot access

The engine is intentionally simple — a linear step executor with
conditional skipping.  More complex DAG/parallel execution is
deferred to a future sprint when real usage patterns emerge.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from emet.workflows.schema import WorkflowDef, WorkflowStep

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Execution state
# ---------------------------------------------------------------------------


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class StepResult:
    """Result of executing a single workflow step."""
    step_id: str
    tool: str
    status: StepStatus
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0
    skip_reason: str = ""


@dataclass
class WorkflowRun:
    """Tracks the full state of a workflow execution.

    Supports pause/resume by serializing to dict and rehydrating.
    """
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    workflow_name: str = ""
    status: RunStatus = RunStatus.PENDING
    inputs: dict[str, Any] = field(default_factory=dict)
    step_results: list[StepResult] = field(default_factory=list)
    current_step_index: int = 0
    started_at: str = ""
    completed_at: str = ""
    error: str = ""

    @property
    def step_outputs(self) -> dict[str, dict[str, Any]]:
        """Map of step_id → output for parameter resolution."""
        return {
            sr.step_id: sr.output
            for sr in self.step_results
            if sr.status == StepStatus.COMPLETED
        }

    @property
    def entity_count(self) -> int:
        """Total entities produced across all steps."""
        total = 0
        for sr in self.step_results:
            entities = sr.output.get("entities", [])
            total += len(entities) if isinstance(entities, list) else 0
            total += sr.output.get("entity_count", 0)
        return total

    def summary(self) -> dict[str, Any]:
        """Generate execution summary."""
        return {
            "run_id": self.run_id,
            "workflow": self.workflow_name,
            "status": self.status.value,
            "inputs": self.inputs,
            "steps_completed": sum(
                1 for sr in self.step_results
                if sr.status in (StepStatus.COMPLETED, StepStatus.SKIPPED)
            ),
            "steps_total": len(self.step_results) + (
                1 if self.status == RunStatus.RUNNING else 0
            ),
            "entity_count": self.entity_count,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize for persistence/resume."""
        return {
            "run_id": self.run_id,
            "workflow_name": self.workflow_name,
            "status": self.status.value,
            "inputs": self.inputs,
            "current_step_index": self.current_step_index,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "step_results": [
                {
                    "step_id": sr.step_id,
                    "tool": sr.tool,
                    "status": sr.status.value,
                    "output": sr.output,
                    "error": sr.error,
                    "started_at": sr.started_at,
                    "completed_at": sr.completed_at,
                    "duration_seconds": sr.duration_seconds,
                    "skip_reason": sr.skip_reason,
                }
                for sr in self.step_results
            ],
        }


# ---------------------------------------------------------------------------
# Parameter resolution
# ---------------------------------------------------------------------------

# Matches {{ expr }} patterns
_TEMPLATE_RE = re.compile(r"\{\{\s*(.+?)\s*\}\}")


def resolve_params(
    params: dict[str, Any],
    inputs: dict[str, Any],
    step_outputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Resolve {{ }} template expressions in step parameters.

    Supports:
      - {{ target }}              → inputs["target"]
      - {{ search.entities }}     → step_outputs["search"]["entities"]
      - {{ search.result_count }} → step_outputs["search"]["result_count"]
      - Nested: {{ search.entities[0].name }}

    Non-string values are passed through unchanged.
    """
    resolved = {}
    for key, value in params.items():
        resolved[key] = _resolve_value(value, inputs, step_outputs)
    return resolved


def _resolve_value(
    value: Any,
    inputs: dict[str, Any],
    step_outputs: dict[str, dict[str, Any]],
) -> Any:
    """Resolve a single value, handling strings and nested structures."""
    if isinstance(value, str):
        return _resolve_string(value, inputs, step_outputs)
    if isinstance(value, dict):
        return {k: _resolve_value(v, inputs, step_outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_value(v, inputs, step_outputs) for v in value]
    return value


def _resolve_string(
    template: str,
    inputs: dict[str, Any],
    step_outputs: dict[str, dict[str, Any]],
) -> Any:
    """Resolve template expressions in a string value.

    If the entire string is a single {{ expr }}, return the resolved
    value directly (preserving type).  If it contains mixed text and
    templates, interpolate as string.
    """
    # Check if entire string is a single expression
    match = _TEMPLATE_RE.fullmatch(template.strip())
    if match:
        expr = match.group(1).strip()
        return _evaluate_expr(expr, inputs, step_outputs)

    # Mixed template — interpolate as string
    def replacer(m: re.Match) -> str:
        expr = m.group(1).strip()
        result = _evaluate_expr(expr, inputs, step_outputs)
        return str(result) if result is not None else ""

    return _TEMPLATE_RE.sub(replacer, template)


def _evaluate_expr(
    expr: str,
    inputs: dict[str, Any],
    step_outputs: dict[str, dict[str, Any]],
) -> Any:
    """Evaluate a template expression.

    Supports dot-access and simple comparisons.
    """
    # Handle comparison expressions (for conditions)
    for op in (" > ", " < ", " >= ", " <= ", " == ", " != "):
        if op in expr:
            left, right = expr.split(op, 1)
            left_val = _evaluate_expr(left.strip(), inputs, step_outputs)
            right_val = _evaluate_expr(right.strip(), inputs, step_outputs)
            try:
                right_val = type(left_val)(right_val) if left_val is not None else right_val
            except (ValueError, TypeError):
                pass
            ops = {
                " > ": lambda a, b: a > b,
                " < ": lambda a, b: a < b,
                " >= ": lambda a, b: a >= b,
                " <= ": lambda a, b: a <= b,
                " == ": lambda a, b: a == b,
                " != ": lambda a, b: a != b,
            }
            try:
                return ops[op](left_val, right_val)
            except (TypeError, ValueError):
                return False

    # Try as number literal
    try:
        return int(expr)
    except ValueError:
        pass
    try:
        return float(expr)
    except ValueError:
        pass

    # Dot-access resolution
    parts = expr.split(".")
    root = parts[0]

    # Check inputs first, then step outputs
    if root in inputs:
        value = inputs[root]
        return _drill_down(value, parts[1:])
    if root in step_outputs:
        value = step_outputs[root]
        return _drill_down(value, parts[1:])

    # Unresolved — return as-is
    return expr


def _drill_down(value: Any, parts: list[str]) -> Any:
    """Navigate into nested data with dot-separated keys."""
    for part in parts:
        if value is None:
            return None
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list):
            try:
                value = value[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            value = getattr(value, part, None)
    return value


def evaluate_condition(
    condition_expr: str,
    inputs: dict[str, Any],
    step_outputs: dict[str, dict[str, Any]],
) -> bool:
    """Evaluate a step condition expression.  Returns True if step should run."""
    if not condition_expr:
        return True

    # Strip {{ }} if present
    expr = condition_expr.strip()
    if expr.startswith("{{") and expr.endswith("}}"):
        expr = expr[2:-2].strip()

    result = _evaluate_expr(expr, inputs, step_outputs)
    return bool(result)


# ---------------------------------------------------------------------------
# Workflow engine
# ---------------------------------------------------------------------------


class WorkflowEngine:
    """Executes investigation workflows.

    Workflow execution:
      1. Validate inputs against workflow parameters
      2. For each step:
         a. Evaluate condition (skip if false)
         b. Resolve parameters (substitute {{ }} references)
         c. Execute tool via EmetToolExecutor
         d. Record result
      3. Return WorkflowRun with all results

    Supports:
      - Pause/resume via WorkflowRun serialization
      - Error handling per step (continue/abort/skip)
      - Dry-run mode (resolve params without executing)
    """

    def __init__(self, tool_executor: Any = None) -> None:
        """Initialize with optional tool executor.

        If no executor provided, creates one from emet.mcp.tools.
        """
        self._executor = tool_executor

    def _get_executor(self) -> Any:
        if self._executor is None:
            from emet.mcp.tools import EmetToolExecutor
            self._executor = EmetToolExecutor()
        return self._executor

    async def run(
        self,
        workflow: WorkflowDef,
        inputs: dict[str, Any],
        dry_run: bool = False,
    ) -> WorkflowRun:
        """Execute a workflow with the given inputs."""
        # Validate
        errors = workflow.validate()
        if errors:
            run = WorkflowRun(
                workflow_name=workflow.name,
                status=RunStatus.FAILED,
                error=f"Validation errors: {'; '.join(errors)}",
            )
            return run

        # Check required parameters
        missing = []
        for param in workflow.parameters:
            if param.required and param.name not in inputs:
                if param.default is not None:
                    inputs[param.name] = param.default
                else:
                    missing.append(param.name)

        if missing:
            run = WorkflowRun(
                workflow_name=workflow.name,
                status=RunStatus.FAILED,
                inputs=inputs,
                error=f"Missing required parameters: {', '.join(missing)}",
            )
            return run

        # Initialize run
        run = WorkflowRun(
            workflow_name=workflow.name,
            status=RunStatus.RUNNING,
            inputs=inputs,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        logger.info(
            "Starting workflow '%s' (run %s) with inputs: %s",
            workflow.name, run.run_id, list(inputs.keys()),
        )

        # Execute steps
        executor = self._get_executor()
        for i, step in enumerate(workflow.steps):
            run.current_step_index = i
            step_result = await self._execute_step(
                step, inputs, run.step_outputs, executor, dry_run
            )
            run.step_results.append(step_result)

            # Handle errors
            if step_result.status == StepStatus.FAILED:
                if step.on_error == "abort":
                    run.status = RunStatus.ABORTED
                    run.error = f"Step '{step.id}' failed: {step_result.error}"
                    break
                elif step.on_error == "skip":
                    logger.warning("Step '%s' failed, skipping: %s", step.id, step_result.error)
                # continue: just proceed to next step

        # Finalize
        if run.status == RunStatus.RUNNING:
            run.status = RunStatus.COMPLETED
        run.completed_at = datetime.now(timezone.utc).isoformat()

        logger.info(
            "Workflow '%s' (run %s): %s — %d steps, %d entities",
            workflow.name, run.run_id, run.status.value,
            len(run.step_results), run.entity_count,
        )

        return run

    async def resume(
        self,
        workflow: WorkflowDef,
        run: WorkflowRun,
    ) -> WorkflowRun:
        """Resume a paused workflow from where it left off."""
        if run.status != RunStatus.PAUSED:
            run.error = f"Cannot resume: status is {run.status.value}"
            return run

        run.status = RunStatus.RUNNING
        executor = self._get_executor()

        for i in range(run.current_step_index, len(workflow.steps)):
            step = workflow.steps[i]
            run.current_step_index = i
            step_result = await self._execute_step(
                step, run.inputs, run.step_outputs, executor, dry_run=False
            )
            run.step_results.append(step_result)

            if step_result.status == StepStatus.FAILED and step.on_error == "abort":
                run.status = RunStatus.ABORTED
                run.error = f"Step '{step.id}' failed: {step_result.error}"
                break

        if run.status == RunStatus.RUNNING:
            run.status = RunStatus.COMPLETED
        run.completed_at = datetime.now(timezone.utc).isoformat()
        return run

    async def _execute_step(
        self,
        step: WorkflowStep,
        inputs: dict[str, Any],
        step_outputs: dict[str, dict[str, Any]],
        executor: Any,
        dry_run: bool,
    ) -> StepResult:
        """Execute a single workflow step."""
        started_at = datetime.now(timezone.utc).isoformat()
        start_time = time.monotonic()

        # Evaluate condition
        if step.condition and step.condition.if_expr:
            should_run = evaluate_condition(
                step.condition.if_expr, inputs, step_outputs
            )
            if not should_run:
                return StepResult(
                    step_id=step.id,
                    tool=step.tool,
                    status=StepStatus.SKIPPED,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    skip_reason=step.condition.skip_message or "Condition not met",
                )

        # Resolve parameters
        try:
            resolved_params = resolve_params(step.params, inputs, step_outputs)
        except Exception as exc:
            return StepResult(
                step_id=step.id,
                tool=step.tool,
                status=StepStatus.FAILED,
                error=f"Parameter resolution failed: {exc}",
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )

        # Dry run — return resolved params without executing
        if dry_run:
            return StepResult(
                step_id=step.id,
                tool=step.tool,
                status=StepStatus.COMPLETED,
                output={"_dry_run": True, "_resolved_params": resolved_params},
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )

        # Execute
        try:
            logger.info("Executing step '%s' (tool: %s)", step.id, step.tool)
            result = await executor.execute_raw(step.tool, resolved_params)

            elapsed = time.monotonic() - start_time
            completed_at = datetime.now(timezone.utc).isoformat()

            return StepResult(
                step_id=step.id,
                tool=step.tool,
                status=StepStatus.COMPLETED,
                output=result,
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=elapsed,
            )

        except Exception as exc:
            elapsed = time.monotonic() - start_time
            logger.exception("Step '%s' failed", step.id)
            return StepResult(
                step_id=step.id,
                tool=step.tool,
                status=StepStatus.FAILED,
                error=str(exc),
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
                duration_seconds=elapsed,
            )

    def dry_run(
        self,
        workflow: WorkflowDef,
        inputs: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Preview parameter resolution without executing.

        Synchronous convenience method — returns resolved params for each step.
        """
        preview = []
        step_outputs: dict[str, dict[str, Any]] = {}

        for step in workflow.steps:
            try:
                resolved = resolve_params(step.params, inputs, step_outputs)
            except Exception as exc:
                resolved = {"_error": str(exc)}

            should_run = True
            if step.condition and step.condition.if_expr:
                should_run = evaluate_condition(
                    step.condition.if_expr, inputs, step_outputs
                )

            preview.append({
                "step_id": step.id,
                "tool": step.tool,
                "resolved_params": resolved,
                "will_execute": should_run,
                "condition": step.condition.if_expr if step.condition else None,
            })

        return preview
