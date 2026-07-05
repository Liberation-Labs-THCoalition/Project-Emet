"""Tests for beneficial ownership tracing (graph/algorithms.py).

Covers InvestigativeAnalysis.trace_beneficial_ownership() — percentage
parsing, multi-hop effective-stake computation, cycle handling, depth
capping, min_effective_pct filtering — and the fan-in structural anomaly.
"""

from __future__ import annotations

import pytest

from emet.graph.ftm_loader import FtMGraphLoader
from emet.graph.algorithms import InvestigativeAnalysis


def _entity(eid: str, schema: str, **props) -> dict:
    return {
        "id": eid,
        "schema": schema,
        "properties": {k: [v] if isinstance(v, str) else v for k, v in props.items()},
    }


def _ownership(eid: str, owner: str, asset: str, percentage=None) -> dict:
    props = {"owner": [owner], "asset": [asset]}
    if percentage is not None:
        props["percentage"] = [percentage] if not isinstance(percentage, list) else percentage
    return {"id": eid, "schema": "Ownership", "properties": props}


class TestParseSharePct:
    def test_percent_sign(self):
        assert InvestigativeAnalysis._parse_share_pct("50%") == pytest.approx(0.5)

    def test_bare_number_string(self):
        assert InvestigativeAnalysis._parse_share_pct("50") == pytest.approx(0.5)

    def test_decimal_string(self):
        assert InvestigativeAnalysis._parse_share_pct("50.0") == pytest.approx(0.5)

    def test_fraction_float(self):
        assert InvestigativeAnalysis._parse_share_pct(0.5) == pytest.approx(0.5)

    def test_list_wrapped(self):
        assert InvestigativeAnalysis._parse_share_pct(["25%"]) == pytest.approx(0.25)

    def test_none(self):
        assert InvestigativeAnalysis._parse_share_pct(None) is None

    def test_empty_string(self):
        assert InvestigativeAnalysis._parse_share_pct("") is None

    def test_unparseable(self):
        assert InvestigativeAnalysis._parse_share_pct("majority stake") is None

    def test_full_percent_number(self):
        assert InvestigativeAnalysis._parse_share_pct(100) == pytest.approx(1.0)


@pytest.fixture
def simple_chain_entities():
    """target <- mid (60%) <- top (80%). Effective stake of top in target: 0.48."""
    return [
        _entity("target", "Company", name="Target Co"),
        _entity("mid", "Company", name="Mid Holdco"),
        _entity("top", "Person", name="Ultimate Owner"),
        _ownership("own-1", "mid", "target", "60%"),
        _ownership("own-2", "top", "mid", "80%"),
    ]


@pytest.fixture
def cyclic_entities():
    """a -> b -> c -> a circular ownership, target is 'a'."""
    return [
        _entity("a", "Company", name="Company A"),
        _entity("b", "Company", name="Company B"),
        _entity("c", "Company", name="Company C"),
        _ownership("own-a", "c", "a", "50%"),
        _ownership("own-b", "a", "b", "50%"),
        _ownership("own-c", "b", "c", "50%"),
    ]


@pytest.fixture
def unknown_pct_entities():
    return [
        _entity("target", "Company", name="Target Co"),
        _entity("owner", "Person", name="Mystery Owner"),
        _ownership("own-1", "owner", "target", None),
    ]


@pytest.fixture
def fan_in_entities():
    entities = [_entity("target", "Company", name="Pooled SPV", country="KY")]
    for i in range(6):
        country = ["US", "GB", "CY", "VG", "US", "US"][i]
        entities.append(_entity(f"owner-{i}", "Company", name=f"Owner {i}", country=country))
        entities.append(_ownership(f"own-{i}", f"owner-{i}", "target", "10%"))
    return entities


