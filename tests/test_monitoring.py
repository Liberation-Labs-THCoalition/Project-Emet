"""Tests for emet.monitoring — change detection and monitoring.

Tests cover:
  - SnapshotDiffer: new entities, removed entities, changed properties, sanctions
  - ChangeDetector: query registration, persistence, snapshot management
  - ChangeAlert: summary generation for each alert type
"""

import json
import tempfile
from pathlib import Path

import pytest

from emet.monitoring import ChangeAlert, ChangeDetector, MonitoredQuery, SnapshotDiffer


# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------

def _entity(eid: str, schema: str, name: str, **extra_props) -> dict:
    props = {"name": [name]}
    for k, v in extra_props.items():
        props[k] = [v] if isinstance(v, str) else v
    return {"id": eid, "schema": schema, "properties": props}


def _entity_with_source(eid: str, schema: str, name: str, source: str) -> dict:
    return {
        "id": eid, "schema": schema,
        "properties": {"name": [name]},
        "_provenance": {"source": source},
    }


# ---------------------------------------------------------------------------
# SnapshotDiffer tests
# ---------------------------------------------------------------------------


class TestSnapshotDiffer:
    def test_detects_new_entity(self):
        previous = []
        current = [_entity("e1", "Person", "Alice")]

        alerts = SnapshotDiffer.diff(previous, current, "test query")

        assert len(alerts) == 1
        assert alerts[0].alert_type == "new_entity"
        assert alerts[0].entity_name == "Alice"
        assert alerts[0].entity_schema == "Person"
        assert alerts[0].query == "test query"

    def test_detects_removed_entity(self):
        previous = [_entity("e1", "Person", "Alice")]
        current = []

        alerts = SnapshotDiffer.diff(previous, current, "test")

        assert len(alerts) == 1
        assert alerts[0].alert_type == "removed_entity"
        assert alerts[0].entity_name == "Alice"
        assert alerts[0].severity == "low"

    def test_detects_changed_property(self):
        previous = [_entity("e1", "Company", "Acme Inc", country="US")]
        current = [_entity("e1", "Company", "Acme Inc", country="VG")]

        alerts = SnapshotDiffer.diff(previous, current, "test")

        changed = [a for a in alerts if a.alert_type == "changed_property"]
        assert len(changed) == 1
        assert changed[0].details["property"] == "country"
        assert changed[0].details["old_value"] == ["US"]
        assert changed[0].details["new_value"] == ["VG"]

    def test_no_changes_no_alerts(self):
        entities = [_entity("e1", "Person", "Alice")]
        alerts = SnapshotDiffer.diff(entities, entities, "test")
        assert len(alerts) == 0

    def test_detects_new_sanction(self):
        previous = []
        current = [{
            "id": "s1",
            "schema": "Person",
            "properties": {
                "name": ["Viktor Petrov"],
                "topics": ["sanction"],
            },
        }]

        alerts = SnapshotDiffer.diff(previous, current, "test")

        assert len(alerts) == 1
        assert alerts[0].alert_type == "new_sanction"
        assert alerts[0].severity == "high"

    def test_multiple_changes_in_one_diff(self):
        previous = [
            _entity("e1", "Person", "Alice"),
            _entity("e2", "Company", "OldCorp"),
        ]
        current = [
            _entity("e1", "Person", "Alice", country="UK"),  # Changed
            _entity("e3", "Company", "NewCorp"),              # New
            # e2 removed
        ]

        alerts = SnapshotDiffer.diff(previous, current, "test")

        types = {a.alert_type for a in alerts}
        assert "changed_property" in types
        assert "new_entity" in types
        assert "removed_entity" in types

    def test_source_provenance_in_alerts(self):
        previous = []
        current = [_entity_with_source("e1", "Person", "Alice", "opensanctions")]

        alerts = SnapshotDiffer.diff(previous, current, "test")
        assert alerts[0].source == "opensanctions"

    def test_empty_both(self):
        alerts = SnapshotDiffer.diff([], [], "test")
        assert len(alerts) == 0

    def test_entities_without_ids_skipped(self):
        previous = [{"schema": "Person", "properties": {"name": ["Alice"]}}]  # No id
        current = [_entity("e1", "Person", "Bob")]

        alerts = SnapshotDiffer.diff(previous, current, "test")
        assert len(alerts) == 1
        assert alerts[0].entity_name == "Bob"


