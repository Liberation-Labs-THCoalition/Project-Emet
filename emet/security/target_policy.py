"""Targeting policy — investigate organizations and public figures only.

Emet's cameras point *up* the power hierarchy, never down. Until now the
"organizations and public figures only, not private individuals"
constraint lived only as prose in VALUES.json, the LICENSE, and
CLAUDE.md — nothing in code enforced it. This module makes it an
enforced guardrail.

The policy classifies an investigation target into:

    - ``ORGANIZATION`` — companies, PACs, agencies, public bodies. Always
      permitted (organizations are not private individuals).
    - ``PUBLIC_FIGURE`` — a natural person with a public-power signal:
      elected/appointed office, a corporate role, a sanctions/PEP hit, or
      appearance in an inherently-public dataset (Congress, FEC, EDGAR
      officers, sanctions lists). Permitted.
    - ``PRIVATE_INDIVIDUAL`` — a natural person with no public-power
      signal. Denied unless an explicit, logged justification override is
      supplied (e.g. a documented public-interest reason approved by an
      editor).

The classifier is intentionally conservative: an *unknown* person with
no public signal is treated as private and blocked, so the safe default
is to protect people, not to expose them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TargetClass(str, Enum):
    ORGANIZATION = "organization"
    PUBLIC_FIGURE = "public_figure"
    PRIVATE_INDIVIDUAL = "private_individual"
    UNKNOWN = "unknown"


# FtM schemas that are inherently organizations (never private persons).
_ORG_SCHEMAS = {
    "Company",
    "Organization",
    "LegalEntity",
    "PublicBody",
    "Airplane",
    "Vessel",
    "Security",
}

# Data sources whose records are, by definition, about public actors.
_PUBLIC_SOURCES = {
    "congress",
    "fec",
    "opensanctions",
    "edgar",
    "sec_edgar",
    "gleif",
    "companies_house",
    "icij",
}

# Free-text cues that a person holds public power.
_PUBLIC_ROLE_RE = re.compile(
    r"\b(senator|congress|representative|member of congress|minister|"
    r"president|governor|mayor|secretary|commissioner|director|"
    r"chief executive|ceo|cfo|chair|chairman|chairwoman|board member|"
    r"officer|founder|owner|beneficial owner|oligarch|ambassador|"
    r"judge|candidate|official|executive|trustee|general)\b",
    re.IGNORECASE,
)


@dataclass
class TargetDecision:
    """Result of a targeting-policy check."""

    allowed: bool
    target_class: TargetClass
    reason: str
    signals: list[str] = field(default_factory=list)
    requires_override: bool = False


def _properties(entity: dict[str, Any]) -> dict[str, Any]:
    props = entity.get("properties", {})
    return props if isinstance(props, dict) else {}


def _first(props: dict[str, Any], key: str) -> str:
    val = props.get(key)
    if isinstance(val, list):
        return str(val[0]) if val else ""
    return str(val) if val else ""


def classify_target(entity: dict[str, Any]) -> tuple[TargetClass, list[str]]:
    """Classify an FtM entity and return (class, signals).

    ``signals`` records *why* — for the audit trail and the report's
    methodology notes.
    """
    signals: list[str] = []
    schema = entity.get("schema", "")

    if schema in _ORG_SCHEMAS:
        signals.append(f"schema={schema} (organization)")
        return TargetClass.ORGANIZATION, signals

    if schema not in ("Person", "LegalEntity", ""):
        # Non-person, non-org things (Address, Document, Payment...) are
        # not "private individuals" — allow as organization-adjacent.
        signals.append(f"schema={schema} (non-person)")
        return TargetClass.ORGANIZATION, signals

    props = _properties(entity)
    prov = entity.get("_provenance", {})
    source = prov.get("source", "") if isinstance(prov, dict) else ""

    # Public-power signals for a natural person.
    if source in _PUBLIC_SOURCES:
        signals.append(f"appears in public dataset: {source}")

    for role_key in ("position", "publicRole", "role", "classification", "summary"):
        role_val = _first(props, role_key)
        if role_val and _PUBLIC_ROLE_RE.search(role_val):
            signals.append(f"public role: {role_key}='{role_val}'")

    topics = props.get("topics", []) or []
    if isinstance(topics, list) and any(
        t in ("role.pep", "sanction", "role.oligarch", "gov.national")
        for t in topics
    ):
        signals.append(f"topics: {topics}")

    if entity.get("_sanctioned") or entity.get("_pep"):
        signals.append("flagged sanctions/PEP")

    if signals:
        return TargetClass.PUBLIC_FIGURE, signals

    # A person with no public-power signal.
    if schema == "Person":
        return TargetClass.PRIVATE_INDIVIDUAL, ["no public-power signal found"]

    return TargetClass.UNKNOWN, ["insufficient information to classify"]


def check_target(
    entity: dict[str, Any],
    override_justification: str = "",
) -> TargetDecision:
    """Decide whether an entity may be investigated.

    Organizations and public figures are allowed. Private individuals and
    unknowns are denied unless a non-empty ``override_justification`` is
    supplied, in which case the investigation may proceed but the decision
    is flagged ``requires_override`` so the audit trail records that a
    human took explicit responsibility.
    """
    target_class, signals = classify_target(entity)

    if target_class in (TargetClass.ORGANIZATION, TargetClass.PUBLIC_FIGURE):
        return TargetDecision(
            allowed=True,
            target_class=target_class,
            reason=f"{target_class.value} — permitted",
            signals=signals,
        )

    # Private individual or unknown.
    if override_justification.strip():
        return TargetDecision(
            allowed=True,
            target_class=target_class,
            reason=(
                f"{target_class.value} — permitted under logged override: "
                f"{override_justification.strip()}"
            ),
            signals=signals,
            requires_override=True,
        )

    name = _first(_properties(entity), "name") or entity.get("id", "this target")
    return TargetDecision(
        allowed=False,
        target_class=target_class,
        reason=(
            f"{name} classified as {target_class.value}. Emet investigates "
            "organizations and public figures, not private individuals. "
            "Supply a documented public-interest override to proceed."
        ),
        signals=signals,
        requires_override=True,
    )


def filter_investigable(
    entities: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split entities into (investigable, blocked) per the policy."""
    investigable: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for entity in entities:
        if check_target(entity).allowed:
            investigable.append(entity)
        else:
            blocked.append(entity)
    return investigable, blocked
