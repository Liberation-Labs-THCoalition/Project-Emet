"""Watchlist monitoring — persistent entity tracking with change detection.

Maintains a watchlist of entities to monitor. On each run, checks for:
  1. New sanctions matches (screen_sanctions)
  2. New news mentions (monitor_entity via GDELT)
  3. Corporate record changes (search_entities diff)

Compares current results against previous snapshots and surfaces only
deltas — new sanctions hits, new articles, new entities appearing in
the corporate graph.

Usage:
    # CLI
    emet watch add "Viktor Bout" --type Person
    emet watch add "Meridian Holdings" --type Company
    emet watch list
    emet watch run                    # One-shot check
    emet watch run --install-cron     # Schedule daily checks
    emet watch history "Viktor Bout"  # Show change timeline

    # Programmatic
    from emet.agent.watchlist import Watchlist
    wl = Watchlist("investigations/watchlist")
    wl.add("Viktor Bout", entity_type="Person")
    deltas = await wl.check_all()
    for d in deltas:
        print(d.summary)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import subprocess
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class WatchedEntity:
    """A single entity on the watchlist."""

    name: str
    entity_type: str = "Any"  # Person, Company, Any
    added_at: str = ""
    tags: list[str] = field(default_factory=list)
    enabled: bool = True

    def __post_init__(self):
        if not self.added_at:
            self.added_at = datetime.now(timezone.utc).isoformat()

    @property
    def key(self) -> str:
        return f"{self.name.lower().strip()}:{self.entity_type.lower()}"


@dataclass
class Delta:
    """A single detected change for a watched entity."""

    entity_name: str
    change_type: str  # "sanctions_hit", "new_article", "new_entity", "entity_gone"
    severity: str  # "critical", "high", "medium", "low"
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    detected_at: str = ""

    def __post_init__(self):
        if not self.detected_at:
            self.detected_at = datetime.now(timezone.utc).isoformat()


@dataclass
class CheckResult:
    """Result of checking all watched entities."""

    deltas: list[Delta] = field(default_factory=list)
    entities_checked: int = 0
    checked_at: str = ""
    errors: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.checked_at:
            self.checked_at = datetime.now(timezone.utc).isoformat()

    @property
    def has_critical(self) -> bool:
        return any(d.severity == "critical" for d in self.deltas)

    @property
    def summary(self) -> str:
        if not self.deltas:
            return f"No changes detected across {self.entities_checked} watched entities."
        lines = [
            f"{len(self.deltas)} change(s) detected across {self.entities_checked} entities:",
        ]
        for d in self.deltas:
            icon = {
                "critical": "🚨",
                "high": "⚠️",
                "medium": "📋",
                "low": "ℹ️",
            }.get(d.severity, "•")
            lines.append(f"  {icon} [{d.entity_name}] {d.summary}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Snapshot management
# ---------------------------------------------------------------------------


def _snapshot_hash(data: Any) -> str:
    """Deterministic hash for comparing snapshots."""
    serialized = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]


def _extract_entity_names(entities: list[dict]) -> set[str]:
    """Extract comparable entity names from search results."""
    names = set()
    for e in entities:
        name = e.get("name", "") or e.get("caption", "") or ""
        if name:
            names.add(name.lower().strip())
    return names


def _extract_sanctions_hits(result: dict) -> list[dict]:
    """Extract comparable sanctions matches."""
    hits = result.get("matches", result.get("results", result.get("hits", [])))
    if not isinstance(hits, list):
        return []
    return [
        {
            "name": h.get("name", h.get("caption", "")),
            "score": h.get("score", 0),
            "schema": h.get("schema", ""),
        }
        for h in hits
        if h.get("score", 0) > 0.5
    ]


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------


class Watchlist:
    """Persistent entity watchlist with change detection.

    All state stored as JSON files — no database required.

    Directory layout:
        {base_dir}/
            watchlist.json           # Entity list
            snapshots/
                {entity_key}/
                    latest.json      # Most recent check results
                    history.jsonl    # Append-only change log
    """

    def __init__(self, base_dir: str | Path = "investigations/watchlist") -> None:
        self._base_dir = Path(base_dir)
        self._watchlist_path = self._base_dir / "watchlist.json"
        self._snapshots_dir = self._base_dir / "snapshots"
        self._entities: list[WatchedEntity] = []
        self._load()

    def _load(self) -> None:
        """Load watchlist from disk."""
        if self._watchlist_path.exists():
            data = json.loads(self._watchlist_path.read_text())
            self._entities = [WatchedEntity(**e) for e in data]

    def _save(self) -> None:
        """Save watchlist to disk."""
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._watchlist_path.write_text(
            json.dumps(
                [
                    {
                        "name": e.name,
                        "entity_type": e.entity_type,
                        "added_at": e.added_at,
                        "tags": e.tags,
                        "enabled": e.enabled,
                    }
                    for e in self._entities
                ],
                indent=2,
            )
        )

    def add(
        self,
        name: str,
        entity_type: str = "Any",
        tags: list[str] | None = None,
    ) -> WatchedEntity:
        """Add an entity to the watchlist."""
        entity = WatchedEntity(
            name=name,
            entity_type=entity_type,
            tags=tags or [],
        )
        # Deduplicate
        existing_keys = {e.key for e in self._entities}
        if entity.key in existing_keys:
            logger.info("Entity already on watchlist: %s", name)
            return entity
        self._entities.append(entity)
        self._save()
        logger.info("Added to watchlist: %s (%s)", name, entity_type)
        return entity

    def remove(self, name: str) -> bool:
        """Remove an entity from the watchlist."""
        key = f"{name.lower().strip()}:"
        before = len(self._entities)
        self._entities = [e for e in self._entities if not e.key.startswith(key)]
        if len(self._entities) < before:
            self._save()
            return True
        return False

    def list_entities(self) -> list[WatchedEntity]:
        """List all watched entities."""
        return list(self._entities)

    def _get_snapshot_dir(self, entity: WatchedEntity) -> Path:
        """Get snapshot directory for an entity."""
        safe_name = entity.key.replace(":", "_").replace(" ", "_")
        return self._snapshots_dir / safe_name

    def _load_previous_snapshot(self, entity: WatchedEntity) -> dict[str, Any] | None:
        """Load the most recent snapshot for an entity."""
        snap_dir = self._get_snapshot_dir(entity)
        latest = snap_dir / "latest.json"
        if latest.exists():
            return json.loads(latest.read_text())
        return None

    def _save_snapshot(
        self,
        entity: WatchedEntity,
        snapshot: dict[str, Any],
        deltas: list[Delta],
    ) -> None:
        """Save current snapshot and append deltas to history."""
        snap_dir = self._get_snapshot_dir(entity)
        snap_dir.mkdir(parents=True, exist_ok=True)

        # Save latest
        (snap_dir / "latest.json").write_text(
            json.dumps(snapshot, indent=2, default=str)
        )

        # Append deltas to history
        if deltas:
            history_path = snap_dir / "history.jsonl"
            with open(history_path, "a") as f:
                for d in deltas:
                    f.write(json.dumps({
                        "detected_at": d.detected_at,
                        "change_type": d.change_type,
                        "severity": d.severity,
                        "summary": d.summary,
                        "details": d.details,
                    }, default=str) + "\n")

    def get_history(self, name: str, limit: int = 50) -> list[dict]:
        """Get change history for an entity."""
        # Find entity
        matches = [e for e in self._entities if name.lower() in e.name.lower()]
        if not matches:
            return []
        entity = matches[0]
        history_path = self._get_snapshot_dir(entity) / "history.jsonl"
        if not history_path.exists():
            return []
        events = []
        for line in history_path.read_text().strip().split("\n"):
            if line:
                events.append(json.loads(line))
        return events[-limit:]

    # ------------------------------------------------------------------
    # Check logic
    # ------------------------------------------------------------------

    async def check_entity(self, entity: WatchedEntity) -> list[Delta]:
        """Check a single entity for changes."""
        from emet.mcp.tools import EmetToolExecutor

        executor = EmetToolExecutor()
        deltas: list[Delta] = []
        previous = self._load_previous_snapshot(entity)
        current: dict[str, Any] = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "entity": entity.name,
        }

        # 1. Sanctions screening
        try:
            sanctions = await asyncio.wait_for(
                executor.execute_raw("screen_sanctions", {
                    "entity_name": entity.name,
                    "entity_type": entity.entity_type,
                }),
                timeout=15.0,
            )
            current_hits = _extract_sanctions_hits(sanctions)
            current["sanctions_hits"] = current_hits
            current["sanctions_hash"] = _snapshot_hash(current_hits)

            if previous:
                prev_hash = previous.get("sanctions_hash", "")
                if current["sanctions_hash"] != prev_hash:
                    prev_hits = previous.get("sanctions_hits", [])
                    prev_names = {h["name"].lower() for h in prev_hits}
                    new_hits = [h for h in current_hits if h["name"].lower() not in prev_names]
                    if new_hits:
                        deltas.append(Delta(
                            entity_name=entity.name,
                            change_type="sanctions_hit",
                            severity="critical",
                            summary=f"NEW sanctions match: {', '.join(h['name'] for h in new_hits)}",
                            details={"new_hits": new_hits},
                        ))
            elif current_hits:
                # First check — report existing hits
                deltas.append(Delta(
                    entity_name=entity.name,
                    change_type="sanctions_hit",
                    severity="critical",
                    summary=f"Sanctions match found: {len(current_hits)} hit(s)",
                    details={"hits": current_hits},
                ))
        except Exception as exc:
            current["sanctions_error"] = str(exc)

        # 2. News monitoring (GDELT)
        try:
            news = await asyncio.wait_for(
                executor.execute_raw("monitor_entity", {
                    "entity_name": entity.name,
                    "timespan": "7d",
                }),
                timeout=15.0,
            )
            article_count = news.get("article_count", 0)
            current["article_count"] = article_count
            current["articles_hash"] = _snapshot_hash(news.get("articles", [])[:20])

            if previous:
                prev_count = previous.get("article_count", 0)
                if article_count > prev_count + 5:
                    deltas.append(Delta(
                        entity_name=entity.name,
                        change_type="new_article",
                        severity="high" if article_count > prev_count + 20 else "medium",
                        summary=f"News spike: {article_count} articles (was {prev_count})",
                        details={"article_count": article_count, "previous": prev_count},
                    ))
        except Exception as exc:
            current["news_error"] = str(exc)

        # 3. Entity search diff
        try:
            search = await asyncio.wait_for(
                executor.execute_raw("search_entities", {
                    "query": entity.name,
                    "entity_type": entity.entity_type,
                    "limit": 20,
                }),
                timeout=15.0,
            )
            entities_found = search.get("entities", [])
            entity_names = _extract_entity_names(entities_found)
            current["entity_names"] = sorted(entity_names)
            current["entity_hash"] = _snapshot_hash(sorted(entity_names))
            current["entity_count"] = len(entity_names)

            if previous:
                prev_names = set(previous.get("entity_names", []))
                new_entities = entity_names - prev_names
                gone_entities = prev_names - entity_names

                if new_entities:
                    deltas.append(Delta(
                        entity_name=entity.name,
                        change_type="new_entity",
                        severity="medium",
                        summary=f"{len(new_entities)} new entity/ies in corporate graph",
                        details={"new": sorted(new_entities)},
                    ))
                if gone_entities:
                    deltas.append(Delta(
                        entity_name=entity.name,
                        change_type="entity_gone",
                        severity="medium",
                        summary=f"{len(gone_entities)} entity/ies no longer found",
                        details={"gone": sorted(gone_entities)},
                    ))
        except Exception as exc:
            current["search_error"] = str(exc)

        # Save snapshot
        self._save_snapshot(entity, current, deltas)
        return deltas

    async def check_all(self) -> CheckResult:
        """Check all enabled entities on the watchlist."""
        result = CheckResult()
        enabled = [e for e in self._entities if e.enabled]
        result.entities_checked = len(enabled)

        for entity in enabled:
            try:
                deltas = await self.check_entity(entity)
                result.deltas.extend(deltas)
            except Exception as exc:
                result.errors.append(f"{entity.name}: {exc}")
                logger.warning("Watchlist check failed for %s: %s", entity.name, exc)

        return result


# ---------------------------------------------------------------------------
# Notification dispatch
# ---------------------------------------------------------------------------


def format_notification(result: CheckResult) -> str:
    """Format check result for notification delivery."""
    if not result.deltas:
        return ""

    lines = [
        f"🔍 Emet Watchlist Alert — {result.checked_at[:10]}",
        f"{len(result.deltas)} change(s) across {result.entities_checked} entities",
        "",
    ]

    # Critical first
    for severity in ("critical", "high", "medium", "low"):
        for d in result.deltas:
            if d.severity == severity:
                icon = {
                    "critical": "🚨",
                    "high": "⚠️",
                    "medium": "📋",
                    "low": "ℹ️",
                }[severity]
                lines.append(f"{icon} {d.entity_name}: {d.summary}")

    return "\n".join(lines)


def send_notification(message: str, method: str = "stdout") -> bool:
    """Send a notification via the configured method.

    Methods:
        stdout:  Print to console (default, cron-friendly)
        file:    Append to investigations/watchlist/alerts.log
        notify:  Desktop notification via notify-send (Linux)
        webhook: POST to EMET_WEBHOOK_URL (Slack, Discord, email relay, etc.)
    """
    if not message:
        return False

    if method == "stdout":
        print(message)
        return True

    elif method == "file":
        path = Path("investigations/watchlist/alerts.log")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(message + "\n---\n")
        return True

    elif method == "notify":
        try:
            subprocess.run(
                ["notify-send", "Emet Watchlist", message[:500]],
                timeout=5,
                capture_output=True,
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            print(message)
            return True

    elif method == "webhook":
        url = os.environ.get("EMET_WEBHOOK_URL", "")
        if not url:
            logger.warning("EMET_WEBHOOK_URL not set, falling back to stdout")
            print(message)
            return False
        try:
            import httpx
            # Slack-compatible payload (also works with Discord, Mattermost, etc.)
            payload = {"text": message}
            resp = httpx.post(url, json=payload, timeout=10.0)
            resp.raise_for_status()
            return True
        except Exception as exc:
            logger.warning("Webhook delivery failed: %s", exc)
            # Fallback to stdout
            print(message)
            return False

    return False


# ---------------------------------------------------------------------------
# Cron management
# ---------------------------------------------------------------------------


CRON_WATCHLIST = "0 8 * * *"  # Daily 8 AM
CRON_COMMENT = "# Emet watchlist daily check"


def install_watchlist_cron() -> tuple[bool, str]:
    """Install daily watchlist check crontab entry."""
    try:
        emet_path = shutil.which("emet") or "emet"
        entry = f"{CRON_WATCHLIST} {emet_path} watch run --quiet >> /tmp/emet_watchlist.log 2>&1  {CRON_COMMENT}"

        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True, text=True, timeout=5,
        )
        existing = result.stdout if result.returncode == 0 else ""

        if "emet" in existing and "watch" in existing:
            return True, "Emet watchlist cron already installed"

        new_crontab = existing.rstrip() + "\n\n" + entry + "\n"
        proc = subprocess.run(
            ["crontab", "-"],
            input=new_crontab, capture_output=True, text=True, timeout=5,
        )

        if proc.returncode == 0:
            return True, f"Installed daily watchlist check (8 AM): {entry}"
        else:
            return False, f"crontab install failed: {proc.stderr}"

    except FileNotFoundError:
        return False, "crontab not available on this system"
    except Exception as e:
        return False, f"Cron install failed: {e}"
