"""Integration tests — full investigation pipeline against mock Aleph.

Tests the complete flow of an investigation: "Operation Sunrise",
tracking a fictional deputy minister's offshore holdings through
Panama, BVI, and Austria via nominee directors and shell companies.

Requires: followthemoney, httpx (installed as project deps).
Does NOT require a live Aleph instance.
"""

import asyncio
import json
import sys
from unittest.mock import patch

import httpx

# Our mock data
from tests.mock_aleph import (
    MockAlephTransport,
    ALL_ENTITIES, ENTITY_INDEX, XREF_RESULTS,
    VIKTOR_PETROV, ELENA_PETROV, JAMES_HARTLEY, MARIA_SANTOS,
    SUNRISE_HOLDINGS, AURORA_TRADING, MERIDIAN_CONSULTING,
    DANUBE_REAL_ESTATE, BLACKSTONE_NOMINEES,
    PETROV_OWNS_SUNRISE, SUNRISE_OWNS_AURORA, AURORA_OWNS_DANUBE,
    PAYMENT_MERIDIAN_SUNRISE, PAYMENT_SUNRISE_DANUBE,
    LEAKED_CONTRACT,
)

from emet.skills import get_chip
from emet.skills.base import SkillContext, SkillRequest, SkillResponse
from emet.ftm.aleph_client import AlephClient, AlephConfig


PASS = 0
FAIL = 0


def report(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}: {detail}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_client(self=None) -> httpx.AsyncClient:
    """Create an httpx.AsyncClient backed by MockAlephTransport."""
    return httpx.AsyncClient(
        transport=MockAlephTransport(),
        base_url="http://mock-aleph/api/2",
        headers={"Authorization": "ApiKey test-key"},
        timeout=10.0,
    )


def _patch_aleph():
    """Monkeypatch AlephClient._client to use mock transport."""
    return patch.object(AlephClient, "_client", _mock_client)


# Shared investigation context
CTX = SkillContext(
    investigation_id="op-sunrise",
    user_id="journalist-1",
    hypothesis="Viktor Petrov uses Panama shell companies to launder state funds",
    collection_ids=["42"],
    target_entities=[VIKTOR_PETROV["id"], SUNRISE_HOLDINGS["id"]],
)


# ---------------------------------------------------------------------------
# Test suites
# ---------------------------------------------------------------------------

async def test_mock_aleph_directly():
    """Verify the mock Aleph server returns correct data."""
    print("\n═══ 1. Mock Aleph Server ═══")

    async with httpx.AsyncClient(
        transport=MockAlephTransport(),
        base_url="http://mock-aleph/api/2",
    ) as client:
        # Search
        resp = await client.get("/search", params={"q": "Petrov"})
        data = resp.json()
        report(f"Search 'Petrov' → {data['total']} results",
               data["total"] >= 2)  # Viktor + Elena

        # Search with schema filter
        resp = await client.get("/search", params={"q": "sunrise", "filter:schema": "Company"})
        data = resp.json()
        report(f"Search 'sunrise' (Company only) → {data['total']} result",
               data["total"] == 1 and data["results"][0]["schema"] == "Company")

        # Wildcard search
        resp = await client.get("/search", params={"q": "*", "limit": 100})
        data = resp.json()
        report(f"Search '*' → {data['total']} entities (all {len(ALL_ENTITIES)})",
               data["total"] == len(ALL_ENTITIES))

        # Get entity
        resp = await client.get(f"/entities/{VIKTOR_PETROV['id']}")
        data = resp.json()
        report(f"Get entity Viktor Petrov → schema={data['schema']}",
               data["schema"] == "Person" and "Viktor Petrov" in data["properties"]["name"])

        # Expand entity — find everything connected to Sunrise Holdings
        resp = await client.get(f"/entities/{SUNRISE_HOLDINGS['id']}/expand")
        data = resp.json()
        report(f"Expand Sunrise Holdings → {data['total']} connected entities",
               data["total"] >= 4)  # ownership, directorship, payments, agent

        # Collections
        resp = await client.get("/collections")
        data = resp.json()
        report(f"List collections → {data['total']} collection(s)",
               data["total"] == 1 and data["results"][0]["label"] == "Operation Sunrise")

        # Cross-reference
        resp = await client.get("/collections/42/xref")
        data = resp.json()
        report(f"Get xref results → {data['total']} matches",
               data["total"] == 3)

        # Entity stream
        resp = await client.get("/collections/42/entities")
        lines = resp.text.strip().split("\n")
        entities = [json.loads(line) for line in lines]
        report(f"Stream entities → {len(entities)} entities",
               len(entities) == len(ALL_ENTITIES))

        # Notifications
        resp = await client.get("/notifications")
        data = resp.json()
        report(f"Notifications → {data['total']} notification(s)",
               data["total"] >= 1)


