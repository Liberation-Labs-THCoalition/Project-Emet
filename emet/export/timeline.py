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

import html
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

# Fallback color palette for the HTML timeline's schema badges. Assigned
# round-robin to whatever distinct entity_schema values show up in a given
# timeline — doesn't need to match the graph visualizer's palette exactly,
# just needs to be visually distinct per schema.
_HTML_SCHEMA_PALETTE = [
    "#3498DB", "#E74C3C", "#E67E22", "#9B59B6", "#1ABC9C",
    "#2C3E50", "#27AE60", "#F39C12", "#16A085", "#8E44AD",
    "#2ECC71", "#34495E", "#C0392B", "#7F8C8D",
]

# Severity -> band color for pattern highlighting in the HTML timeline.
_HTML_SEVERITY_COLORS = {
    "low": "#f1c40f",
    "medium": "#e67e22",
    "high": "#e74c3c",
}


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

    def to_html(self, entities: list[dict[str, Any]]) -> str:
        """Render an interactive, self-contained, fully-offline HTML timeline.

        Calls ``self.extract_events(entities)`` and ``self.detect_patterns(entities)``
        internally (same inputs the existing ``to_markdown``/``to_json`` helpers
        take), then returns a single complete HTML document string (a full
        ``<!DOCTYPE html>...<html>...</html>`` — this is meant to be written
        directly to a ``.html`` file and opened in a browser, NOT embedded as a
        page fragment) with:

          - A vertical timeline: one entry per ``TimelineEvent``, sorted
            chronologically (already sorted by ``extract_events``), each showing
            date, entity_name, entity_schema (as a small colored badge), and
            description.
          - A schema filter: checkboxes listing every distinct entity_schema
            present in the events, with inline vanilla JS (no external
            libraries, no CDN links) that shows/hides timeline entries when the
            filter changes. Works fully offline (file:// URL, no network
            requests of any kind).
          - Pattern bands: for each ``TemporalPattern`` from
            ``detect_patterns()``, entries whose date falls within
            ``[pattern.events[0].date, pattern.events[-1].date]`` get a
            severity-colored highlight (yellow/orange/red for
            low/medium/high), with the pattern's ``explanation`` shown both as
            a hover tooltip on the highlighted rows and in a "Detected
            patterns" panel above the timeline.

        Returns a minimal valid HTML page saying "No dated events found." if no
        dated events are extracted (handles the empty-events case gracefully).
        """
        events = self.extract_events(entities)
        if not events:
            return self._empty_timeline_html()

        patterns = self.detect_patterns(entities)

        schemas = sorted({e.entity_schema or "Unknown" for e in events})
        schema_colors = {
            schema: _HTML_SCHEMA_PALETTE[i % len(_HTML_SCHEMA_PALETTE)]
            for i, schema in enumerate(schemas)
        }
        severity_rank = {"low": 0, "medium": 1, "high": 2}

        row_chunks: list[str] = []
        current_year = ""
        for event in events:
            year = event.date[:4] if len(event.date) >= 4 else "Unknown"
            if year != current_year:
                current_year = year
                row_chunks.append(f'<div class="year-header">{html.escape(year)}</div>')

            schema = event.entity_schema or "Unknown"
            color = schema_colors[schema]

            matched = [p for p in patterns if self._event_in_pattern_range(event, p)]
            band_class = ""
            title_attr = ""
            if matched:
                top = max(matched, key=lambda p: severity_rank.get(p.severity, 0))
                band_class = f" band-{top.severity}"
                tooltip = " | ".join(p.explanation for p in matched)
                title_attr = f' title="{html.escape(tooltip)}"'

            row_chunks.append(
                f'<div class="event-row{band_class}" data-schema="{html.escape(schema)}"{title_attr}>'
                f'<div class="event-date">{html.escape(event.date)}</div>'
                f'<div class="event-badge" style="background:{color}">{html.escape(schema)}</div>'
                f'<div class="event-body">'
                f'<div class="event-name">{html.escape(event.entity_name)}</div>'
                f'<div class="event-desc">{html.escape(event.description)}</div>'
                f'</div>'
                f'</div>'
            )

        filter_chunks = [
            f'<label class="filter-item">'
            f'<input type="checkbox" class="schema-filter" value="{html.escape(schema)}" checked> '
            f'<span class="swatch" style="background:{schema_colors[schema]}"></span>'
            f'{html.escape(schema)}</label>'
            for schema in schemas
        ]

        patterns_html = ""
        if patterns:
            pattern_items = "".join(
                f'<li class="pattern-item pattern-{p.severity}">'
                f'<span class="pattern-severity">{html.escape(p.severity.upper())}</span> '
                f'<span class="pattern-type">{html.escape(p.pattern_type)}</span>: '
                f'{html.escape(p.explanation)}</li>'
                for p in patterns
            )
            patterns_html = (
                '<div class="patterns-panel">'
                '<h2>Detected patterns</h2>'
                f'<ul>{pattern_items}</ul>'
                '</div>'
            )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Investigation Timeline</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
    margin: 0; padding: 1.5rem 2rem 3rem;
    background: #f7f7f9; color: #1c1c1e;
  }}
  h1 {{ margin-top: 0; }}
  .controls {{
    background: #fff; border: 1px solid #ddd; border-radius: 8px;
    padding: 0.75rem 1rem; margin-bottom: 1rem;
  }}
  .filter-item {{
    display: inline-flex; align-items: center; gap: 0.35rem;
    margin: 0.25rem 0.75rem 0.25rem 0; cursor: pointer; font-size: 0.9rem;
  }}
  .swatch {{
    display: inline-block; width: 0.8rem; height: 0.8rem; border-radius: 3px;
  }}
  .patterns-panel {{
    background: #fffbe6; border: 1px solid #e6d68a; border-radius: 8px;
    padding: 0.75rem 1rem; margin-bottom: 1.25rem;
  }}
  .patterns-panel h2 {{ margin-top: 0; font-size: 1.05rem; }}
  .patterns-panel ul {{ margin: 0; padding-left: 1.2rem; }}
  .pattern-item {{ margin-bottom: 0.4rem; font-size: 0.9rem; }}
  .pattern-severity {{
    font-weight: 700; font-size: 0.75rem; padding: 0.05rem 0.4rem;
    border-radius: 4px; color: #fff;
  }}
  .pattern-low .pattern-severity {{ background: {_HTML_SEVERITY_COLORS["low"]}; }}
  .pattern-medium .pattern-severity {{ background: {_HTML_SEVERITY_COLORS["medium"]}; }}
  .pattern-high .pattern-severity {{ background: {_HTML_SEVERITY_COLORS["high"]}; }}
  .timeline {{ display: flex; flex-direction: column; }}
  .year-header {{
    font-size: 1.1rem; font-weight: 700; margin: 1rem 0 0.4rem; color: #555;
  }}
  .event-row {{
    display: flex; align-items: flex-start; gap: 0.75rem;
    background: #fff; border: 1px solid #e2e2e6; border-radius: 6px;
    padding: 0.5rem 0.75rem; margin-bottom: 0.4rem;
    border-left: 4px solid transparent;
  }}
  .event-row.band-low {{ background: rgba(241, 196, 15, 0.15); border-left-color: {_HTML_SEVERITY_COLORS["low"]}; }}
  .event-row.band-medium {{ background: rgba(230, 126, 34, 0.15); border-left-color: {_HTML_SEVERITY_COLORS["medium"]}; }}
  .event-row.band-high {{ background: rgba(231, 76, 60, 0.15); border-left-color: {_HTML_SEVERITY_COLORS["high"]}; }}
  .event-date {{ flex: 0 0 auto; font-variant-numeric: tabular-nums; color: #555; min-width: 6.5rem; }}
  .event-badge {{
    flex: 0 0 auto; color: #fff; font-size: 0.72rem; font-weight: 700;
    padding: 0.15rem 0.45rem; border-radius: 4px; white-space: nowrap;
  }}
  .event-body {{ flex: 1 1 auto; }}
  .event-name {{ font-weight: 600; }}
  .event-desc {{ color: #444; font-size: 0.9rem; }}
  .event-row[style*="display: none"] {{ display: none; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #1c1c1e; color: #f2f2f2; }}
    .controls, .event-row {{ background: #2c2c2e; border-color: #3a3a3c; }}
    .patterns-panel {{ background: #3a331a; border-color: #6b5d2b; }}
    .event-desc {{ color: #c7c7cc; }}
    .event-date {{ color: #aeaeb2; }}
  }}
</style>
</head>
<body>
<h1>Investigation Timeline</h1>
<div class="controls">
  <strong>Filter by schema:</strong><br>
  {''.join(filter_chunks)}
</div>
{patterns_html}
<div class="timeline" id="timeline">
{''.join(row_chunks)}
</div>
<script>
(function () {{
  var checkboxes = document.querySelectorAll('.schema-filter');
  var rows = document.querySelectorAll('.event-row');

  function applyFilter() {{
    var active = {{}};
    checkboxes.forEach(function (cb) {{
      if (cb.checked) {{ active[cb.value] = true; }}
    }});
    rows.forEach(function (row) {{
      var schema = row.getAttribute('data-schema');
      row.style.display = active[schema] ? '' : 'none';
    }});
  }}

  checkboxes.forEach(function (cb) {{
    cb.addEventListener('change', applyFilter);
  }});

  applyFilter();
}})();
</script>
</body>
</html>"""

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
    def _empty_timeline_html() -> str:
        """Minimal valid HTML page for the empty-events case."""
        return (
            "<!DOCTYPE html>\n"
            '<html lang="en"><head><meta charset="utf-8">'
            "<title>Investigation Timeline</title></head>"
            "<body><p>No dated events found.</p></body></html>"
        )

    @staticmethod
    def _event_in_pattern_range(event: TimelineEvent, pattern: TemporalPattern) -> bool:
        """Check whether an event's date falls within a pattern's date range."""
        if not pattern.events:
            return False
        start, end = pattern.events[0], pattern.events[-1]
        if event.date_parsed is not None and start.date_parsed is not None and end.date_parsed is not None:
            return start.date_parsed <= event.date_parsed <= end.date_parsed
        return start.date <= event.date <= end.date

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
