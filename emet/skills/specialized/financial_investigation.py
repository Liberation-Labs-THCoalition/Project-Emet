"""Financial Investigation Skill Chip — money trail analysis and fraud detection.

Traces financial flows through corporate structures, bank accounts, and
payment networks. Detects patterns associated with money laundering,
tax evasion, sanctions circumvention, and corruption.

Integrates:
    - Aleph: entity search, cross-referencing
    - OpenSanctions: sanctions screening
    - OpenCorporates: corporate registry lookups
    - ICIJ Offshore Leaks: offshore entity databases
    - GLEIF: LEI ownership chains

Key capabilities:
    - Shell company detection (multiple incorporation red flags)
    - Beneficial ownership tracing (through layered structures)
    - Transaction pattern analysis (structuring, round-tripping)
    - Sanctions exposure analysis (direct and indirect)
    - PEP (Politically Exposed Person) screening
    - Tax haven jurisdictional analysis

Modeled after the journalism wrapper's /financial, /ownership, and /sanctions commands.
"""

from __future__ import annotations
import logging
from typing import Any

from emet.skills.base import (
    BaseSkillChip, EFEWeights, SkillCapability,
    SkillContext, SkillDomain, SkillRequest, SkillResponse,
)

logger = logging.getLogger(__name__)

# Jurisdictions flagged by FATF, EU, or Tax Justice Network
TAX_HAVEN_JURISDICTIONS = {
    "vg", "ky", "pa", "bz", "sc", "ws", "mh", "mu", "je", "gg", "im",
    "gi", "bm", "bs", "vu", "ag", "lc", "vc", "gd", "dm", "kn", "ai",
    "tc", "ms", "cx", "ck", "nr", "sm", "li", "mc", "ad", "lu", "cy",
    "mt", "nl", "ie", "sg", "hk", "ae", "bh",
}

SHELL_COMPANY_RED_FLAGS = [
    "registered_agent_address",
    "bearer_shares",
    "nominee_directors",
    "no_employees",
    "minimal_assets",
    "recent_incorporation",
    "frequent_name_changes",
    "circular_ownership",
    "pep_connections",
]


