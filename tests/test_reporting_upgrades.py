"""Tests for evidence chain, confidence scoring, and other reporting upgrades."""

from __future__ import annotations

from emet.export.evidence import Claim, EvidenceChain, SourceRef, score_confidence
from emet.export.timeline import TimelineAnalyzer


def _entity(eid, schema, **props):
    return {
        "id": eid,
        "schema": schema,
        "properties": {k: [v] if isinstance(v, str) else v for k, v in props.items()},
    }


class TestSourceRef:
    def test_defaults(self) -> None:
        src = SourceRef(source="opensanctions")
        assert src.source == "opensanctions"
        assert src.source_id == ""
        assert src.source_url == ""
        assert src.confidence == 1.0
        assert src.retrieved_at == ""

    def test_from_provenance_full(self) -> None:
        provenance = {
            "source": "gleif",
            "source_id": "5493001KJTIIGC8Y1R12",
            "source_url": "https://search.gleif.org/#/record/5493001KJTIIGC8Y1R12",
            "confidence": 0.98,
            "retrieved_at": "2026-07-04T00:00:00+00:00",
        }
        src = SourceRef.from_provenance(provenance)
        assert src.source == "gleif"
        assert src.source_id == "5493001KJTIIGC8Y1R12"
        assert src.source_url == provenance["source_url"]
        assert src.confidence == 0.98
        assert src.retrieved_at == provenance["retrieved_at"]

    def test_from_provenance_missing_confidence_defaults_to_half(self) -> None:
        provenance = {"source": "unknown_source"}
        src = SourceRef.from_provenance(provenance)
        assert src.source == "unknown_source"
        assert src.confidence == 0.5

    def test_from_provenance_explicit_zero_confidence_is_honored(self) -> None:
        provenance = {"source": "sketchy_source", "confidence": 0.0}
        src = SourceRef.from_provenance(provenance)
        assert src.confidence == 0.0

    def test_from_provenance_ignores_extra_keys(self) -> None:
        provenance = {
            "source": "opensanctions",
            "confidence": 0.9,
            "match_score": 0.77,
            "datasets": ["sanctions_eu"],
        }
        src = SourceRef.from_provenance(provenance)
        assert src.source == "opensanctions"
        assert src.confidence == 0.9


class TestScoreConfidence:
    def test_no_sources_is_zero(self) -> None:
        claim = Claim(statement="Unsupported assertion.")
        assert score_confidence(claim) == 0.0

    def test_single_source_equals_its_confidence_exactly(self) -> None:
        claim = Claim(
            statement="Acme Holdings was incorporated in Delaware.",
            sources=[SourceRef(source="opencorporates", confidence=0.83)],
        )
        assert score_confidence(claim) == 0.83

    def test_two_distinct_sources_score_higher_than_either_alone_capped_at_one(self) -> None:
        claim = Claim(
            statement="Acme Holdings shares an address with Beta Ltd.",
            sources=[
                SourceRef(source="opencorporates", confidence=0.8),
                SourceRef(source="gleif", confidence=0.7),
            ],
        )
        score = score_confidence(claim)
        assert score > 0.8
        assert score > 0.7
        assert score <= 1.0

    def test_two_high_confidence_distinct_sources_capped_at_one(self) -> None:
        claim = Claim(
            statement="Fully corroborated fact.",
            sources=[
                SourceRef(source="gleif", confidence=1.0),
                SourceRef(source="sec_edgar", confidence=1.0),
            ],
        )
        assert score_confidence(claim) == 1.0

    def test_contradiction_lowers_score(self) -> None:
        sources = [SourceRef(source="opencorporates", confidence=0.9)]
        claim_uncontested = Claim(statement="Claim A.", sources=list(sources))
        claim_contested = Claim(
            statement="Claim A.",
            sources=list(sources),
            contradicted_by=[SourceRef(source="icij_offshore_leaks", confidence=0.6)],
        )
        assert score_confidence(claim_contested) < score_confidence(claim_uncontested)

    def test_stronger_contradiction_hurts_more(self) -> None:
        base_sources = [SourceRef(source="opencorporates", confidence=0.9)]
        weak_contradiction = Claim(
            statement="Claim.",
            sources=list(base_sources),
            contradicted_by=[SourceRef(source="rumor_mill", confidence=0.1)],
        )
        strong_contradiction = Claim(
            statement="Claim.",
            sources=list(base_sources),
            contradicted_by=[SourceRef(source="sec_edgar", confidence=0.95)],
        )
        assert score_confidence(strong_contradiction) < score_confidence(weak_contradiction)

    def test_same_source_twice_does_not_corroborate(self) -> None:
        same_source_twice = Claim(
            statement="Claim repeated by one source.",
            sources=[
                SourceRef(source="opencorporates", confidence=0.75),
                SourceRef(source="opencorporates", confidence=0.75),
            ],
        )
        two_distinct_sources = Claim(
            statement="Claim corroborated by two sources.",
            sources=[
                SourceRef(source="opencorporates", confidence=0.75),
                SourceRef(source="gleif", confidence=0.75),
            ],
        )
        same_source_score = score_confidence(same_source_twice)
        distinct_source_score = score_confidence(two_distinct_sources)

        # Repeating the same source should score exactly like a single source.
        assert same_source_score == 0.75
        # Two genuinely distinct sources should corroborate and score higher.
        assert distinct_source_score > same_source_score

    def test_result_never_exceeds_one_or_drops_below_zero(self) -> None:
        claim = Claim(
            statement="Heavily contradicted but well-sourced claim.",
            sources=[
                SourceRef(source="a", confidence=1.0),
                SourceRef(source="b", confidence=1.0),
                SourceRef(source="c", confidence=1.0),
            ],
            contradicted_by=[
                SourceRef(source="x", confidence=1.0),
                SourceRef(source="y", confidence=1.0),
                SourceRef(source="z", confidence=1.0),
            ],
        )
        score = score_confidence(claim)
        assert 0.0 <= score <= 1.0

    def test_deterministic(self) -> None:
        claim = Claim(
            statement="Deterministic claim.",
            sources=[
                SourceRef(source="opencorporates", confidence=0.8),
                SourceRef(source="gleif", confidence=0.6),
            ],
            contradicted_by=[SourceRef(source="icij_offshore_leaks", confidence=0.4)],
        )
        first = score_confidence(claim)
        second = score_confidence(claim)
        assert first == second


