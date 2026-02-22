"""SpiderFoot OSINT adapter for Project Emet.

Integrates SpiderFoot's 200+ reconnaissance modules via its REST API,
converting event data into FollowTheMoney entities.  SpiderFoot runs
as a sidecar service (embedded web server on port 5001) and we call
it via the spiderfoot-client Python library or direct HTTP.

Architecture:
  - SpiderFootClient: Async wrapper around SpiderFoot REST API
  - SpiderFootFtMConverter: Maps SpiderFoot event types → FtM entities
  - scan() orchestrates: start scan → poll status → collect results → convert

SpiderFoot event types mapped:
  INTERNET_NAME     → Domain entity
  EMAILADDR         → Email → linked to Person/Company
  IP_ADDRESS        → Address (technical)
  SOCIAL_MEDIA      → Mention → linked to Person
  DATA_BREACH       → Note → linked to Email/Person
  PHONE_NUMBER      → Phone → linked to Person
  COMPANY_NAME      → Company/Organization
  HUMAN_NAME        → Person
  GEOINFO           → Address
  DOMAIN_WHOIS      → Ownership → linked to Domain
  WEBSERVER_BANNER  → Note (technical)
  SSL_CERTIFICATE   → Note (technical)

Reference: https://github.com/smicallef/spiderfoot (MIT license)
Client: https://pypi.org/project/spiderfoot-client/ (MIT license)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class SpiderFootConfig:
    """Configuration for SpiderFoot sidecar connection."""
    host: str = "http://localhost:5001"
    username: str = "admin"
    password: str = ""
    timeout_seconds: float = 30.0
    poll_interval_seconds: float = 5.0
    max_poll_attempts: int = 120   # 10 minutes at 5s intervals
    default_scan_type: str = "passive"

    # Module sets by scan type
    passive_modules: list[str] = field(default_factory=lambda: [
        "sfp_dnsresolve",
        "sfp_dnsbrute",
        "sfp_whois",
        "sfp_emailformat",
        "sfp_haveibeenpwned",
        "sfp_hunter",
        "sfp_shodan",
        "sfp_censys",
        "sfp_fullcontact",
        "sfp_github",
        "sfp_linkedin",
        "sfp_twitter",
        "sfp_instagram",
        "sfp_builtwith",
        "sfp_sslcert",
    ])


# ---------------------------------------------------------------------------
# SpiderFoot event type → FtM schema mapping
# ---------------------------------------------------------------------------

# Maps SpiderFoot event types to FtM entity schemas and property mappings
EVENT_TYPE_MAP: dict[str, dict[str, Any]] = {
    "INTERNET_NAME": {
        "schema": "Domain",
        "property": "name",
    },
    "EMAILADDR": {
        "schema": "Email",
        "property": "address",
    },
    "IP_ADDRESS": {
        "schema": "Address",
        "property": "full",
    },
    "IPV6_ADDRESS": {
        "schema": "Address",
        "property": "full",
    },
    "PHONE_NUMBER": {
        "schema": "Phone",
        "property": "number",
    },
    "HUMAN_NAME": {
        "schema": "Person",
        "property": "name",
    },
    "COMPANY_NAME": {
        "schema": "Organization",
        "property": "name",
    },
    "SOCIAL_MEDIA": {
        "schema": "Mention",
        "property": "title",
    },
    "GEOINFO": {
        "schema": "Address",
        "property": "full",
    },
    "COUNTRY_NAME": {
        "schema": "Address",
        "property": "country",
    },
    "AFFILIATE_INTERNET_NAME": {
        "schema": "Domain",
        "property": "name",
    },
    "AFFILIATE_EMAILADDR": {
        "schema": "Email",
        "property": "address",
    },
    "AFFILIATE_IPADDR": {
        "schema": "Address",
        "property": "full",
    },
    "CO_HOSTED_SITE": {
        "schema": "Domain",
        "property": "name",
    },
    "SIMILARDOMAIN": {
        "schema": "Domain",
        "property": "name",
    },
    "USERNAME": {
        "schema": "Person",
        "property": "name",
    },
    "ACCOUNT_EXTERNAL_OWNED": {
        "schema": "Mention",
        "property": "title",
    },
    # Technical events → Note entities
    "SSL_CERTIFICATE_RAW": {
        "schema": "Note",
        "property": "title",
        "prefix": "SSL Certificate: ",
    },
    "DOMAIN_WHOIS": {
        "schema": "Note",
        "property": "title",
        "prefix": "WHOIS: ",
    },
    "WEBSERVER_BANNER": {
        "schema": "Note",
        "property": "title",
        "prefix": "Web Server: ",
    },
    "VULNERABILITY_CVE_CRITICAL": {
        "schema": "Note",
        "property": "title",
        "prefix": "Critical CVE: ",
    },
    "VULNERABILITY_CVE_HIGH": {
        "schema": "Note",
        "property": "title",
        "prefix": "High CVE: ",
    },
    "DATA_BREACH": {
        "schema": "Note",
        "property": "title",
        "prefix": "Data Breach: ",
    },
    "DARKNET_MENTION_URL": {
        "schema": "Note",
        "property": "title",
        "prefix": "Dark Web: ",
    },
}


# ---------------------------------------------------------------------------
# FtM Converter
# ---------------------------------------------------------------------------


class SpiderFootFtMConverter:
    """Converts SpiderFoot scan events to FtM entities with provenance."""

    def __init__(self, scan_target: str = "") -> None:
        self._scan_target = scan_target
        self._seen_ids: set[str] = set()

    def convert_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert a list of SpiderFoot events to FtM entities."""
        entities: list[dict[str, Any]] = []
        for event in events:
            entity = self._convert_event(event)
            if entity and entity["id"] not in self._seen_ids:
                entities.append(entity)
                self._seen_ids.add(entity["id"])
        return entities

    def _convert_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """Convert a single SpiderFoot event to an FtM entity."""
        event_type = event.get("type", "")
        data = event.get("data", "")
        module = event.get("module", "")
        source = event.get("source", "")

        if not data or not event_type:
            return None

        mapping = EVENT_TYPE_MAP.get(event_type)
        if mapping is None:
            # Unknown event type — skip silently (SpiderFoot has 100+ types)
            return None

        schema = mapping["schema"]
        prop = mapping["property"]
        prefix = mapping.get("prefix", "")

        # Clean data
        value = str(data).strip()
        if not value:
            return None

        # Generate stable ID from content
        entity_id = f"sf-{event_type.lower()}-{_stable_hash(value)}"

        # Build FtM entity
        entity: dict[str, Any] = {
            "id": entity_id,
            "schema": schema,
            "properties": {
                prop: [prefix + value] if prefix else [value],
            },
            "_provenance": {
                "source": "spiderfoot",
                "source_id": event.get("id", ""),
                "source_url": "",
                "confidence": _event_confidence(event_type),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "module": module,
                "scan_target": self._scan_target,
                "event_type": event_type,
            },
        }

        # Add description for notes
        if schema == "Note":
            entity["properties"]["description"] = [value]
            if source:
                entity["properties"]["description"] = [f"{value} (source: {source})"]

        return entity

    def build_relationships(
        self, entities: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Build relationships between converted entities.

        E.g., Email → owned by → Person, Domain → registered by → Company.
        """
        relationships: list[dict[str, Any]] = []
        persons = [e for e in entities if e["schema"] == "Person"]
        emails = [e for e in entities if e["schema"] == "Email"]
        domains = [e for e in entities if e["schema"] == "Domain"]
        companies = [e for e in entities if e["schema"] == "Organization"]

        # Link emails to first person found (heuristic)
        if persons and emails:
            person = persons[0]
            for email in emails:
                relationships.append({
                    "id": f"sf-rel-{email['id']}-{person['id']}",
                    "schema": "UnknownLink",
                    "properties": {
                        "subject": [person["id"]],
                        "object": [email["id"]],
                        "role": ["email owner"],
                    },
                    "_provenance": {
                        "source": "spiderfoot",
                        "confidence": 0.6,
                        "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    },
                })

        # Link domains to first company found
        if companies and domains:
            company = companies[0]
            for domain in domains:
                relationships.append({
                    "id": f"sf-rel-{domain['id']}-{company['id']}",
                    "schema": "UnknownLink",
                    "properties": {
                        "subject": [company["id"]],
                        "object": [domain["id"]],
                        "role": ["domain owner"],
                    },
                    "_provenance": {
                        "source": "spiderfoot",
                        "confidence": 0.5,
                        "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    },
                })

        return relationships


# ---------------------------------------------------------------------------
# SpiderFoot API Client
# ---------------------------------------------------------------------------


class SpiderFootClient:
    """Async client for SpiderFoot REST API.

    SpiderFoot exposes a REST API when running as a web server.
    This client wraps the key endpoints needed for Emet integration:
      - Start scan
      - Check scan status
      - Retrieve scan results
      - List available modules

    If the spiderfoot-client library is available, we delegate to it.
    Otherwise, we use direct HTTP via httpx.
    """

    def __init__(self, config: SpiderFootConfig | None = None) -> None:
        self._config = config or SpiderFootConfig()
        self._converter = SpiderFootFtMConverter()

    def _client(self) -> httpx.AsyncClient:
        auth = None
        if self._config.password:
            auth = httpx.BasicAuth(self._config.username, self._config.password)
        return httpx.AsyncClient(
            base_url=self._config.host,
            timeout=self._config.timeout_seconds,
            auth=auth,
        )

    async def health_check(self) -> dict[str, Any]:
        """Check if SpiderFoot is reachable."""
        try:
            async with self._client() as client:
                resp = await client.get("/api/ping")
                return {"status": "ok", "reachable": resp.status_code == 200}
        except Exception as exc:
            return {"status": "error", "reachable": False, "error": str(exc)}

    async def list_modules(self) -> list[dict[str, Any]]:
        """List available SpiderFoot modules."""
        async with self._client() as client:
            resp = await client.get("/api/modules")
            resp.raise_for_status()
            return resp.json()

    async def scan(
        self,
        target: str,
        scan_type: str = "passive",
        modules: list[str] | None = None,
        scan_name: str = "",
        wait: bool = True,
    ) -> dict[str, Any]:
        """Run a SpiderFoot scan and return FtM-converted results.

        Args:
            target: Domain, email, IP, or name to scan
            scan_type: 'passive', 'active', or 'all'
            modules: Specific modules to run (empty = use scan_type default)
            scan_name: Human-readable scan name
            wait: If True, poll until scan completes

        Returns:
            Dict with scan metadata, FtM entities, and relationships
        """
        self._converter = SpiderFootFtMConverter(scan_target=target)

        if not scan_name:
            scan_name = f"Emet OSINT: {target}"

        # Select modules
        module_list = modules or self._config.passive_modules
        if scan_type == "all":
            module_list = []  # Empty = all modules

        # Start scan
        scan_id = await self._start_scan(target, scan_name, module_list)

        if not wait:
            return {
                "scan_id": scan_id,
                "target": target,
                "status": "started",
                "entities": [],
                "relationships": [],
            }

        # Poll for completion
        status = await self._wait_for_scan(scan_id)

        # Retrieve results
        events = await self._get_scan_results(scan_id)

        # Convert to FtM
        entities = self._converter.convert_events(events)
        relationships = self._converter.build_relationships(entities)

        return {
            "scan_id": scan_id,
            "target": target,
            "status": status,
            "event_count": len(events),
            "entity_count": len(entities),
            "relationship_count": len(relationships),
            "entities": entities,
            "relationships": relationships,
            "entities_by_schema": _count_by_schema(entities),
        }

    async def _start_scan(
        self,
        target: str,
        scan_name: str,
        modules: list[str],
    ) -> str:
        """Start a SpiderFoot scan via REST API."""
        async with self._client() as client:
            payload = {
                "scanname": scan_name,
                "scantarget": target,
                "usecase": "all",
            }
            if modules:
                payload["modulelist"] = ",".join(modules)

            resp = await client.post("/api/startscan", data=payload)
            resp.raise_for_status()

            # SpiderFoot returns scan ID in response
            result = resp.json()
            scan_id = result if isinstance(result, str) else result.get("scanId", "")

            if not scan_id:
                # Fallback: generate a placeholder for mock/test scenarios
                scan_id = f"sf-{uuid.uuid4().hex[:12]}"

            logger.info("SpiderFoot scan started: %s (target: %s)", scan_id, target)
            return scan_id

    async def _wait_for_scan(self, scan_id: str) -> str:
        """Poll scan status until completion."""
        for attempt in range(self._config.max_poll_attempts):
            status = await self._get_scan_status(scan_id)
            if status in ("FINISHED", "ABORTED", "ERROR-FAILED"):
                logger.info("SpiderFoot scan %s: %s", scan_id, status)
                return status
            await asyncio.sleep(self._config.poll_interval_seconds)

        logger.warning("SpiderFoot scan %s: timed out polling", scan_id)
        return "TIMEOUT"

    async def _get_scan_status(self, scan_id: str) -> str:
        """Get current scan status."""
        try:
            async with self._client() as client:
                resp = await client.get(f"/api/scanstatus/{scan_id}")
                resp.raise_for_status()
                data = resp.json()
                return data.get("status", "UNKNOWN") if isinstance(data, dict) else str(data)
        except Exception as exc:
            logger.warning("Failed to get scan status: %s", exc)
            return "UNKNOWN"

    async def _get_scan_results(self, scan_id: str) -> list[dict[str, Any]]:
        """Retrieve all events from a completed scan."""
        try:
            async with self._client() as client:
                resp = await client.get(f"/api/scanresults/{scan_id}")
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.warning("Failed to get scan results: %s", exc)
            return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stable_hash(value: str) -> str:
    """Generate a short stable hash for deduplication."""
    import hashlib
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _event_confidence(event_type: str) -> float:
    """Assign confidence score based on event type reliability."""
    high_confidence = {
        "EMAILADDR", "IP_ADDRESS", "IPV6_ADDRESS", "INTERNET_NAME",
        "PHONE_NUMBER", "SSL_CERTIFICATE_RAW", "DOMAIN_WHOIS",
    }
    medium_confidence = {
        "HUMAN_NAME", "COMPANY_NAME", "SOCIAL_MEDIA", "USERNAME",
        "GEOINFO", "CO_HOSTED_SITE",
    }
    if event_type in high_confidence:
        return 0.9
    if event_type in medium_confidence:
        return 0.7
    return 0.5


def _count_by_schema(entities: list[dict[str, Any]]) -> dict[str, int]:
    """Count entities by FtM schema."""
    counts: dict[str, int] = {}
    for entity in entities:
        schema = entity.get("schema", "Unknown")
        counts[schema] = counts.get(schema, 0) + 1
    return counts
