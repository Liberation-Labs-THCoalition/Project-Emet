"""End-to-end smoke test for Emet.

Tests: imports, skill chip registry, FtM data spine, orchestrator routing,
skill chip execution, and a simulated investigation flow.
"""

import asyncio
import sys
import traceback

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


# ─── 1. Core Imports ─────────────────────────────────────────────────

print("\n═══ 1. Core Imports ═══")

try:
    from emet.skills.base import (
        BaseSkillChip, SkillDomain, SkillCapability,
        EFEWeights, SkillContext, SkillRequest, SkillResponse,
    )
    report("skills.base", True)
except Exception as e:
    report("skills.base", False, str(e))

try:
    from emet.skills import get_chip, list_chips, SKILL_CHIP_REGISTRY
    report("skills registry", True)
except Exception as e:
    report("skills registry", False, str(e))

try:
    from emet.ftm.data_spine import (
        FtMFactory, FtMDomain, InvestigationEntity,
        CrossReferenceMatch, InvestigationContext,
    )
    report("ftm.data_spine", True)
except Exception as e:
    report("ftm.data_spine", False, str(e))

try:
    from emet.ftm.aleph_client import AlephClient, AlephConfig
    report("ftm.aleph_client", True)
except Exception as e:
    report("ftm.aleph_client", False, str(e))

try:
    from emet.ftm.external.adapters import (
        YenteClient, OpenCorporatesClient, ICIJClient, GLEIFClient,
    )
    report("ftm.external.adapters", True)
except Exception as e:
    report("ftm.external.adapters", False, str(e))

try:
    from emet.cognition.efe import EFECalculator
    report("cognition.efe", True)
except Exception as e:
    report("cognition.efe", False, str(e))

try:
    from emet.cognition.orchestrator import Orchestrator
    report("cognition.orchestrator", True)
except Exception as e:
    report("cognition.orchestrator", False, str(e))

# ─── 2. Skill Chip Registry ─────────────────────────────────────────

print("\n═══ 2. Skill Chip Registry ═══")

expected_chips = [
    "entity_search", "cross_reference", "document_analysis",
    "nlp_extraction", "network_analysis", "data_quality",
    "financial_investigation", "government_accountability",
    "corporate_research", "environmental_investigation",
    "labor_investigation", "monitoring", "verification",
    "story_development", "resources",
]

report(f"Registry has {len(SKILL_CHIP_REGISTRY)} chips", len(SKILL_CHIP_REGISTRY) == 15)

for name in expected_chips:
    try:
        chip = get_chip(name)
        is_base = isinstance(chip, BaseSkillChip)
        has_handle = hasattr(chip, 'handle') and callable(chip.handle)
        has_domain = hasattr(chip, 'domain') and isinstance(chip.domain, SkillDomain)
        report(f"  {name}", is_base and has_handle and has_domain,
               f"base={is_base} handle={has_handle} domain={has_domain}")
    except Exception as e:
        report(f"  {name}", False, str(e))


# ─── 3. FtM Data Spine ──────────────────────────────────────────────

print("\n═══ 3. FtM Data Spine ═══")

try:
    factory = FtMFactory()
    report("FtMFactory instantiation", True)
except Exception as e:
    report("FtMFactory instantiation", False, str(e))

# Create Person entity
try:
    person = factory.make_entity(
        schema="Person",
        properties={"name": "John Smith", "nationality": "gb"},
        id_parts=["John Smith", "Person"],
    )
    report(f"Person entity created (id={person['id'][:12]}...)", 
           person["schema"] == "Person" and "John Smith" in person["properties"]["name"])
except Exception as e:
    report("Person entity", False, str(e))

# Create Company entity
try:
    company = factory.make_entity(
        schema="Company",
        properties={"name": "Acme Holdings Ltd", "jurisdiction": "pa"},
        id_parts=["Acme Holdings Ltd", "Company"],
    )
    report(f"Company entity created (id={company['id'][:12]}...)",
           company["schema"] == "Company")
except Exception as e:
    report("Company entity", False, str(e))

# Create Ownership relationship
try:
    ownership = factory.make_entity(
        schema="Ownership",
        properties={"owner": [person["id"]], "asset": [company["id"]]},
        id_parts=[person["id"], "owns", company["id"]],
    )
    report(f"Ownership entity created", ownership["schema"] == "Ownership")
except Exception as e:
    report("Ownership entity", False, str(e))

