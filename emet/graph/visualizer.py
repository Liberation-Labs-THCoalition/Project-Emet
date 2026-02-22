"""Interactive graph visualization using Cytoscape.js.

Generates standalone HTML files with embedded Cytoscape.js that
render investigation graphs with:
  - Force-directed layout (cose-bilkent)
  - Node coloring by FtM schema
  - Node sizing by PageRank/degree
  - Edge labeling by relationship type
  - Click-to-inspect entity details
  - Search/filter by name or schema
  - PNG export button

The HTML is fully self-contained (CDN dependencies) — open in any browser.

Reference:
  Cytoscape.js: https://js.cytoscape.org/ (MIT)
  cose-bilkent: https://github.com/cytoscape/cytoscape.js-cose-bilkent
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Schema → color mapping for FtM entity types
SCHEMA_COLORS = {
    "Person": "#3498DB",
    "Company": "#E74C3C",
    "Organization": "#E67E22",
    "LegalEntity": "#9B59B6",
    "PublicBody": "#1ABC9C",
    "Vessel": "#2C3E50",
    "RealEstate": "#27AE60",
    "CryptoWallet": "#F39C12",
    "Email": "#16A085",
    "Phone": "#8E44AD",
    "Address": "#2ECC71",
    "Document": "#34495E",
    "Mention": "#7F8C8D",
    "Sanction": "#C0392B",
    "Note": "#95A5A6",
    "Unknown": "#BDC3C7",
}

# Schema → shape mapping
SCHEMA_SHAPES = {
    "Person": "ellipse",
    "Company": "rectangle",
    "Organization": "diamond",
    "LegalEntity": "hexagon",
    "PublicBody": "pentagon",
    "Vessel": "triangle",
    "Document": "barrel",
    "Sanction": "star",
}


def generate_graph_html(
    cytoscape_elements: list[dict[str, Any]],
    title: str = "Investigation Graph",
    layout: str = "cose-bilkent",
    width: str = "100%",
    height: str = "100vh",
) -> str:
    """Generate a standalone HTML page with interactive graph.

    Args:
        cytoscape_elements: Cytoscape.js elements array (nodes + edges)
        title: Page title
        layout: Layout algorithm (cose-bilkent, cose, dagre, circle, grid)
        width: CSS width
        height: CSS height

    Returns:
        Complete HTML string
    """
    elements_json = json.dumps(cytoscape_elements, indent=2)

    # Build schema legend from actual data
    schemas_in_data = set()
    for el in cytoscape_elements:
        if el.get("group") == "nodes":
            schemas_in_data.add(el.get("data", {}).get("schema", "Unknown"))

    legend_items = ""
    for schema in sorted(schemas_in_data):
        color = SCHEMA_COLORS.get(schema, SCHEMA_COLORS["Unknown"])
        legend_items += f'<span class="legend-item"><span class="legend-dot" style="background:{color}"></span>{schema}</span>\n'

    # Build style rules
    style_rules = _build_cytoscape_style()

    return _HTML_TEMPLATE.format(
        title=title,
        elements_json=elements_json,
        layout=layout,
        width=width,
        height=height,
        legend_items=legend_items,
        style_rules=json.dumps(style_rules),
    )


def save_graph_html(
    cytoscape_elements: list[dict[str, Any]],
    path: str | Path,
    title: str = "Investigation Graph",
    **kwargs: Any,
) -> str:
    """Generate and save the graph viewer to an HTML file."""
    html = generate_graph_html(cytoscape_elements, title=title, **kwargs)
    path = Path(path)
    path.write_text(html)
    logger.info("Saved interactive graph to %s (%d elements)", path, len(cytoscape_elements))
    return str(path)


def ftm_entities_to_cytoscape(
    entities: list[dict[str, Any]],
    relationships: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Convert FtM entities and relationships to Cytoscape.js elements.

    Standalone converter for cases where GraphEngine isn't used.
    """
    elements: list[dict[str, Any]] = []

    for entity in entities:
        entity_id = entity.get("id", "")
        schema = entity.get("schema", "Unknown")
        props = entity.get("properties", {})
        names = props.get("name", props.get("title", []))
        label = names[0] if names else entity_id[:12]

        elements.append({
            "data": {
                "id": entity_id,
                "label": label,
                "schema": schema,
                "color": SCHEMA_COLORS.get(schema, SCHEMA_COLORS["Unknown"]),
                **{k: ", ".join(str(x) for x in v) for k, v in props.items() if v and k not in ("name", "title")},
            },
            "group": "nodes",
        })

    if relationships:
        for i, rel in enumerate(relationships):
            elements.append({
                "data": {
                    "id": f"e{i}",
                    "source": rel.get("source", ""),
                    "target": rel.get("target", ""),
                    "label": rel.get("label", rel.get("schema", "")),
                    "schema": rel.get("schema", ""),
                },
                "group": "edges",
            })

    return elements


