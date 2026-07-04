"""Tests for beneficial-ownership (UBO) tracing and fan-in anomaly."""

from __future__ import annotations

from emet.graph.algorithms import InvestigativeAnalysis
from emet.graph.ftm_loader import FtMGraphLoader


def _graph(entities):
    graph, _ = FtMGraphLoader().load(entities)
    return InvestigativeAnalysis(graph)


def _own(oid, owner, asset, pct=None):
    props = {"owner": [owner], "asset": [asset]}
    if pct is not None:
        props["percentage"] = [pct]
    return {"id": oid, "schema": "Ownership", "properties": props}


class TestShareParsing:
    def test_percent_forms(self):
        p = InvestigativeAnalysis._parse_share_pct
        assert p("50%") == 0.5
        assert p("50") == 0.5
        assert p(0.5) == 0.5
        assert p("100") == 1.0
        assert p(["25%"]) == 0.25
        assert p("") is None
        assert p(None) is None


class TestUBOTracing:
    def test_simple_chain_effective_pct(self):
        ents = [
            {"id": "p:x", "schema": "Person", "properties": {"name": ["X"]}},
            {"id": "c:hold", "schema": "Company", "properties": {"name": ["Hold"]}},
            {"id": "c:t", "schema": "Company", "properties": {"name": ["Target"]}},
            _own("o1", "p:x", "c:hold", "50%"),
            _own("o2", "c:hold", "c:t", "80%"),
        ]
        trace = _graph(ents).trace_beneficial_ownership("c:t")
        assert len(trace.ultimate_owners) == 1
        ubo = trace.ultimate_owners[0]
        assert ubo.name == "X"
        assert ubo.effective_pct == 0.4
        assert ubo.is_ultimate

    def test_unknown_pct_propagates_none(self):
        ents = [
            {"id": "p:x", "schema": "Person", "properties": {"name": ["X"]}},
            {"id": "c:t", "schema": "Company", "properties": {"name": ["Target"]}},
            _own("o1", "p:x", "c:t"),  # no percentage
        ]
        trace = _graph(ents).trace_beneficial_ownership("c:t")
        assert trace.ultimate_owners[0].effective_pct is None

    def test_cycle_is_broken(self):
        ents = [
            {"id": "a", "schema": "Company", "properties": {"name": ["A"]}},
            {"id": "b", "schema": "Company", "properties": {"name": ["B"]}},
            _own("o1", "a", "b", "100%"),
            _own("o2", "b", "a", "100%"),  # circular
        ]
        trace = _graph(ents).trace_beneficial_ownership("a")
        assert trace.cycles_detected

    def test_no_owners(self):
        ents = [{"id": "c:t", "schema": "Company", "properties": {"name": ["T"]}}]
        trace = _graph(ents).trace_beneficial_ownership("c:t")
        assert trace.ultimate_owners == []
        assert "opaque" in trace.explanation.lower()

    def test_missing_entity(self):
        trace = _graph([]).trace_beneficial_ownership("nope")
        assert "not found" in trace.explanation.lower()

    def test_depth_bound_truncates(self):
        ents = [{"id": "n0", "schema": "Company", "properties": {"name": ["n0"]}}]
        for i in range(1, 6):
            ents.append(
                {"id": f"n{i}", "schema": "Company", "properties": {"name": [f"n{i}"]}}
            )
            ents.append(_own(f"o{i}", f"n{i}", f"n{i-1}", "100%"))
        trace = _graph(ents).trace_beneficial_ownership("n0", max_depth=2)
        assert trace.truncated


class TestFanInAnomaly:
    def test_fan_in_detected(self):
        ents = [{"id": "hub", "schema": "Company", "properties": {"name": ["Hub"]}}]
        for i in range(6):
            ents.append(
                {"id": f"p{i}", "schema": "Company", "properties": {"name": [f"P{i}"]}}
            )
            ents.append(_own(f"o{i}", f"p{i}", "hub", "20%"))
        anomalies = _graph(ents).find_structural_anomalies()
        types = {a.anomaly_type for a in anomalies}
        assert "fan_in_ownership" in types
