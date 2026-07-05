"""Unit tests for emet.agent.audit.AuditArchive and friends.

Covers pre-existing behavior (open/record/close/verify without an actor)
as a regression guard, plus the actor-identity tracking added on top:
every event (not just session_start) should carry a top-level "actor"
key, and the actor should round-trip through the manifest sidecar and
verify_archive().
"""

from __future__ import annotations

import json

from emet.agent.audit import AuditArchive, AuditManifest, read_archive, verify_archive


# ---------------------------------------------------------------------------
# Pre-existing behavior (no actor) — regression coverage
# ---------------------------------------------------------------------------

class TestAuditArchiveBasics:

    def test_open_without_actor_defaults_to_empty_dict(self, tmp_path):
        archive = AuditArchive(base_dir=tmp_path)
        archive.open("session-1", goal="investigate widgets")

        events = archive._events  # in-memory buffer, not yet flushed
        assert len(events) == 1
        first = json.loads(events[0])
        assert first["type"] == "session_start"
        assert first["data"]["session_id"] == "session-1"
        assert first["data"]["goal"] == "investigate widgets"
        assert first["data"]["actor"] == {}
        assert first["actor"] == {}

        archive.close()

    def test_close_produces_valid_manifest(self, tmp_path):
        archive = AuditArchive(base_dir=tmp_path)
        archive.open("session-2")
        archive.record_tool_call("search_entities", {"query": "x"}, {"hits": []})
        manifest = archive.close(final_summary={"findings": 0})

        assert isinstance(manifest, AuditManifest)
        assert manifest.session_id == "session-2"
        assert manifest.event_count == 3  # session_start, tool_call, session_end
        assert manifest.actor == {}

        archive_path = tmp_path / "session-2.jsonl.gz"
        manifest_path = tmp_path / "session-2.manifest.json"
        assert archive_path.exists()
        assert manifest_path.exists()

        valid, reloaded = verify_archive(archive_path)
        assert valid
        assert reloaded.actor == {}

    def test_record_event_noop_when_not_open(self, tmp_path):
        archive = AuditArchive(base_dir=tmp_path)
        archive.record_event("reasoning", {"thought": "should be dropped"})
        assert archive._events == []


# ---------------------------------------------------------------------------
# Actor identity tracking
# ---------------------------------------------------------------------------

class TestAuditArchiveActor:

    def test_session_start_records_actor(self, tmp_path):
        actor = {"id": "truthstrike", "type": "service"}
        archive = AuditArchive(base_dir=tmp_path)
        archive.open("session-actor-1", goal="probe", actor=actor)
        archive.close()

        archive_path = tmp_path / "session-actor-1.jsonl.gz"
        events = read_archive(archive_path)

        session_start = next(e for e in events if e["type"] == "session_start")
        assert session_start["actor"] == actor
        assert session_start["data"]["actor"] == actor

    def test_multiple_event_types_carry_actor(self, tmp_path):
        actor = {"id": "operator-jane", "type": "human"}
        archive = AuditArchive(base_dir=tmp_path)
        archive.open("session-actor-2", goal="probe", actor=actor)

        archive.record_tool_call(
            "search_entities", {"query": "Meridian Holdings"}, {"hits": [1, 2]},
            duration_ms=12.5, decision_source="llm",
        )
        archive.record_llm_exchange(
            system_prompt="sys", user_prompt="user", raw_response="raw",
            parsed_action={"action": "search"}, model="claude-x",
        )
        archive.record_reasoning("thinking about it")
        archive.record_safety("pii_check", "search_entities", "pass")

        archive.close(final_summary={"findings": 1})

        archive_path = tmp_path / "session-actor-2.jsonl.gz"
        events = read_archive(archive_path)

        by_type = {}
        for e in events:
            by_type.setdefault(e["type"], []).append(e)

        expected_types = {
            "session_start", "tool_call", "llm_exchange",
            "reasoning", "safety_check", "session_end",
        }
        assert expected_types.issubset(by_type.keys())

        # Every single event line — not just session_start — carries the actor.
        for event_type in expected_types:
            for event in by_type[event_type]:
                assert event["actor"] == actor, (
                    f"event type {event_type!r} missing actor: {event}"
                )

    def test_close_writes_actor_to_manifest_sidecar(self, tmp_path):
        actor = {"id": "truthstrike", "type": "service"}
        archive = AuditArchive(base_dir=tmp_path)
        archive.open("session-actor-3", actor=actor)
        archive.close()

        manifest_path = tmp_path / "session-actor-3.manifest.json"
        meta = json.loads(manifest_path.read_text())
        assert meta["actor"] == actor

    def test_verify_archive_round_trips_actor(self, tmp_path):
        actor = {"id": "operator-jane", "type": "human", "org": "newsroom-1"}
        archive = AuditArchive(base_dir=tmp_path)
        archive.open("session-actor-4", goal="probe", actor=actor)
        archive.record_reasoning("step one")
        archive.close()

        archive_path = tmp_path / "session-actor-4.jsonl.gz"
        valid, manifest = verify_archive(archive_path)

        assert valid
        assert isinstance(manifest, AuditManifest)
        assert manifest.actor == actor
