"""Cross-module integration tests — full pipeline verification.

Tests the complete investigative pipeline:
  FtM entities → Graph engine → Analysis → Export → Report → Monitoring

This is Sprint 9's primary deliverable: proving all 8 sprints
work together as a coherent system.
"""

import json
import tempfile
from pathlib import Path

import pytest

from emet.graph.engine import GraphEngine
from emet.graph.algorithms import InvestigativeAnalysis
from emet.export.markdown import MarkdownReport
from emet.export.ftm_bundle import FtMBundleExporter
from emet.export.timeline import TimelineAnalyzer
from emet.monitoring import SnapshotDiffer, ChangeDetector
from emet.skills.llm_integration import SkillLLMHelper, TokenUsage, parse_json_response
from emet.cognition.llm_stub import StubClient


# ---------------------------------------------------------------------------
# Shared test data: a realistic multi-jurisdiction investigation
# ---------------------------------------------------------------------------

def _ent(eid, schema, name, **props):
    p = {"name": [name]}
    for k, v in props.items():
        p[k] = [v] if isinstance(v, str) else v
    return {"id": eid, "schema": schema, "properties": p}


def _rel(eid, schema, src_prop, src_id, tgt_prop, tgt_id, **extra):
    p = {src_prop: [src_id], tgt_prop: [tgt_id]}
    for k, v in extra.items():
        p[k] = [v] if isinstance(v, str) else v
    return {"id": eid, "schema": schema, "properties": p}


INVESTIGATION_ENTITIES = [
    # Persons
    _ent("p1", "Person", "Dmitri Volkov", country="RU", birthDate="1965-04-12"),
    _ent("p2", "Person", "Maria Volkov", country="CY"),
    _ent("p3", "Person", "James Hartley", country="GB"),

    # Companies
    _ent("c1", "Company", "Volkov Holdings Ltd", country="VG",
         jurisdiction="VG", incorporationDate="2019-01-10"),
    _ent("c2", "Company", "Crimson Trading SA", country="CH",
         jurisdiction="CH", incorporationDate="2019-01-12"),
    _ent("c3", "Company", "Azure Properties Ltd", country="CY",
         jurisdiction="CY", incorporationDate="2019-01-14"),
    _ent("c4", "Company", "Northern Consulting GmbH", country="DE",
         jurisdiction="DE", incorporationDate="2020-06-01"),

    # Assets
    _ent("a1", "RealEstate", "Penthouse Limassol", country="CY",
         address="18 Amathus, Limassol"),
    _ent("a2", "BankAccount", "Account ZH-887766"),

    # Ownership chain: Dmitri → Volkov Holdings → Crimson → Azure → (back to Volkov Holdings)
    _rel("o1", "Ownership", "owner", "p1", "asset", "c1", percentage="100",
         startDate="2019-01-10"),
    _rel("o2", "Ownership", "owner", "c1", "asset", "c2", percentage="100",
         startDate="2019-01-12"),
    _rel("o3", "Ownership", "owner", "c2", "asset", "c3", percentage="90",
         startDate="2019-01-14"),
    # Circular: Azure → Volkov Holdings (5% back-link)
    _rel("o4", "Ownership", "owner", "c3", "asset", "c1", percentage="5",
         startDate="2019-02-01"),

    # Directorships
    _rel("d1", "Directorship", "director", "p2", "organization", "c3",
         startDate="2019-01-14"),
    _rel("d2", "Directorship", "director", "p3", "organization", "c4",
         startDate="2020-06-01"),

    # Family
    _rel("f1", "Family", "person", "p1", "relative", "p2"),

    # Payments
    _rel("pay1", "Payment", "payer", "c2", "beneficiary", "c3",
         date="2019-03-15"),
    _rel("pay2", "Payment", "payer", "c3", "beneficiary", "c4",
         date="2020-07-20"),

    # Property ownership
    _rel("o5", "Ownership", "owner", "c3", "asset", "a1"),
    _rel("o6", "Ownership", "owner", "c2", "asset", "a2"),

    # Employment
    _rel("e1", "Employment", "employee", "p3", "employer", "c4"),
]


