"""Tests for the targeting policy (organizations & public figures only)."""

from __future__ import annotations

from emet.security.target_policy import (
    TargetClass,
    check_target,
    classify_target,
    filter_investigable,
)


class TestClassification:
    def test_company_is_organization(self):
        cls, _ = classify_target({"schema": "Company", "properties": {"name": ["Acme"]}})
        assert cls == TargetClass.ORGANIZATION

    def test_public_body_is_organization(self):
        cls, _ = classify_target({"schema": "PublicBody", "properties": {"name": ["EPA"]}})
        assert cls == TargetClass.ORGANIZATION

    def test_person_from_public_dataset_is_public_figure(self):
        cls, signals = classify_target(
            {
                "schema": "Person",
                "properties": {"name": ["Nancy Pelosi"]},
                "_provenance": {"source": "congress"},
            }
        )
        assert cls == TargetClass.PUBLIC_FIGURE
        assert any("congress" in s for s in signals)

    def test_person_with_public_role(self):
        cls, _ = classify_target(
            {"schema": "Person", "properties": {"name": ["J"], "position": ["CEO of Acme"]}}
        )
        assert cls == TargetClass.PUBLIC_FIGURE

    def test_bare_person_is_private(self):
        cls, _ = classify_target({"schema": "Person", "properties": {"name": ["Jane Public"]}})
        assert cls == TargetClass.PRIVATE_INDIVIDUAL


class TestCheck:
    def test_organization_allowed(self):
        assert check_target({"schema": "Company", "properties": {"name": ["X"]}}).allowed

    def test_private_individual_blocked(self):
        d = check_target({"schema": "Person", "properties": {"name": ["Jane"]}})
        assert not d.allowed
        assert d.requires_override

    def test_override_permits_with_flag(self):
        d = check_target(
            {"schema": "Person", "properties": {"name": ["Jane"]}},
            override_justification="named in leaked contract; editor approved",
        )
        assert d.allowed
        assert d.requires_override

    def test_filter_investigable_splits(self):
        entities = [
            {"schema": "Company", "properties": {"name": ["Acme"]}},
            {"schema": "Person", "properties": {"name": ["Jane Public"]}},
            {"schema": "Person", "properties": {"name": ["Sen X"]},
             "_provenance": {"source": "fec"}},
        ]
        allowed, blocked = filter_investigable(entities)
        assert len(allowed) == 2
        assert len(blocked) == 1