# Domain classification
try:
    assert FtMDomain.classify_schema("Person") == FtMDomain.PERSON
    assert FtMDomain.classify_schema("Company") == FtMDomain.LEGAL_ENTITY
    assert FtMDomain.classify_schema("Ownership") == FtMDomain.OWNERSHIP
    assert FtMDomain.classify_schema("Payment") == FtMDomain.FINANCIAL_LINK
    assert FtMDomain.classify_schema("Vessel") == FtMDomain.ASSET
    report("Domain classification (5 schemas)", True)
except Exception as e:
    report("Domain classification", False, str(e))

# Investigation context
try:
    inv_ctx = InvestigationContext(
        investigation_id="test-inv-001",
        title="Acme Holdings Ownership Investigation",
        hypothesis="Test beneficial ownership of Acme Holdings",
        collection_ids=["42"],
        target_entities=[person["id"], company["id"]],
        open_questions=["Who is the ultimate beneficial owner?"],
    )
    report(f"InvestigationContext created", inv_ctx.investigation_id == "test-inv-001")
except Exception as e:
    report("InvestigationContext", False, str(e))


# ─── 4. EFE Weight Profiles ─────────────────────────────────────────

print("\n═══ 4. EFE Weight Profiles ═══")

try:
    from emet.cognition import efe as efe_mod
    expected_profiles = [
        "ENTITY_SEARCH_WEIGHTS", "CROSS_REFERENCE_WEIGHTS",
        "DOCUMENT_ANALYSIS_WEIGHTS", "FINANCIAL_INVESTIGATION_WEIGHTS",
        "VERIFICATION_WEIGHTS", "PUBLICATION_WEIGHTS",
        "DIGITAL_SECURITY_WEIGHTS", "MONITORING_WEIGHTS",
        "DEFAULT_WEIGHTS",
    ]
    profiles = {}
    for name in expected_profiles:
        val = getattr(efe_mod, name, None)
        assert val is not None, f"Missing: {name}"
        profiles[name] = val
    report(f"All {len(expected_profiles)} weight profiles present", True)
except Exception as e:
    report("Weight profiles", False, str(e))

# Verify weights sum to ~1.0
try:
    for name, profile in profiles.items():
        total = profile.risk + profile.ambiguity + profile.epistemic
        assert 0.99 <= total <= 1.01, f"{name} sums to {total}"
    report(f"All {len(profiles)} profiles sum to 1.0", True)
except Exception as e:
    report("Weight profile sums", False, str(e))


# ─── 5. Skill Chip Execution ────────────────────────────────────────

print("\n═══ 5. Skill Chip Execution (async) ═══")

