"""Tests for JSON-LD export, evidence chain, confidence, timeline HTML."""

from __future__ import annotations

from emet.export.evidence import (
    Claim,
    EvidenceChain,
    SourceRef,
    confidence_label,
    score_confidence,
)
from emet.export.timeline import TimelineAnalyzer
from emet.graph.exporters import GraphExporter
from emet.graph.ftm_loader import FtMGraphLoader


def _graph():
    ents = [
        {"id": "p:a", "schema": "Person", "properties": {"name": ["Alice"]}},
        {"id": "c:b", "schema": "Company", "properties": {"name": ["BCo"]}},
        {
            "id": "o",
            "schema": "Ownership",
            "properties": {"owner": ["p:a"], "asset": ["c:b"], "percentage": ["60%"]},
        },
    ]
    g, _ = FtMGraphLoader().load(ents)
    return g


class TestJSONLD:
    def test_context_and_types(self):
        doc = GraphExporter(_graph()).to_jsonld("inv1")
        assert doc["@context"]["schema"] == "https://schema.org/"
        assert doc["@id"] == "emet:investigation:inv1"
        types = {n["@type"] for n in doc["@graph"]}
        assert "schema:Person" in types
        assert "schema:Organization" in types
        assert "ftm:ownershipOf" in types

    def test_relationship_endpoints(self):
        doc = GraphExporter(_graph()).to_jsonld()
        rels = [n for n in doc["@graph"] if n["@type"] == "ftm:ownershipOf"]
        assert rels
        assert rels[0]["source"]["@id"] == "emet:p:a"
        assert rels[0]["target"]["@id"] == "emet:c:b"


class TestConfidence:
    def test_single_source(self):
        assert score_confidence([SourceRef("a", confidence=0.8)]) == 0.8

    def test_corroboration_raises(self):
        sources = [SourceRef("a", confidence=0.8), SourceRef("b", confidence=0.8)]
        assert score_confidence(sources) == 0.9  # 0.8 + half the gap

    def test_same_source_no_double_count(self):
        sources = [SourceRef("a", confidence=0.8), SourceRef("a", confidence=0.8)]
        assert score_confidence(sources) == 0.8

    def test_contradiction_lowers(self):
        sources = [SourceRef("a", confidence=0.8), SourceRef("b", confidence=0.6, supports=False)]
        assert score_confidence(sources) < 0.8

    def test_no_support_is_zero(self):
        assert score_confidence([SourceRef("a", confidence=0.9, supports=False)]) < 0.35

    def test_labels(self):
        assert confidence_label(0.9) == "high"
        assert confidence_label(0.7) == "moderate"
        assert confidence_label(0.4) == "low"
        assert confidence_label(0.1) == "unverified"


class TestEvidenceChain:
    def test_add_and_serialize(self):
        chain = EvidenceChain()
        chain.add_claim(
            "BCo is owned by Alice",
            sources=[SourceRef.from_provenance({"source": "gleif", "confidence": 0.9})],
        )
        d = chain.to_dict()
        assert d["claim_count"] == 1
        assert d["claims"][0]["citations"][0]["n"] == 1

    def test_unsupported_flagged(self):
        chain = EvidenceChain()
        chain.add_claim("rumor", sources=[])
        assert len(chain.unsupported_claims()) == 1

    def test_markdown_footnotes(self):
        chain = EvidenceChain()
        chain.add_claim("x", sources=[SourceRef("gleif", confidence=0.9, source_url="u")])
        md = chain.to_markdown()
        assert "[^1]" in md
        assert "gleif" in md

    def test_citation_numbers_sequential(self):
        chain = EvidenceChain()
        chain.add_claim("a", sources=[SourceRef("s1"), SourceRef("s2")])
        chain.add_claim("b", sources=[SourceRef("s3")])
        d = chain.to_dict()
        assert d["claims"][1]["citations"][0]["n"] == 3


class TestTimelineHTML:
    def test_self_contained_html(self):
        ents = [
            {
                "id": "c:b",
                "schema": "Company",
                "properties": {"name": ["BCo"], "incorporationDate": ["2021-03-01"]},
            }
        ]
        ta = TimelineAnalyzer()
        events = ta.extract_events(ents)
        html = ta.to_html(events, "TL")
        assert html.strip().startswith("<!doctype html>")
        assert "cytoscape" not in html.lower()  # no external CDN needed
        assert "2021-03-01" in html

    def test_empty_timeline_renders(self):
        html = TimelineAnalyzer().to_html([], "Empty")
        assert "<!doctype html>" in html
