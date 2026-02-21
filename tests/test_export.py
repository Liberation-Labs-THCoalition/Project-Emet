"""Tests for emet.export — reporting and export pipeline.

Covers:
  - Markdown report generation
  - FtM bundle export (JSONL + zip)
  - Timeline extraction and temporal pattern detection
"""

import json
import tempfile
import zipfile
from pathlib import Path

import pytest

from emet.export.markdown import MarkdownReport, InvestigationReport
from emet.export.ftm_bundle import FtMBundleExporter
from emet.export.timeline import TimelineAnalyzer, TimelineEvent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _entity(eid, schema, **props):
    return {
        "id": eid,
        "schema": schema,
        "properties": {k: [v] if isinstance(v, str) else v for k, v in props.items()},
    }


def _relationship(eid, schema, source_prop, source_id, target_prop, target_id, **extra):
    props = {source_prop: [source_id], target_prop: [target_id]}
    for k, v in extra.items():
        props[k] = [v] if isinstance(v, str) else v
    return {"id": eid, "schema": schema, "properties": props}


@pytest.fixture
def sample_entities():
    """Mixed entities with dates for timeline testing."""
    return [
        _entity("co-1", "Company", name="Alpha Corp", country="VG",
                incorporationDate="2019-03-15"),
        _entity("co-2", "Company", name="Beta Ltd", country="CY",
                incorporationDate="2019-03-17"),
        _entity("co-3", "Company", name="Gamma SA", country="CH",
                incorporationDate="2019-03-18"),
        _entity("person-1", "Person", name="John Doe", country="US"),
        _relationship("pay-1", "Payment", "payer", "co-1", "beneficiary", "co-2",
                       date="2019-04-01"),
        _relationship("own-1", "Ownership", "owner", "person-1", "asset", "co-1",
                       startDate="2019-03-10"),
    ]


@pytest.fixture
def sample_findings():
    """GraphEngine-style findings dict."""
    return {
        "query": "Viktor Petrov",
        "graph_summary": {"node_count": 8, "edge_count": 9},
        "key_players": [
            {"name": "Sunrise Holdings", "schema": "Company",
             "composite_score": 0.85, "explanation": "Top ranked entity"},
        ],
        "brokers": [
            {"name": "Elena Kozlova", "schema": "Person",
             "betweenness": 0.42, "explanation": "Key intermediary",
             "follow_up": ["Check PEP lists"]},
        ],
        "communities": [
            {"id": 0, "size": 5, "cross_jurisdiction": True,
             "explanation": "Cross-border cluster"},
        ],
        "circular_ownership": [
            {"length": 3, "entities": ["Sunrise", "Gamma", "Sunrise"],
             "risk_score": 0.8, "explanation": "Circular ownership detected"},
        ],
        "anomalies": [
            {"type": "fan_out_ownership", "severity": "high",
             "explanation": "Sunrise owns 3 entities across jurisdictions",
             "follow_up": ["Verify holding structure"]},
        ],
    }


# ---------------------------------------------------------------------------
# MarkdownReport tests
# ---------------------------------------------------------------------------