def _build_cytoscape_style() -> list[dict[str, Any]]:
    """Build Cytoscape.js style array with schema-based coloring."""
    styles = [
        # Base node style
        {
            "selector": "node",
            "style": {
                "label": "data(label)",
                "text-valign": "bottom",
                "text-halign": "center",
                "font-size": "11px",
                "font-family": "Inter, system-ui, sans-serif",
                "color": "#333",
                "text-outline-width": 2,
                "text-outline-color": "#fff",
                "background-color": "data(color)",
                "width": 35,
                "height": 35,
                "border-width": 2,
                "border-color": "#fff",
                "overlay-opacity": 0,
            },
        },
        # Selected node
        {
            "selector": "node:selected",
            "style": {
                "border-width": 4,
                "border-color": "#2980B9",
                "font-weight": "bold",
            },
        },
        # Base edge style
        {
            "selector": "edge",
            "style": {
                "label": "data(label)",
                "font-size": "9px",
                "color": "#666",
                "text-rotation": "autorotate",
                "text-outline-width": 1,
                "text-outline-color": "#fff",
                "line-color": "#BDC3C7",
                "target-arrow-color": "#BDC3C7",
                "target-arrow-shape": "triangle",
                "curve-style": "bezier",
                "width": 1.5,
                "arrow-scale": 0.8,
                "overlay-opacity": 0,
            },
        },
        # Selected edge
        {
            "selector": "edge:selected",
            "style": {
                "line-color": "#2980B9",
                "target-arrow-color": "#2980B9",
                "width": 3,
            },
        },
    ]

    # Schema-specific node colors
    for schema, color in SCHEMA_COLORS.items():
        styles.append({
            "selector": f'node[schema = "{schema}"]',
            "style": {
                "background-color": color,
            },
        })

    # Schema-specific node shapes
    for schema, shape in SCHEMA_SHAPES.items():
        styles.append({
            "selector": f'node[schema = "{schema}"]',
            "style": {
                "shape": shape,
            },
        })

    return styles


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.28.1/cytoscape.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape-cose-bilkent/4.1.0/cytoscape-cose-bilkent.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: Inter, system-ui, sans-serif; background: #f8f9fa; }}
  #header {{
    background: #1a1a2e; color: #fff; padding: 12px 24px;
    display: flex; align-items: center; justify-content: space-between;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
  }}
  #header h1 {{ font-size: 16px; font-weight: 600; }}
  #controls {{ display: flex; gap: 8px; align-items: center; }}
  #controls input {{
    padding: 6px 12px; border: 1px solid #444; border-radius: 4px;
    background: #16213e; color: #fff; font-size: 13px; width: 200px;
  }}
  #controls input::placeholder {{ color: #888; }}
  #controls button {{
    padding: 6px 14px; border: none; border-radius: 4px;
    background: #2980B9; color: #fff; font-size: 13px; cursor: pointer;
  }}
  #controls button:hover {{ background: #3498DB; }}
  #cy {{ width: {width}; height: calc({height} - 90px); }}
  #legend {{
    background: #fff; padding: 8px 16px; display: flex; gap: 16px;
    flex-wrap: wrap; border-top: 1px solid #dee2e6; font-size: 12px;
  }}
  .legend-item {{ display: flex; align-items: center; gap: 4px; }}
  .legend-dot {{ width: 12px; height: 12px; border-radius: 50%; }}
  #detail {{
    position: fixed; right: 16px; top: 60px; width: 280px;
    background: #fff; border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,0.12);
    padding: 16px; font-size: 13px; display: none; max-height: 80vh; overflow-y: auto;
  }}
  #detail h3 {{ font-size: 14px; margin-bottom: 8px; }}
  #detail .prop {{ margin: 4px 0; color: #555; }}
  #detail .prop strong {{ color: #333; }}
  #stats {{ font-size: 12px; color: #aaa; }}
