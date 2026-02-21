"""Change detection and monitoring for ongoing investigations.

Tracks entity states across federated search snapshots and detects:
  - New entities appearing in data sources
  - Changed properties on existing entities
  - New sanctions listings
  - New relationships / connections
  - Entity removals or de-listings

Persistence: JSON files for pilot, PostgreSQL for production.

Usage::

    detector = ChangeDetector(storage_dir="/path/to/state")
    detector.register_query("Viktor Petrov", entity_type="Person")

    # Run check (calls federated search, compares to previous snapshot)
    alerts = await detector.check_all()
    for alert in alerts:
        print(alert.summary)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Alert types
# ---------------------------------------------------------------------------


@dataclass
class ChangeAlert:
    """A detected change in monitored data."""
    alert_type: str          # new_entity, changed_property, new_sanction, removed_entity
    entity_id: str
    entity_name: str
    entity_schema: str
    query: str               # The monitoring query that triggered this
    details: dict[str, Any]  # Change-specific details
    severity: str            # low, medium, high
    timestamp: str           # ISO timestamp of detection
    source: str              # Which data source detected the change

    @property
    def summary(self) -> str:
        """One-line human-readable summary."""
        summaries = {
            "new_entity": f"New entity: {self.entity_name} ({self.entity_schema}) found in {self.source}",
            "changed_property": f"Changed: {self.entity_name} — {self.details.get('property', '?')} updated",
            "new_sanction": f"⚠️ NEW SANCTION: {self.entity_name} listed in {self.source}",
            "removed_entity": f"Removed: {self.entity_name} no longer in {self.source}",
            "new_relationship": f"New relationship: {self.entity_name} — {self.details.get('relationship', '?')}",
        }
        return summaries.get(self.alert_type, f"Change detected: {self.entity_name}")


@dataclass
class MonitoredQuery:
    """A registered monitoring query."""
    query: str
    entity_type: str = ""
    jurisdictions: list[str] = field(default_factory=list)
    created_at: str = ""
    last_checked: str = ""
    check_count: int = 0


# ---------------------------------------------------------------------------
# Snapshot comparison
# ---------------------------------------------------------------------------


class SnapshotDiffer:
    """Compare two entity snapshots to detect changes."""

    @staticmethod
    def diff(
        previous: list[dict[str, Any]],
        current: list[dict[str, Any]],
        query: str,
    ) -> list[ChangeAlert]:
        """Compare previous and current entity lists, return alerts."""
        now = datetime.now(timezone.utc).isoformat()
        alerts: list[ChangeAlert] = []

        # Index by ID
        prev_by_id = {e["id"]: e for e in previous if e.get("id")}
        curr_by_id = {e["id"]: e for e in current if e.get("id")}

        prev_ids = set(prev_by_id.keys())
        curr_ids = set(curr_by_id.keys())

        # New entities
        for eid in curr_ids - prev_ids:
            entity = curr_by_id[eid]
            props = entity.get("properties", {})
            name = (props.get("name", []) or [eid[:12]])[0]
            schema = entity.get("schema", "Unknown")
            source = entity.get("_provenance", {}).get("source", "unknown")

            # Check if it's a sanctions listing
            is_sanction = schema in ("Sanction", "SanctionEntity") or any(
                "sanction" in str(v).lower()
                for v in props.get("topics", props.get("dataset", []))
            )

            alert_type = "new_sanction" if is_sanction else "new_entity"
            severity = "high" if is_sanction else "medium"

            alerts.append(ChangeAlert(
                alert_type=alert_type,
                entity_id=eid,
                entity_name=name,
                entity_schema=schema,
                query=query,
                details={"properties": {k: v for k, v in props.items() if k != "name"}},
                severity=severity,
                timestamp=now,
                source=source,
            ))

        # Removed entities
        for eid in prev_ids - curr_ids:
            entity = prev_by_id[eid]
            props = entity.get("properties", {})
            name = (props.get("name", []) or [eid[:12]])[0]

            alerts.append(ChangeAlert(
                alert_type="removed_entity",
                entity_id=eid,
                entity_name=name,
                entity_schema=entity.get("schema", "Unknown"),
                query=query,
                details={},
                severity="low",
                timestamp=now,
                source=entity.get("_provenance", {}).get("source", "unknown"),
            ))

        # Changed entities
        for eid in prev_ids & curr_ids:
            prev_entity = prev_by_id[eid]
            curr_entity = curr_by_id[eid]
            prev_props = prev_entity.get("properties", {})
            curr_props = curr_entity.get("properties", {})

            # Compare properties
            all_keys = set(prev_props.keys()) | set(curr_props.keys())
            for key in all_keys:
                prev_val = prev_props.get(key, [])
                curr_val = curr_props.get(key, [])
                if prev_val != curr_val:
                    name = (curr_props.get("name", []) or [eid[:12]])[0]
                    alerts.append(ChangeAlert(
                        alert_type="changed_property",
                        entity_id=eid,
                        entity_name=name,
                        entity_schema=curr_entity.get("schema", "Unknown"),
                        query=query,
                        details={
                            "property": key,
                            "old_value": prev_val,
                            "new_value": curr_val,
                        },
                        severity="low",
                        timestamp=now,
                        source=curr_entity.get("_provenance", {}).get("source", "unknown"),
                    ))

        return alerts


# ---------------------------------------------------------------------------
# Change detector with file-based persistence
# ---------------------------------------------------------------------------


class ChangeDetector:
    """Monitor registered queries for changes over time.

    Parameters
    ----------
    storage_dir:
        Directory for storing query registrations and snapshots.
        Created automatically if it doesn't exist.
    """

    def __init__(self, storage_dir: str | Path = ".emet_monitoring") -> None:
        self._storage = Path(storage_dir)
        self._storage.mkdir(parents=True, exist_ok=True)
        self._queries: dict[str, MonitoredQuery] = {}
        self._differ = SnapshotDiffer()
        self._load_queries()

    def register_query(
        self,
        query: str,
        entity_type: str = "",
        jurisdictions: list[str] | None = None,
    ) -> MonitoredQuery:
        """Register a query for ongoing monitoring."""
        mq = MonitoredQuery(
            query=query,
            entity_type=entity_type,
            jurisdictions=jurisdictions or [],
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._queries[query] = mq
        self._save_queries()
        logger.info("Registered monitoring query: %s", query)
        return mq

    def unregister_query(self, query: str) -> bool:
        """Remove a monitoring query."""
        if query in self._queries:
            del self._queries[query]
            self._save_queries()
            # Clean up snapshots
            snapshot_file = self._snapshot_path(query)
            if snapshot_file.exists():
                snapshot_file.unlink()
            return True
        return False

    def list_queries(self) -> list[MonitoredQuery]:
        """List all registered monitoring queries."""
        return list(self._queries.values())

    async def check_query(self, query: str) -> list[ChangeAlert]:
        """Run a single monitoring check against federated search."""
        mq = self._queries.get(query)
        if not mq:
            logger.warning("Query not registered: %s", query)
            return []

        # Load previous snapshot
        previous = self._load_snapshot(query)

        # Run federated search
        try:
            from emet.ftm.external.federation import FederatedSearch
            federation = FederatedSearch()
            results = await federation.search_entity(
                name=query,
                entity_type=mq.entity_type,
                jurisdictions=mq.jurisdictions,
            )
            current = results.get("entities", [])
        except Exception as e:
            logger.error("Federated search failed for monitoring query %s: %s", query, e)
            return []

        # Diff
        alerts = self._differ.diff(previous, current, query)

        # Save new snapshot
        self._save_snapshot(query, current)

        # Update query metadata
        mq.last_checked = datetime.now(timezone.utc).isoformat()
        mq.check_count += 1
        self._save_queries()

        logger.info(
            "Monitoring check for %r: %d alerts (%d entities prev, %d now)",
            query, len(alerts), len(previous), len(current),
        )

        return alerts

    async def check_all(self) -> list[ChangeAlert]:
        """Run monitoring checks for all registered queries."""
        all_alerts: list[ChangeAlert] = []
        for query in self._queries:
            alerts = await self.check_query(query)
            all_alerts.extend(alerts)
        return all_alerts

    # -- Persistence ---------------------------------------------------------

    def _queries_path(self) -> Path:
        return self._storage / "queries.json"

    def _snapshot_path(self, query: str) -> Path:
        # Sanitize query for filename
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in query)
        return self._storage / f"snapshot_{safe}.json"

    def _load_queries(self) -> None:
        path = self._queries_path()
        if path.exists():
            try:
                data = json.loads(path.read_text())
                for qd in data:
                    mq = MonitoredQuery(**qd)
                    self._queries[mq.query] = mq
            except Exception as e:
                logger.warning("Failed to load monitoring queries: %s", e)

    def _save_queries(self) -> None:
        data = [
            {
                "query": mq.query,
                "entity_type": mq.entity_type,
                "jurisdictions": mq.jurisdictions,
                "created_at": mq.created_at,
                "last_checked": mq.last_checked,
                "check_count": mq.check_count,
            }
            for mq in self._queries.values()
        ]
        self._queries_path().write_text(json.dumps(data, indent=2))

    def _load_snapshot(self, query: str) -> list[dict[str, Any]]:
        path = self._snapshot_path(query)
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:
                return []
        return []

    def _save_snapshot(self, query: str, entities: list[dict[str, Any]]) -> None:
        path = self._snapshot_path(query)
        path.write_text(json.dumps(entities, indent=2, default=str))
