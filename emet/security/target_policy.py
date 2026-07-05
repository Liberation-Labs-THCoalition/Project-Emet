"""Target policy — code enforcement of the "organizations and public figures only" rule.

Emet's governance documents (VALUES.json pillar `public_interest`, hard constraint
"NEVER investigate private individuals without clear public interest justification";
LICENSE Section 5) state that this system may only be pointed at organizations and
public figures, never private individuals. Until now that rule lived only in prose.
This module gives it a code path: classify an FtM-shaped entity's target type from
its schema and provenance, then gate access through `check_target` / `filter_targets`
so callers (API routes, pipelines) have a single place to enforce — and log — the
public-interest boundary.

This module makes decisions; it does not do I/O. Callers are responsible for writing
any resulting decision (especially overrides) to an audit trail.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class TargetType(str, Enum):
    """The kind of subject an entity represents, for public-interest gating."""

    ORGANIZATION = "organization"
    PUBLIC_FIGURE = "public_figure"
    PRIVATE_INDIVIDUAL = "private_individual"
    UNKNOWN = "unknown"


# Schemas that are always organizations (never require public-figure justification).
ORGANIZATION_SCHEMAS = {"Company", "LegalEntity", "Organization", "PublicBody"}

# Provenance sources whose mere presence signals a public role (appearing in a
# congressional disclosure, FEC filing, SEC filing, sanctions/PEP list, or court docket
# as a party is itself evidence of public exposure).
PUBLIC_ROLE_SOURCES = {
    "congress_stock_act",
    "fec",
    "sec_edgar",
    "opensanctions",
    "courtlistener",
}

# FtM property names on a Person entity that, if present and non-empty, indicate a
# public role (position/title held, political exposure flag, etc.)
PUBLIC_ROLE_PROPERTIES = {"position", "politicalExposure", "topics"}


def classify_target(entity: dict[str, Any]) -> TargetType:
    """Classify an FtM-shaped entity as an organization, public figure, or unknown.

    `classify_target` never positively returns PRIVATE_INDIVIDUAL — a bare, unsourced
    Person is classified UNKNOWN rather than PRIVATE_INDIVIDUAL, because we have no
    positive evidence either way and asserting "private individual" would imply a
    certainty we don't have. `check_target` treats UNKNOWN the same as
    PRIVATE_INDIVIDUAL (deny by default) so the safe behavior falls out of the gate,
    not out of a guess made here.
    """
    schema = entity.get("schema") or ""

    if schema in ORGANIZATION_SCHEMAS:
        return TargetType.ORGANIZATION

    if schema == "Person":
        provenance = entity.get("_provenance") or {}
        if provenance.get("source") in PUBLIC_ROLE_SOURCES:
            return TargetType.PUBLIC_FIGURE
        if provenance.get("datasets"):
            return TargetType.PUBLIC_FIGURE
        properties = entity.get("properties") or {}
        if any(properties.get(prop) for prop in PUBLIC_ROLE_PROPERTIES):
            return TargetType.PUBLIC_FIGURE
        return TargetType.UNKNOWN

    return TargetType.UNKNOWN


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------


@dataclass
class PublicInterestOverride:
    """An explicit, auditable justification for investigating an otherwise-blocked target."""

    reason: str
    authorized_by: str  # who/what authorized it, e.g. "truthstrike" or an operator id
    timestamp: str = ""  # ISO8601; filled with the current time if left blank

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class TargetDecision:
    """The outcome of gating a single entity, with a journalist-readable explanation."""

    allowed: bool
    target_type: TargetType
    entity_id: str
    reason: str  # journalist/operator-readable explanation of the decision


def check_target(
    entity: dict[str, Any],
    override: PublicInterestOverride | None = None,
) -> TargetDecision:
    """Decide whether an entity may be investigated under the public-interest policy.

    ORGANIZATION and PUBLIC_FIGURE targets are always allowed. UNKNOWN and
    PRIVATE_INDIVIDUAL targets are denied unless an explicit `PublicInterestOverride`
    is supplied, in which case the override's `reason` and `authorized_by` are folded
    into the decision's `reason` so the justification is auditable downstream. This
    function only decides and explains — it does not write to an audit trail; the
    caller (e.g. an API route) is responsible for logging the decision.
    """
    entity_id = entity.get("id", "")
    target_type = classify_target(entity)

    if target_type == TargetType.ORGANIZATION:
        return TargetDecision(
            allowed=True,
            target_type=target_type,
            entity_id=entity_id,
            reason="Entity schema classifies as an organization; organizations are always "
            "in-scope for investigation.",
        )

    if target_type == TargetType.PUBLIC_FIGURE:
        return TargetDecision(
            allowed=True,
            target_type=target_type,
            entity_id=entity_id,
            reason="Entity has provenance indicating a public role (disclosure filing, "
            "sanctions/PEP listing, or documented position); public figures are in-scope "
            "for investigation.",
        )

    # UNKNOWN or PRIVATE_INDIVIDUAL: deny unless overridden.
    if override is not None:
        return TargetDecision(
            allowed=True,
            target_type=target_type,
            entity_id=entity_id,
            reason=(
                f"Access denied by default ({target_type.value}) but permitted by "
                f"public-interest override: reason={override.reason!r}, "
                f"authorized_by={override.authorized_by!r}, timestamp={override.timestamp!r}."
            ),
        )

    return TargetDecision(
        allowed=False,
        target_type=target_type,
        entity_id=entity_id,
        reason=(
            "No evidence of a public role or organizational status was found for this "
            "entity. Emet may only investigate organizations and public figures without "
            "explicit public-interest justification (VALUES.json: public_interest); "
            "supply a PublicInterestOverride to proceed."
        ),
    )


def filter_targets(
    entities: list[dict[str, Any]],
    override: PublicInterestOverride | None = None,
) -> tuple[list[dict[str, Any]], list[TargetDecision]]:
    """Batch-gate a list of entities.

    Returns (allowed_entities, all_decisions) — the decisions list covers every input
    entity, allowed and denied alike, so callers can log or report the full picture
    rather than only what survived the filter.
    """
    allowed_entities: list[dict[str, Any]] = []
    decisions: list[TargetDecision] = []

    for entity in entities:
        decision = check_target(entity, override=override)
        decisions.append(decision)
        if decision.allowed:
            allowed_entities.append(entity)
        else:
            logger.info(
                "Denied target %s (%s): %s",
                decision.entity_id,
                decision.target_type.value,
                decision.reason,
            )

    return allowed_entities, decisions
