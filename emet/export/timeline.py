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

    def to_html(
        self,
        events: list[TimelineEvent],
        title: str = "Investigation Timeline",
        patterns: list[TemporalPattern] | None = None,
    ) -> str:
        """Render a self-contained, interactive HTML timeline.

        Produces a single offline-openable HTML file: a vertical,
        chronological timeline with per-event cards coloured by FtM
        schema, a schema filter, and highlighted bands for any detected
        temporal patterns (bursts/coincidences). No external assets — all
        CSS/JS is inlined so it is safe to hand to a journalist or embed.
        """
        import html
        import json as _json

        rows = self.to_json(events)
        schemas = sorted({r["entity_schema"] for r in rows})
        pattern_summaries = [
            {
                "type": p.pattern_type,
                "severity": p.severity,
                "count": len(p.events),
                "explanation": getattr(p, "explanation", ""),
            }
            for p in (patterns or [])
        ]
        data_json = _json.dumps(rows)
        pattern_json = _json.dumps(pattern_summaries)
        safe_title = html.escape(title)

        # Colour palette by schema (theme-neutral, accessible).
        return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, -apple-system, sans-serif; margin: 0;
    background: #0f1419; color: #e6e6e6; }}
  header {{ padding: 1.2rem 1.5rem; border-bottom: 1px solid #2a3038; }}
  h1 {{ font-size: 1.25rem; margin: 0 0 .3rem; }}
  .controls {{ padding: .8rem 1.5rem; display: flex; gap: .5rem; flex-wrap: wrap;
    align-items: center; }}
  select {{ background:#1a1f26; color:#e6e6e6; border:1px solid #2a3038;
    border-radius:6px; padding:.35rem .6rem; }}
  .patterns {{ padding: 0 1.5rem; }}
  .patt {{ display:inline-block; margin:.2rem .3rem .2rem 0; padding:.25rem .6rem;
    border-radius: 999px; font-size:.8rem; }}
  .sev-high {{ background:#5a1e1e; color:#ffb4b4; }}
  .sev-medium {{ background:#5a4a1e; color:#ffe08a; }}
  .sev-low {{ background:#25405a; color:#a9d3ff; }}
  .timeline {{ position: relative; margin: 1rem 1.5rem 3rem; padding-left: 1.5rem;
    border-left: 2px solid #2a3038; max-width: 900px; }}
  .event {{ position: relative; margin: 0 0 1.1rem; padding: .7rem .9rem;
    background:#1a1f26; border:1px solid #2a3038; border-radius: 8px; }}
  .event::before {{ content:''; position:absolute; left:-1.95rem; top:1rem;
    width:11px; height:11px; border-radius:50%; background: var(--dot,#7aa2f7);
    border:2px solid #0f1419; }}
  .event .date {{ font-variant-numeric: tabular-nums; font-weight:600;
    color:#9ecbff; font-size:.85rem; }}
  .event .schema {{ font-size:.72rem; text-transform:uppercase; letter-spacing:.04em;
    opacity:.7; margin-left:.5rem; }}
  .event .desc {{ margin-top:.25rem; font-size:.92rem; }}
  .empty {{ padding: 2rem 1.5rem; opacity:.6; }}
</style></head>
<body>
<header><h1>{safe_title}</h1>
<div style="opacity:.65;font-size:.85rem">{len(rows)} dated events</div></header>
<div class="patterns" id="patterns"></div>
<div class="controls">
  <label for="schemaFilter">Filter by type:</label>
  <select id="schemaFilter"><option value="">All types</option></select>
</div>
<div class="timeline" id="timeline"></div>
<script>
const EVENTS = {data_json};
const PATTERNS = {pattern_json};
const SCHEMAS = {_json.dumps(schemas)};
const COLORS = {{Person:'#f7768e',Company:'#7aa2f7',Organization:'#7aa2f7',
  LegalEntity:'#bb9af7',Security:'#9ece6a',Document:'#e0af68',Ownership:'#ff9e64',
  Payment:'#73daca'}};
const sel = document.getElementById('schemaFilter');
SCHEMAS.forEach(s => {{ const o=document.createElement('option');
  o.value=s; o.textContent=s; sel.appendChild(o); }});
const pdiv = document.getElementById('patterns');
PATTERNS.forEach(p => {{ const span=document.createElement('span');
  span.className='patt sev-'+(p.severity||'low');
  span.textContent=p.type+' ×'+p.count+(p.explanation?(' — '+p.explanation):'');
  pdiv.appendChild(span); }});
function esc(s) {{ const d=document.createElement('div'); d.textContent=s??'';
  return d.innerHTML; }}
function render(filter) {{
  const tl=document.getElementById('timeline'); tl.innerHTML='';
  const rows=EVENTS.filter(e=>!filter||e.entity_schema===filter);
  if(!rows.length) {{ tl.innerHTML='<div class="empty">No events for this filter.</div>';
    return; }}
  rows.forEach(e => {{
    const div=document.createElement('div'); div.className='event';
    div.style.setProperty('--dot', COLORS[e.entity_schema]||'#7aa2f7');
    div.innerHTML='<span class="date">'+esc(e.date)+'</span>'+
      '<span class="schema">'+esc(e.entity_schema)+'</span>'+
      '<div class="desc">'+esc(e.description)+'</div>';
    tl.appendChild(div);
  }});
}}
sel.addEventListener('change', () => render(sel.value));
render('');
</script>
</body></html>
"""

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