# ---------------------------------------------------------------------------
# Pipeline integration tests
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """Test the complete investigation pipeline end-to-end."""

    @pytest.fixture
    def graph_result(self):
        engine = GraphEngine()
        return engine.build_from_entities(INVESTIGATION_ENTITIES)

    def test_graph_builds_correctly(self, graph_result):
        """Step 1: Entities load into graph with correct counts."""
        assert graph_result.node_count == 9  # 3 persons + 4 companies + 2 assets
        assert graph_result.edge_count >= 12  # All relationships
        assert graph_result.stats.relationship_entities == 12

    def test_circular_ownership_detected(self, graph_result):
        """Step 2: Circular ownership flagged."""
        cycles = graph_result.analysis.find_circular_ownership()
        assert len(cycles) >= 1

        # Cycle should involve c1, c2, c3
        cycle_ids = set()
        for cycle in cycles:
            for ent in cycle.cycle_entities:
                cycle_ids.add(ent["id"])
        assert "c1" in cycle_ids  # Volkov Holdings
        assert "c3" in cycle_ids  # Azure Properties

    def test_key_player_identified(self, graph_result):
        """Step 3: Dmitri or Volkov Holdings ranks as key player."""
        players = graph_result.analysis.find_key_players(top_n=3)
        top_names = {p.name for p in players}
        key_names = {"Dmitri Volkov", "Volkov Holdings Ltd", "Crimson Trading SA"}
        assert top_names & key_names, f"Expected key entity in top 3, got {top_names}"

    def test_brokers_found(self, graph_result):
        """Step 4: Intermediary entities identified."""
        brokers = graph_result.analysis.find_brokers(top_n=5)
        assert len(brokers) > 0

    def test_communities_detected(self, graph_result):
        """Step 5: Entity clusters identified."""
        communities = graph_result.analysis.find_communities()
        assert len(communities) >= 1
        total = sum(c.member_count for c in communities)
        assert total > 0

    def test_hidden_connections(self, graph_result):
        """Step 6: Path from Dmitri to James Hartley found."""
        paths = graph_result.analysis.find_hidden_connections("p1", "p3")
        assert len(paths) >= 1
        # Path should go through companies
        intermediaries = [e["name"] for e in paths[0].path_entities[1:-1]]
        assert len(intermediaries) >= 1

    def test_shell_score_differentiates(self, graph_result):
        """Step 7: Shell company score is higher for suspicious entities."""
        azure_score = graph_result.analysis.shell_company_topology_score("c3")
        northern_score = graph_result.analysis.shell_company_topology_score("c4")

        assert azure_score is not None
        assert northern_score is not None
        # Azure has circular ownership + cross-jurisdiction — should score higher
        assert azure_score.score > northern_score.score

    def test_timeline_extraction(self):
        """Step 8: Temporal patterns extracted and bursts detected."""
        analyzer = TimelineAnalyzer(burst_window_days=7, burst_threshold=3)
        events = analyzer.extract_events(INVESTIGATION_ENTITIES)

        # Should find incorporation dates + payment dates + other dates
        assert len(events) >= 5

        # Incorporation burst: 3 companies within 4 days (Jan 10, 12, 14)
        patterns = analyzer.detect_patterns(INVESTIGATION_ENTITIES)
        burst_patterns = [p for p in patterns if p.pattern_type == "burst"]
        assert len(burst_patterns) >= 1, "Should detect incorporation burst"

    def test_markdown_report_generation(self, graph_result):
        """Step 9: Investigation report generated with findings."""
        # Gather findings
        findings = {
            "query": "Dmitri Volkov",
            "graph_summary": graph_result.summary(),
            "key_players": [
                {"name": kp.name, "schema": kp.schema,
                 "composite_score": kp.composite_score, "explanation": kp.explanation}
                for kp in graph_result.analysis.find_key_players(top_n=3)
            ],
            "circular_ownership": [
                {"length": c.cycle_length,
                 "entities": [e["name"] for e in c.cycle_entities],
                 "risk_score": c.risk_score, "explanation": c.explanation}
                for c in graph_result.analysis.find_circular_ownership()
            ],
            "brokers": [],
            "communities": [],
            "anomalies": [],
        }

        reporter = MarkdownReport()
        md = reporter.generate_from_engine_result(
            title="Investigation: Volkov Network",
            findings=findings,
            summary="Multi-jurisdiction corporate network with circular ownership.",
        )

        assert "Volkov" in md
        assert "Circular Ownership" in md
        assert "Key Entities" in md
        assert "Methodology" in md

    def test_ftm_bundle_export(self):
        """Step 10: Entities exportable as FtM bundle for Aleph."""
        exporter = FtMBundleExporter()

        with tempfile.NamedTemporaryFile(suffix=".ftm.json", delete=False) as f:
            count = exporter.export_jsonl(INVESTIGATION_ENTITIES, f.name)
            assert count == len(INVESTIGATION_ENTITIES)

            # Verify each line is valid JSON with required fields
            lines = Path(f.name).read_text().strip().split("\n")
            for line in lines:
                entity = json.loads(line)
                assert "id" in entity
                assert "schema" in entity
                assert "properties" in entity

    def test_ftm_zip_bundle(self):
        """Step 11: Zip bundle with manifest."""
        exporter = FtMBundleExporter()

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            path = exporter.export_zip(
                INVESTIGATION_ENTITIES, f.name,
                investigation_name="Volkov Network",
            )
            assert path.exists()
            assert path.stat().st_size > 0

    def test_graph_export_formats(self, graph_result):
        """Step 12: Graph exports in all formats."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # GEXF
            graph_result.exporter.to_gexf(Path(tmpdir) / "network.gexf")
            assert (Path(tmpdir) / "network.gexf").exists()

            # CSV
            nodes_path, edges_path = graph_result.exporter.to_csv_files(tmpdir)
            assert nodes_path.exists()
            assert edges_path.exists()

            # D3 JSON
            d3 = graph_result.exporter.to_d3_json()
            assert len(d3["nodes"]) == 9
            assert len(d3["links"]) >= 12

            # Cytoscape JSON
            cyto = graph_result.exporter.to_cytoscape_json()
            nodes = [e for e in cyto["elements"] if e["group"] == "nodes"]
            assert len(nodes) == 9

    def test_monitoring_change_detection(self):
        """Step 13: Monitoring detects changes between snapshots."""
        # Simulate day 1: initial entities
        snapshot1 = INVESTIGATION_ENTITIES[:5]  # First 5 entities

        # Simulate day 2: new sanctions listing appears
        snapshot2 = snapshot1 + [{
            "id": "sanction-new",
            "schema": "Person",
            "properties": {
                "name": ["Dmitri Volkov"],
                "topics": ["sanction"],
            },
            "_provenance": {"source": "opensanctions"},
        }]

        alerts = SnapshotDiffer.diff(snapshot1, snapshot2, "Dmitri Volkov")

        sanction_alerts = [a for a in alerts if a.alert_type == "new_sanction"]
        assert len(sanction_alerts) == 1
        assert sanction_alerts[0].severity == "high"
        assert "SANCTION" in sanction_alerts[0].summary

    def test_llm_helper_with_investigation_data(self):
        """Step 14: LLM helper processes investigation entities."""
        stub = StubClient(default_response='{"risk_level": "high", "score": 0.85}')
        helper = SkillLLMHelper(stub, domain="corporate_analysis")

        evidence_text = SkillLLMHelper._format_evidence(INVESTIGATION_ENTITIES[:5])
        assert "Dmitri Volkov" in evidence_text
        assert "Volkov Holdings" in evidence_text

    def test_pipeline_with_empty_data(self):
        """Edge case: empty entity list produces valid (empty) outputs."""
        engine = GraphEngine()
        result = engine.build_from_entities([])
        assert result.node_count == 0

        reporter = MarkdownReport()
        md = reporter.generate_from_engine_result("Empty", {"graph_summary": result.summary()})
        assert "Empty" in md

        analyzer = TimelineAnalyzer()
        events = analyzer.extract_events([])
        assert events == []


class TestCrossModuleConsistency:
    """Verify data flows correctly between modules."""

    def test_graph_nodes_match_entity_count(self):
        """Node entities in → graph nodes out."""
        engine = GraphEngine()
        result = engine.build_from_entities(INVESTIGATION_ENTITIES)

        # Count non-relationship entities
        node_count = sum(
            1 for e in INVESTIGATION_ENTITIES
            if e["schema"] not in (
                "Ownership", "Directorship", "Membership", "Employment",
                "Family", "Associate", "Payment", "Debt", "Representation",
                "Succession", "UnknownLink",
            )
        )
        assert result.node_count == node_count

    def test_timeline_events_ground_in_entities(self):
        """Every timeline event traces back to a real entity."""
        analyzer = TimelineAnalyzer()
        events = analyzer.extract_events(INVESTIGATION_ENTITIES)

        entity_ids = {e["id"] for e in INVESTIGATION_ENTITIES}
        for event in events:
            assert event.entity_id in entity_ids, (
                f"Event references unknown entity: {event.entity_id}"
            )

    def test_ftm_bundle_roundtrip(self):
        """Export → re-import preserves entity data."""
        exporter = FtMBundleExporter(include_provenance=False)

        with tempfile.NamedTemporaryFile(suffix=".ftm.json", delete=False) as f:
            exporter.export_jsonl(INVESTIGATION_ENTITIES, f.name)

            # Re-import
            reimported = []
            for line in Path(f.name).read_text().strip().split("\n"):
                reimported.append(json.loads(line))

            assert len(reimported) == len(INVESTIGATION_ENTITIES)

            # Build graph from reimported data — should work identically
            engine = GraphEngine()
            original = engine.build_from_entities(INVESTIGATION_ENTITIES)
            roundtripped = engine.build_from_entities(reimported)

            assert original.node_count == roundtripped.node_count
            assert original.edge_count == roundtripped.edge_count