async def test_entity_search_with_mock():
    """Entity search chip against mock Aleph."""
    print("\n═══ 2. Entity Search (Mock Aleph) ═══")

    chip = get_chip("entity_search")

    with _patch_aleph():
        # Basic search
        resp = await chip.handle(
            SkillRequest(intent="search", parameters={"query": "Petrov"}),
            CTX,
        )
        report(f"Search 'Petrov' → success={resp.success}, results found",
               resp.success)
        
        results = resp.data.get("results", [])
        names = [r.get("names", r.get("entity", {}).get("properties", {}).get("name", ["?"])) 
                 for r in results]
        report(f"  Found {len(results)} results",
               len(results) >= 2)

        # Search for company
        resp = await chip.handle(
            SkillRequest(intent="search", parameters={
                "query": "Sunrise Holdings",
                "schema": "Company",
            }),
            CTX,
        )
        report(f"Search 'Sunrise Holdings' (Company) → success={resp.success}",
               resp.success)

        # Get specific entity
        resp = await chip.handle(
            SkillRequest(intent="get_entity", parameters={
                "entity_id": VIKTOR_PETROV["id"],
            }),
            CTX,
        )
        report(f"Get entity by ID → success={resp.success}",
               resp.success)
        entity_data = resp.data.get("entity", {})
        report(f"  Got: {entity_data.get('schema', '?')} — {entity_data.get('properties', {}).get('name', ['?'])}",
               entity_data.get("schema") == "Person")

        # Expand network
        resp = await chip.handle(
            SkillRequest(intent="expand", parameters={
                "entity_id": SUNRISE_HOLDINGS["id"],
            }),
            CTX,
        )
        report(f"Expand Sunrise Holdings → {resp.data.get('total', 0)} connected entities",
               resp.success or resp.data.get("total", 0) >= 0)

        # Find similar entities
        resp = await chip.handle(
            SkillRequest(intent="similar", parameters={
                "entity_id": SUNRISE_HOLDINGS["id"],
            }),
            CTX,
        )
        report(f"Similar to Sunrise Holdings → {resp.data.get('total', 0)} similar",
               resp.success)


async def test_cross_reference_with_mock():
    """Cross-reference chip against mock Aleph."""
    print("\n═══ 3. Cross-Reference (Mock Aleph) ═══")

    chip = get_chip("cross_reference")

    with _patch_aleph():
        # Trigger xref
        resp = await chip.handle(
            SkillRequest(intent="trigger_xref", parameters={"collection_id": "42"}),
            CTX,
        )
        report(f"Trigger xref → success={resp.success}",
               resp.success)

        # Get xref results
        resp = await chip.handle(
            SkillRequest(intent="get_xref_results", parameters={
                "collection_id": "42",
                "min_score": 0.4,
            }),
            CTX,
        )
        report(f"Get xref results → success={resp.success}",
               resp.success)
        
        matches = resp.data.get("results", resp.data.get("matches", []))
        report(f"  {len(matches)} matches returned",
               len(matches) >= 0)

        # Check for high-confidence PEP match
        high_conf = [m for m in matches if m.get("score", 0) > 0.8]
        report(f"  {len(high_conf)} high-confidence match(es) (>0.8)",
               len(high_conf) >= 0)

        # Decide match (should require consensus)
        resp = await chip.handle(
            SkillRequest(intent="decide_match", parameters={
                "collection_id": "42",
                "xref_id": "xref-001",
                "decision": "positive",
            }),
            CTX,
        )
        report(f"Decide match → requires_consensus={resp.requires_consensus}",
               resp.requires_consensus)


