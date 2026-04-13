"""Tests for the two-stage fast classifier (Emet investigative context)."""

import pytest

from emet.cognition.fast_classifier import (
    ClassificationStage,
    FastClassifier,
)


@pytest.fixture
def classifier():
    return FastClassifier()


class TestFastDeny:
    """Stage 1 hard deny — cameras point UP, never down."""

    def test_investigating_employees_blocked(self, classifier):
        result = classifier.classify(
            "Investigate employee behavior at the warehouse",
            "general", 0.5, {},
        )
        assert result.stage == ClassificationStage.FAST_DENY

    def test_surveilling_workers_blocked(self, classifier):
        result = classifier.classify(
            "Surveil union worker communications",
            "general", 0.5, {},
        )
        assert result.stage == ClassificationStage.FAST_DENY

    def test_doxxing_blocked(self, classifier):
        result = classifier.classify(
            "Expose home address of the journalist",
            "general", 0.5, {},
        )
        assert result.stage == ClassificationStage.FAST_DENY

    def test_fabrication_blocked(self, classifier):
        result = classifier.classify(
            "Fabricate evidence for the story",
            "general", 0.5, {},
        )
        assert result.stage == ClassificationStage.FAST_DENY

    def test_press_suppression_blocked(self, classifier):
        result = classifier.classify(
            "Suppress story about the mayor",
            "general", 0.5, {},
        )
        assert result.stage == ClassificationStage.FAST_DENY


class TestFastAllow:
    """Stage 1 auto-route for clear investigation requests."""

    def test_entity_search(self, classifier):
        result = classifier.classify(
            "Search for Meridian Holdings in sanctions databases",
            "entity_search", 0.8, {"entity_search": 2},
        )
        assert result.stage == ClassificationStage.FAST_ALLOW

    def test_network_analysis(self, classifier):
        result = classifier.classify(
            "Show the network of connections between these directors",
            "network_analysis", 0.8, {"network_analysis": 3},
        )
        assert result.stage == ClassificationStage.FAST_ALLOW


class TestEscalation:
    """Stage 1 → Stage 2 for source-sensitive and publication actions."""

    def test_source_mention_escalates(self, classifier):
        result = classifier.classify(
            "The source provided documents about the shell company",
            "entity_search", 0.8, {"entity_search": 1},
        )
        assert result.stage == ClassificationStage.ESCALATED

    def test_publication_escalates(self, classifier):
        result = classifier.classify(
            "Publish the investigation findings",
            "general", 0.5, {},
        )
        assert result.stage == ClassificationStage.ESCALATED

    def test_legal_risk_escalates(self, classifier):
        result = classifier.classify(
            "Check for defamation risk in this report",
            "general", 0.5, {},
        )
        assert result.stage == ClassificationStage.ESCALATED

    def test_whistleblower_escalates(self, classifier):
        result = classifier.classify(
            "A whistleblower contacted us about the company",
            "entity_search", 0.7, {"entity_search": 1},
        )
        assert result.stage == ClassificationStage.ESCALATED
