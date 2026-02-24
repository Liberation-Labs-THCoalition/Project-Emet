"""Forensic audit archive — complete investigation records.

Captures every tool call (full args + full result), every LLM prompt and
response, every reasoning step, and all session metadata in a compressed,
integrity-verified local archive.

Unlike CMA (which is lossy by design for active recall), the audit archive
is a complete forensic record.  Nothing is summarized or discarded.

Format: gzip-compressed JSONL with SHA-256 integrity hash.
Each line is a timestamped event with full payloads.

    from emet.agent.audit import AuditArchive

    archive = AuditArchive("investigations/audit")
    archive.open("session-abc123")

    archive.record_event("tool_call", {
        "tool": "search_entities",
        "args": {"query": "Meridian Holdings"},
        "result": { ... full result dict ... },
    })

    archive.record_event("llm_prompt", {
        "system": "...",
        "prompt": "...",
    })

    archive.record_event("llm_response", {
        "raw_text": "...",
        "parsed_action": { ... },
    })

    manifest = archive.close()
    # manifest.path = "investigations/audit/session-abc123.jsonl.gz"
    # manifest.sha256 = "a1b2c3..."
    # manifest.event_count = 47
    # manifest.compressed_bytes = 12847
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AuditManifest:
    """Summary of a completed audit archive."""

    session_id: str
    path: str
    sha256: str
    event_count: int
    compressed_bytes: int
    uncompressed_bytes: int
    started_at: str
    closed_at: str
    goal: str = ""


class AuditArchive:
    """Append-only, compressed audit trail for investigations.

    Each event is written as a JSON line to an in-memory buffer,
    then gzip-compressed and SHA-256 hashed on close().

    Parameters
    ----------
    base_dir:
        Directory where archive files are written.
    """

    def __init__(self, base_dir: str | Path = "investigations/audit") -> None:
        self._base_dir = Path(base_dir)
        self._session_id: str = ""
        self._goal: str = ""
        self._events: list[bytes] = []
        self._started_at: str = ""
        self._is_open: bool = False

    def open(self, session_id: str, goal: str = "") -> None:
        """Start recording events for an investigation session."""
        self._session_id = session_id
        self._goal = goal
        self._events = []
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._is_open = True

        # Record session start
        self.record_event("session_start", {
            "session_id": session_id,
            "goal": goal,
        })

    def record_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Append a timestamped event to the archive.

        Parameters
        ----------
        event_type:
            One of: session_start, tool_call, tool_result, llm_prompt,
            llm_response, reasoning, finding, lead, safety_check,
            session_end, error.
        payload:
            Full event data — nothing is summarized or truncated.
        """
        if not self._is_open:
            return

        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "session": self._session_id,
            "data": payload,
        }

        line = json.dumps(event, default=str, ensure_ascii=False) + "\n"
        self._events.append(line.encode("utf-8"))

    def record_tool_call(
        self,
        tool: str,
        args: dict[str, Any],
        result: dict[str, Any],
        duration_ms: float = 0,
        decision_source: str = "",
    ) -> None:
        """Record a complete tool invocation with full result."""
        self.record_event("tool_call", {
            "tool": tool,
            "args": args,
            "result": result,
            "duration_ms": duration_ms,
            "decision_source": decision_source,
        })

    def record_llm_exchange(
        self,
        system_prompt: str,
        user_prompt: str,
        raw_response: str,
        parsed_action: dict[str, Any] | None = None,
        model: str = "",
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> None:
        """Record a complete LLM prompt→response exchange."""
        self.record_event("llm_exchange", {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "raw_response": raw_response,
            "parsed_action": parsed_action,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        })

    def record_reasoning(self, thought: str) -> None:
        """Record a chain-of-thought reasoning step."""
        self.record_event("reasoning", {"thought": thought})

    def record_safety(
        self,
        check_type: str,
        tool: str,
        verdict: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record a safety harness check result."""
        self.record_event("safety_check", {
            "check_type": check_type,
            "tool": tool,
            "verdict": verdict,
            "details": details or {},
        })

    def close(
        self,
        final_summary: dict[str, Any] | None = None,
    ) -> AuditManifest:
        """Finalize archive: compress, hash, write to disk.

        Returns an AuditManifest with the file path and integrity hash.
        """
        if not self._is_open:
            raise RuntimeError("Archive is not open")

        # Record session end
        self.record_event("session_end", {
            "summary": final_summary or {},
        })

        self._is_open = False
        closed_at = datetime.now(timezone.utc).isoformat()

        # Concatenate all events
        raw_data = b"".join(self._events)
        uncompressed_size = len(raw_data)

        # Gzip compress
        compressed = gzip.compress(raw_data, compresslevel=6)
        compressed_size = len(compressed)

        # SHA-256 of compressed archive
        sha256 = hashlib.sha256(compressed).hexdigest()

        # Write to disk
        self._base_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{self._session_id}.jsonl.gz"
        path = self._base_dir / filename
        path.write_bytes(compressed)

        # Write manifest sidecar
        manifest = AuditManifest(
            session_id=self._session_id,
            path=str(path),
            sha256=sha256,
            event_count=len(self._events),
            compressed_bytes=compressed_size,
            uncompressed_bytes=uncompressed_size,
            started_at=self._started_at,
            closed_at=closed_at,
            goal=self._goal,
        )

        manifest_path = self._base_dir / f"{self._session_id}.manifest.json"
        manifest_path.write_text(
            json.dumps({
                "session_id": manifest.session_id,
                "path": manifest.path,
                "sha256": manifest.sha256,
                "event_count": manifest.event_count,
                "compressed_bytes": manifest.compressed_bytes,
                "uncompressed_bytes": manifest.uncompressed_bytes,
                "compression_ratio": (
                    f"{uncompressed_size / compressed_size:.1f}x"
                    if compressed_size else "N/A"
                ),
                "started_at": manifest.started_at,
                "closed_at": manifest.closed_at,
                "goal": manifest.goal,
            }, indent=2)
        )

        logger.info(
            "Audit archive closed: %s (%d events, %d→%d bytes, SHA=%s…)",
            path.name,
            manifest.event_count,
            uncompressed_size,
            compressed_size,
            sha256[:12],
        )

        # Release memory
        self._events = []

        return manifest


def verify_archive(path: str | Path) -> tuple[bool, AuditManifest | None]:
    """Verify the integrity of an audit archive.

    Re-computes SHA-256 and compares against manifest.

    Returns (is_valid, manifest) or (False, None) on error.
    """
    path = Path(path)
    manifest_path = path.with_suffix("").with_suffix(".manifest.json")

    if not path.exists() or not manifest_path.exists():
        return False, None

    try:
        # Read manifest
        meta = json.loads(manifest_path.read_text())
        expected_sha = meta["sha256"]

        # Compute actual hash
        data = path.read_bytes()
        actual_sha = hashlib.sha256(data).hexdigest()

        is_valid = actual_sha == expected_sha

        manifest = AuditManifest(
            session_id=meta["session_id"],
            path=meta["path"],
            sha256=meta["sha256"],
            event_count=meta["event_count"],
            compressed_bytes=meta["compressed_bytes"],
            uncompressed_bytes=meta["uncompressed_bytes"],
            started_at=meta["started_at"],
            closed_at=meta["closed_at"],
            goal=meta.get("goal", ""),
        )

        return is_valid, manifest

    except Exception as exc:
        logger.error("Archive verification failed: %s", exc)
        return False, None


def read_archive(path: str | Path) -> list[dict[str, Any]]:
    """Decompress and read all events from an audit archive."""
    path = Path(path)
    compressed = path.read_bytes()
    raw = gzip.decompress(compressed)
    events = []
    for line in raw.decode("utf-8").strip().split("\n"):
        if line:
            events.append(json.loads(line))
    return events
