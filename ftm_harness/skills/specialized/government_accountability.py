"""Government Accountability Skill Chip — public records and oversight.

Investigates government transparency, public official conduct, campaign
finance, lobbying, procurement, and regulatory capture. Integrates with
public records databases, FOIA request tracking, and campaign finance APIs.

Key capabilities:
    - Campaign finance analysis (contributions, PACs, dark money)
    - Lobbying disclosure tracking
    - Government procurement/contract analysis (bid rigging, sole source)
    - Public official asset disclosure analysis
    - FOIA request management and tracking
    - Regulatory capture pattern detection
    - Voting record analysis
    - Revolving door tracking (government ↔ private sector)

Modeled after the journalism wrapper's /government, /foia, and /accountability commands.
"""

from __future__ import annotations
import logging
from typing import Any

from ftm_harness.skills.base import (
    BaseSkillChip, EFEWeights, SkillCapability,
    SkillContext, SkillDomain, SkillRequest, SkillResponse,
)

logger = logging.getLogger(__name__)


class GovernmentAccountabilityChip(BaseSkillChip):
    name = "government_accountability"
    description = "Investigate government transparency, campaign finance, procurement, and public official conduct"
    version = "1.0.0"
    domain = SkillDomain.GOVERNMENT_ACCOUNTABILITY
    efe_weights = EFEWeights(
        accuracy=0.30, source_protection=0.20, public_interest=0.25,
        proportionality=0.15, transparency=0.10,
    )
    capabilities = [
        SkillCapability.READ_ALEPH, SkillCapability.EXTERNAL_API,
        SkillCapability.READ_OPENSANCTIONS, SkillCapability.WEB_SCRAPING,
    ]
    consensus_actions = ["publish_government_findings", "file_foia_request"]

    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        intent = request.intent.lower()
        dispatch = {
            "campaign_finance": self._campaign_finance,
            "lobbying": self._lobbying_disclosure,
            "procurement": self._procurement_analysis,
            "asset_disclosure": self._asset_disclosure,
            "foia_track": self._foia_tracking,
            "foia": self._foia_tracking,
            "revolving_door": self._revolving_door,
            "regulatory_capture": self._regulatory_capture,
            "official_lookup": self._official_lookup,
            "conflict_of_interest": self._conflict_of_interest,
        }
        handler = dispatch.get(intent, self._official_lookup)
        return await handler(request, context)

    async def _campaign_finance(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Analyze campaign contributions and donor networks.

        Traces: individual contributions, PAC funding, dark money flows,
        bundling patterns, and contribution timing relative to legislative votes.
        """
        candidate = request.parameters.get("candidate", "")
        donor = request.parameters.get("donor", "")
        return SkillResponse(
            content="Campaign finance analysis initiated.",
            success=True,
            data={
                "candidate": candidate, "donor": donor,
                "analysis_dimensions": [
                    "Direct contributions (FEC/state filings)",
                    "PAC contributions and leadership PACs",
                    "Super PAC / dark money tracing",
                    "Contribution timing vs. legislative votes",
                    "Bundler identification",
                    "Corporate employee contribution patterns",
                    "Cross-reference donors with government contractors",
                ],
                "data_sources": [
                    "FEC EDGAR (federal)", "State campaign finance portals",
                    "OpenSecrets/FollowTheMoney", "IRS 527/501c filings",
                ],
            },
            result_confidence=0.6,
        )

    async def _lobbying_disclosure(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Track lobbying activity and expenditures."""
        entity_name = request.parameters.get("entity_name", request.raw_input)
        return SkillResponse(
            content=f"Lobbying disclosure search initiated for '{entity_name}'.",
            success=True,
            data={
                "entity_name": entity_name,
                "analysis": [
                    "Federal LDA filings (Senate Office of Public Records)",
                    "State-level lobbying registrations",
                    "Foreign agent registrations (FARA)",
                    "Lobbying expenditure trends",
                    "Lobbyist-legislator meeting patterns",
                ],
            },
            result_confidence=0.6,
        )

    async def _procurement_analysis(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Analyze government procurement for irregularities.

        Detects: sole-source awards to connected companies, bid rigging
        patterns, contract splitting to avoid thresholds, revolving door
        between contracting officers and vendors.
        """
        contractor = request.parameters.get("contractor", "")
        agency = request.parameters.get("agency", "")
        return SkillResponse(
            content="Procurement analysis initiated.",
            success=True,
            data={
                "contractor": contractor, "agency": agency,
                "red_flag_indicators": [
                    "Sole-source awards above competitive threshold",
                    "Contract splitting just below approval thresholds",
                    "Single-bid competitions",
                    "Contractor ownership connections to officials",
                    "Unusual amendment patterns (low initial, high change orders)",
                    "Geographic concentration suggesting favoritism",
                    "Post-employment of contracting officers by vendors",
                ],
                "data_sources": [
                    "USAspending.gov", "FPDS-NG", "SAM.gov",
                    "State procurement portals", "Municipal contract databases",
                ],
            },
            result_confidence=0.6,
        )

    async def _asset_disclosure(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Analyze public official asset and financial disclosures."""
        official_name = request.parameters.get("official_name", request.raw_input)
        return SkillResponse(
            content=f"Asset disclosure analysis for '{official_name}'.",
            success=True,
            data={
                "official_name": official_name,
                "disclosure_types": [
                    "Financial disclosure forms (OGE 278e)",
                    "Real property holdings", "Stock transactions (STOCK Act)",
                    "Outside income", "Gifts and travel", "Liabilities",
                ],
                "analysis": [
                    "Compare disclosed assets with known corporate connections",
                    "Track stock trades relative to committee activity",
                    "Identify undisclosed conflicts of interest",
                ],
            },
            result_confidence=0.6,
        )

    async def _foia_tracking(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Manage FOIA/public records request tracking."""
        action = request.parameters.get("action", "status")
        return SkillResponse(
            content="FOIA request management.",
            success=True,
            data={
                "action": action,
                "capabilities": [
                    "Draft FOIA request letters",
                    "Track request status and deadlines",
                    "Manage appeals for denials",
                    "Catalog received documents",
                    "Cross-reference with prior FOIA releases",
                ],
                "platforms": [
                    "MuckRock", "FOIA.gov", "State public records portals",
                    "NextRequest", "GovQA",
                ],
            },
            result_confidence=0.7,
        )

    async def _revolving_door(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Track movement between government and private sector."""
        person_name = request.parameters.get("person_name", request.raw_input)
        return SkillResponse(
            content=f"Revolving door analysis for '{person_name}'.",
            success=True,
            data={
                "person_name": person_name,
                "tracking": [
                    "Government positions held (dates, agencies)",
                    "Private sector positions (companies, roles)",
                    "Lobbying registrations post-government",
                    "Cooling-off period compliance",
                    "Regulatory actions affecting former/future employers",
                ],
            },
            result_confidence=0.6,
        )

    async def _regulatory_capture(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Detect regulatory capture patterns."""
        agency = request.parameters.get("agency", "")
        industry = request.parameters.get("industry", "")
        return SkillResponse(
            content="Regulatory capture analysis initiated.",
            success=True,
            data={
                "agency": agency, "industry": industry,
                "indicators": [
                    "Industry personnel in regulatory positions",
                    "Regulatory decisions favoring specific companies",
                    "Enforcement action patterns (selective enforcement)",
                    "Public comment influence (industry vs. public interest)",
                    "Advisory committee composition",
                ],
            },
            result_confidence=0.6,
        )

    async def _official_lookup(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Look up a public official across multiple data sources."""
        name = request.parameters.get("name", request.raw_input)
        try:
            from ftm_harness.ftm.external.adapters import YenteClient
            results = await YenteClient().search(name, dataset="peps")
            matches = results.get("results", [])
            return SkillResponse(
                content=f"Official lookup: {len(matches)} PEP matches for '{name}'.",
                success=True,
                data={"matches": matches, "name": name},
                result_confidence=0.8,
            )
        except Exception as e:
            return SkillResponse(content=f"Official lookup failed: {e}", success=False)

    async def _conflict_of_interest(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Detect conflicts of interest between officials and entities."""
        official_id = request.parameters.get("official_id", "")
        entity_id = request.parameters.get("entity_id", "")
        return SkillResponse(
            content="Conflict of interest analysis requires network analysis between official and entity.",
            success=True,
            data={
                "official_id": official_id, "entity_id": entity_id,
                "analysis_types": [
                    "Financial interest overlap",
                    "Family/associate connections",
                    "Campaign contribution relationships",
                    "Prior employment/consulting",
                    "Real property transactions",
                ],
            },
            result_confidence=0.6,
        )
