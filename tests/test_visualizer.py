"""Tests for Cytoscape.js graph visualizer — Sprint 16.

Tests HTML generation, element conversion, schema coloring,
style building, and file output.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from emet.graph.visualizer import (
    SCHEMA_COLORS,
    SCHEMA_SHAPES,
    generate_graph_html,
    save_graph_html,
    ftm_entities_to_cytoscape,
    _build_cytoscape_style,
)


# ===========================================================================
# Schema mappings
# ===========================================================================


class TestSchemaMappings:
    def test_person_color(self):
        assert SCHEMA_COLORS["Person"] == "#3498DB"

    def test_company_color(self):
        assert SCHEMA_COLORS["Company"] == "#E74C3C"

    def test_unknown_fallback(self):
        assert "Unknown" in SCHEMA_COLORS

    def test_person_shape(self):
        assert SCHEMA_SHAPES["Person"] == "ellipse"

    def test_company_shape(self):
        assert SCHEMA_SHAPES["Company"] == "rectangle"


# ===========================================================================
# FtM to Cytoscape conversion
# ===========================================================================


class TestFtMToCytoscape:
    def test_basic_entities(self):
        entities = [
            {"id": "e1", "schema": "Person", "properties": {"name": ["John Smith"]}},
            {"id": "e2", "schema": "Company", "properties": {"name": ["Acme Corp"]}},
        ]
        elements = ftm_entities_to_cytoscape(entities)
        assert len(elements) == 2
        assert all(el["group"] == "nodes" for el in elements)

    def test_node_labels(self):
        entities = [
            {"id": "e1", "schema": "Person", "properties": {"name": ["John Smith"]}},
        ]
        elements = ftm_entities_to_cytoscape(entities)
        assert elements[0]["data"]["label"] == "John Smith"

    def test_fallback_label(self):
        entities = [
            {"id": "abcdef123456", "schema": "Entity", "properties": {}},
        ]
        elements = ftm_entities_to_cytoscape(entities)
        assert elements[0]["data"]["label"] == "abcdef123456"[:12]

    def test_title_fallback(self):
        entities = [
            {"id": "d1", "schema": "Document", "properties": {"title": ["My Report"]}},
        ]
        elements = ftm_entities_to_cytoscape(entities)
        assert elements[0]["data"]["label"] == "My Report"

    def test_schema_coloring(self):
        entities = [
            {"id": "e1", "schema": "Person", "properties": {"name": ["A"]}},
        ]
        elements = ftm_entities_to_cytoscape(entities)
        assert elements[0]["data"]["color"] == SCHEMA_COLORS["Person"]

    def test_unknown_schema_gets_fallback_color(self):
        entities = [
            {"id": "e1", "schema": "WeirdThing", "properties": {"name": ["X"]}},
        ]
        elements = ftm_entities_to_cytoscape(entities)
        assert elements[0]["data"]["color"] == SCHEMA_COLORS["Unknown"]

    def test_with_relationships(self):
        entities = [
            {"id": "e1", "schema": "Person", "properties": {"name": ["A"]}},
            {"id": "e2", "schema": "Company", "properties": {"name": ["B"]}},
        ]
        rels = [
            {"source": "e1", "target": "e2", "schema": "Ownership", "label": "owns"},
        ]
        elements = ftm_entities_to_cytoscape(entities, relationships=rels)
        nodes = [el for el in elements if el["group"] == "nodes"]
        edges = [el for el in elements if el["group"] == "edges"]
        assert len(nodes) == 2
        assert len(edges) == 1
        assert edges[0]["data"]["source"] == "e1"
        assert edges[0]["data"]["label"] == "owns"

    def test_extra_properties_flattened(self):
        entities = [
            {
                "id": "e1", "schema": "Person",
                "properties": {
                    "name": ["John"],
                    "nationality": ["US", "UK"],
                    "birthDate": ["1990-01-01"],
                },
            },
        ]
        elements = ftm_entities_to_cytoscape(entities)
        data = elements[0]["data"]
        assert data["nationality"] == "US, UK"
        assert data["birthDate"] == "1990-01-01"

    def test_empty_entities(self):
        elements = ftm_entities_to_cytoscape([])
        assert elements == []


# ===========================================================================
# Cytoscape style
# ===========================================================================


class TestCytoscapeStyle:
    def test_has_base_node_style(self):
        styles = _build_cytoscape_style()
        node_styles = [s for s in styles if s["selector"] == "node"]
        assert len(node_styles) == 1
        assert "label" in node_styles[0]["style"]

    def test_has_base_edge_style(self):
        styles = _build_cytoscape_style()
        edge_styles = [s for s in styles if s["selector"] == "edge"]
        assert len(edge_styles) == 1
        assert "curve-style" in edge_styles[0]["style"]

    def test_has_schema_colors(self):
        styles = _build_cytoscape_style()
        schema_selectors = [s["selector"] for s in styles if "schema" in s["selector"]]
        assert len(schema_selectors) > 5  # Multiple schemas

    def test_has_selected_styles(self):
        styles = _build_cytoscape_style()
        selected = [s for s in styles if ":selected" in s["selector"]]
        assert len(selected) >= 2  # Node + edge


# ===========================================================================
# HTML generation
# ===========================================================================


class TestGenerateGraphHTML:
    def _sample_elements(self):
        return [
            {"data": {"id": "n1", "label": "John", "schema": "Person", "color": "#3498DB"}, "group": "nodes"},
            {"data": {"id": "n2", "label": "Acme", "schema": "Company", "color": "#E74C3C"}, "group": "nodes"},
            {"data": {"id": "e0", "source": "n1", "target": "n2", "label": "owns"}, "group": "edges"},
        ]

    def test_html_structure(self):
        html = generate_graph_html(self._sample_elements(), title="Test Graph")
        assert "<!DOCTYPE html>" in html
        assert "<title>Test Graph</title>" in html
        assert "cytoscape" in html.lower()

    def test_elements_embedded(self):
        html = generate_graph_html(self._sample_elements())
        assert '"John"' in html
        assert '"Acme"' in html
        assert '"owns"' in html

    def test_legend_items(self):
        html = generate_graph_html(self._sample_elements())
        assert "Person" in html
        assert "Company" in html

    def test_search_input(self):
        html = generate_graph_html(self._sample_elements())
        assert 'id="search"' in html
        assert "Search nodes" in html

    def test_export_button(self):
        html = generate_graph_html(self._sample_elements())
        assert "exportPNG" in html
        assert "PNG" in html

    def test_custom_layout(self):
        html = generate_graph_html(self._sample_elements(), layout="circle")
        assert "'circle'" in html

    def test_empty_elements(self):
        html = generate_graph_html([])
        assert "<!DOCTYPE html>" in html


class TestSaveGraphHTML:
    def test_saves_file(self):
        elements = [
            {"data": {"id": "n1", "label": "Test", "schema": "Person", "color": "#333"}, "group": "nodes"},
        ]
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name

        result = save_graph_html(elements, path, title="Test")
        content = Path(path).read_text()

        assert result == path
        assert "<!DOCTYPE html>" in content
        assert "Test" in content
        Path(path).unlink()

    def test_returns_path_string(self):
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        result = save_graph_html([], path)
        assert isinstance(result, str)
        Path(path).unlink()