# ---------------------------------------------------------------------------
# ChangeAlert tests
# ---------------------------------------------------------------------------


class TestChangeAlert:
    def test_summary_new_entity(self):
        alert = ChangeAlert(
            alert_type="new_entity", entity_id="e1", entity_name="Alice",
            entity_schema="Person", query="test", details={},
            severity="medium", timestamp="2026-01-01T00:00:00Z", source="yente",
        )
        assert "New entity" in alert.summary
        assert "Alice" in alert.summary

    def test_summary_new_sanction(self):
        alert = ChangeAlert(
            alert_type="new_sanction", entity_id="e1", entity_name="Viktor",
            entity_schema="Person", query="test", details={},
            severity="high", timestamp="2026-01-01T00:00:00Z", source="opensanctions",
        )
        assert "SANCTION" in alert.summary
        assert "Viktor" in alert.summary

    def test_summary_changed_property(self):
        alert = ChangeAlert(
            alert_type="changed_property", entity_id="e1", entity_name="Acme",
            entity_schema="Company", query="test",
            details={"property": "country"},
            severity="low", timestamp="2026-01-01T00:00:00Z", source="oc",
        )
        assert "Changed" in alert.summary
        assert "country" in alert.summary

    def test_summary_removed(self):
        alert = ChangeAlert(
            alert_type="removed_entity", entity_id="e1", entity_name="Ghost Corp",
            entity_schema="Company", query="test", details={},
            severity="low", timestamp="2026-01-01T00:00:00Z", source="icij",
        )
        assert "Removed" in alert.summary


# ---------------------------------------------------------------------------
# ChangeDetector tests
# ---------------------------------------------------------------------------


class TestChangeDetector:
    def test_register_query(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            detector = ChangeDetector(storage_dir=tmpdir)
            mq = detector.register_query("Viktor Petrov", entity_type="Person")

            assert mq.query == "Viktor Petrov"
            assert mq.entity_type == "Person"
            assert mq.created_at  # Should have timestamp

    def test_list_queries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            detector = ChangeDetector(storage_dir=tmpdir)
            detector.register_query("Query A")
            detector.register_query("Query B")

            queries = detector.list_queries()
            assert len(queries) == 2
            names = {q.query for q in queries}
            assert names == {"Query A", "Query B"}

    def test_unregister_query(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            detector = ChangeDetector(storage_dir=tmpdir)
            detector.register_query("Query A")
            assert len(detector.list_queries()) == 1

            result = detector.unregister_query("Query A")
            assert result is True
            assert len(detector.list_queries()) == 0

    def test_unregister_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            detector = ChangeDetector(storage_dir=tmpdir)
            assert detector.unregister_query("nonexistent") is False

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Register in first instance
            d1 = ChangeDetector(storage_dir=tmpdir)
            d1.register_query("Persistent Query")

            # Load in second instance
            d2 = ChangeDetector(storage_dir=tmpdir)
            queries = d2.list_queries()
            assert len(queries) == 1
            assert queries[0].query == "Persistent Query"

    def test_snapshot_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            detector = ChangeDetector(storage_dir=tmpdir)
            detector.register_query("test")

            # Manually save a snapshot
            detector._save_snapshot("test", [_entity("e1", "Person", "Alice")])

            # Load it back
            snapshot = detector._load_snapshot("test")
            assert len(snapshot) == 1
            assert snapshot[0]["id"] == "e1"

    def test_empty_snapshot_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            detector = ChangeDetector(storage_dir=tmpdir)
            snapshot = detector._load_snapshot("nonexistent")
            assert snapshot == []

    def test_snapshot_diff_integration(self):
        """Simulate two monitoring checks with changing data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            detector = ChangeDetector(storage_dir=tmpdir)
            detector.register_query("test")

            # First snapshot
            snapshot1 = [_entity("e1", "Person", "Alice")]
            detector._save_snapshot("test", snapshot1)

            # Second snapshot (Alice + new Bob)
            snapshot2 = [
                _entity("e1", "Person", "Alice"),
                _entity("e2", "Person", "Bob"),
            ]

            # Manually diff (check_query would call federated search)
            previous = detector._load_snapshot("test")
            alerts = SnapshotDiffer.diff(previous, snapshot2, "test")

            assert len(alerts) == 1
            assert alerts[0].alert_type == "new_entity"
            assert alerts[0].entity_name == "Bob"