async def test_chip_execution():
    ctx = SkillContext(
        investigation_id="test-001",
        user_id="test-journalist",
        hypothesis="Test investigation",
        collection_ids=["42"],
    )

    # Entity search — with no Aleph connection, should fail gracefully
    chip = get_chip("entity_search")
    req = SkillRequest(intent="search", parameters={"query": "Acme Holdings"})
    resp = await chip.handle(req, ctx)
    # Should fail gracefully (no Aleph running) but still return a response
    report(f"entity_search.search → response (success={resp.success})",
           isinstance(resp, SkillResponse))

    # NLP extraction — regex fallback (no spaCy model needed)
    chip = get_chip("nlp_extraction")
    test_text = """
    John Smith (john.smith@example.com) transferred $500,000 via 
    IBAN GB29NWBK60161331926819 to Acme Holdings Ltd on 2024-01-15.
    Contact: +44 20 7946 0958
    """
    req = SkillRequest(intent="extract_financial", parameters={"text": test_text})
    resp = await chip.handle(req, ctx)
    findings = resp.data.get("findings", {})
    report(f"nlp_extraction.extract_financial → {resp.data.get('total', 0)} findings",
           resp.success and resp.data.get("total", 0) > 0)

    # Check specific extractions
    ibans = findings.get("ibans", [])
    emails = findings.get("emails", [])
    report(f"  Found IBAN: {ibans[0] if ibans else 'none'}",
           len(ibans) > 0 and "GB29" in ibans[0])
    report(f"  Found email: {emails[0] if emails else 'none'}",
           len(emails) > 0 and "john.smith" in emails[0])

    # Financial investigation — shell company detection
    chip = get_chip("financial_investigation")
    req = SkillRequest(
        intent="detect_shell",
        parameters={
            "entity_data": {
                "schema": "Company",
                "properties": {
                    "name": ["Acme Holdings Ltd"],
                    "jurisdiction": ["pa"],  # Panama — tax haven
                    "incorporationDate": ["2023-06-15"],  # Recent
                    "address": ["Calle 50, Torre Global Bank, Panama City"],
                },
            },
        },
    )
    resp = await chip.handle(req, ctx)
    risk_level = resp.data.get("risk_level", "")
    red_flags = resp.data.get("red_flags", [])
    report(f"financial_investigation.detect_shell → {risk_level} risk, {len(red_flags)} red flags",
           resp.success and len(red_flags) > 0)

    # Verification — claim check
    chip = get_chip("verification")
    req = SkillRequest(
        intent="fact_check",
        parameters={
            "claim": "Acme Holdings is a shell company in Panama",
            "evidence": ["OpenCorporates record", "ICIJ match"],
        },
    )
    resp = await chip.handle(req, ctx)
    report(f"verification.fact_check → verification steps provided",
           resp.success and "verification_steps" in resp.data)

    # Network analysis — build graph (will fail gracefully without Aleph)
    chip = get_chip("network_analysis")
    req = SkillRequest(intent="build_graph", parameters={"collection_id": "42"})
    resp = await chip.handle(req, ctx)
    report(f"network_analysis.build_graph → response (success={resp.success})",
           isinstance(resp, SkillResponse))

    # Data quality — validate entities
    chip = get_chip("data_quality")
    req = SkillRequest(
        intent="validate",
        parameters={"entities": [person, company, ownership]},
    )
    resp = await chip.handle(req, ctx)
    report(f"data_quality.validate → {resp.data.get('valid_count', 0)} valid, {resp.data.get('invalid_count', 0)} invalid",
           resp.success)

    # Monitoring — create watchlist
    chip = get_chip("monitoring")
    req = SkillRequest(
        intent="create_watchlist",
        parameters={"name": "Acme Investigation", "queries": ["Acme Holdings", "John Smith"]},
    )
    resp = await chip.handle(req, ctx)
    report(f"monitoring.create_watchlist → '{resp.data.get('watchlist_name')}'",
           resp.success and resp.data.get("watchlist_name") == "Acme Investigation")

    # Story development — outline
    chip = get_chip("story_development")
    req = SkillRequest(intent="outline", parameters={})
    resp = await chip.handle(req, ctx)
    report(f"story_development.outline → {len(resp.data.get('outline_template', []))} sections",
           resp.success and len(resp.data.get("outline_template", [])) > 0)

    # Government accountability — PEP screening (will fail without API)
    chip = get_chip("government_accountability")
    req = SkillRequest(intent="official_lookup", parameters={"name": "Test Official"})
    resp = await chip.handle(req, ctx)
    report(f"government_accountability.official_lookup → response (success={resp.success})",
           isinstance(resp, SkillResponse))

    # Corporate research — company search (will fail without API)
    chip = get_chip("corporate_research")
    req = SkillRequest(intent="company", parameters={"query": "Acme Holdings"})
    resp = await chip.handle(req, ctx)
    report(f"corporate_research.company → response (success={resp.success})",
           isinstance(resp, SkillResponse))

    # Resources chip
    chip = get_chip("resources")
    req = SkillRequest(intent="help", parameters={})
    resp = await chip.handle(req, ctx)
    report(f"resources.help → response",
           isinstance(resp, SkillResponse) and resp.success)

asyncio.run(test_chip_execution())


# ─── 6. Orchestrator Keyword Routing ────────────────────────────────

print("\n═══ 6. Orchestrator Routing ═══")

