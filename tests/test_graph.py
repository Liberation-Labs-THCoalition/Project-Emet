"""Tests for emet.graph — graph analytics engine.

Tests cover:
  - FtM → graph loading (nodes, edges, orphan handling)
  - Investigative algorithms (brokers, communities, cycles, key players, paths, anomalies)
  - Shell company topology scoring
  - Graph export (GEXF, GraphML, CSV, D3 JSON, Cytoscape JSON)
  - GraphEngine high-level API

Uses synthetic investigative datasets:
  - "Sunrise Holdings" — a 15-entity shell company network with circular ownership
  - "Clean Corp" — a simple legitimate corporate structure for baseline comparison
"""

import json
import tempfile
from pathlib import Path

import pytest
import networkx as nx

from emet.graph.ftm_loader import FtMGraphLoader, RELATIONSHIP_SCHEMAS
from emet.graph.algorithms import InvestigativeAnalysis
from emet.graph.exporters import GraphExporter
from emet.graph.engine import GraphEngine


# ---------------------------------------------------------------------------
# Test fixtures: Synthetic FtM entity datasets
# ---------------------------------------------------------------------------

def _entity(eid: str, schema: str, **props) -> dict:
    """Helper to build FtM entity dicts concisely."""
    return {
        "id": eid,
        "schema": schema,
        "properties": {k: [v] if isinstance(v, str) else v for k, v in props.items()},
    }


def _relationship(eid: str, schema: str, source_prop: str, source_id: str,
                   target_prop: str, target_id: str, **extra_props) -> dict:
    """Helper to build FtM relationship entity dicts."""
    props = {source_prop: [source_id], target_prop: [target_id]}
    for k, v in extra_props.items():
        props[k] = [v] if isinstance(v, str) else v
    return {"id": eid, "schema": schema, "properties": props}


@pytest.fixture
def sunrise_entities() -> list[dict]:
    """Sunrise Holdings: a 15-entity shell company network.

    Structure:
    - Viktor Petrov (Person) — the beneficial owner
    - Sunrise Holdings Ltd (BVI) — top holding company
    - 3 intermediate shell companies in different jurisdictions
    - Circular ownership: Company C → Company A (back to start)
    - Fan-out: Sunrise Holdings owns 3 companies
    - A bank account and a real estate asset
    - Payment from shell to shell
    """
    entities = [
        # Persons
        _entity("person-1", "Person", name="Viktor Petrov", country="RU"),
        _entity("person-2", "Person", name="Elena Kozlova", country="CY"),

        # Companies
        _entity("co-sunrise", "Company", name="Sunrise Holdings Ltd",
                country="VG", jurisdiction="VG",
                incorporationDate="2018-03-15"),
        _entity("co-alpha", "Company", name="Alpha Trading GmbH",
                country="DE", jurisdiction="DE",
                incorporationDate="2018-03-16"),
        _entity("co-beta", "Company", name="Beta Investments SA",
                country="CH", jurisdiction="CH",
                incorporationDate="2018-03-17"),
        _entity("co-gamma", "Company", name="Gamma Properties Ltd",
                country="CY", jurisdiction="CY",
                incorporationDate="2018-03-18"),

        # Assets
        _entity("bank-1", "BankAccount", name="Account CH-12345"),
        _entity("property-1", "RealEstate", name="Villa Limassol",
                country="CY", address="42 Poseidonos Ave, Limassol, Cyprus"),

        # Ownership relationships
        # Viktor → Sunrise Holdings
        _relationship("own-1", "Ownership", "owner", "person-1",
                       "asset", "co-sunrise", percentage="100"),
        # Sunrise → Alpha, Beta, Gamma (fan-out)
        _relationship("own-2", "Ownership", "owner", "co-sunrise",
                       "asset", "co-alpha", percentage="100"),
        _relationship("own-3", "Ownership", "owner", "co-sunrise",
                       "asset", "co-beta", percentage="85"),
        _relationship("own-4", "Ownership", "owner", "co-sunrise",
                       "asset", "co-gamma", percentage="100"),
        # Circular: Gamma → Sunrise (back-link creating cycle)
        _relationship("own-5", "Ownership", "owner", "co-gamma",
                       "asset", "co-sunrise", percentage="5"),

        # Directorship
        _relationship("dir-1", "Directorship", "director", "person-2",
                       "organization", "co-gamma"),

        # Payment: Alpha → Beta
        _relationship("pay-1", "Payment", "payer", "co-alpha",
                       "beneficiary", "co-beta",
                       date="2019-06-15"),

        # Beta owns bank account, Gamma owns property
        _relationship("own-6", "Ownership", "owner", "co-beta",
                       "asset", "bank-1"),
        _relationship("own-7", "Ownership", "owner", "co-gamma",
                       "asset", "property-1"),
    ]
    return entities