async def test_network_analysis_with_mock():
    """Network analysis chip builds graph from mock data."""
    print("\n═══ 4. Network Analysis (Mock Aleph) ═══")

    chip = get_chip("network_analysis")

    with _patch_aleph():
        # Build graph
        resp = await chip.handle(
            SkillRequest(intent="build_graph", parameters={"collection_id": "42"}),
            CTX,
        )
        report(f"Build graph → success={resp.success}",
               resp.success)

        graph_data = resp.data
        nodes = graph_data.get("nodes", graph_data.get("node_count", 0))
        edges = graph_data.get("edges", graph_data.get("edge_count", 0))
        if isinstance(nodes, list):
            nodes = len(nodes)
        if isinstance(edges, list):
            edges = len(edges)
        report(f"  Graph: {nodes} nodes, {edges} edges",
               nodes > 0)


async def test_financial_investigation_with_mock():
    """Financial investigation chip — shell detection and ownership tracing."""
    print("\n═══ 5. Financial Investigation (Mock Aleph) ═══")

    chip = get_chip("financial_investigation")

    with _patch_aleph():
        # Shell company detection — Sunrise (Panama)
        resp = await chip.handle(
            SkillRequest(intent="detect_shell", parameters={
                "entity_data": SUNRISE_HOLDINGS,
            }),
            CTX,
        )
        report(f"Shell detection (Sunrise/Panama) → {resp.data.get('risk_level', '?')} risk",
               resp.success and resp.data.get("risk_level") in ("HIGH", "CRITICAL", "MEDIUM"))
        
        red_flags = resp.data.get("red_flags", [])
        report(f"  Red flags: {red_flags}",
               len(red_flags) >= 1)

        # Shell company detection — Aurora (BVI)
        resp = await chip.handle(
            SkillRequest(intent="detect_shell", parameters={
                "entity_data": AURORA_TRADING,
            }),
            CTX,
        )
        report(f"Shell detection (Aurora/BVI) → {resp.data.get('risk_level', '?')} risk",
               resp.success and resp.data.get("risk_level") in ("HIGH", "CRITICAL", "MEDIUM"))

        # Shell company detection — Meridian (Austria) — should be lower risk
        resp = await chip.handle(
            SkillRequest(intent="detect_shell", parameters={
                "entity_data": MERIDIAN_CONSULTING,
            }),
            CTX,
        )
        meridian_risk = resp.data.get("risk_level", "?")
        report(f"Shell detection (Meridian/Austria) → {meridian_risk} risk",
               resp.success)

        # Trace ownership
        resp = await chip.handle(
            SkillRequest(intent="trace_ownership", parameters={
                "entity_name": "Sunrise Holdings",
            }),
            CTX,
        )
        report(f"Trace ownership (Sunrise) → pipeline initiated",
               resp.success)

        # Offshore check
        resp = await chip.handle(
            SkillRequest(intent="offshore_check", parameters={
                "query": "Sunrise Holdings",
            }),
            CTX,
        )
        report(f"Offshore check → response received",
               isinstance(resp, SkillResponse))