</style>
</head>
<body>
<div id="header">
  <div>
    <h1>{title}</h1>
    <span id="stats"></span>
  </div>
  <div id="controls">
    <input type="text" id="search" placeholder="Search nodes...">
    <select id="schema-filter">
      <option value="">All types</option>
    </select>
    <button onclick="resetView()">Reset</button>
    <button onclick="exportPNG()">PNG</button>
  </div>
</div>
<div id="cy"></div>
<div id="legend">{legend_items}</div>
<div id="detail">
  <h3 id="detail-title"></h3>
  <div id="detail-props"></div>
</div>

<script>
const elements = {elements_json};
const styleRules = {style_rules};

const cy = cytoscape({{
  container: document.getElementById('cy'),
  elements: elements,
  style: styleRules,
  layout: {{
    name: '{layout}',
    animate: false,
    nodeDimensionsIncludeLabels: true,
    idealEdgeLength: 120,
    nodeRepulsion: 6000,
    gravity: 0.3,
  }},
  minZoom: 0.1,
  maxZoom: 5,
}});

// Stats
const nodeCount = cy.nodes().length;
const edgeCount = cy.edges().length;
document.getElementById('stats').textContent =
  nodeCount + ' nodes, ' + edgeCount + ' edges';

// Populate schema filter
const schemas = new Set();
cy.nodes().forEach(n => schemas.add(n.data('schema')));
const select = document.getElementById('schema-filter');
[...schemas].sort().forEach(s => {{
  const opt = document.createElement('option');
  opt.value = s; opt.textContent = s;
  select.appendChild(opt);
}});

// Search
document.getElementById('search').addEventListener('input', function(e) {{
  const q = e.target.value.toLowerCase();
  if (!q) {{ cy.nodes().style('opacity', 1); cy.edges().style('opacity', 1); return; }}
  cy.nodes().forEach(n => {{
    const match = n.data('label').toLowerCase().includes(q);
    n.style('opacity', match ? 1 : 0.15);
  }});
  cy.edges().style('opacity', 0.15);
}});

// Schema filter
document.getElementById('schema-filter').addEventListener('change', function(e) {{
  const s = e.target.value;
  if (!s) {{ cy.nodes().style('opacity', 1); cy.edges().style('opacity', 1); return; }}
  cy.nodes().forEach(n => {{
    n.style('opacity', n.data('schema') === s ? 1 : 0.15);
  }});
  cy.edges().style('opacity', 0.15);
}});

// Click detail
cy.on('tap', 'node', function(e) {{
  const d = e.target.data();
  document.getElementById('detail-title').textContent = d.label || d.id;
  let html = '<div class="prop"><strong>Type:</strong> ' + (d.schema || 'Unknown') + '</div>';
  for (const [k, v] of Object.entries(d)) {{
    if (['id','label','schema','color'].includes(k)) continue;
    html += '<div class="prop"><strong>' + k + ':</strong> ' + v + '</div>';
  }}
  document.getElementById('detail-props').innerHTML = html;
  document.getElementById('detail').style.display = 'block';
}});

cy.on('tap', function(e) {{
  if (e.target === cy) document.getElementById('detail').style.display = 'none';
}});

function resetView() {{
  cy.nodes().style('opacity', 1);
  cy.edges().style('opacity', 1);
  cy.fit(undefined, 50);
  document.getElementById('search').value = '';
  document.getElementById('schema-filter').value = '';
  document.getElementById('detail').style.display = 'none';
}}

function exportPNG() {{
  const png = cy.png({{ bg: '#f8f9fa', scale: 2, full: true }});
  const a = document.createElement('a');
  a.href = png; a.download = 'investigation-graph.png';
  a.click();
}}
</script>
</body>
</html>"""