try:
    from emet.cognition.orchestrator import Orchestrator, OrchestratorConfig, RoutingDecision
    orch = Orchestrator(OrchestratorConfig())

    # Test keyword routing (classify_request is async)
    test_cases = [
        ("find John Smith in Aleph", "entity_search"),
        ("cross reference xref this collection", "cross_reference"),
        ("upload this PDF document to the collection", "document_analysis"),
        ("run NER extract entities from this text", "nlp_extraction"),
        ("build a network graph of connections", "network_analysis"),
        ("trace the financial money trail", "financial_investigation"),
        ("check campaign finance lobby records", "government_accountability"),
        ("opencorporates company registry corporate tree", "corporate_research"),
        ("check EPA pollution emissions data", "environmental_investigation"),
        ("search OSHA workplace labor violations", "labor_investigation"),
        ("set up a watchlist monitor alert", "monitoring"),
        ("verify and fact-check this claim", "verification"),
        ("build a timeline for the story", "publication"),
        ("clean normalize data quality of entities", "data_quality"),
    ]

    async def test_routing():
        routed = 0
        for msg, expected_domain in test_cases:
            result = await orch.classify_request(msg)
            domain = result.skill_domain
            ok = domain == expected_domain
            if ok:
                routed += 1
            else:
                report(f"  Route '{msg[:40]}...' → expected {expected_domain}, got {domain}", False)
        return routed

    routed = asyncio.run(test_routing())
    report(f"Keyword routing: {routed}/{len(test_cases)} messages routed correctly",
           routed == len(test_cases))

except Exception as e:
    report("Orchestrator routing", False, f"{e}\n{traceback.format_exc()}")


# ─── 7. Aleph Client Structure ──────────────────────────────────────

print("\n═══ 7. Aleph Client API Surface ═══")

try:
    client = AlephClient(AlephConfig(host="http://localhost:8080", api_key="test"))
    expected_methods = [
        "search", "get_entity", "get_entity_references", "get_entity_expand",
        "get_similar_entities", "list_collections", "get_collection",
        "create_collection", "stream_entities", "write_entities",
        "trigger_xref", "get_xref_results", "decide_xref",
        "ingest_file", "list_entity_sets", "create_entity_set",
        "get_notifications", "reingest_collection", "reindex_collection",
    ]
    missing = [m for m in expected_methods if not hasattr(client, m)]
    report(f"AlephClient has {len(expected_methods) - len(missing)}/{len(expected_methods)} methods",
           len(missing) == 0, f"Missing: {missing}" if missing else "")
except Exception as e:
    report("AlephClient API surface", False, str(e))


# ─── 8. External Adapter Structure ──────────────────────────────────

print("\n═══ 8. External Adapters ═══")

try:
    yente = YenteClient()
    for method in ["search", "match_entity", "get_entity", "screen_entities"]:
        assert hasattr(yente, method), f"YenteClient missing {method}"
    report("YenteClient — 4 methods", True)
except Exception as e:
    report("YenteClient", False, str(e))

try:
    oc = OpenCorporatesClient()
    for method in ["search_companies", "get_company", "search_officers", "company_to_ftm"]:
        assert hasattr(oc, method), f"OpenCorporatesClient missing {method}"
    report("OpenCorporatesClient — 4 methods", True)
except Exception as e:
    report("OpenCorporatesClient", False, str(e))

try:
    icij = ICIJClient()
    for method in ["search", "get_entity", "get_relationships"]:
        assert hasattr(icij, method), f"ICIJClient missing {method}"
    report("ICIJClient — 3 methods", True)
except Exception as e:
    report("ICIJClient", False, str(e))

try:
    gleif = GLEIFClient()
    for method in ["search_entities", "get_entity_by_lei", "get_direct_parent",
                    "get_ultimate_parent", "get_children", "lei_record_to_ftm"]:
        assert hasattr(gleif, method), f"GLEIFClient missing {method}"
    report("GLEIFClient — 6 methods", True)
except Exception as e:
    report("GLEIFClient", False, str(e))


# ─── 9. VALUES.json ─────────────────────────────────────────────────

print("\n═══ 9. Governance ═══")

try:
    import json
    with open("VALUES.json") as f:
        values = json.load(f)
    
    pillars = values.get("pillars", {})
    expected_pillars = ["accuracy", "source_protection", "public_interest",
                        "proportionality", "transparency"]
    for p in expected_pillars:
        assert p in pillars, f"Missing pillar: {p}"
    
    total_weight = sum(pillars[p]["weight"] for p in expected_pillars)
    report(f"VALUES.json — {len(expected_pillars)} pillars, weight sum = {total_weight}",
           0.99 <= total_weight <= 1.01)
except Exception as e:
    report("VALUES.json", False, str(e))


# ─── Summary ─────────────────────────────────────────────────────────

print(f"\n{'═' * 50}")
print(f"  RESULTS: {PASS} passed, {FAIL} failed, {PASS + FAIL} total")
print(f"{'═' * 50}")

if __name__ == "__main__":
    sys.exit(0 if FAIL == 0 else 1)