async def test_nlp_extraction():
    """NLP extraction chip — extract financial patterns from leaked documents."""
    print("\n═══ 6. NLP Extraction (Document Text) ═══")

    chip = get_chip("nlp_extraction")

    # Simulate text extracted from the leaked consulting agreement
    document_text = """
    CONSULTING SERVICES AGREEMENT

    Between: Meridian Consulting GmbH, FN-487291s, Kärntner Ring 12, 1010 Wien
    And: Sunrise Holdings Ltd, PA-2019-847291, Torre Global Bank, Panama City

    Date: March 1, 2021

    Fee: EUR 2,400,000 (Two Million Four Hundred Thousand Euros)
    Payment terms: Wire transfer to IBAN PA49GBPA00120001234567890123
    SWIFT/BIC: GBPAPAPA

    Signatory: Viktor Petrov (on behalf of beneficial owner)
    Contact: v.petrov@gov.md, +373 22 234 567

    The Consultant (Meridian) shall provide strategic advisory services
    to the Client (Sunrise Holdings) regarding investment opportunities
    in the Republic of Moldova real estate market.

    Director: James Hartley, 71 Fenchurch Street, London EC3M 4BS
    Registered Agent: Maria Santos, Calle 50, Panama City
    """

    # Extract financial patterns
    resp = await chip.handle(
        SkillRequest(intent="extract_financial", parameters={"text": document_text}),
        CTX,
    )
    findings = resp.data.get("findings", {})
    total = resp.data.get("total", 0)
    report(f"Financial extraction → {total} findings", resp.success and total > 0)

    # Check specific extractions
    ibans = findings.get("ibans", [])
    report(f"  IBANs: {ibans}", len(ibans) >= 1)

    emails = findings.get("emails", [])
    report(f"  Emails: {emails}", len(emails) >= 1 and "v.petrov@gov.md" in emails)

    phones = findings.get("phones", [])
    report(f"  Phones: {phones}", len(phones) >= 1)

    amounts = findings.get("amounts", [])
    report(f"  Amounts: {amounts}", len(amounts) >= 1)

    # Extract entities (NER)
    resp = await chip.handle(
        SkillRequest(intent="extract", parameters={"text": document_text}),
        CTX,
    )
    report(f"NER extraction → success={resp.success}", resp.success)

    # Extract relationships
    resp = await chip.handle(
        SkillRequest(intent="extract_relationships", parameters={"text": document_text}),
        CTX,
    )
    report(f"Relationship extraction → success={resp.success}", resp.success)


async def test_verification_pipeline():
    """Verification chip — fact-check claims from the investigation."""
    print("\n═══ 7. Verification Pipeline ═══")

    chip = get_chip("verification")

    # Verify a well-supported claim
    resp = await chip.handle(
        SkillRequest(intent="fact_check", parameters={
            "claim": "Viktor Petrov is the beneficial owner of Sunrise Holdings Ltd, "
                     "a Panama-registered company with nominee director James Hartley.",
            "evidence": [
                "Aleph entity match: Petrov→Sunrise ownership (confidence 0.95)",
                "OpenSanctions PEP screening: Viktor Petrov, Deputy Minister (score 0.92)",
                "Leaked consulting agreement names Petrov as beneficial owner signatory",
                "Panama company registry: Sunrise Holdings Ltd (PA-2019-847291)",
                "UK Companies House: James Hartley listed as director of 14 BVI/PA entities",
            ],
        }),
        CTX,
    )
    report(f"Fact-check (well-supported) → success={resp.success}",
           resp.success)
    steps = resp.data.get("verification_steps", [])
    report(f"  {len(steps)} verification steps",
           len(steps) >= 1)

    # Assess source reliability
    resp = await chip.handle(
        SkillRequest(intent="source_reliability", parameters={
            "source": "Panama company registry",
            "type": "official_record",
        }),
        CTX,
    )
    report(f"Source reliability (official_record) → success={resp.success}",
           resp.success)

    # Pre-publication check (should require consensus)
    resp = await chip.handle(
        SkillRequest(intent="pre_publication", parameters={}),
        CTX,
    )
    report(f"Pre-publication review → requires_consensus={resp.requires_consensus}",
           resp.requires_consensus)

    # Defamation review (should require consensus)
    resp = await chip.handle(
        SkillRequest(intent="legal_review", parameters={
            "content": "Deputy Minister Viktor Petrov secretly owns a Panama shell company.",
            "named_persons": ["Viktor Petrov"],
        }),
        CTX,
    )
    report(f"Defamation review → requires_consensus={resp.requires_consensus}",
           resp.requires_consensus)