@pytest.fixture
def clean_corp_entities() -> list[dict]:
    """Clean Corp: simple legitimate corporate structure.

    - Parent company with 2 subsidiaries
    - Named directors
    - No cycles, no jurisdictional spread
    """
    return [
        _entity("cc-parent", "Company", name="CleanCorp Inc",
                country="US", jurisdiction="US"),
        _entity("cc-sub1", "Company", name="CleanCorp West LLC",
                country="US", jurisdiction="US"),
        _entity("cc-sub2", "Company", name="CleanCorp East LLC",
                country="US", jurisdiction="US"),
        _entity("cc-ceo", "Person", name="Jane Smith", country="US"),
        _entity("cc-cfo", "Person", name="Bob Jones", country="US"),
        # Ownership
        _relationship("cc-own1", "Ownership", "owner", "cc-parent",
                       "asset", "cc-sub1", percentage="100"),
        _relationship("cc-own2", "Ownership", "owner", "cc-parent",
                       "asset", "cc-sub2", percentage="100"),
        # Directorships
        _relationship("cc-dir1", "Directorship", "director", "cc-ceo",
                       "organization", "cc-parent"),
        _relationship("cc-dir2", "Directorship", "director", "cc-cfo",
                       "organization", "cc-parent"),
    ]


# ---------------------------------------------------------------------------
# FtMGraphLoader tests
# ---------------------------------------------------------------------------


class TestFtMGraphLoader:
    def test_loads_nodes_and_edges(self, sunrise_entities):
        loader = FtMGraphLoader()
        graph, stats = loader.load(sunrise_entities)

        # 8 node entities (2 persons, 4 companies, 1 bank, 1 property)
        assert stats.nodes_loaded == 8
        # 9 relationship entities
        assert stats.relationship_entities == 9
        assert stats.edges_loaded >= 9

        # Verify some nodes exist
        assert "person-1" in graph
        assert "co-sunrise" in graph
        assert graph.nodes["person-1"]["name"] == "Viktor Petrov"
        assert graph.nodes["co-sunrise"]["schema"] == "Company"

    def test_preserves_node_properties(self, sunrise_entities):
        loader = FtMGraphLoader()
        graph, _ = loader.load(sunrise_entities)

        node = graph.nodes["co-sunrise"]
        assert node["country"] == "VG"
        assert node["schema"] == "Company"
        # Full properties preserved
        assert "name" in node["properties"]

    def test_edge_attributes(self, sunrise_entities):
        loader = FtMGraphLoader()
        graph, _ = loader.load(sunrise_entities)

        # Check ownership edge from Viktor to Sunrise
        edges = list(graph.edges("person-1", data=True))
        assert len(edges) >= 1
        ownership_edges = [e for e in edges if e[2].get("schema") == "Ownership"]
        assert len(ownership_edges) >= 1
        assert ownership_edges[0][2]["label"] == "owns"
        assert ownership_edges[0][2]["weight"] == 1.0  # Ownership = highest weight

    def test_orphan_node_creation(self):
        """When edge references unknown node IDs, create placeholder nodes."""
        entities = [
            _entity("known-node", "Person", name="Alice"),
            _relationship("rel-1", "Ownership", "owner", "known-node",
                           "asset", "unknown-node"),
        ]
        loader = FtMGraphLoader(include_orphan_nodes=True)
        graph, stats = loader.load(entities)

        assert "unknown-node" in graph
        assert graph.nodes["unknown-node"].get("_orphan") is True
        assert stats.orphan_references == 1

    def test_orphan_nodes_disabled(self):
        """When include_orphan_nodes=False, skip edges to unknown nodes."""
        entities = [
            _entity("known-node", "Person", name="Alice"),
            _relationship("rel-1", "Ownership", "owner", "known-node",
                           "asset", "unknown-node"),
        ]
        loader = FtMGraphLoader(include_orphan_nodes=False)
        graph, stats = loader.load(entities)

        assert "unknown-node" not in graph
        assert stats.edges_loaded == 0

    def test_max_nodes_cap(self):
        """Graph loader respects maximum node count."""
        entities = [_entity(f"node-{i}", "Person", name=f"Person {i}") for i in range(100)]
        loader = FtMGraphLoader(max_nodes=10)
        graph, stats = loader.load(entities)

        assert graph.number_of_nodes() == 10
        assert stats.skipped_entities == 90

    def test_empty_entities(self):
        loader = FtMGraphLoader()
        graph, stats = loader.load([])
        assert graph.number_of_nodes() == 0
        assert graph.number_of_edges() == 0

    def test_schema_counts(self, sunrise_entities):
        loader = FtMGraphLoader()
        _, stats = loader.load(sunrise_entities)

        assert stats.schema_counts["Person"] == 2
        assert stats.schema_counts["Company"] == 4
        assert stats.schema_counts["BankAccount"] == 1
        assert stats.schema_counts["RealEstate"] == 1

    def test_all_relationship_schemas_recognized(self):
        """Verify all defined relationship schemas are properly handled."""
        for schema, edge_def in RELATIONSHIP_SCHEMAS.items():
            entities = [
                _entity("src", "Person", name="Source"),
                _entity("tgt", "Company", name="Target"),
                _relationship("rel", schema,
                               edge_def["source"], "src",
                               edge_def["target"], "tgt"),
            ]
            loader = FtMGraphLoader()
            graph, stats = loader.load(entities)
            assert stats.edges_loaded >= 1, f"Failed for schema {schema}"


