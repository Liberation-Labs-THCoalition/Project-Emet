"""Mock Aleph Server — realistic FtM data for integration testing.

Provides an httpx-compatible mock transport that simulates Aleph API
responses with a realistic investigation dataset: a Panama-based shell
company network involving PEPs, offshore holdings, and cross-border
payments.

The dataset models a scenario familiar to OCCRP/ICIJ investigations:
- A politically exposed person (Viktor Petrov, fictional deputy minister)
- Multiple shell companies across tax haven jurisdictions
- Layered ownership through nominees
- Cross-border payments between entities
- Leaked documents with extracted metadata

Usage:
    from tests.mock_aleph import MockAlephTransport, MOCK_ENTITIES

    transport = MockAlephTransport()
    client = httpx.AsyncClient(transport=transport, base_url="http://mock")
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from followthemoney import model as ftm_model


# ---------------------------------------------------------------------------
# Test dataset: "Operation Sunrise" — fictional investigation
# ---------------------------------------------------------------------------

def _make_entity(schema: str, properties: dict, id_parts: list[str]) -> dict:
    """Create a FollowTheMoney entity dict."""
    proxy = ftm_model.make_entity(schema)
    for prop, values in properties.items():
        if isinstance(values, str):
            values = [values]
        for v in values:
            proxy.add(prop, v)
    proxy.id = proxy.make_id(*id_parts)
    return proxy.to_dict()


# --- People ---

VIKTOR_PETROV = _make_entity("Person", {
    "name": ["Viktor Petrov", "Виктор Петров"],
    "nationality": "md",
    "birthDate": "1968-03-14",
    "position": "Deputy Minister of Economy",
    "country": "md",
    "gender": "male",
    "email": "v.petrov@gov.md",
}, ["Viktor Petrov", "Person", "md"])

ELENA_PETROV = _make_entity("Person", {
    "name": "Elena Petrov",
    "nationality": "md",
    "birthDate": "1972-09-22",
    "country": "md",
    "gender": "female",
}, ["Elena Petrov", "Person", "md"])

JAMES_HARTLEY = _make_entity("Person", {
    "name": "James Hartley",
    "nationality": "gb",
    "country": "gb",
    "position": "Nominee Director",
}, ["James Hartley", "Person", "gb"])

MARIA_SANTOS = _make_entity("Person", {
    "name": "Maria Santos",
    "nationality": "pa",
    "country": "pa",
    "position": "Registered Agent",
}, ["Maria Santos", "Person", "pa"])

# --- Companies ---

SUNRISE_HOLDINGS = _make_entity("Company", {
    "name": "Sunrise Holdings Ltd",
    "jurisdiction": "pa",
    "country": "pa",
    "registrationNumber": "PA-2019-847291",
    "incorporationDate": "2019-06-15",
    "address": "Calle 50, Torre Global Bank, Piso 32, Panama City",
    "status": "active",
}, ["Sunrise Holdings Ltd", "Company", "pa"])

AURORA_TRADING = _make_entity("Company", {
    "name": "Aurora Trading LLC",
    "jurisdiction": "vg",
    "country": "vg",
    "registrationNumber": "BVI-2020-192837",
    "incorporationDate": "2020-01-10",
    "status": "active",
}, ["Aurora Trading LLC", "Company", "vg"])

MERIDIAN_CONSULTING = _make_entity("Company", {
    "name": "Meridian Consulting GmbH",
    "jurisdiction": "at",
    "country": "at",
    "registrationNumber": "FN-487291s",
    "incorporationDate": "2018-11-03",
    "address": "Kärntner Ring 12, 1010 Wien",
    "status": "active",
}, ["Meridian Consulting GmbH", "Company", "at"])

BLACKSTONE_NOMINEES = _make_entity("Company", {
    "name": "Blackstone Nominees Ltd",
    "jurisdiction": "gb",
    "country": "gb",
    "registrationNumber": "UK-12847391",
    "incorporationDate": "2005-03-20",
    "address": "71 Fenchurch Street, London EC3M 4BS",
    "status": "active",
}, ["Blackstone Nominees Ltd", "Company", "gb"])

DANUBE_REAL_ESTATE = _make_entity("Company", {
    "name": "Danube Real Estate SRL",
    "jurisdiction": "md",
    "country": "md",
    "registrationNumber": "MD-1004829173",
    "incorporationDate": "2017-05-12",
    "address": "Str. Puskin 22, Chișinău",
    "status": "active",
}, ["Danube Real Estate SRL", "Company", "md"])

# --- Ownership relationships ---

PETROV_OWNS_SUNRISE = _make_entity("Ownership", {
    "owner": VIKTOR_PETROV["id"],
    "asset": SUNRISE_HOLDINGS["id"],
    "ownershipType": "beneficial",
    "percentage": "100",
    "startDate": "2019-06-15",
}, [VIKTOR_PETROV["id"], "owns", SUNRISE_HOLDINGS["id"]])

SUNRISE_OWNS_AURORA = _make_entity("Ownership", {
    "owner": SUNRISE_HOLDINGS["id"],
    "asset": AURORA_TRADING["id"],
    "percentage": "100",
    "startDate": "2020-01-10",
}, [SUNRISE_HOLDINGS["id"], "owns", AURORA_TRADING["id"]])

AURORA_OWNS_DANUBE = _make_entity("Ownership", {
    "owner": AURORA_TRADING["id"],
    "asset": DANUBE_REAL_ESTATE["id"],
    "percentage": "80",
    "startDate": "2020-06-01",
}, [AURORA_TRADING["id"], "owns", DANUBE_REAL_ESTATE["id"]])

ELENA_OWNS_MERIDIAN = _make_entity("Ownership", {
    "owner": ELENA_PETROV["id"],
    "asset": MERIDIAN_CONSULTING["id"],
    "percentage": "100",
    "startDate": "2018-11-03",
}, [ELENA_PETROV["id"], "owns", MERIDIAN_CONSULTING["id"]])

# --- Directorships ---

HARTLEY_DIRECTS_SUNRISE = _make_entity("Directorship", {
    "director": JAMES_HARTLEY["id"],
    "organization": SUNRISE_HOLDINGS["id"],
    "role": "Director",
    "startDate": "2019-06-15",
}, [JAMES_HARTLEY["id"], "directs", SUNRISE_HOLDINGS["id"]])

HARTLEY_DIRECTS_AURORA = _make_entity("Directorship", {
    "director": JAMES_HARTLEY["id"],
    "organization": AURORA_TRADING["id"],
    "role": "Director",
    "startDate": "2020-01-10",
}, [JAMES_HARTLEY["id"], "directs", AURORA_TRADING["id"]])

SANTOS_AGENT_SUNRISE = _make_entity("Representation", {
    "agent": MARIA_SANTOS["id"],
    "client": SUNRISE_HOLDINGS["id"],
    "role": "Registered Agent",
    "startDate": "2019-06-15",
}, [MARIA_SANTOS["id"], "represents", SUNRISE_HOLDINGS["id"]])

# --- Family ---

PETROV_FAMILY = _make_entity("Family", {
    "person": VIKTOR_PETROV["id"],
    "relative": ELENA_PETROV["id"],
    "relationship": "spouse",
}, [VIKTOR_PETROV["id"], "married", ELENA_PETROV["id"]])

# --- Payments ---

PAYMENT_MERIDIAN_SUNRISE = _make_entity("Payment", {
    "payer": MERIDIAN_CONSULTING["id"],
    "beneficiary": SUNRISE_HOLDINGS["id"],
    "amount": "2400000",
    "currency": "EUR",
    "date": "2021-03-15",
    "purpose": "Consulting services agreement",
}, [MERIDIAN_CONSULTING["id"], "pays", SUNRISE_HOLDINGS["id"], "2021-03-15"])

PAYMENT_SUNRISE_DANUBE = _make_entity("Payment", {
    "payer": SUNRISE_HOLDINGS["id"],
    "beneficiary": DANUBE_REAL_ESTATE["id"],
    "amount": "1800000",
    "currency": "EUR",
    "date": "2021-04-02",
    "purpose": "Real estate acquisition",
}, [SUNRISE_HOLDINGS["id"], "pays", DANUBE_REAL_ESTATE["id"], "2021-04-02"])

PAYMENT_AURORA_OFFSHORE = _make_entity("Payment", {
    "payer": AURORA_TRADING["id"],
    "beneficiary": SUNRISE_HOLDINGS["id"],
    "amount": "750000",
    "currency": "USD",
    "date": "2022-01-20",
    "purpose": "Management fee",
}, [AURORA_TRADING["id"], "pays", SUNRISE_HOLDINGS["id"], "2022-01-20"])

# --- Documents ---

LEAKED_CONTRACT = _make_entity("Document", {
    "title": "Consulting Agreement — Meridian / Sunrise",
    "fileName": "consulting_agreement_2021.pdf",
    "mimeType": "application/pdf",
    "language": "en",
    "date": "2021-03-01",
    "author": "Maria Santos",
}, ["consulting_agreement_2021.pdf", "Document"])

BANK_STATEMENT = _make_entity("Document", {
    "title": "Sunrise Holdings — Bank Statement Q1 2021",
    "fileName": "sunrise_bank_q1_2021.pdf",
    "mimeType": "application/pdf",
    "language": "en",
    "date": "2021-04-15",
}, ["sunrise_bank_q1_2021.pdf", "Document"])

PROPERTY_DEED = _make_entity("Document", {
    "title": "Danube Real Estate — Property Deed, Str. Puskin 22",
    "fileName": "property_deed_puskin22.pdf",
    "mimeType": "application/pdf",
    "language": "ro",
    "date": "2020-06-15",
}, ["property_deed_puskin22.pdf", "Document"])


# ---------------------------------------------------------------------------
# Assembled dataset
# ---------------------------------------------------------------------------

ALL_ENTITIES: list[dict[str, Any]] = [
    # People
    VIKTOR_PETROV, ELENA_PETROV, JAMES_HARTLEY, MARIA_SANTOS,
    # Companies
    SUNRISE_HOLDINGS, AURORA_TRADING, MERIDIAN_CONSULTING,
    BLACKSTONE_NOMINEES, DANUBE_REAL_ESTATE,
    # Ownership
    PETROV_OWNS_SUNRISE, SUNRISE_OWNS_AURORA, AURORA_OWNS_DANUBE,
    ELENA_OWNS_MERIDIAN,
    # Directorships
    HARTLEY_DIRECTS_SUNRISE, HARTLEY_DIRECTS_AURORA,
    # Other relationships
    SANTOS_AGENT_SUNRISE, PETROV_FAMILY,
    # Payments
    PAYMENT_MERIDIAN_SUNRISE, PAYMENT_SUNRISE_DANUBE, PAYMENT_AURORA_OFFSHORE,
    # Documents
    LEAKED_CONTRACT, BANK_STATEMENT, PROPERTY_DEED,
]

ENTITY_INDEX: dict[str, dict] = {e["id"]: e for e in ALL_ENTITIES}

COLLECTION = {
    "id": "42",
    "label": "Operation Sunrise",
    "summary": "Investigation into Viktor Petrov's offshore holdings",
    "category": "investigation",
    "creator_id": "journalist-1",
    "count": len(ALL_ENTITIES),
    "created_at": "2024-01-15T10:00:00Z",
    "updated_at": "2024-06-20T14:30:00Z",
}

# --- Cross-reference matches (simulated xref results) ---

XREF_RESULTS = [
    {
        "id": "xref-001",
        "score": 0.92,
        "entity_id": VIKTOR_PETROV["id"],
        "match_id": "opensanctions-md-pep-petrov",
        "collection_id": "opensanctions",
        "match": {
            "id": "opensanctions-md-pep-petrov",
            "schema": "Person",
            "properties": {
                "name": ["Viktor Petrov"],
                "position": ["Deputy Minister of Economy"],
                "country": ["md"],
            },
        },
        "decision": None,
        "judgement": "no_judgement",
    },
    {
        "id": "xref-002",
        "score": 0.78,
        "entity_id": SUNRISE_HOLDINGS["id"],
        "match_id": "icij-pa-sunrise-847291",
        "collection_id": "icij_offshore",
        "match": {
            "id": "icij-pa-sunrise-847291",
            "schema": "Company",
            "properties": {
                "name": ["Sunrise Holdings Ltd"],
                "jurisdiction": ["pa"],
            },
        },
        "decision": None,
        "judgement": "no_judgement",
    },
    {
        "id": "xref-003",
        "score": 0.45,
        "entity_id": JAMES_HARTLEY["id"],
        "match_id": "uk-companies-hartley-dir",
        "collection_id": "uk_companies",
        "match": {
            "id": "uk-companies-hartley-dir",
            "schema": "Person",
            "properties": {
                "name": ["James R. Hartley"],
                "country": ["gb"],
            },
        },
        "decision": None,
        "judgement": "no_judgement",
    },
]


# ---------------------------------------------------------------------------
# Mock HTTP Transport
# ---------------------------------------------------------------------------

class MockAlephTransport(httpx.AsyncBaseTransport):
    """Mock transport that simulates Aleph API responses.

    Handles the same URL patterns as the real Aleph /api/2/ endpoints.
    """

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)

        # --- Search ---
        if path.endswith("/search"):
            return self._search(params)

        # --- Entity by ID ---
        m = re.search(r"/entities/([^/]+)$", path)
        if m:
            return self._get_entity(m.group(1))

        # --- Entity expand ---
        m = re.search(r"/entities/([^/]+)/expand", path)
        if m:
            return self._expand_entity(m.group(1))

        # --- Entity references ---
        m = re.search(r"/entities/([^/]+)/references", path)
        if m:
            return self._entity_references(m.group(1))

        # --- Entity similar ---
        m = re.search(r"/entities/([^/]+)/similar", path)
        if m:
            return self._similar_entities(m.group(1))

        # --- Collections ---
        if path.endswith("/collections"):
            return self._list_collections()

        m = re.search(r"/collections/(\d+)$", path)
        if m:
            return self._get_collection(m.group(1))

        # --- Cross-reference ---
        m = re.search(r"/collections/(\d+)/xref", path)
        if m:
            if request.method == "POST":
                return self._trigger_xref(m.group(1))
            return self._get_xref(m.group(1), params)

        # --- Notifications ---
        if path.endswith("/notifications"):
            return self._notifications()

        # --- Entity stream ---
        m = re.search(r"/collections/(\d+)/entities", path)
        if m:
            return self._stream_entities(m.group(1))

        # Fallback
        return httpx.Response(404, json={"status": "error", "message": f"Not found: {path}"})

    # -- handlers -----------------------------------------------------------

    def _search(self, params: dict) -> httpx.Response:
        query = params.get("q", "").lower()
        schema_filter = params.get("filter:schema", "")
        limit = int(params.get("limit", "20"))

        results = []
        for entity in ALL_ENTITIES:
            # Text match against all property values
            text = json.dumps(entity.get("properties", {})).lower()
            if query == "*" or query in text or query in entity.get("id", ""):
                if schema_filter and entity["schema"] != schema_filter:
                    continue
                results.append(entity)

        results = results[:limit]
        return httpx.Response(200, json={
            "status": "ok",
            "results": [
                {
                    "id": e["id"],
                    "schema": e["schema"],
                    "properties": e["properties"],
                    "collection_id": "42",
                    "score": 1.0,
                }
                for e in results
            ],
            "total": len(results),
            "limit": limit,
            "offset": 0,
        })

    def _get_entity(self, entity_id: str) -> httpx.Response:
        entity = ENTITY_INDEX.get(entity_id)
        if not entity:
            return httpx.Response(404, json={"status": "error", "message": "Not found"})
        return httpx.Response(200, json={
            "id": entity["id"],
            "schema": entity["schema"],
            "properties": entity["properties"],
            "collection_id": "42",
        })

    def _expand_entity(self, entity_id: str) -> httpx.Response:
        """Find all entities that reference this entity in any property."""
        related = []
        for e in ALL_ENTITIES:
            if e["id"] == entity_id:
                continue
            props_text = json.dumps(e.get("properties", {}))
            if entity_id in props_text:
                related.append(e)
        return httpx.Response(200, json={
            "status": "ok",
            "results": [
                {
                    "id": e["id"],
                    "schema": e["schema"],
                    "properties": e["properties"],
                    "property": "related",
                    "count": 1,
                }
                for e in related
            ],
            "total": len(related),
        })

    def _entity_references(self, entity_id: str) -> httpx.Response:
        """Same as expand but returns reference format."""
        refs = []
        for e in ALL_ENTITIES:
            if e["id"] == entity_id:
                continue
            for prop, vals in e.get("properties", {}).items():
                if entity_id in vals:
                    refs.append({"entity": e, "property": prop})
        return httpx.Response(200, json={
            "status": "ok",
            "results": refs,
            "total": len(refs),
        })

    def _similar_entities(self, entity_id: str) -> httpx.Response:
        entity = ENTITY_INDEX.get(entity_id)
        if not entity:
            return httpx.Response(404, json={"status": "error"})
        # Return entities of the same schema
        similar = [
            e for e in ALL_ENTITIES
            if e["schema"] == entity["schema"] and e["id"] != entity_id
        ][:5]
        return httpx.Response(200, json={
            "status": "ok",
            "results": [
                {"id": e["id"], "schema": e["schema"],
                 "properties": e["properties"], "score": 0.6}
                for e in similar
            ],
            "total": len(similar),
        })

    def _list_collections(self) -> httpx.Response:
        return httpx.Response(200, json={
            "status": "ok",
            "results": [COLLECTION],
            "total": 1,
        })

    def _get_collection(self, collection_id: str) -> httpx.Response:
        if collection_id == "42":
            return httpx.Response(200, json=COLLECTION)
        return httpx.Response(404, json={"status": "error"})

    def _trigger_xref(self, collection_id: str) -> httpx.Response:
        return httpx.Response(200, json={
            "status": "ok",
            "message": f"Cross-referencing started for collection {collection_id}",
            "job_id": "xref-job-001",
        })

    def _get_xref(self, collection_id: str, params: dict) -> httpx.Response:
        return httpx.Response(200, json={
            "status": "ok",
            "results": XREF_RESULTS,
            "total": len(XREF_RESULTS),
        })

    def _notifications(self) -> httpx.Response:
        return httpx.Response(200, json={
            "status": "ok",
            "results": [
                {
                    "id": "notif-001",
                    "event": "entity_update",
                    "entity_id": VIKTOR_PETROV["id"],
                    "collection_id": "42",
                    "created_at": "2024-06-20T14:30:00Z",
                },
            ],
            "total": 1,
        })

    def _stream_entities(self, collection_id: str) -> httpx.Response:
        """Return NDJSON stream of all entities."""
        lines = [json.dumps(e) for e in ALL_ENTITIES]
        body = "\n".join(lines) + "\n"
        return httpx.Response(200, content=body.encode(),
                              headers={"content-type": "application/x-ndjson"})