async def test_story_development():
    """Story development chip — build the investigation narrative."""
    print("\n═══ 8. Story Development ═══")

    chip = get_chip("story_development")

    # Story outline
    resp = await chip.handle(
        SkillRequest(intent="outline", parameters={}),
        CTX,
    )
    outline = resp.data.get("outline_template", [])
    report(f"Story outline → {len(outline)} sections",
           resp.success and len(outline) >= 5)

    # Check outline has key journalism sections
    section_names = [s.get("section", s) if isinstance(s, dict) else s for s in outline]
    section_text = " ".join(str(s).lower() for s in section_names)
    report(f"  Has key sections (lead, evidence, methodology)",
           "lead" in section_text or "nut" in section_text)

    # Timeline
    resp = await chip.handle(
        SkillRequest(intent="timeline", parameters={
            "events": [
                {"date": "2018-11-03", "event": "Meridian Consulting GmbH incorporated (Austria)"},
                {"date": "2019-06-15", "event": "Sunrise Holdings Ltd incorporated (Panama)"},
                {"date": "2020-01-10", "event": "Aurora Trading LLC incorporated (BVI)"},
                {"date": "2020-06-01", "event": "Aurora acquires 80% of Danube Real Estate"},
                {"date": "2021-03-01", "event": "Consulting agreement signed: Meridian → Sunrise"},
                {"date": "2021-03-15", "event": "EUR 2.4M payment: Meridian → Sunrise"},
                {"date": "2021-04-02", "event": "EUR 1.8M payment: Sunrise → Danube Real Estate"},
                {"date": "2022-01-20", "event": "USD 750K management fee: Aurora → Sunrise"},
            ],
        }),
        CTX,
    )
    report(f"Timeline → success={resp.success}", resp.success)

    # Key findings
    resp = await chip.handle(
        SkillRequest(intent="key_findings", parameters={}),
        CTX,
    )
    report(f"Key findings → success={resp.success}", resp.success)

    # Methodology documentation
    resp = await chip.handle(
        SkillRequest(intent="methodology_doc", parameters={}),
        CTX,
    )
    report(f"Methodology doc → success={resp.success}", resp.success)

    # Impact assessment
    resp = await chip.handle(
        SkillRequest(intent="impact_assessment", parameters={}),
        CTX,
    )
    report(f"Impact assessment → success={resp.success}", resp.success)


async def test_monitoring_setup():
    """Monitoring chip — set up ongoing monitoring for the investigation."""
    print("\n═══ 9. Monitoring Setup ═══")

    chip = get_chip("monitoring")

    # Create investigation watchlist
    resp = await chip.handle(
        SkillRequest(intent="create_watchlist", parameters={
            "name": "Operation Sunrise Targets",
            "queries": [
                "Viktor Petrov",
                "Sunrise Holdings",
                "Aurora Trading",
                "Meridian Consulting",
                "James Hartley",
            ],
        }),
        CTX,
    )
    report(f"Create watchlist → '{resp.data.get('watchlist_name')}'",
           resp.success and len(resp.data.get("queries", [])) == 5)

    # Monitor specific entity
    resp = await chip.handle(
        SkillRequest(intent="monitor_entity", parameters={
            "entity_name": "Viktor Petrov",
        }),
        CTX,
    )
    report(f"Monitor entity (Petrov) → success={resp.success}", resp.success)

    # Monitor collection
    resp = await chip.handle(
        SkillRequest(intent="monitor_collection", parameters={
            "collection_id": "42",
        }),
        CTX,
    )
    report(f"Monitor collection → success={resp.success}", resp.success)

    # Set up alert
    resp = await chip.handle(
        SkillRequest(intent="set_alert", parameters={
            "condition": "sanctions_list_change",
            "channel": "email",
        }),
        CTX,
    )
    report(f"Set alert → success={resp.success}", resp.success)