class TestEvidenceChain:
    def test_add_claim_assigns_sequential_ids(self) -> None:
        chain = EvidenceChain()
        c1 = chain.add_claim(
            "First claim.", sources=[SourceRef(source="opencorporates", confidence=0.9)]
        )
        c2 = chain.add_claim(
            "Second claim.", sources=[SourceRef(source="gleif", confidence=0.9)]
        )
        c3 = chain.add_claim("Third claim, unsupported.", sources=[])

        assert c1.id == "c1"
        assert c2.id == "c2"
        assert c3.id == "c3"
        assert [c.id for c in chain.claims] == ["c1", "c2", "c3"]

    def test_add_claim_computes_confidence(self) -> None:
        chain = EvidenceChain()
        claim = chain.add_claim(
            "Well-supported claim.",
            sources=[SourceRef(source="gleif", confidence=0.95)],
        )
        assert claim.confidence == 0.95

    def test_unsupported_claims_finds_zero_source_and_low_confidence(self) -> None:
        chain = EvidenceChain()
        well_supported = chain.add_claim(
            "Well-supported claim.",
            sources=[
                SourceRef(source="gleif", confidence=0.95),
                SourceRef(source="sec_edgar", confidence=0.9),
            ],
        )
        zero_source = chain.add_claim("No evidence at all.", sources=[])
        low_confidence = chain.add_claim(
            "Weakly supported claim.",
            sources=[SourceRef(source="anonymous_tip", confidence=0.15)],
        )

        unsupported = chain.unsupported_claims()
        unsupported_ids = {c.id for c in unsupported}

        assert zero_source.id in unsupported_ids
        assert low_confidence.id in unsupported_ids
        assert well_supported.id not in unsupported_ids

    def test_unsupported_claims_respects_custom_threshold(self) -> None:
        chain = EvidenceChain()
        mid_confidence = chain.add_claim(
            "Medium-confidence claim.",
            sources=[SourceRef(source="opencorporates", confidence=0.5)],
        )
        unsupported_default = chain.unsupported_claims()
        unsupported_strict = chain.unsupported_claims(threshold=0.6)

        assert mid_confidence.id not in {c.id for c in unsupported_default}
        assert mid_confidence.id in {c.id for c in unsupported_strict}

    def test_to_markdown_contains_footnote_markers_and_unsupported_section(self) -> None:
        chain = EvidenceChain()
        chain.add_claim(
            "Acme Holdings filed a corporate registry filing.",
            sources=[SourceRef(source="opencorporates", confidence=0.9)],
        )
        chain.add_claim("Unverified rumor about the CEO.", sources=[])

        markdown = chain.to_markdown()

        assert "[^c1]" in markdown
        assert "[^c2]" in markdown
        assert "opencorporates" in markdown
        assert "Unsupported" in markdown or "unsupported" in markdown

    def test_to_markdown_omits_unsupported_section_when_all_well_supported(self) -> None:
        chain = EvidenceChain()
        chain.add_claim(
            "Well-supported claim.",
            sources=[
                SourceRef(source="gleif", confidence=0.95),
                SourceRef(source="sec_edgar", confidence=0.9),
            ],
        )

        markdown = chain.to_markdown()

        assert "unsupported" not in markdown.lower()

    def test_to_markdown_handles_empty_chain(self) -> None:
        chain = EvidenceChain()
        markdown = chain.to_markdown()
        assert "No claims recorded" in markdown

    def test_to_jsonld_structure(self) -> None:
        chain = EvidenceChain()
        chain.add_claim(
            "Acme Holdings was incorporated in Delaware.",
            sources=[
                SourceRef(
                    source="opencorporates",
                    source_id="us_de/12345",
                    source_url="https://opencorporates.com/companies/us_de/12345",
                    confidence=0.9,
                )
            ],
        )

        jsonld = chain.to_jsonld()

        assert jsonld["@context"] == "https://schema.org"
        assert len(jsonld["@graph"]) == 1
        node = jsonld["@graph"][0]
        assert node["@type"] == "Claim"
        assert node["identifier"] == "c1"
        assert len(node["citation"]) == 1
        assert node["citation"][0]["name"] == "opencorporates"

    def test_to_jsonld_marks_disputed_claims(self) -> None:
        chain = EvidenceChain()
        chain.add_claim(
            "Disputed claim.",
            sources=[SourceRef(source="opencorporates", confidence=0.8)],
            contradicted_by=[SourceRef(source="icij_offshore_leaks", confidence=0.5)],
        )

        jsonld = chain.to_jsonld()
        node = jsonld["@graph"][0]
        assert node.get("disputed") is True