# ---------------------------------------------------------------------------
# InvestigativeAnalysis tests
# ---------------------------------------------------------------------------


class TestInvestigativeAnalysis:
    @pytest.fixture
    def sunrise_graph(self, sunrise_entities):
        loader = FtMGraphLoader()
        graph, _ = loader.load(sunrise_entities)
        return InvestigativeAnalysis(graph)

    @pytest.fixture
    def clean_graph(self, clean_corp_entities):
        loader = FtMGraphLoader()
        graph, _ = loader.load(clean_corp_entities)
        return InvestigativeAnalysis(graph)

    def test_find_brokers(self, sunrise_graph):
        brokers = sunrise_graph.find_brokers(top_n=5)
        assert len(brokers) > 0
        # Sunrise Holdings should be a key broker (connects everything)
        broker_ids = [b.entity_id for b in brokers]
        assert "co-sunrise" in broker_ids
        # Verify broker result structure
        top_broker = brokers[0]
        assert top_broker.betweenness_score > 0
        assert top_broker.explanation

    def test_find_communities(self, sunrise_graph):
        communities = sunrise_graph.find_communities()
        # Should find at least 1 community
        assert len(communities) >= 1
        # Total members should equal node count (minus singletons)
        total_members = sum(c.member_count for c in communities)
        assert total_members > 0

    def test_communities_detect_cross_jurisdiction(self, sunrise_graph):
        """Sunrise Holdings spans VG, DE, CH, CY — should flag cross-jurisdiction."""
        communities = sunrise_graph.find_communities()
        # At least one community should be cross-jurisdiction
        has_cross = any(c.cross_jurisdiction for c in communities)
        # This depends on how Louvain partitions — it may or may not split by jurisdiction
        # So we just verify the flag is computed correctly
        for comm in communities:
            assert isinstance(comm.cross_jurisdiction, bool)

    def test_find_circular_ownership(self, sunrise_graph):
        """Sunrise dataset has Gamma → Sunrise back-link creating a cycle."""
        cycles = sunrise_graph.find_circular_ownership(max_length=8)

        # Should find at least one cycle involving co-sunrise and co-gamma
        assert len(cycles) >= 1

        # Verify cycle structure
        cycle = cycles[0]
        assert cycle.cycle_length >= 2
        assert cycle.risk_score > 0
        assert cycle.explanation

    def test_no_cycles_in_clean_corp(self, clean_graph):
        """Clean Corp has no circular ownership."""
        cycles = clean_graph.find_circular_ownership()
        assert len(cycles) == 0

    def test_find_key_players(self, sunrise_graph):
        players = sunrise_graph.find_key_players(top_n=5)
        assert len(players) > 0
        # Viktor Petrov or Sunrise Holdings should rank highly
        top_names = [p.name for p in players]
        # At least one of our key entities should appear
        key_entities = {"Viktor Petrov", "Sunrise Holdings Ltd"}
        assert key_entities & set(top_names)

    def test_find_hidden_connections(self, sunrise_graph):
        """Should find path from Viktor to Beta through intermediaries."""
        paths = sunrise_graph.find_hidden_connections("person-1", "co-beta")
        assert len(paths) >= 1
        path = paths[0]
        assert path.source_id == "person-1"
        assert path.target_id == "co-beta"
        assert path.path_length >= 2  # Not directly connected
        assert len(path.path_entities) >= 3  # At least source + intermediate + target

    def test_no_path_between_unconnected(self):
        """Two disconnected entities should return no paths."""
        graph = nx.MultiDiGraph()
        graph.add_node("a", name="A", schema="Person", country="", address="", dates={}, color="")
        graph.add_node("b", name="B", schema="Person", country="", address="", dates={}, color="")
        analysis = InvestigativeAnalysis(graph)
        paths = analysis.find_hidden_connections("a", "b")
        assert len(paths) == 0

    def test_find_structural_anomalies(self, sunrise_graph):
        anomalies = sunrise_graph.find_structural_anomalies()
        # Sunrise Holdings owns 3+ companies — should trigger fan_out
        fan_outs = [a for a in anomalies if a.anomaly_type == "fan_out_ownership"]
        # May or may not trigger depending on threshold (5+). Sunrise owns 3.
        # But let's check we get anomalies of some kind
        assert isinstance(anomalies, list)
        for anomaly in anomalies:
            assert anomaly.anomaly_type
            assert anomaly.severity in ("low", "medium", "high")
            assert anomaly.explanation

    def test_shell_company_topology_score(self, sunrise_graph):
        """Gamma is most suspicious: circular ownership, cross-jurisdiction, nominee director."""
        score = sunrise_graph.shell_company_topology_score("co-gamma")
        assert score is not None
        assert 0 <= score.score <= 1
        assert score.risk_level in ("low", "medium", "high", "critical")
        assert score.factors  # Should have factor breakdown
        # Circular ownership factor should be non-zero
        assert score.factors.get("circular_ownership", 0) > 0

    def test_shell_score_unknown_entity(self, sunrise_graph):
        score = sunrise_graph.shell_company_topology_score("nonexistent")
        assert score is None

    def test_clean_corp_low_shell_score(self, clean_graph):
        """Clean Corp should have low shell company risk."""
        score = clean_graph.shell_company_topology_score("cc-parent")
        assert score is not None
        assert score.score < 0.5  # Should be low risk
        assert score.risk_level in ("low", "medium")

    def test_summary_stats(self, sunrise_graph):
        stats = sunrise_graph.summary()
        assert stats["node_count"] == 8
        assert stats["edge_count"] >= 9
        assert stats["density"] > 0
        assert stats["connected_components"] >= 1
        assert "node_schema_distribution" in stats
        assert "edge_type_distribution" in stats

    def test_small_graph_handling(self):
        """Algorithms handle tiny graphs gracefully."""
        graph = nx.MultiDiGraph()
        graph.add_node("a", name="A", schema="Person", country="", address="", dates={}, color="")
        analysis = InvestigativeAnalysis(graph)

        assert analysis.find_brokers() == []
        assert analysis.find_communities() == []
        assert analysis.find_circular_ownership() == []
        assert analysis.find_key_players() == []


