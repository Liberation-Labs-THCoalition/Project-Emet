"""Tests for investigation workflow engine — Sprint 11.

Tests workflow schema, parameter resolution, condition evaluation,
engine execution, registry, and built-in templates.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from emet.workflows.schema import (
    WorkflowDef,
    WorkflowStep,
    WorkflowParam,
    StepCondition,
)
from emet.workflows.engine import (
    WorkflowEngine,
    WorkflowRun,
    StepResult,
    RunStatus,
    StepStatus,
    resolve_params,
    evaluate_condition,
    _evaluate_expr,
    _drill_down,
)
from emet.workflows.registry import WorkflowRegistry, BUILTIN_WORKFLOWS


# ===========================================================================
# Schema
# ===========================================================================


class TestWorkflowDef:
    """Test workflow definition validation and serialization."""

    def test_valid_workflow(self):
        wf = WorkflowDef(
            name="test",
            description="Test workflow",
            steps=[
                WorkflowStep(id="s1", tool="search_entities", params={"query": "test"}),
            ],
        )
        assert wf.validate() == []

    def test_missing_name(self):
        wf = WorkflowDef(name="", description="", steps=[
            WorkflowStep(id="s1", tool="search_entities"),
        ])
        errors = wf.validate()
        assert any("name" in e.lower() for e in errors)

    def test_no_steps(self):
        wf = WorkflowDef(name="test", description="", steps=[])
        errors = wf.validate()
        assert any("step" in e.lower() for e in errors)

    def test_duplicate_step_ids(self):
        wf = WorkflowDef(
            name="test", description="",
            steps=[
                WorkflowStep(id="s1", tool="tool_a"),
                WorkflowStep(id="s1", tool="tool_b"),
            ],
        )
        errors = wf.validate()
        assert any("duplicate" in e.lower() for e in errors)

    def test_missing_step_tool(self):
        wf = WorkflowDef(
            name="test", description="",
            steps=[WorkflowStep(id="s1", tool="")],
        )
        errors = wf.validate()
        assert any("tool" in e.lower() for e in errors)

    def test_get_required_params(self):
        wf = WorkflowDef(
            name="test", description="",
            parameters=[
                WorkflowParam(name="a", required=True),
                WorkflowParam(name="b", required=False),
                WorkflowParam(name="c", required=True),
            ],
            steps=[WorkflowStep(id="s1", tool="t")],
        )
        assert wf.get_required_params() == ["a", "c"]

    def test_to_dict_roundtrip(self):
        wf = WorkflowDef(
            name="test",
            description="desc",
            version="2.0",
            parameters=[
                WorkflowParam(name="target", required=True, description="Target name"),
            ],
            steps=[
                WorkflowStep(
                    id="search",
                    tool="search_entities",
                    params={"query": "{{ target }}"},
                    condition=StepCondition(if_expr="{{ target != '' }}"),
                ),
            ],
        )
        data = wf.to_dict()
        restored = WorkflowDef.from_dict(data)
        assert restored.name == "test"
        assert restored.version == "2.0"
        assert len(restored.parameters) == 1
        assert restored.parameters[0].name == "target"
        assert len(restored.steps) == 1
        assert restored.steps[0].condition.if_expr == "{{ target != '' }}"

    def test_from_dict_minimal(self):
        data = {
            "name": "minimal",
            "steps": [{"id": "s1", "tool": "ping"}],
        }
        wf = WorkflowDef.from_dict(data)
        assert wf.name == "minimal"
        assert len(wf.steps) == 1


# ===========================================================================
# Parameter resolution
# ===========================================================================


class TestParameterResolution:
    """Test {{ expr }} template resolution."""

    def test_simple_input_ref(self):
        result = resolve_params(
            {"query": "{{ target }}"},
            {"target": "Acme Corp"},
            {},
        )
        assert result["query"] == "Acme Corp"

    def test_step_output_ref(self):
        result = resolve_params(
            {"entities": "{{ search.entities }}"},
            {},
            {"search": {"entities": [{"id": "e1"}], "result_count": 1}},
        )
        assert result["entities"] == [{"id": "e1"}]

    def test_nested_dot_access(self):
        result = resolve_params(
            {"count": "{{ search.result_count }}"},
            {},
            {"search": {"result_count": 42}},
        )
        assert result["count"] == 42

    def test_mixed_template_and_text(self):
        result = resolve_params(
            {"title": "Report: {{ target }}"},
            {"target": "Acme"},
            {},
        )
        assert result["title"] == "Report: Acme"

    def test_non_string_passthrough(self):
        result = resolve_params(
            {"threshold": 0.7, "include": True, "limit": 20},
            {},
            {},
        )
        assert result["threshold"] == 0.7
        assert result["include"] is True
        assert result["limit"] == 20

    def test_list_values_resolved(self):
        result = resolve_params(
            {"sources": ["opensanctions", "{{ extra_source }}"]},
            {"extra_source": "icij"},
            {},
        )
        assert result["sources"] == ["opensanctions", "icij"]

    def test_dict_values_resolved(self):
        result = resolve_params(
            {"entity": {"name": "{{ target }}", "schema": "Person"}},
            {"target": "John"},
            {},
        )
        assert result["entity"]["name"] == "John"

    def test_unresolved_returns_expr(self):
        result = resolve_params(
            {"query": "{{ unknown_param }}"},
            {},
            {},
        )
        assert result["query"] == "unknown_param"


class TestDrillDown:
    """Test nested data navigation."""

    def test_dict_access(self):
        assert _drill_down({"a": {"b": 1}}, ["a", "b"]) == 1

    def test_list_access(self):
        assert _drill_down([10, 20, 30], ["1"]) == 20

    def test_none_handling(self):
        assert _drill_down(None, ["a"]) is None

    def test_missing_key(self):
        assert _drill_down({"a": 1}, ["b"]) is None

    def test_empty_parts(self):
        assert _drill_down({"a": 1}, []) == {"a": 1}


class TestEvaluateExpr:
    """Test expression evaluation."""

    def test_numeric_comparison(self):
        inputs = {}
        outputs = {"search": {"result_count": 5}}
        assert _evaluate_expr("search.result_count > 0", inputs, outputs) is True
        assert _evaluate_expr("search.result_count > 10", inputs, outputs) is False

    def test_string_comparison(self):
        inputs = {"target": "hello"}
        assert _evaluate_expr("target != ''", inputs, {}) is True

    def test_equality(self):
        inputs = {"type": "Person"}
        assert _evaluate_expr("type == Person", inputs, {}) is True

    def test_number_literal(self):
        assert _evaluate_expr("42", {}, {}) == 42
        assert _evaluate_expr("3.14", {}, {}) == 3.14


class TestEvaluateCondition:
    """Test condition evaluation for step skipping."""

    def test_empty_condition_runs(self):
        assert evaluate_condition("", {}, {}) is True

    def test_true_condition(self):
        assert evaluate_condition(
            "{{ search.result_count > 0 }}",
            {},
            {"search": {"result_count": 5}},
        ) is True

    def test_false_condition(self):
        assert evaluate_condition(
            "{{ search.result_count > 0 }}",
            {},
            {"search": {"result_count": 0}},
        ) is False

    def test_string_condition(self):
        assert evaluate_condition(
            "{{ email != '' }}",
            {"email": "test@test.com"},
            {},
        ) is True

    def test_without_braces(self):
        assert evaluate_condition(
            "search.result_count > 0",
            {},
            {"search": {"result_count": 3}},
        ) is True


# ===========================================================================
# Workflow Run state
# ===========================================================================


class TestWorkflowRun:
    """Test workflow run state tracking."""

    def test_initial_state(self):
        run = WorkflowRun(workflow_name="test")
        assert run.status == RunStatus.PENDING
        assert run.entity_count == 0

    def test_step_outputs_map(self):
        run = WorkflowRun()
        run.step_results = [
            StepResult(step_id="s1", tool="t1", status=StepStatus.COMPLETED, output={"a": 1}),
            StepResult(step_id="s2", tool="t2", status=StepStatus.SKIPPED),
            StepResult(step_id="s3", tool="t3", status=StepStatus.COMPLETED, output={"b": 2}),
        ]
        outputs = run.step_outputs
        assert "s1" in outputs
        assert "s3" in outputs
        assert "s2" not in outputs  # Skipped

    def test_entity_count(self):
        run = WorkflowRun()
        run.step_results = [
            StepResult(
                step_id="s1", tool="t1", status=StepStatus.COMPLETED,
                output={"entities": [{"id": "e1"}, {"id": "e2"}]},
            ),
            StepResult(
                step_id="s2", tool="t2", status=StepStatus.COMPLETED,
                output={"entity_count": 3},
            ),
        ]
        assert run.entity_count == 5

    def test_summary(self):
        run = WorkflowRun(workflow_name="test", status=RunStatus.COMPLETED)
        run.step_results = [
            StepResult(step_id="s1", tool="t", status=StepStatus.COMPLETED),
            StepResult(step_id="s2", tool="t", status=StepStatus.SKIPPED),
        ]
        summary = run.summary()
        assert summary["workflow"] == "test"
        assert summary["status"] == "completed"
        assert summary["steps_completed"] == 2

    def test_serialization(self):
        run = WorkflowRun(workflow_name="test", status=RunStatus.COMPLETED)
        run.step_results = [
            StepResult(step_id="s1", tool="t", status=StepStatus.COMPLETED, output={"x": 1}),
        ]
        data = run.to_dict()
        assert data["workflow_name"] == "test"
        assert len(data["step_results"]) == 1


# ===========================================================================
# Workflow Engine
# ===========================================================================


class MockExecutor:
    """Mock tool executor for workflow engine tests."""

    def __init__(self, responses: dict[str, dict] | None = None):
        self.responses = responses or {}
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, tool_name: str, arguments: dict) -> dict:
        self.calls.append((tool_name, arguments))
        response = self.responses.get(tool_name, {
            "isError": False,
            "content": [{"type": "text", "text": "ok"}],
            "_raw": {"result_count": 1, "entities": []},
        })
        return response

    async def execute_raw(self, tool_name: str, arguments: dict) -> dict:
        wrapped = await self.execute(tool_name, arguments)
        if wrapped.get("isError"):
            error_text = ""
            for content in wrapped.get("content", []):
                if content.get("type") == "text":
                    error_text = content.get("text", "")
            raise RuntimeError(error_text or "Tool execution failed")
        return wrapped.get("_raw", wrapped)


class TestWorkflowEngine:
    """Test workflow engine execution."""

    def _simple_workflow(self) -> WorkflowDef:
        return WorkflowDef(
            name="test_wf",
            description="Test",
            parameters=[WorkflowParam(name="target", required=True)],
            steps=[
                WorkflowStep(id="search", tool="search_entities", params={"query": "{{ target }}"}),
                WorkflowStep(id="report", tool="generate_report", params={"title": "Report: {{ target }}"}),
            ],
        )

    @pytest.mark.asyncio
    async def test_basic_execution(self):
        executor = MockExecutor()
        engine = WorkflowEngine(tool_executor=executor)

        run = await engine.run(self._simple_workflow(), {"target": "Acme"})

        assert run.status == RunStatus.COMPLETED
        assert len(run.step_results) == 2
        assert all(sr.status == StepStatus.COMPLETED for sr in run.step_results)
        assert len(executor.calls) == 2
        assert executor.calls[0] == ("search_entities", {"query": "Acme"})
        assert executor.calls[1] == ("generate_report", {"title": "Report: Acme"})

    @pytest.mark.asyncio
    async def test_missing_required_param(self):
        engine = WorkflowEngine(tool_executor=MockExecutor())
        run = await engine.run(self._simple_workflow(), {})
        assert run.status == RunStatus.FAILED
        assert "Missing required" in run.error

    @pytest.mark.asyncio
    async def test_default_param(self):
        wf = WorkflowDef(
            name="test", description="",
            parameters=[
                WorkflowParam(name="target", required=True),
                WorkflowParam(name="limit", required=True, default=20),
            ],
            steps=[
                WorkflowStep(id="s1", tool="search_entities", params={"query": "{{ target }}", "limit": "{{ limit }}"}),
            ],
        )
        executor = MockExecutor()
        engine = WorkflowEngine(tool_executor=executor)
        run = await engine.run(wf, {"target": "Test"})
        assert run.status == RunStatus.COMPLETED
        assert executor.calls[0][1]["limit"] == 20

    @pytest.mark.asyncio
    async def test_condition_skips_step(self):
        wf = WorkflowDef(
            name="test", description="",
            parameters=[WorkflowParam(name="target", required=True)],
            steps=[
                WorkflowStep(
                    id="search", tool="search_entities",
                    params={"query": "{{ target }}"},
                ),
                WorkflowStep(
                    id="graph", tool="analyze_graph",
                    params={"algorithm": "centrality"},
                    condition=StepCondition(
                        if_expr="{{ search.result_count > 10 }}",
                        skip_message="Not enough results",
                    ),
                ),
            ],
        )
        executor = MockExecutor({
            "search_entities": {
                "isError": False,
                "content": [{"type": "text", "text": "ok"}],
                "_raw": {"result_count": 2, "entities": []},
            },
        })
        engine = WorkflowEngine(tool_executor=executor)
        run = await engine.run(wf, {"target": "Test"})

        assert run.status == RunStatus.COMPLETED
        assert run.step_results[1].status == StepStatus.SKIPPED
        assert run.step_results[1].skip_reason == "Not enough results"
        assert len(executor.calls) == 1  # Graph not called

    @pytest.mark.asyncio
    async def test_step_error_continue(self):
        wf = WorkflowDef(
            name="test", description="",
            parameters=[WorkflowParam(name="target", required=True)],
            steps=[
                WorkflowStep(id="s1", tool="failing_tool", on_error="continue"),
                WorkflowStep(id="s2", tool="search_entities"),
            ],
        )
        executor = MockExecutor({
            "failing_tool": {
                "isError": True,
                "content": [{"type": "text", "text": "boom"}],
            },
        })
        engine = WorkflowEngine(tool_executor=executor)
        run = await engine.run(wf, {"target": "Test"})

        assert run.status == RunStatus.COMPLETED  # Continued past error
        assert run.step_results[0].status == StepStatus.FAILED
        assert run.step_results[1].status == StepStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_step_error_abort(self):
        wf = WorkflowDef(
            name="test", description="",
            parameters=[WorkflowParam(name="target", required=True)],
            steps=[
                WorkflowStep(id="s1", tool="failing_tool", on_error="abort"),
                WorkflowStep(id="s2", tool="search_entities"),
            ],
        )
        executor = MockExecutor({
            "failing_tool": {
                "isError": True,
                "content": [{"type": "text", "text": "boom"}],
            },
        })
        engine = WorkflowEngine(tool_executor=executor)
        run = await engine.run(wf, {"target": "Test"})

        assert run.status == RunStatus.ABORTED
        assert len(run.step_results) == 1  # Stopped after first step

    @pytest.mark.asyncio
    async def test_step_output_passed_to_next(self):
        wf = WorkflowDef(
            name="test", description="",
            parameters=[WorkflowParam(name="target", required=True)],
            steps=[
                WorkflowStep(id="search", tool="search_entities", params={"query": "{{ target }}"}),
                WorkflowStep(id="screen", tool="screen_sanctions", params={"entities": "{{ search.entities }}"}),
            ],
        )
        mock_entities = [{"id": "e1", "name": "Bad Corp"}]
        executor = MockExecutor({
            "search_entities": {
                "result_count": 1, "entities": mock_entities,
            },
        })
        engine = WorkflowEngine(tool_executor=executor)
        run = await engine.run(wf, {"target": "Test"})

        # screen_sanctions should receive the entities from search
        assert executor.calls[1][1]["entities"] == mock_entities

    @pytest.mark.asyncio
    async def test_dry_run(self):
        executor = MockExecutor()
        engine = WorkflowEngine(tool_executor=executor)
        run = await engine.run(self._simple_workflow(), {"target": "Acme"}, dry_run=True)

        assert run.status == RunStatus.COMPLETED
        assert len(executor.calls) == 0  # Nothing actually executed
        for sr in run.step_results:
            assert sr.output.get("_dry_run") is True

    @pytest.mark.asyncio
    async def test_validation_errors_fail_immediately(self):
        bad_wf = WorkflowDef(name="", description="", steps=[])
        engine = WorkflowEngine(tool_executor=MockExecutor())
        run = await engine.run(bad_wf, {})
        assert run.status == RunStatus.FAILED
        assert "Validation" in run.error

    def test_dry_run_preview(self):
        engine = WorkflowEngine()
        wf = self._simple_workflow()
        preview = engine.dry_run(wf, {"target": "Acme"})
        assert len(preview) == 2
        assert preview[0]["resolved_params"]["query"] == "Acme"
        assert preview[1]["resolved_params"]["title"] == "Report: Acme"


# ===========================================================================
# Registry
# ===========================================================================


class TestWorkflowRegistry:
    """Test workflow registry."""

    def test_register_and_get(self):
        registry = WorkflowRegistry()
        wf = WorkflowDef(
            name="test", description="",
            steps=[WorkflowStep(id="s1", tool="t")],
        )
        registry.register(wf)
        assert registry.get("test") is not None
        assert registry.get("nonexistent") is None

    def test_register_invalid_raises(self):
        registry = WorkflowRegistry()
        bad_wf = WorkflowDef(name="", description="", steps=[])
        with pytest.raises(ValueError):
            registry.register(bad_wf)

    def test_unregister(self):
        registry = WorkflowRegistry()
        wf = WorkflowDef(name="test", description="", steps=[WorkflowStep(id="s1", tool="t")])
        registry.register(wf)
        registry.unregister("test")
        assert registry.get("test") is None

    def test_list_workflows(self):
        registry = WorkflowRegistry()
        wf = WorkflowDef(
            name="test", description="A test", category="testing",
            parameters=[WorkflowParam(name="x", required=True)],
            steps=[WorkflowStep(id="s1", tool="t")],
        )
        registry.register(wf)
        listing = registry.list_workflows()
        assert len(listing) == 1
        assert listing[0]["name"] == "test"
        assert listing[0]["category"] == "testing"
        assert listing[0]["step_count"] == 1

    def test_load_builtins(self):
        registry = WorkflowRegistry()
        registry.load_builtins()
        listing = registry.list_workflows()
        assert len(listing) == 5
        names = {w["name"] for w in listing}
        assert names == {
            "corporate_ownership",
            "person_investigation",
            "sanctions_screening",
            "domain_investigation",
            "due_diligence",
        }


# ===========================================================================
# Built-in workflows validation
# ===========================================================================


class TestBuiltinWorkflows:
    """Validate all built-in workflow templates."""

    def test_all_valid(self):
        for wf in BUILTIN_WORKFLOWS:
            errors = wf.validate()
            assert errors == [], f"Workflow '{wf.name}' has errors: {errors}"

    def test_all_have_parameters(self):
        for wf in BUILTIN_WORKFLOWS:
            assert len(wf.parameters) > 0, f"Workflow '{wf.name}' has no parameters"
            required = wf.get_required_params()
            assert len(required) > 0, f"Workflow '{wf.name}' has no required params"

    def test_all_have_report_step(self):
        for wf in BUILTIN_WORKFLOWS:
            tools = [s.tool for s in wf.steps]
            assert "generate_report" in tools, (
                f"Workflow '{wf.name}' missing report generation step"
            )

    def test_corporate_ownership(self):
        wf = next(w for w in BUILTIN_WORKFLOWS if w.name == "corporate_ownership")
        assert wf.category == "corporate"
        assert "target" in wf.get_required_params()
        tools = [s.tool for s in wf.steps]
        assert "search_entities" in tools
        assert "trace_ownership" in tools
        assert "screen_sanctions" in tools

    def test_person_investigation(self):
        wf = next(w for w in BUILTIN_WORKFLOWS if w.name == "person_investigation")
        assert "target_name" in wf.get_required_params()
        # OSINT step has condition on email
        osint_step = next(s for s in wf.steps if s.tool == "osint_recon")
        assert osint_step.condition is not None

    def test_due_diligence(self):
        wf = next(w for w in BUILTIN_WORKFLOWS if w.name == "due_diligence")
        assert wf.category == "compliance"
        tools = [s.tool for s in wf.steps]
        assert "investigate_blockchain" in tools
        # Blockchain step has condition on crypto_address
        btc_step = next(s for s in wf.steps if s.tool == "investigate_blockchain")
        assert btc_step.condition is not None

    def test_roundtrip_serialization(self):
        for wf in BUILTIN_WORKFLOWS:
            data = wf.to_dict()
            restored = WorkflowDef.from_dict(data)
            assert restored.name == wf.name
            assert len(restored.steps) == len(wf.steps)
            assert len(restored.parameters) == len(wf.parameters)
