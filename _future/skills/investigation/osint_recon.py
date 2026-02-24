"""OSINT reconnaissance skill chip for investigative journalism.

Provides technical OSINT capabilities via SpiderFoot integration:
  - Domain reconnaissance (WHOIS, DNS, subdomains, tech stack)
  - Email investigation (breach detection, social profiles)
  - IP address analysis (geolocation, hosting, open ports)
  - Person/company name reconnaissance (social media, public records)

All results are returned as FtM entities with provenance tracking.

Usage::

    chip = OSINTReconChip()
    request = SkillRequest(
        intent="investigate_domain",
        parameters={"target": "example.com", "scan_type": "passive"},
    )
    response = await chip.handle(request, context)
"""

from __future__ import annotations

import logging
from typing import Any

from emet.skills.base import (
    BaseSkillChip,
    EFEWeights,
    SkillCapability,
    SkillContext,
    SkillDomain,
    SkillRequest,
    SkillResponse,
)

logger = logging.getLogger(__name__)


class OSINTReconChip(BaseSkillChip):
    """Technical OSINT reconnaissance via SpiderFoot.

    Wraps 200+ SpiderFoot modules and converts results to FtM entities.
    Supports passive (no direct target contact) and active scanning.

    Intents:
      - investigate_domain: Full domain recon
      - investigate_email: Email breach/profile search
      - investigate_ip: IP address analysis
      - investigate_name: Person/company OSINT
      - list_modules: Show available SpiderFoot modules
    """

    name = "osint_recon"
    description = "Technical OSINT reconnaissance via SpiderFoot (200+ modules)"
    version = "1.0.0"
    domain = SkillDomain.ENTITY_SEARCH
    efe_weights = EFEWeights(
        accuracy=0.30,
        source_protection=0.25,  # OSINT must not expose methods
        public_interest=0.20,
        proportionality=0.15,    # Passive by default
        transparency=0.10,
    )
    capabilities = [
        SkillCapability.EXTERNAL_API,
        SkillCapability.WEB_SCRAPING,
    ]
    consensus_actions = ["active_scan"]  # Active scans require editorial approval

    # Intent → handler mapping
    INTENTS = {
        "investigate_domain",
        "investigate_email",
        "investigate_ip",
        "investigate_name",
        "osint_recon",
        "list_modules",
    }

    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Route to appropriate OSINT handler."""
        intent = request.intent
        params = request.parameters

        # Normalize intent
        if intent not in self.INTENTS:
            intent = "osint_recon"  # Default to general recon

        # Check for active scan consensus requirement
        scan_type = params.get("scan_type", "passive")
        if scan_type == "active" and self.requires_consensus("active_scan"):
            return SkillResponse(
                content=(
                    "Active OSINT scanning requires editorial approval. "
                    "Active scans make direct contact with the target "
                    "(port scanning, content fetching, etc.). "
                    "Please confirm this is appropriate for the investigation."
                ),
                success=False,
                requires_consensus=True,
                consensus_action="active_scan",
                metadata={"target": params.get("target", ""), "scan_type": scan_type},
            )

        if intent == "list_modules":
            return await self._list_modules()

        target = params.get("target", request.raw_input)
        if not target:
            return SkillResponse(
                content="Please provide a target (domain, email, IP, or name) for OSINT reconnaissance.",
                success=False,
            )

        return await self._run_recon(target, scan_type, params.get("modules"))

    async def _run_recon(
        self,
        target: str,
        scan_type: str = "passive",
        modules: list[str] | None = None,
    ) -> SkillResponse:
        """Run SpiderFoot OSINT reconnaissance."""
        try:
            from emet.ftm.external.spiderfoot import SpiderFootClient, SpiderFootConfig

            client = SpiderFootClient(SpiderFootConfig())

            # Check connectivity first
            health = await client.health_check()
            if not health.get("reachable"):
                return SkillResponse(
                    content=(
                        "SpiderFoot service is not reachable. "
                        "Ensure SpiderFoot is running on localhost:5001. "
                        "Start with: `python3 -m spiderfoot -l 127.0.0.1:5001`"
                    ),
                    success=False,
                    metadata={"error": "spiderfoot_unreachable"},
                )

            # Run scan
            result = await client.scan(
                target=target,
                scan_type=scan_type,
                modules=modules,
            )

            entities = result.get("entities", [])
            relationships = result.get("relationships", [])
            schema_counts = result.get("entities_by_schema", {})

            # Build summary
            summary_parts = [
                f"OSINT reconnaissance complete for **{target}**:",
                f"- {result.get('event_count', 0)} raw events collected",
                f"- {len(entities)} FtM entities extracted",
                f"- {len(relationships)} relationships identified",
            ]
            if schema_counts:
                summary_parts.append("- Entity types: " + ", ".join(
                    f"{count} {schema}" for schema, count in schema_counts.items()
                ))

            return SkillResponse(
                content="\n".join(summary_parts),
                success=True,
                data={
                    "scan_id": result.get("scan_id", ""),
                    "target": target,
                    "scan_type": scan_type,
                    "entities_by_schema": schema_counts,
                },
                produced_entities=entities + relationships,
                result_confidence=0.8 if scan_type == "passive" else 0.7,
                suggestions=[
                    f"Run graph analysis on the {len(entities)} discovered entities",
                    "Screen extracted persons/companies against sanctions lists",
                    "Check discovered email addresses for data breaches",
                ],
            )

        except ImportError:
            return SkillResponse(
                content=(
                    "SpiderFoot integration not available. "
                    "Install with: `pip install spiderfoot-client`"
                ),
                success=False,
            )
        except Exception as exc:
            logger.exception("OSINT recon failed for %s", target)
            return SkillResponse(
                content=f"OSINT reconnaissance failed: {exc}",
                success=False,
                metadata={"error": str(exc)},
            )

    async def _list_modules(self) -> SkillResponse:
        """List available SpiderFoot modules."""
        try:
            from emet.ftm.external.spiderfoot import SpiderFootClient, SpiderFootConfig

            client = SpiderFootClient(SpiderFootConfig())
            modules = await client.list_modules()

            return SkillResponse(
                content=f"SpiderFoot has {len(modules)} modules available.",
                success=True,
                data={"module_count": len(modules), "modules": modules},
            )
        except Exception as exc:
            return SkillResponse(
                content=f"Failed to list modules: {exc}",
                success=False,
            )