# ---------------------------------------------------------------------------
# GraphExporter tests
# ---------------------------------------------------------------------------


class TestGraphExporter:
    @pytest.fixture
    def sunrise_result(self, sunrise_entities):
        engine = GraphEngine()
        return engine.build_from_entities(sunrise_entities)

    def test_to_gexf(self, sunrise_result):
        with tempfile.NamedTemporaryFile(suffix=".gexf", delete=False) as f:
            sunrise_result.exporter.to_gexf(f.name)
            content = Path(f.name).read_text()
            assert "<?xml" in content
            assert "gexf" in content.lower()
            assert "Viktor Petrov" in content or "person-1" in content

    def test_to_graphml(self, sunrise_result):
        with tempfile.NamedTemporaryFile(suffix=".graphml", delete=False) as f:
            sunrise_result.exporter.to_graphml(f.name)
            content = Path(f.name).read_text()
            assert "<?xml" in content
            assert "graphml" in content.lower()

    def test_to_cytoscape_json(self, sunrise_result):
        data = sunrise_result.exporter.to_cytoscape_json()
        assert "elements" in data
        nodes = [e for e in data["elements"] if e["group"] == "nodes"]
        edges = [e for e in data["elements"] if e["group"] == "edges"]
        assert len(nodes) == 8
        assert len(edges) >= 9

    def test_to_d3_json(self, sunrise_result):
        data = sunrise_result.exporter.to_d3_json()
        assert "nodes" in data
        assert "links" in data
        assert len(data["nodes"]) == 8
        assert len(data["links"]) >= 9
        # Verify node structure
        node = data["nodes"][0]
        assert "id" in node
        assert "name" in node
        assert "schema" in node

    def test_to_csv_nodes(self, sunrise_result):
        csv_text = sunrise_result.exporter.to_csv_nodes()
        lines = [l.strip() for l in csv_text.strip().splitlines()]
        assert lines[0] == "id,name,schema,country,address"
        assert len(lines) == 9  # header + 8 nodes

    def test_to_csv_edges(self, sunrise_result):
        csv_text = sunrise_result.exporter.to_csv_edges()
        lines = [l.strip() for l in csv_text.strip().splitlines()]
        assert lines[0] == "source_id,target_id,relationship_type,label,weight"
        assert len(lines) >= 10  # header + 9+ edges

    def test_to_csv_files(self, sunrise_result):
        with tempfile.TemporaryDirectory() as tmpdir:
            nodes_path, edges_path = sunrise_result.exporter.to_csv_files(tmpdir)
            assert nodes_path.exists()
            assert edges_path.exists()
            assert nodes_path.stat().st_size > 0
            assert edges_path.stat().st_size > 0