class TestTimelineHTML:
    """Tests for TimelineAnalyzer.to_html — the offline interactive timeline."""

    def _burst_entities(self):
        """Entities spanning a mix of dates, with a burst of 3 close incorporations."""
        return [
            _entity("co-1", "Company", name="Alpha Corp", country="VG",
                    incorporationDate="2019-03-15"),
            _entity("co-2", "Company", name="Beta Ltd", country="CY",
                    incorporationDate="2019-03-17"),
            _entity("co-3", "Company", name="Gamma SA", country="CH",
                    incorporationDate="2019-03-18"),
            _entity("person-1", "Person", name="John Doe", country="US",
                    birthDate="1975-06-01"),
            _entity("doc-1", "Document", name="Contract Alpha-Beta",
                    authoredAt="2019-06-01"),
        ]

    def test_returns_full_html_document(self) -> None:
        analyzer = TimelineAnalyzer()
        out = analyzer.to_html(self._burst_entities())
        assert out.startswith("<!DOCTYPE html>")
        assert "<html" in out
        assert "</html>" in out

    def test_all_distinct_schemas_appear(self) -> None:
        analyzer = TimelineAnalyzer()
        entities = self._burst_entities()
        out = analyzer.to_html(entities)
        schemas = {e["schema"] for e in entities}
        for schema in schemas:
            assert schema in out

    def test_pattern_explanations_appear(self) -> None:
        analyzer = TimelineAnalyzer(burst_window_days=7, burst_threshold=3)
        entities = self._burst_entities()
        patterns = analyzer.detect_patterns(entities)
        assert patterns, "expected the fixture to trigger at least one pattern"

        out = analyzer.to_html(entities)
        for pattern in patterns:
            assert pattern.explanation in out

    def test_empty_events_returns_graceful_html(self) -> None:
        analyzer = TimelineAnalyzer()

        # No entities at all.
        out = analyzer.to_html([])
        assert out.startswith("<!DOCTYPE html>")
        assert "No dated events found" in out

        # Entities with no dated properties also produce zero events.
        out2 = analyzer.to_html([_entity("p-1", "Person", name="No Dates")])
        assert out2.startswith("<!DOCTYPE html>")
        assert "No dated events found" in out2

    def test_fully_offline_no_external_resources(self) -> None:
        analyzer = TimelineAnalyzer()
        out = analyzer.to_html(self._burst_entities())

        assert 'src="http' not in out
        assert 'href="http' not in out
        assert "//cdn" not in out
        assert "<script src=" not in out
        assert "<link href=" not in out

    def test_schema_filter_controls_present(self) -> None:
        analyzer = TimelineAnalyzer()
        out = analyzer.to_html(self._burst_entities())
        assert "schema-filter" in out
        assert 'type="checkbox"' in out
