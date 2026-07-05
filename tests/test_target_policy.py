"""Tests for emet.security.target_policy — the code enforcement of Emet's
"organizations and public figures only" rule (VALUES.json: public_interest).
"""

from __future__ import annotations

import pytest

from emet.security.target_policy import (
    ORGANIZATION_SCHEMAS,
    PUBLIC_ROLE_PROPERTIES,
    PUBLIC_ROLE_SOURCES,
    PublicInterestOverride,
    TargetDecision,
    TargetType,
    check_target,
    classify_target,
    filter_targets,
)


def _entity(schema: str, provenance: dict | None = None, properties: dict | None = None, entity_id: str = "e1") -> dict:
    return {
        "id": entity_id,
        "schema": schema,
        "properties": properties or {},
        "_provenance": provenance or {},
    }


# ---------------------------------------------------------------------------
# classify_target
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("schema", sorted(ORGANIZATION_SCHEMAS))
def test_organization_schemas_always_classify_organization(schema):
    # Even with no provenance at all, and even with provenance that would otherwise
    # look "private", org schemas are always ORGANIZATION.
    entity = _entity(schema, provenance={})
    assert classify_target(entity) == TargetType.ORGANIZATION

    entity_with_weird_provenance = _entity(schema, provenance={"source": "some_random_leak"})
    assert classify_target(entity_with_weird_provenance) == TargetType.ORGANIZATION


@pytest.mark.parametrize("source", sorted(PUBLIC_ROLE_SOURCES))
def test_person_with_public_role_source_is_public_figure(source):
    entity = _entity("Person", provenance={"source": source})
    assert classify_target(entity) == TargetType.PUBLIC_FIGURE


def test_person_with_nonempty_datasets_is_public_figure():
    entity = _entity(
        "Person",
        provenance={"source": "opencorporates", "datasets": ["us_ofac_sdn", "eu_fsf"]},
    )
    assert classify_target(entity) == TargetType.PUBLIC_FIGURE


def test_person_with_empty_datasets_is_not_public_figure_via_datasets():
    entity = _entity("Person", provenance={"source": "opencorporates", "datasets": []})
    assert classify_target(entity) == TargetType.UNKNOWN


@pytest.mark.parametrize("prop", sorted(PUBLIC_ROLE_PROPERTIES))
def test_person_with_public_role_property_is_public_figure(prop):
    entity = _entity("Person", provenance={}, properties={prop: ["Senator"]})
    assert classify_target(entity) == TargetType.PUBLIC_FIGURE


def test_bare_person_with_no_provenance_or_properties_is_unknown():
    entity = _entity("Person", provenance={}, properties={})
    assert classify_target(entity) == TargetType.UNKNOWN


def test_person_with_unrelated_source_and_no_role_properties_is_unknown():
    entity = _entity(
        "Person",
        provenance={"source": "aleph"},
        properties={"birthDate": ["1980-01-01"]},
    )
    assert classify_target(entity) == TargetType.UNKNOWN


def test_non_org_non_person_schema_is_unknown():
    entity = _entity("Address")
    assert classify_target(entity) == TargetType.UNKNOWN


def test_missing_schema_is_unknown():
    entity = {"id": "e1", "properties": {}, "_provenance": {}}
    assert classify_target(entity) == TargetType.UNKNOWN


def test_empty_schema_is_unknown():
    entity = _entity("")
    assert classify_target(entity) == TargetType.UNKNOWN


# ---------------------------------------------------------------------------
# check_target
# ---------------------------------------------------------------------------


def test_check_target_allows_organization_without_override():
    entity = _entity("Company")
    decision = check_target(entity)
    assert decision.allowed is True
    assert decision.target_type == TargetType.ORGANIZATION
    assert isinstance(decision, TargetDecision)


def test_check_target_allows_public_figure_without_override():
    entity = _entity("Person", provenance={"source": "sec_edgar"})
    decision = check_target(entity)
    assert decision.allowed is True
    assert decision.target_type == TargetType.PUBLIC_FIGURE


def test_check_target_denies_unknown_person_without_override():
    entity = _entity("Person")
    decision = check_target(entity)
    assert decision.allowed is False
    assert decision.target_type == TargetType.UNKNOWN


def test_check_target_allows_unknown_person_with_override_and_reason_is_auditable():
    entity = _entity("Person")
    override = PublicInterestOverride(
        reason="Named in whistleblower complaint re: municipal contract fraud",
        authorized_by="truthstrike",
    )
    decision = check_target(entity, override=override)
    assert decision.allowed is True
    assert decision.target_type == TargetType.UNKNOWN
    assert "Named in whistleblower complaint re: municipal contract fraud" in decision.reason
    assert "truthstrike" in decision.reason


def test_public_interest_override_fills_blank_timestamp():
    override = PublicInterestOverride(reason="r", authorized_by="a")
    assert override.timestamp != ""


def test_public_interest_override_preserves_supplied_timestamp():
    override = PublicInterestOverride(reason="r", authorized_by="a", timestamp="2026-01-01T00:00:00+00:00")
    assert override.timestamp == "2026-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# filter_targets
# ---------------------------------------------------------------------------


def test_filter_targets_splits_mixed_list_and_returns_all_decisions():
    org = _entity("Company", entity_id="org1")
    public_figure = _entity("Person", provenance={"source": "fec"}, entity_id="pf1")
    unknown_person = _entity("Person", entity_id="unk1")

    entities = [org, public_figure, unknown_person]
    allowed, decisions = filter_targets(entities)

    assert allowed == [org, public_figure]
    assert len(decisions) == 3
    assert {d.entity_id for d in decisions} == {"org1", "pf1", "unk1"}

    decisions_by_id = {d.entity_id: d for d in decisions}
    assert decisions_by_id["org1"].allowed is True
    assert decisions_by_id["pf1"].allowed is True
    assert decisions_by_id["unk1"].allowed is False


def test_filter_targets_with_override_allows_previously_denied_entity():
    unknown_person = _entity("Person", entity_id="unk1")
    override = PublicInterestOverride(reason="Elected official's undisclosed relative", authorized_by="editor-1")

    allowed, decisions = filter_targets([unknown_person], override=override)

    assert allowed == [unknown_person]
    assert decisions[0].allowed is True
    assert "editor-1" in decisions[0].reason