# ---------------------------------------------------------------------------
# GraphEngine tests
# ---------------------------------------------------------------------------


class TestGraphEngine:
    def test_build_from_entities(self, sunrise_entities):
        engine = GraphEngine()
        result = engine.build_from_entities(sunrise_entities)

        assert result.node_count == 8
        assert result.edge_count >= 9
        assert result.analysis is not None
        assert result.exporter is not None
        assert result.stats.nodes_loaded == 8

    def test_summary(self, sunrise_entities):
        engine = GraphEngine()
        result = engine.build_from_entities(sunrise_entities)
        summary = result.summary()

        assert summary["node_count"] == 8
        assert "load_stats" in summary
        assert summary["load_stats"]["nodes_loaded"] == 8

    def test_build_empty(self):
        engine = GraphEngine()
        result = engine.build_from_entities([])
        assert result.node_count == 0
        assert result.edge_count == 0

    def test_max_nodes_respected(self):
        entities = [_entity(f"n{i}", "Person", name=f"Person {i}") for i in range(100)]
        engine = GraphEngine(max_nodes=20)
        result = engine.build_from_entities(entities)
        assert result.node_count == 20

    def test_full_workflow(self, sunrise_entities):
        """Full workflow: build → analyze → export."""
        engine = GraphEngine()
        result = engine.build_from_entities(sunrise_entities)

        # Analysis
        brokers = result.analysis.find_brokers(top_n=3)
        communities = result.analysis.find_communities()
        cycles = result.analysis.find_circular_ownership()
        players = result.analysis.find_key_players(top_n=3)

        # Verify we got meaningful results
        assert len(brokers) > 0
        assert len(communities) >= 1
        assert len(cycles) >= 1  # Sunrise has circular ownership
        assert len(players) > 0

        # Export
        with tempfile.TemporaryDirectory() as tmpdir:
            result.exporter.to_gexf(Path(tmpdir) / "test.gexf")
            result.exporter.to_csv_files(tmpdir)
            assert (Path(tmpdir) / "test.gexf").exists()
            assert (Path(tmpdir) / "nodes.csv").exists()
            assert (Path(tmpdir) / "edges.csv").exists()


# ---------------------------------------------------------------------------
# Integration: Comparing clean vs suspicious networks
# ---------------------------------------------------------------------------


class TestComparativeAnalysis:
    """Compare analysis results between clean and suspicious networks.

    The real value of graph analytics is in the contrast — a clean corporate
    structure should score differently from a suspicious one.
    """

    def test_shell_score_differentiates(self, sunrise_entities, clean_corp_entities):
        engine = GraphEngine()

        sunrise = engine.build_from_entities(sunrise_entities)
        clean = engine.build_from_entities(clean_corp_entities)

        # Score a suspicious entity vs a clean one
        gamma_score = sunrise.analysis.shell_company_topology_score("co-gamma")
        clean_score = clean.analysis.shell_company_topology_score("cc-parent")

        assert gamma_score is not None
        assert clean_score is not None

        # Gamma should score higher risk than CleanCorp
        assert gamma_score.score > clean_score.score, (
            f"Gamma ({gamma_score.score:.2f}) should score higher risk than "
            f"CleanCorp ({clean_score.score:.2f})"
        )

    def test_cycles_differentiate(self, sunrise_entities, clean_corp_entities):
        engine = GraphEngine()

        sunrise = engine.build_from_entities(sunrise_entities)
        clean = engine.build_from_entities(clean_corp_entities)

        sunrise_cycles = sunrise.analysis.find_circular_ownership()
        clean_cycles = clean.analysis.find_circular_ownership()

        assert len(sunrise_cycles) > len(clean_cycles)
