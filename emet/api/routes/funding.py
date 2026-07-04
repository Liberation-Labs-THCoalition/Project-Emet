"""Follow-the-money lookup API — "who funds this outlet?".

This is the integration surface for TruthStrike's *Follow the Money*
feature: a lightweight, real-time endpoint that answers "who owns / who
funds this organization?" without spinning up a full autonomous
investigation.

    GET  /api/funding/{entity}          — quick ownership + funding lookup
    POST /api/funding                   — same, with options in the body

Given an organization name (typically a media outlet), it:
  1. federates a search across corporate registries + FEC + sanctions,
  2. enriches the best match (GLEIF ownership chain, offshore, sanctions),
  3. builds a graph and traces beneficial ownership (effective % up the
     chain),
  4. attaches an evidence chain + confidence score,
  5. records the query in the audit trail with the *requester's* identity.

The targeting policy is enforced: organizations and public figures are
answerable; a bare private-individual name is refused.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Query
from pydantic import BaseModel

from emet.export.evidence import EvidenceChain, SourceRef
from emet.graph.algorithms import InvestigativeAnalysis
from emet.graph.ftm_loader import FtMGraphLoader
from emet.security.target_policy import check_target

logger = logging.getLogger(__name__)

router = APIRouter(tags=["funding"])


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


class FundingRequest(BaseModel):
    entity: str
    entity_type: str = "Company"
    max_depth: int = 6
    requester: str = "anonymous"


def _entity_name(entity: dict[str, Any]) -> str:
    props = entity.get("properties", {}) or {}
    name = props.get("name")
    if isinstance(name, list) and name:
        return str(name[0])
    return str(name or entity.get("id", ""))


async def lookup_funding(
    name: str,
    fed: Any,
    entity_type: str = "Company",
    max_depth: int = 6,
    requester: str = "anonymous",
    audit: Any = None,
) -> dict[str, Any]:
    """Core follow-the-money lookup. Framework-agnostic and testable.

    Parameters
    ----------
    fed:
        A ``FederatedSearch``-compatible object (dependency-injected so
        tests can supply a fake without hitting the network).
    audit:
        Optional ``AuditArchive`` — when given, the query is logged with
        the ``requester`` identity so lookups are attributable.
    """
    if audit is not None:
        audit.open(
            f"funding-{name}",
            goal=f"who funds {name}",
            actor={"id": requester, "type": "service"},
        )

    report: dict[str, Any] = {
        "query": name,
        "requester": requester,
        "outlet": None,
        "beneficial_owners": [],
        "funders": [],
        "sanctions_flags": [],
        "confidence": 0.0,
        "confidence_label": "unverified",
        "sources_checked": [],
        "policy": None,
        "notes": [],
    }

    # 1. Enrich the entity across sources.
    try:
        enriched = await fed.enrich_entity(name, entity_type=entity_type)
    except Exception as exc:  # network / source failure
        logger.warning("Funding lookup enrich failed for %s: %s", name, exc)
        enriched = {
            "entity": None,
            "sanctions_matches": [],
            "offshore_connections": [],
            "ownership_chain": [],
            "sources_checked": [],
        }

    report["sources_checked"] = list(enriched.get("sources_checked", []))
    outlet = enriched.get("entity")

    if not outlet:
        report["notes"].append(
            "No matching organization found in public registries."
        )
        if audit is not None:
            audit.record_event("funding_result", {"found": False})
            audit.close({"found": False})
        return report

    # 2. Enforce the targeting policy on the resolved entity.
    decision = check_target(outlet)
    report["policy"] = {
        "target_class": decision.target_class.value,
        "allowed": decision.allowed,
        "reason": decision.reason,
    }
    if not decision.allowed:
        report["notes"].append(decision.reason)
        if audit is not None:
            audit.record_event("funding_blocked", report["policy"])
            audit.close({"blocked": True})
        return report

    report["outlet"] = {
        "id": outlet.get("id", ""),
        "name": _entity_name(outlet),
        "schema": outlet.get("schema", ""),
    }

    # 3. Assemble the graph from every entity the enrichment surfaced.
    graph_entities: list[dict[str, Any]] = [outlet]
    graph_entities.extend(enriched.get("ownership_chain", []) or [])
    graph_entities.extend(enriched.get("offshore_connections", []) or [])

    chain = EvidenceChain()

    try:
        graph, _stats = FtMGraphLoader().load(graph_entities)
        analysis = InvestigativeAnalysis(graph)
        trace = analysis.trace_beneficial_ownership(
            outlet.get("id", ""), max_depth=max_depth
        )
        for bo in trace.ultimate_owners:
            report["beneficial_owners"].append(
                {
                    "name": bo.name,
                    "schema": bo.schema,
                    "effective_pct": bo.effective_pct,
                    "chain_length": len(bo.path) - 1,
                }
            )
        if trace.ultimate_owners:
            chain.add_claim(
                trace.explanation,
                sources=[
                    SourceRef.from_provenance(
                        outlet.get("_provenance", {"source": "federation"})
                    )
                ],
                entity_ids=[outlet.get("id", "")],
                tags=["beneficial-ownership"],
            )
        else:
            report["notes"].append(
                "Ownership is opaque: no beneficial-ownership records found."
            )
    except Exception as exc:
        logger.warning("Funding graph/UBO trace failed for %s: %s", name, exc)
        report["notes"].append("Ownership graph could not be constructed.")

    # 4. Direct funders: named owner entities (skip the relationship
    # records themselves — Ownership/Directorship/Payment are edges).
    _relationship_schemas = {
        "Ownership", "Directorship", "Payment", "Membership",
        "Representation", "Interest",
    }
    for entity in enriched.get("ownership_chain", []) or []:
        if entity.get("schema", "") in _relationship_schemas:
            continue
        prov = entity.get("_provenance", {})
        report["funders"].append(
            {
                "name": _entity_name(entity),
                "schema": entity.get("schema", ""),
                "source": prov.get("source", ""),
            }
        )

    # 5. Sanctions exposure.
    for match in enriched.get("sanctions_matches", []) or []:
        report["sanctions_flags"].append(
            {
                "name": _entity_name(match),
                "datasets": match.get("_provenance", {}).get("datasets", []),
            }
        )
        chain.add_claim(
            f"{report['outlet']['name']} has a sanctions/PEP match: {_entity_name(match)}",
            sources=[SourceRef.from_provenance({"source": "opensanctions", "confidence": 0.95})],
            tags=["sanctions"],
        )

    report["confidence"] = chain.overall_confidence
    from emet.export.evidence import confidence_label

    report["confidence_label"] = confidence_label(report["confidence"])
    report["evidence"] = chain.to_dict()

    if audit is not None:
        audit.record_event(
            "funding_result",
            {
                "found": True,
                "beneficial_owner_count": len(report["beneficial_owners"]),
                "sanctions_flag_count": len(report["sanctions_flags"]),
            },
        )
        audit.close({"found": True})

    return report


def _build_fed() -> Any:
    from emet.ftm.external.federation import FederatedSearch, FederationConfig

    return FederatedSearch(FederationConfig.from_env())


def _build_audit() -> Any:
    try:
        from emet.agent.audit import AuditArchive

        return AuditArchive("investigations/audit")
    except Exception:
        return None


@router.get("/api/funding/{entity}")
async def get_funding(
    entity: str,
    entity_type: str = Query("Company"),
    max_depth: int = Query(6, ge=1, le=12),
    requester: str = Query("anonymous"),
) -> dict[str, Any]:
    """Quick 'who funds this outlet?' lookup for TruthStrike."""
    return await lookup_funding(
        entity,
        fed=_build_fed(),
        entity_type=entity_type,
        max_depth=max_depth,
        requester=requester,
        audit=_build_audit(),
    )


@router.post("/api/funding")
async def post_funding(req: FundingRequest = Body(...)) -> dict[str, Any]:
    """Same lookup with options supplied in the request body."""
    return await lookup_funding(
        req.entity,
        fed=_build_fed(),
        entity_type=req.entity_type,
        max_depth=req.max_depth,
        requester=req.requester,
        audit=_build_audit(),
    )