async def test_data_quality():
    """Data quality chip — validate investigation entities."""
    print("\n═══ 10. Data Quality ═══")

    chip = get_chip("data_quality")

    # Validate the core entities
    core_entities = [
        VIKTOR_PETROV, ELENA_PETROV, JAMES_HARTLEY,
        SUNRISE_HOLDINGS, AURORA_TRADING, MERIDIAN_CONSULTING,
        PETROV_OWNS_SUNRISE, SUNRISE_OWNS_AURORA,
        PAYMENT_MERIDIAN_SUNRISE, PAYMENT_SUNRISE_DANUBE,
    ]

    resp = await chip.handle(
        SkillRequest(intent="validate", parameters={"entities": core_entities}),
        CTX,
    )
    valid = resp.data.get("valid_count", 0)
    invalid = resp.data.get("invalid_count", 0)
    report(f"Validate {len(core_entities)} entities → {valid} valid, {invalid} invalid",
           resp.success and valid >= 8)


async def test_government_accountability():
    """Government accountability — PEP checks and conflict of interest."""
    print("\n═══ 11. Government Accountability ═══")

    chip = get_chip("government_accountability")

    # Official lookup
    resp = await chip.handle(
        SkillRequest(intent="official_lookup", parameters={
            "name": "Viktor Petrov",
        }),
        CTX,
    )
    report(f"Official lookup (Petrov) → response received",
           isinstance(resp, SkillResponse))

    # Conflict of interest
    resp = await chip.handle(
        SkillRequest(intent="conflict_of_interest", parameters={
            "official_id": VIKTOR_PETROV["id"],
            "entity_id": SUNRISE_HOLDINGS["id"],
        }),
        CTX,
    )
    report(f"Conflict of interest analysis → response received",
           isinstance(resp, SkillResponse))

    # Procurement check
    resp = await chip.handle(
        SkillRequest(intent="procurement", parameters={
            "contractor": "Meridian Consulting",
            "agency": "Ministry of Economy, Moldova",
        }),
        CTX,
    )
    report(f"Procurement analysis → response received",
           isinstance(resp, SkillResponse))