class TestMarkdownReport:
    def test_basic_report_generation(self, sample_findings):
        reporter = MarkdownReport()
        md = reporter.generate_from_engine_result(
            title="Viktor Petrov Investigation",
            findings=sample_findings,
            summary="Investigation into offshore holdings.",
        )

        assert "# Viktor Petrov Investigation" in md
        assert "Investigation into offshore holdings." in md
        assert "Emet Investigative Framework" in md

    def test_contains_key_players(self, sample_findings):
        reporter = MarkdownReport()
        md = reporter.generate_from_engine_result("Test", sample_findings)
        assert "Sunrise Holdings" in md
        assert "Key Entities" in md

    def test_contains_brokers(self, sample_findings):
        reporter = MarkdownReport()
        md = reporter.generate_from_engine_result("Test", sample_findings)
        assert "Elena Kozlova" in md
        assert "Intermediaries" in md

    def test_contains_circular_ownership(self, sample_findings):
        reporter = MarkdownReport()
        md = reporter.generate_from_engine_result("Test", sample_findings)
        assert "Circular Ownership" in md
        assert "0.80" in md  # risk score

    def test_contains_anomalies(self, sample_findings):
        reporter = MarkdownReport()
        md = reporter.generate_from_engine_result("Test", sample_findings)
        assert "Fan Out Ownership" in md

    def test_contains_caveats(self, sample_findings):
        reporter = MarkdownReport()
        md = reporter.generate_from_engine_result("Test", sample_findings)
        assert "independently verified" in md

    def test_manual_report(self):
        report = InvestigationReport(
            title="Test Report",
            summary="A test.",
            entities=[
                {"id": "e1", "schema": "Company", "name": "Acme Corp",
                 "country": "US", "properties": {}},
            ],
            data_sources=[
                {"name": "OpenSanctions", "type": "Sanctions", "records": "42"},
            ],
        )
        reporter = MarkdownReport()
        md = reporter.generate(report)
        assert "# Test Report" in md
        assert "Acme Corp" in md
        assert "OpenSanctions" in md

    def test_empty_findings(self):
        reporter = MarkdownReport()
        md = reporter.generate_from_engine_result("Empty", {})
        assert "# Empty" in md
        assert "No significant network patterns" in md


# ---------------------------------------------------------------------------
# FtMBundleExporter tests
# ---------------------------------------------------------------------------


class TestFtMBundleExporter:
    def test_export_jsonl(self, sample_entities):
        exporter = FtMBundleExporter()
        with tempfile.NamedTemporaryFile(suffix=".ftm.json", delete=False) as f:
            count = exporter.export_jsonl(sample_entities, f.name)
            assert count == len(sample_entities)

            # Verify each line is valid JSON with required fields
            lines = Path(f.name).read_text().strip().split("\n")
            assert len(lines) == count
            for line in lines:
                entity = json.loads(line)
                assert "id" in entity
                assert "schema" in entity
                assert "properties" in entity

    def test_export_zip(self, sample_entities):
        exporter = FtMBundleExporter()
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            path = exporter.export_zip(sample_entities, f.name, "test-investigation")
            assert Path(path).exists()

            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
                assert "entities.ftm.json" in names
                assert "manifest.json" in names

                manifest = json.loads(zf.read("manifest.json"))
                assert manifest["entity_count"] == len(sample_entities)
                assert manifest["investigation"] == "test-investigation"
                assert "schema_counts" in manifest

    def test_to_bytes(self, sample_entities):
        exporter = FtMBundleExporter()
        data = exporter.to_bytes(sample_entities)
        assert isinstance(data, bytes)
        lines = data.decode().strip().split("\n")
        assert len(lines) == len(sample_entities)

    def test_excludes_orphans(self):
        entities = [
            {"id": "real", "schema": "Person", "properties": {"name": ["Alice"]}},
            {"id": "orphan", "schema": "Unknown", "properties": {}, "_orphan": True},
        ]
        exporter = FtMBundleExporter(include_orphans=False)
        data = exporter.to_bytes(entities)
        lines = data.decode().strip().split("\n")
        assert len(lines) == 1

    def test_includes_orphans_when_enabled(self):
        entities = [
            {"id": "real", "schema": "Person", "properties": {"name": ["Alice"]}},
            {"id": "orphan", "schema": "Unknown", "properties": {}, "_orphan": True},
        ]
        exporter = FtMBundleExporter(include_orphans=True)
        data = exporter.to_bytes(entities)
        lines = data.decode().strip().split("\n")
        assert len(lines) == 2

    def test_provenance_attached(self):
        entities = [
            {
                "id": "e1", "schema": "Company",
                "properties": {"name": ["Test Corp"]},
                "_provenance": {"source": "https://opensanctions.org", "retrieved_at": "2024-01-15"},
            },
        ]
        exporter = FtMBundleExporter(include_provenance=True)
        data = exporter.to_bytes(entities)
        entity = json.loads(data.decode().strip())
        assert "https://opensanctions.org" in entity["properties"].get("sourceUrl", [])

    def test_skips_invalid_entities(self):
        entities = [
            {"id": "", "schema": "Person", "properties": {}},  # No ID
            {"id": "valid", "schema": "", "properties": {}},   # No schema
            {"id": "good", "schema": "Person", "properties": {"name": ["Bob"]}},
        ]
        exporter = FtMBundleExporter()
        data = exporter.to_bytes(entities)
        lines = data.decode().strip().split("\n")
        assert len(lines) == 1  # Only "good" survives