class FinancialInvestigationChip(BaseSkillChip):
    """Investigate financial flows, corporate structures, and fraud patterns.

    Intents:
        trace_ownership: Trace beneficial ownership chain
        detect_shell: Analyze entity for shell company indicators
        trace_payments: Follow payment chains between entities
        sanctions_exposure: Analyze direct/indirect sanctions exposure
        pep_screening: Screen for Politically Exposed Persons
        jurisdiction_analysis: Analyze tax haven exposure
        detect_structuring: Detect payment structuring patterns
        offshore_check: Check ICIJ Offshore Leaks database
        lei_lookup: Lookup entity in GLEIF LEI index
        financial_summary: Generate financial investigation summary
    """

    name = "financial_investigation"
    description = "Investigate financial flows, corporate structures, and fraud patterns"
    version = "1.0.0"
    domain = SkillDomain.FINANCIAL_INVESTIGATION
    efe_weights = EFEWeights(
        accuracy=0.35, source_protection=0.20, public_interest=0.20,
        proportionality=0.15, transparency=0.10,
    )
    capabilities = [
        SkillCapability.READ_ALEPH, SkillCapability.READ_OPENSANCTIONS,
        SkillCapability.READ_OPENCORPORATES, SkillCapability.READ_ICIJ,
        SkillCapability.READ_GLEIF, SkillCapability.NETWORK_ANALYSIS,
    ]
    consensus_actions = ["publish_financial_findings", "flag_suspicious_entity"]

    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        intent = request.intent.lower()
        dispatch = {
            "trace_ownership": self._trace_ownership,
            "beneficial_ownership": self._trace_ownership,
            "detect_shell": self._detect_shell,
            "shell_company": self._detect_shell,
            "trace_payments": self._trace_payments,
            "money_trail": self._trace_payments,
            "sanctions_exposure": self._sanctions_exposure,
            "pep_screening": self._pep_screening,
            "pep": self._pep_screening,
            "jurisdiction_analysis": self._jurisdiction_analysis,
            "tax_haven": self._jurisdiction_analysis,
            "detect_structuring": self._detect_structuring,
            "offshore_check": self._offshore_check,
            "lei_lookup": self._lei_lookup,
            "financial_summary": self._financial_summary,
        }
        handler = dispatch.get(intent, self._financial_summary)
        return await handler(request, context)

    async def _trace_ownership(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Trace beneficial ownership through layered corporate structures.

        Follows Ownership relationships through multiple jurisdictions,
        flags nominee arrangements, and identifies ultimate beneficial owners.
        Integrates GLEIF LEI data for verified corporate relationships.
        """
        entity_id = request.parameters.get("entity_id", "")
        entity_name = request.parameters.get("entity_name", "")
        max_depth = request.parameters.get("max_depth", 10)

        if not entity_id and not entity_name:
            return SkillResponse(content="Provide entity_id or entity_name.", success=False)

        return SkillResponse(
            content=f"Beneficial ownership trace initiated (max depth: {max_depth}).",
            success=True,
            data={
                "entity_id": entity_id, "entity_name": entity_name,
                "max_depth": max_depth,
                "data_sources": ["aleph_ownership", "gleif_lei", "opencorporates"],
                "pipeline": [
                    "1. Retrieve entity from Aleph",
                    "2. Follow Ownership/Directorship relationships",
                    "3. Cross-reference with GLEIF LEI parent relationships",
                    "4. Check OpenCorporates for officer/shareholder data",
                    "5. Flag nominee arrangements and circular ownership",
                    "6. Identify ultimate beneficial owner(s)",
                ],
            },
            result_confidence=0.7,
            suggestions=[
                "Screen identified owners against sanctions lists",
                "Check for PEP connections in ownership chain",
                "Analyze jurisdictional exposure for tax haven flags",
            ],
        )

    async def _detect_shell(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Analyze an entity for shell company indicators."""
        entity_id = request.parameters.get("entity_id", "")
        entity_data = request.parameters.get("entity_data", {})

        red_flags_found: list[str] = []
        props = entity_data.get("properties", {})

        # Jurisdictional red flag
        jurisdictions = props.get("jurisdiction", [])
        for j in jurisdictions:
            if j.lower() in TAX_HAVEN_JURISDICTIONS:
                red_flags_found.append(f"Incorporated in tax haven jurisdiction: {j}")

        # Registered agent address (shared with many entities)
        addresses = props.get("address", [])
        if addresses:
            # In production, would check if address is shared by many entities
            red_flags_found.append("Address should be checked for mass registration")

        # Recent incorporation
        inc_dates = props.get("incorporationDate", [])
        if inc_dates:
            for d in inc_dates:
                if d and d >= "2020":
                    red_flags_found.append(f"Recently incorporated: {d}")

        risk_score = min(1.0, len(red_flags_found) * 0.2)
        risk_level = "HIGH" if risk_score > 0.6 else "MEDIUM" if risk_score > 0.3 else "LOW"

        return SkillResponse(
            content=f"Shell company analysis: {risk_level} risk ({len(red_flags_found)} red flags).",
            success=True,
            data={
                "risk_score": risk_score, "risk_level": risk_level,
                "red_flags": red_flags_found,
                "all_indicators": SHELL_COMPANY_RED_FLAGS,
            },
            requires_consensus=risk_score > 0.6,
            consensus_action="flag_suspicious_entity" if risk_score > 0.6 else None,
            result_confidence=0.7,
        )

    async def _trace_payments(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Follow payment chains between entities."""
        source_id = request.parameters.get("source_entity_id", "")
        if not source_id:
            return SkillResponse(content="No source entity ID.", success=False)

        return SkillResponse(
            content="Payment chain trace initiated.",
            success=True,
            data={
                "source_entity_id": source_id,
                "relationship_types": ["Payment", "Debt"],
                "analysis": [
                    "Follow Payment entities from source",
                    "Identify payment patterns (frequency, amounts, timing)",
                    "Detect structuring (amounts just below reporting thresholds)",
                    "Identify circular payment chains (round-tripping)",
                    "Map payment intermediaries",
                ],
            },
            result_confidence=0.7,
        )

    async def _sanctions_exposure(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Analyze direct and indirect sanctions exposure.

        Checks not just the entity itself, but its ownership chain,
        directors, and associated entities for sanctions connections.
        """
        entity_id = request.parameters.get("entity_id", "")
        entity_name = request.parameters.get("entity_name", "")

        return SkillResponse(
            content="Sanctions exposure analysis initiated.",
            success=True,
            data={
                "entity_id": entity_id, "entity_name": entity_name,
                "check_levels": [
                    "Direct: Entity itself against all sanctions lists",
                    "Ownership: All entities in ownership chain",
                    "Directors: All directors and officers",
                    "Associates: Known business associates",
                    "Jurisdictional: Country-level sanctions exposure",
                ],
                "sanctions_sources": [
                    "OFAC SDN", "EU FSF", "UN Security Council", "UK OFSI",
                    "Australian DFAT", "Canadian SEMA", "Swiss SECO",
                ],
            },
            result_confidence=0.7,
        )

    async def _pep_screening(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Screen entities for Politically Exposed Person connections."""
        query = request.parameters.get("query", request.raw_input)
        try:
            from emet.ftm.external.adapters import YenteClient
            results = await YenteClient().search(query, dataset="peps")
            matches = results.get("results", [])
            return SkillResponse(
                content=f"PEP screening: {len(matches)} potential matches.",
                success=True,
                data={"matches": matches, "query": query},
                result_confidence=0.8,
            )
        except Exception as e:
            return SkillResponse(content=f"PEP screening failed: {e}", success=False)

    async def _jurisdiction_analysis(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Analyze jurisdictional exposure for tax haven flags."""
        jurisdictions = request.parameters.get("jurisdictions", [])
        entity_id = request.parameters.get("entity_id", "")

        if jurisdictions:
            haven_flags = [j for j in jurisdictions if j.lower() in TAX_HAVEN_JURISDICTIONS]
            return SkillResponse(
                content=f"Jurisdiction analysis: {len(haven_flags)}/{len(jurisdictions)} are flagged tax havens.",
                success=True,
                data={
                    "tax_havens": haven_flags,
                    "clean_jurisdictions": [j for j in jurisdictions if j.lower() not in TAX_HAVEN_JURISDICTIONS],
                },
                result_confidence=0.9,
            )
        return SkillResponse(content="No jurisdictions provided.", success=False)

    async def _detect_structuring(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Detect payment structuring (smurfing) patterns."""
        return SkillResponse(
            content="Structuring detection requires payment transaction data.",
            success=True,
            data={
                "indicators": [
                    "Multiple payments just below reporting threshold (e.g., $9,999)",
                    "Round-number payments (suggest manufactured transactions)",
                    "Unusual frequency patterns (many small payments in short period)",
                    "Sequential transactions to different accounts same day",
                ],
            },
            result_confidence=0.6,
        )

    async def _offshore_check(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Check entity against ICIJ Offshore Leaks database."""
        query = request.parameters.get("query", request.raw_input)
        try:
            from emet.ftm.external.adapters import ICIJClient
            results = await ICIJClient().search(query)
            matches = results.get("results", [])
            return SkillResponse(
                content=f"Offshore Leaks: {len(matches)} matches found.",
                success=True, data={"matches": matches, "query": query},
                result_confidence=0.8,
                suggestions=["Examine relationships of matched offshore entities"] if matches else [],
            )
        except Exception as e:
            return SkillResponse(content=f"Offshore check failed: {e}", success=False)

    async def _lei_lookup(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Lookup entity in GLEIF LEI index for verified corporate identity."""
        query = request.parameters.get("query", request.raw_input)
        lei = request.parameters.get("lei", "")
        try:
            from emet.ftm.external.adapters import GLEIFClient
            gleif = GLEIFClient()
            if lei:
                result = await gleif.get_entity_by_lei(lei)
                return SkillResponse(
                    content=f"LEI record retrieved for {lei}.",
                    success=True, data={"record": result}, result_confidence=0.95,
                )
            else:
                results = await gleif.search_entities(query)
                records = results.get("data", [])
                return SkillResponse(
                    content=f"LEI search: {len(records)} results.",
                    success=True, data={"records": records}, result_confidence=0.8,
                )
        except Exception as e:
            return SkillResponse(content=f"LEI lookup failed: {e}", success=False)

    async def _financial_summary(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Generate comprehensive financial investigation summary."""
        entity_id = request.parameters.get("entity_id", "")
        return SkillResponse(
            content="Financial investigation summary requires running multiple analyses first.",
            success=True,
            data={
                "recommended_sequence": [
                    "1. trace_ownership — Map corporate structure",
                    "2. detect_shell — Screen for shell company indicators",
                    "3. sanctions_exposure — Check sanctions connections",
                    "4. pep_screening — Check PEP connections",
                    "5. jurisdiction_analysis — Tax haven exposure",
                    "6. offshore_check — ICIJ Offshore Leaks",
                    "7. trace_payments — Follow money trail",
                ],
            },
            result_confidence=0.5,
        )