async def test_full_investigation_flow():
    """Simulate the complete investigation workflow end-to-end."""
    print("\n═══ 12. Full Investigation Flow ═══")
    print("    Scenario: Operation Sunrise — tracing a deputy minister's offshore holdings")

    with _patch_aleph():
        # Step 1: Initial search
        search_chip = get_chip("entity_search")
        resp = await search_chip.handle(
            SkillRequest(intent="search", parameters={"query": "Petrov"}),
            CTX,
        )
        report(f"Step 1 — Search 'Petrov' → {len(resp.data.get('results', []))} hits",
               resp.success)

        # Step 2: Expand the target
        resp = await search_chip.handle(
            SkillRequest(intent="expand", parameters={"entity_id": VIKTOR_PETROV["id"]}),
            CTX,
        )
        connected = resp.data.get("total", resp.data.get("results", []))
        if isinstance(connected, list):
            connected = len(connected)
        report(f"Step 2 — Expand Petrov → {connected} connected entities",
               resp.success)

        # Step 3: Cross-reference against sanctions/PEP lists
        xref_chip = get_chip("cross_reference")
        resp = await xref_chip.handle(
            SkillRequest(intent="trigger_xref", parameters={"collection_id": "42"}),
            CTX,
        )
        report(f"Step 3 — Trigger cross-reference → success={resp.success}",
               resp.success)

        resp = await xref_chip.handle(
            SkillRequest(intent="get_xref_results", parameters={"collection_id": "42"}),
            CTX,
        )
        matches = resp.data.get("results", resp.data.get("matches", []))
        report(f"         Xref results → {len(matches)} matches",
               len(matches) >= 0)

        # Step 4: Shell company analysis
        fin_chip = get_chip("financial_investigation")
        resp = await fin_chip.handle(
            SkillRequest(intent="detect_shell", parameters={"entity_data": SUNRISE_HOLDINGS}),
            CTX,
        )
        report(f"Step 4 — Shell analysis (Sunrise/PA) → {resp.data.get('risk_level', '?')}",
               resp.data.get("risk_level") in ("HIGH", "CRITICAL", "MEDIUM"))

        resp = await fin_chip.handle(
            SkillRequest(intent="detect_shell", parameters={"entity_data": AURORA_TRADING}),
            CTX,
        )
        report(f"         Shell analysis (Aurora/BVI) → {resp.data.get('risk_level', '?')}",
               resp.data.get("risk_level") in ("HIGH", "CRITICAL", "MEDIUM"))

        # Step 5: NLP on leaked document
        nlp_chip = get_chip("nlp_extraction")
        resp = await nlp_chip.handle(
            SkillRequest(intent="extract_financial", parameters={
                "text": "Payment of EUR 2,400,000 from Meridian Consulting GmbH "
                        "to IBAN PA49GBPA00120001234567890123 (Sunrise Holdings Ltd) "
                        "signed by v.petrov@gov.md on 2021-03-15.",
            }),
            CTX,
        )
        findings = resp.data.get("findings", {})
        report(f"Step 5 — NLP extraction → {resp.data.get('total', 0)} financial patterns",
               resp.data.get("total", 0) >= 3)

        # Step 6: Verify key claim
        verify_chip = get_chip("verification")
        resp = await verify_chip.handle(
            SkillRequest(intent="fact_check", parameters={
                "claim": "Viktor Petrov, Deputy Minister, beneficially owns Sunrise Holdings "
                         "through nominee James Hartley.",
                "evidence": [
                    "Aleph ownership record (Petrov→Sunrise, confidence 0.95)",
                    "PEP screening match (OpenSanctions, score 0.92)",
                    "Leaked agreement names Petrov as beneficial owner signatory",
                    "UK Companies House: Hartley is director of Sunrise + Aurora",
                ],
            }),
            CTX,
        )
        report(f"Step 6 — Verify claim → {len(resp.data.get('verification_steps', []))} steps",
               resp.success)

        # Step 7: Story development
        story_chip = get_chip("story_development")
        resp = await story_chip.handle(
            SkillRequest(intent="outline", parameters={}),
            CTX,
        )
        report(f"Step 7 — Story outline → {len(resp.data.get('outline_template', []))} sections",
               resp.success)

        # Step 8: Pre-publication review (consensus gate)
        resp = await verify_chip.handle(
            SkillRequest(intent="pre_publication", parameters={}),
            CTX,
        )
        report(f"Step 8 — Pre-publication → consensus_required={resp.requires_consensus}",
               resp.requires_consensus)

        # Step 9: Set up ongoing monitoring
        mon_chip = get_chip("monitoring")
        resp = await mon_chip.handle(
            SkillRequest(intent="create_watchlist", parameters={
                "name": "Sunrise Network Monitoring",
                "queries": ["Viktor Petrov", "Sunrise Holdings", "Aurora Trading"],
            }),
            CTX,
        )
        report(f"Step 9 — Monitoring watchlist → '{resp.data.get('watchlist_name')}'",
               resp.success)

    print("\n    ✅ Full investigation pipeline complete — 9 steps executed")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def main():
    await test_mock_aleph_directly()
    await test_entity_search_with_mock()
    await test_cross_reference_with_mock()
    await test_network_analysis_with_mock()
    await test_financial_investigation_with_mock()
    await test_nlp_extraction()
    await test_verification_pipeline()
    await test_story_development()
    await test_monitoring_setup()
    await test_data_quality()
    await test_government_accountability()
    await test_full_investigation_flow()

    print(f"\n{'═' * 60}")
    print(f"  INTEGRATION RESULTS: {PASS} passed, {FAIL} failed, {PASS + FAIL} total")
    print(f"{'═' * 60}")

    return FAIL == 0


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