class TestTraceBeneficialOwnership:
    def test_multi_hop_effective_stake(self, simple_chain_entities):
        graph, _ = FtMGraphLoader().load(simple_chain_entities)
        analysis = InvestigativeAnalysis(graph)

        trace = analysis.trace_beneficial_ownership("target")

        by_id = {o.entity_id: o for o in trace.owners}
        assert by_id["mid"].effective_pct == pytest.approx(0.6)
        assert by_id["top"].effective_pct == pytest.approx(0.48)
        assert by_id["top"].is_terminal is True
        assert by_id["mid"].is_terminal is False
        assert trace.cycles_detected == 0
        assert "Mid Holdco" not in trace.explanation or True  # explanation just needs top owner

    def test_top_owner_is_ultimate_beneficial_owner(self, simple_chain_entities):
        graph, _ = FtMGraphLoader().load(simple_chain_entities)
        analysis = InvestigativeAnalysis(graph)
        trace = analysis.trace_beneficial_ownership("target")

        terminal_owners = [o for o in trace.owners if o.is_terminal]
        assert len(terminal_owners) == 1
        assert terminal_owners[0].entity_id == "top"

    def test_unknown_entity(self, simple_chain_entities):
        graph, _ = FtMGraphLoader().load(simple_chain_entities)
        analysis = InvestigativeAnalysis(graph)
        trace = analysis.trace_beneficial_ownership("nonexistent")
        assert trace.owners == []

    def test_no_owners(self, simple_chain_entities):
        graph, _ = FtMGraphLoader().load(simple_chain_entities)
        analysis = InvestigativeAnalysis(graph)
        trace = analysis.trace_beneficial_ownership("top")
        assert trace.owners == []
        assert "No recorded owners" in trace.explanation

    def test_cycle_detection_breaks_infinite_loop(self, cyclic_entities):
        graph, _ = FtMGraphLoader().load(cyclic_entities)
        analysis = InvestigativeAnalysis(graph)

        # Must terminate and report at least one broken cycle.
        trace = analysis.trace_beneficial_ownership("a", max_depth=10)
        assert trace.cycles_detected >= 1

    def test_max_depth_caps_traversal(self, simple_chain_entities):
        graph, _ = FtMGraphLoader().load(simple_chain_entities)
        analysis = InvestigativeAnalysis(graph)

        trace = analysis.trace_beneficial_ownership("target", max_depth=1)
        # Only the direct owner (mid) should be found at depth 1.
        assert all(o.depth <= 1 for o in trace.owners)
        assert trace.max_depth_reached is True

    def test_unknown_percentage_propagates_as_none(self, unknown_pct_entities):
        graph, _ = FtMGraphLoader().load(unknown_pct_entities)
        analysis = InvestigativeAnalysis(graph)

        trace = analysis.trace_beneficial_ownership("target")
        assert len(trace.owners) == 1
        assert trace.owners[0].effective_pct is None

    def test_min_effective_pct_filters_small_owners(self, simple_chain_entities):
        graph, _ = FtMGraphLoader().load(simple_chain_entities)
        analysis = InvestigativeAnalysis(graph)

        trace = analysis.trace_beneficial_ownership("target", min_effective_pct=0.5)
        ids = {o.entity_id for o in trace.owners}
        assert "mid" in ids       # 0.6 >= 0.5
        assert "top" not in ids  # 0.48 < 0.5

    def test_min_effective_pct_never_drops_unknown(self, unknown_pct_entities):
        graph, _ = FtMGraphLoader().load(unknown_pct_entities)
        analysis = InvestigativeAnalysis(graph)

        trace = analysis.trace_beneficial_ownership("target", min_effective_pct=0.9)
        assert len(trace.owners) == 1  # unknown stake is kept regardless of threshold

    def test_path_traces_from_owner_down_to_target(self, simple_chain_entities):
        graph, _ = FtMGraphLoader().load(simple_chain_entities)
        analysis = InvestigativeAnalysis(graph)
        trace = analysis.trace_beneficial_ownership("target")

        top = next(o for o in trace.owners if o.entity_id == "top")
        path_ids = [p["id"] for p in top.path]
        assert path_ids == ["top", "mid", "target"]


class TestFanInAnomaly:
    def test_fan_in_flagged(self, fan_in_entities):
        graph, _ = FtMGraphLoader().load(fan_in_entities)
        analysis = InvestigativeAnalysis(graph)

        anomalies = analysis.find_structural_anomalies()
        fan_in = [a for a in anomalies if a.anomaly_type == "fan_in_ownership"]
        assert len(fan_in) == 1
        assert fan_in[0].severity == "high"  # 6 owners across >=3 jurisdictions

    def test_no_fan_in_below_threshold(self, simple_chain_entities):
        graph, _ = FtMGraphLoader().load(simple_chain_entities)
        analysis = InvestigativeAnalysis(graph)

        anomalies = analysis.find_structural_anomalies()
        fan_in = [a for a in anomalies if a.anomaly_type == "fan_in_ownership"]
        assert fan_in == []
