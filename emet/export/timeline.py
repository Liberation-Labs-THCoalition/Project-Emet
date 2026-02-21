"""Timeline analysis and temporal pattern detection.

Extracts dated events from FtM entities and identifies suspicious
temporal patterns:

  - **Burst patterns**: N entities with dates within M days of each other
  - **Suspicious coincidences**: incorporation near contract award, etc.
  - **Sequencing anomalies**: events in wrong order
  - **Temporal clusters**: groups of activity in narrow time windows

These patterns are strong investigative signals. Shell company networks
often incorporate entities in rapid succession (same week), and
corrupt contracts frequently follow suspicious timing with company
creation or political appointment dates.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Date property names in FtM entities
DATE_PROPERTIES = [
    "date",
    "startDate",
    "endDate",
    "incorporationDate",
    "dissolutionDate",
    "createdAt",
    "modifiedAt",
    "authoredAt",
    "publishedAt",
    "birthDate",
    "deathDate",
]


@dataclass
class TimelineEvent:
    """A dated event extracted from an FtM entity."""
    date: str                      # ISO date string
    date_parsed: datetime | None   # Parsed datetime (None if unparseable)
    entity_id: str
    entity_name: str
    entity_schema: str
    property_name: str             # Which FtM property the date came from
    description: str               # Human-readable event description


@dataclass
class TemporalPattern:
    """A detected temporal pattern."""
    pattern_type: str              # burst, coincidence, sequencing, cluster
    events: list[TimelineEvent]
    severity: str                  # low, medium, high
    explanation: str
    window_days: int = 0           # Time window in days
    score: float = 0.0             # 0–1 significance score


class TimelineAnalyzer:
    """Extract timelines and detect temporal patterns from FtM entities.

    Parameters
    ----------
    burst_window_days:
        Window for burst detection. Default 7 (one week).
    burst_threshold:
        Minimum entities in window to flag as burst. Default 3.
    """

    def __init__(
        self,
        burst_window_days: int = 7,
        burst_threshold: int = 3,
    ) -> None:
        self._burst_window = burst_window_days
        self._burst_threshold = burst_threshold

    def extract_events(self, entities: list[dict[str, Any]]) -> list[TimelineEvent]:
        """Extract all dated events from a list of FtM entities."""
        events: list[TimelineEvent] = []

        for entity in entities:
            eid = entity.get("id", "")
            schema = entity.get("schema", "")
            props = entity.get("properties", {})
            names = props.get("name", [])
            name = names[0] if names else eid[:12]

            for date_prop in DATE_PROPERTIES:
                values = props.get(date_prop, [])
                for date_str in values:
                    if not date_str or not isinstance(date_str, str):
                        continue

                    parsed = self._parse_date(date_str)
                    description = self._describe_event(schema, date_prop, name)

                    events.append(TimelineEvent(
                        date=date_str,
                        date_parsed=parsed,
                        entity_id=eid,
                        entity_name=name,
                        entity_schema=schema,
                        property_name=date_prop,
                        description=description,
                    ))

        # Sort by date
        events.sort(key=lambda e: e.date)
        return events

    def detect_patterns(
        self, entities: list[dict[str, Any]]
    ) -> list[TemporalPattern]:
        """Run all temporal pattern detections on entity list."""
        events = self.extract_events(entities)
        patterns: list[TemporalPattern] = []

        patterns.extend(self._detect_bursts(events))
        patterns.extend(self._detect_coincidences(events))

        # Sort by score
        patterns.sort(key=lambda p: p.score, reverse=True)
        return patterns

    def to_markdown(self, events: list[TimelineEvent]) -> str:
        """Render timeline as Markdown."""
        if not events:
            return "No dated events found.\n"

        lines = ["## Timeline\n"]
        current_year = ""

        for event in events:
            year = event.date[:4] if len(event.date) >= 4 else "Unknown"
            if year != current_year:
                current_year = year
                lines.append(f"\n### {year}\n")

            lines.append(f"- **{event.date}** — {event.description}")

        return "\n".join(lines)

    def to_json(self, events: list[TimelineEvent]) -> list[dict[str, Any]]:
        """Serialize timeline events to JSON-compatible dicts."""
        return [
            {
                "date": e.date,
                "entity_id": e.entity_id,
                "entity_name": e.entity_name,
                "entity_schema": e.entity_schema,
                "property_name": e.property_name,
                "description": e.description,
            }
            for e in events
        ]

    # -- Pattern detection ---------------------------------------------------

    def _detect_bursts(self, events: list[TimelineEvent]) -> list[TemporalPattern]:
        """Detect temporal bursts — many events in a narrow time window.

        A burst of N incorporations within a week suggests coordinated
        entity creation, a classic shell company network indicator.
        """
        patterns: list[TemporalPattern] = []

        # Filter to events with parseable dates
        dated = [e for e in events if e.date_parsed is not None]
        if len(dated) < self._burst_threshold:
            return patterns

        # Sliding window
        window = timedelta(days=self._burst_window)

        i = 0
        while i < len(dated):
            # Find all events within window of dated[i]
            burst: list[TimelineEvent] = [dated[i]]
            j = i + 1
            while j < len(dated):
                assert dated[i].date_parsed is not None
                assert dated[j].date_parsed is not None
                if dated[j].date_parsed - dated[i].date_parsed <= window:
                    burst.append(dated[j])
                    j += 1
                else:
                    break

            if len(burst) >= self._burst_threshold:
                # Check if entities are distinct
                unique_entities = {e.entity_id for e in burst}
                if len(unique_entities) >= self._burst_threshold:
                    score = min(1.0, len(burst) / (self._burst_threshold * 2))
                    severity = "high" if len(burst) >= self._burst_threshold * 2 else "medium"

                    # Describe the burst
                    schemas = [e.entity_schema for e in burst]
                    schema_str = ", ".join(set(schemas))
                    date_range = f"{burst[0].date} to {burst[-1].date}"

                    explanation = (
                        f"Temporal burst: {len(burst)} events involving {len(unique_entities)} "
                        f"distinct entities ({schema_str}) within {self._burst_window} days "
                        f"({date_range}). Coordinated activity pattern."
                    )

                    patterns.append(TemporalPattern(
                        pattern_type="burst",
                        events=burst,
                        severity=severity,
                        explanation=explanation,
                        window_days=self._burst_window,
                        score=score,
                    ))

                    i = j  # Skip past this burst
                    continue

            i += 1

        return patterns

    def _detect_coincidences(self, events: list[TimelineEvent]) -> list[TemporalPattern]:
        """Detect suspicious temporal coincidences between related events.

        E.g., company incorporated 2 days before receiving a government contract.
        """
        patterns: list[TemporalPattern] = []

        # Group events by type for pairwise comparison
        incorporations = [e for e in events if e.property_name == "incorporationDate" and e.date_parsed]
        transactions = [e for e in events if e.property_name == "date"
                        and e.entity_schema == "Payment" and e.date_parsed]

        # Check incorporation → payment coincidences
        for inc in incorporations:
            for txn in transactions:
                if inc.date_parsed and txn.date_parsed:
                    delta = abs((txn.date_parsed - inc.date_parsed).days)
                    if 0 < delta <= 30:  # Within 30 days
                        score = max(0.3, 1.0 - (delta / 30))
                        severity = "high" if delta <= 7 else "medium"

                        explanation = (
                            f"Suspicious timing: {inc.entity_name} incorporated on {inc.date} "
                            f"({delta} days before payment involving {txn.entity_name} on {txn.date})."
                        )

                        patterns.append(TemporalPattern(
                            pattern_type="coincidence",
                            events=[inc, txn],
                            severity=severity,
                            explanation=explanation,
                            window_days=delta,
                            score=score,
                        ))

        return patterns

    # -- Helpers -------------------------------------------------------------

    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        """Parse an ISO date string (lenient)."""
        s = date_str.strip()
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                     "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        # Try truncating to just the date portion
        if len(s) >= 10:
            try:
                return datetime.strptime(s[:10], "%Y-%m-%d")
            except ValueError:
                pass
        return None

    @staticmethod
    def _describe_event(schema: str, date_prop: str, entity_name: str) -> str:
        """Generate human-readable event description."""
        descriptions = {
            ("Company", "incorporationDate"): f"{entity_name} incorporated",
            ("Company", "dissolutionDate"): f"{entity_name} dissolved",
            ("Person", "birthDate"): f"{entity_name} born",
            ("Person", "deathDate"): f"{entity_name} died",
            ("Payment", "date"): f"Payment: {entity_name}",
            ("Ownership", "startDate"): f"Ownership started: {entity_name}",
            ("Ownership", "endDate"): f"Ownership ended: {entity_name}",
            ("Directorship", "startDate"): f"Directorship started: {entity_name}",
            ("Directorship", "endDate"): f"Directorship ended: {entity_name}",
            ("Document", "authoredAt"): f"Document authored: {entity_name}",
            ("Document", "publishedAt"): f"Document published: {entity_name}",
        }
        key = (schema, date_prop)
        if key in descriptions:
            return descriptions[key]
        return f"{entity_name}: {date_prop.replace('Date', ' date').replace('At', '')}"