# ---------------------------------------------------------------------------
# TimelineAnalyzer tests
# ---------------------------------------------------------------------------


class TestTimelineAnalyzer:
    def test_extract_events(self, sample_entities):
        analyzer = TimelineAnalyzer()
        events = analyzer.extract_events(sample_entities)

        assert len(events) >= 3  # 3 incorporation dates + 1 payment date + 1 ownership date
        # Events should be sorted by date
        dates = [e.date for e in events]
        assert dates == sorted(dates)

    def test_event_descriptions(self, sample_entities):
        analyzer = TimelineAnalyzer()
        events = analyzer.extract_events(sample_entities)

        inc_events = [e for e in events if "incorporated" in e.description]
        assert len(inc_events) == 3  # 3 companies with incorporationDate

    def test_detect_burst_pattern(self, sample_entities):
        """Three companies incorporated within 3 days = burst."""
        analyzer = TimelineAnalyzer(burst_window_days=7, burst_threshold=3)
        patterns = analyzer.detect_patterns(sample_entities)

        bursts = [p for p in patterns if p.pattern_type == "burst"]
        assert len(bursts) >= 1
        burst = bursts[0]
        assert burst.severity in ("medium", "high")
        assert burst.score > 0

    def test_detect_coincidence_pattern(self, sample_entities):
        """Alpha Corp incorporated 2019-03-15, payment 2019-04-01 = 17 days."""
        analyzer = TimelineAnalyzer()
        patterns = analyzer.detect_patterns(sample_entities)

        coincidences = [p for p in patterns if p.pattern_type == "coincidence"]
        # Should detect incorporation-near-payment
        assert len(coincidences) >= 1

    def test_no_patterns_in_sparse_data(self):
        """Single entity = no patterns."""
        entities = [_entity("co-1", "Company", name="Solo Corp",
                            incorporationDate="2020-01-01")]
        analyzer = TimelineAnalyzer()
        patterns = analyzer.detect_patterns(entities)
        assert len(patterns) == 0

    def test_to_markdown(self, sample_entities):
        analyzer = TimelineAnalyzer()
        events = analyzer.extract_events(sample_entities)
        md = analyzer.to_markdown(events)

        assert "## Timeline" in md
        assert "2019" in md
        assert "Alpha Corp" in md

    def test_to_json(self, sample_entities):
        analyzer = TimelineAnalyzer()
        events = analyzer.extract_events(sample_entities)
        data = analyzer.to_json(events)

        assert isinstance(data, list)
        assert len(data) == len(events)
        assert "date" in data[0]
        assert "entity_name" in data[0]

    def test_empty_entities(self):
        analyzer = TimelineAnalyzer()
        events = analyzer.extract_events([])
        assert events == []
        md = analyzer.to_markdown([])
        assert "No dated events" in md

    def test_unparseable_dates_handled(self):
        entities = [_entity("co-1", "Company", name="Bad Dates",
                            incorporationDate="not-a-date")]
        analyzer = TimelineAnalyzer()
        events = analyzer.extract_events(entities)
        assert len(events) == 1
        assert events[0].date_parsed is None
