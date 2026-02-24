"""Demo investigation data for first-use experience.

When running in stub/demo mode, this module provides a realistic set
of FtM entities that demonstrate the full investigation pipeline:
  search → sanctions → ownership → graph → report

The scenario models a fictional network of offshore entities with
shell-company patterns, beneficial ownership chains, and a sanctions
proximity flag — the kind of structure Emet is designed to uncover.

**All entities, names, and addresses are entirely fictional.**
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Fictional investigation scenario: "Meridian Holdings"
#
# Structure:
#   Meridian Holdings Ltd (BVI)
#     └── owned by → Zenith Capital Partners LP (Cayman)
#           └── managed by → Viktor Renko (person, sanctions-proximate)
#                              └── also officer of → Nova Offshore LLC (Panama)
#                                    └── owned by → Meridian Holdings (circular!)
#   Meridian Consulting AG (Zurich) — intermediary
#   Pacific Rim Trading Ltd (HK) — nominee shareholder
#   Aurora Financial Services SA (Luxembourg) — administrator
#   Elena Marchetti — compliance officer (clean)
#   James Wu — nominee director
#   Konrad Brauer — registered agent
# ---------------------------------------------------------------------------

_DEMO_ENTITIES: list[dict[str, Any]] = [
    # --- Top entities (first 5 generate leads) ---
    # Companies first (get both sanctions + ownership leads)
    {
        "id": "demo:meridian-holdings",
        "schema": "Company",
        "properties": {
            "name": ["Meridian Holdings Ltd"],
            "jurisdiction": ["vg"],
            "country": ["VG"],
            "incorporationDate": ["2017-03-14"],
            "registrationNumber": ["BVI-1823947"],
            "address": ["Pasea Estate, Road Town, Tortola, British Virgin Islands"],
            "classification": ["International Business Company"],
            "status": ["Active"],
        },
        "_provenance": {
            "source": "demo_dataset",
            "source_id": "meridian-holdings",
            "source_url": "",
            "confidence": 0.95,
            "queried_at": "2026-02-24T00:00:00Z",
        },
    },
    {
        "id": "demo:zenith-capital",
        "schema": "Company",
        "properties": {
            "name": ["Zenith Capital Partners LP"],
            "jurisdiction": ["ky"],
            "country": ["KY"],
            "incorporationDate": ["2015-08-22"],
            "registrationNumber": ["KY-MC-98412"],
            "address": ["PO Box 309, George Town, Grand Cayman, Cayman Islands"],
            "classification": ["Exempted Limited Partnership"],
        },
        "_provenance": {
            "source": "demo_dataset",
            "source_id": "zenith-capital",
            "confidence": 0.95,
            "queried_at": "2026-02-24T00:00:00Z",
        },
    },
    {
        "id": "demo:nova-offshore",
        "schema": "Company",
        "properties": {
            "name": ["Nova Offshore LLC"],
            "jurisdiction": ["pa"],
            "country": ["PA"],
            "incorporationDate": ["2018-11-05"],
            "registrationNumber": ["PA-2018-384721"],
            "address": ["Calle 50, Edificio Global Plaza, Panama City, Panama"],
            "classification": ["Sociedad de Responsabilidad Limitada"],
            "status": ["Active"],
        },
        "_provenance": {
            "source": "demo_dataset",
            "source_id": "nova-offshore",
            "confidence": 0.95,
            "queried_at": "2026-02-24T00:00:00Z",
        },
    },
    {
        "id": "demo:meridian-consulting",
        "schema": "Company",
        "properties": {
            "name": ["Meridian Consulting AG"],
            "jurisdiction": ["ch"],
            "country": ["CH"],
            "incorporationDate": ["2016-05-10"],
            "registrationNumber": ["CHE-412.398.175"],
            "address": ["Bahnhofstrasse 42, 8001 Zurich, Switzerland"],
            "classification": ["Aktiengesellschaft"],
            "status": ["Active"],
        },
        "_provenance": {
            "source": "demo_dataset",
            "source_id": "meridian-consulting",
            "confidence": 0.95,
            "queried_at": "2026-02-24T00:00:00Z",
        },
    },
    {
        "id": "demo:pacific-rim",
        "schema": "Company",
        "properties": {
            "name": ["Pacific Rim Trading Ltd"],
            "jurisdiction": ["hk"],
            "country": ["HK"],
            "incorporationDate": ["2019-02-28"],
            "registrationNumber": ["HK-2847163"],
            "address": ["Unit 2301, 23/F, Tower 6, The Gateway, Tsim Sha Tsui, Hong Kong"],
            "classification": ["Private Company Limited by Shares"],
            "notes": ["Nominee shareholder structure identified"],
        },
        "_provenance": {
            "source": "demo_dataset",
            "source_id": "pacific-rim",
            "confidence": 0.90,
            "queried_at": "2026-02-24T00:00:00Z",
        },
    },
    {
        "id": "demo:aurora-financial",
        "schema": "Company",
        "properties": {
            "name": ["Aurora Financial Services SA"],
            "jurisdiction": ["lu"],
            "country": ["LU"],
            "incorporationDate": ["2014-09-18"],
            "registrationNumber": ["B-198432"],
            "address": ["2 Boulevard Royal, L-2449 Luxembourg"],
            "classification": ["Société Anonyme"],
            "status": ["Active"],
            "notes": ["Provides corporate administration services"],
        },
        "_provenance": {
            "source": "demo_dataset",
            "source_id": "aurora-financial",
            "confidence": 0.95,
            "queried_at": "2026-02-24T00:00:00Z",
        },
    },

    # --- People ---
    {
        "id": "demo:viktor-renko",
        "schema": "Person",
        "properties": {
            "name": ["Viktor Renko"],
            "nationality": ["RU"],
            "country": ["CY"],
            "birthDate": ["1971-04-12"],
            "address": ["28 Arch. Makariou III, Limassol, Cyprus"],
            "notes": [
                "Managing Partner of Zenith Capital Partners LP",
                "Previously associated with sanctioned entity Vostok Energy Group",
            ],
        },
        "_provenance": {
            "source": "demo_dataset",
            "source_id": "viktor-renko",
            "confidence": 0.90,
            "queried_at": "2026-02-24T00:00:00Z",
        },
    },
    {
        "id": "demo:elena-marchetti",
        "schema": "Person",
        "properties": {
            "name": ["Elena Marchetti"],
            "nationality": ["IT"],
            "country": ["CH"],
            "address": ["Gartenstrasse 15, 8002 Zurich, Switzerland"],
            "position": ["Compliance Officer"],
        },
        "_provenance": {
            "source": "demo_dataset",
            "source_id": "elena-marchetti",
            "confidence": 0.85,
            "queried_at": "2026-02-24T00:00:00Z",
        },
    },
    {
        "id": "demo:james-wu",
        "schema": "Person",
        "properties": {
            "name": ["James Wu"],
            "nationality": ["HK"],
            "country": ["HK"],
            "address": ["Flat B, 14/F, Tower 3, Sorrento, West Kowloon, Hong Kong"],
            "notes": ["Professional nominee director — appears in 47 other BVI/HK structures"],
        },
        "_provenance": {
            "source": "demo_dataset",
            "source_id": "james-wu",
            "confidence": 0.85,
            "queried_at": "2026-02-24T00:00:00Z",
        },
    },
    {
        "id": "demo:konrad-brauer",
        "schema": "Person",
        "properties": {
            "name": ["Konrad Brauer"],
            "nationality": ["DE"],
            "country": ["LU"],
            "address": ["2 Boulevard Royal, L-2449 Luxembourg"],
            "position": ["Registered Agent"],
        },
        "_provenance": {
            "source": "demo_dataset",
            "source_id": "konrad-brauer",
            "confidence": 0.85,
            "queried_at": "2026-02-24T00:00:00Z",
        },
    },

    # --- Ownership relationships (modeled as FtM Ownership entities) ---
    {
        "id": "demo:own-zenith-meridian",
        "schema": "Ownership",
        "properties": {
            "owner": ["demo:zenith-capital"],
            "asset": ["demo:meridian-holdings"],
            "ownershipType": ["Beneficial ownership via nominee structure"],
            "percentage": ["100"],
            "startDate": ["2017-03-14"],
        },
        "_provenance": {"source": "demo_dataset", "confidence": 0.80},
    },
    {
        "id": "demo:own-nova-meridian",
        "schema": "Ownership",
        "properties": {
            "owner": ["demo:nova-offshore"],
            "asset": ["demo:zenith-capital"],
            "ownershipType": ["Limited partnership interest"],
            "percentage": ["60"],
            "startDate": ["2018-11-20"],
        },
        "_provenance": {"source": "demo_dataset", "confidence": 0.75},
    },
    {
        "id": "demo:own-meridian-nova",
        "schema": "Ownership",
        "properties": {
            "owner": ["demo:meridian-holdings"],
            "asset": ["demo:nova-offshore"],
            "ownershipType": ["Indirect via Pacific Rim Trading nominee"],
            "percentage": ["100"],
            "startDate": ["2019-03-01"],
            "summary": ["CIRCULAR OWNERSHIP: Meridian → Zenith → Nova → Meridian"],
        },
        "_provenance": {"source": "demo_dataset", "confidence": 0.70},
    },

    # --- Officer/Director relationships ---
    {
        "id": "demo:dir-renko-zenith",
        "schema": "Directorship",
        "properties": {
            "director": ["demo:viktor-renko"],
            "organization": ["demo:zenith-capital"],
            "role": ["Managing Partner"],
            "startDate": ["2015-08-22"],
        },
        "_provenance": {"source": "demo_dataset", "confidence": 0.90},
    },
    {
        "id": "demo:dir-renko-nova",
        "schema": "Directorship",
        "properties": {
            "director": ["demo:viktor-renko"],
            "organization": ["demo:nova-offshore"],
            "role": ["Director"],
            "startDate": ["2018-11-05"],
        },
        "_provenance": {"source": "demo_dataset", "confidence": 0.85},
    },
    {
        "id": "demo:dir-wu-meridian",
        "schema": "Directorship",
        "properties": {
            "director": ["demo:james-wu"],
            "organization": ["demo:meridian-holdings"],
            "role": ["Nominee Director"],
            "startDate": ["2017-03-14"],
        },
        "_provenance": {"source": "demo_dataset", "confidence": 0.85},
    },
    {
        "id": "demo:dir-wu-pacific",
        "schema": "Directorship",
        "properties": {
            "director": ["demo:james-wu"],
            "organization": ["demo:pacific-rim"],
            "role": ["Director"],
            "startDate": ["2019-02-28"],
        },
        "_provenance": {"source": "demo_dataset", "confidence": 0.85},
    },
    {
        "id": "demo:dir-marchetti-meridian-ch",
        "schema": "Directorship",
        "properties": {
            "director": ["demo:elena-marchetti"],
            "organization": ["demo:meridian-consulting"],
            "role": ["Compliance Officer"],
            "startDate": ["2016-05-10"],
        },
        "_provenance": {"source": "demo_dataset", "confidence": 0.85},
    },
    {
        "id": "demo:dir-brauer-aurora",
        "schema": "Directorship",
        "properties": {
            "director": ["demo:konrad-brauer"],
            "organization": ["demo:aurora-financial"],
            "role": ["Registered Agent"],
            "startDate": ["2014-09-18"],
        },
        "_provenance": {"source": "demo_dataset", "confidence": 0.85},
    },
]


# Simulated sanctions screening result for Viktor Renko
_DEMO_SANCTIONS_MATCHES: list[dict[str, Any]] = [
    {
        "entity_id": "demo:viktor-renko",
        "name": "Viktor Renko",
        "match_type": "approximate",
        "score": 0.78,
        "matched_against": {
            "name": "Viktor RENKO",
            "dataset": "OFAC SDN List",
            "list_date": "2022-06-15",
            "reason": "Association with Vostok Energy Group (sanctioned under EO 14024)",
            "source_url": "https://sanctionssearch.ofac.treas.gov/",
        },
        "alert_level": "HIGH",
    },
]


def get_demo_entities(query: str = "") -> list[dict[str, Any]]:
    """Return demo entities, ordered for optimal investigation flow.

    First 5 entities generate initial leads. We put the key companies
    and Viktor Renko (sanctions-proximate) first so the pipeline
    demonstrates: sanctions hit, ownership tracing, then deeper analysis.
    """
    # Optimal order: key companies first, then Viktor Renko for sanctions hit,
    # then remaining entities for graph/relationship analysis
    priority_ids = [
        "demo:meridian-holdings",    # 1. Primary target
        "demo:zenith-capital",       # 2. Parent company
        "demo:nova-offshore",        # 3. Shell company
        "demo:viktor-renko",         # 4. Sanctions-proximate person
        "demo:meridian-consulting",  # 5. Intermediary
    ]

    priority = [e for pid in priority_ids for e in _DEMO_ENTITIES if e["id"] == pid]
    rest = [e for e in _DEMO_ENTITIES if e["id"] not in priority_ids]
    return priority + rest


def get_demo_sanctions_matches() -> list[dict[str, Any]]:
    """Return demo sanctions screening results."""
    return list(_DEMO_SANCTIONS_MATCHES)
