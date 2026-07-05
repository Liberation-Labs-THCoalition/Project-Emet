"""Funding API — "who funds this outlet?" lookups for the TruthStrike integration.

Endpoints:
    GET  /api/funding/{entity}   Look up beneficial ownership for an entity
    POST /api/funding            Same, with an optional public-interest override

This is the Follow the Money integration surface for TruthStrike: given a
media outlet (or any organization/public figure) name, it federates a search,
enriches with GLEIF ownership + sanctions screening, builds a graph, traces
beneficial ownership, and wraps the result in an evidence chain with a
defensible confidence score — while enforcing the "organizations and public
figures only" targeting policy and recording every query, with the
requester's identity, to the audit trail.

Core logic lives in ``lookup_funding()``, a framework-agnostic function with
dependency-injected federation + audit, so it's testable without a running
FastAPI app or live network access. The route handlers below are thin HTTP
adapters around it.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from emet.agent.audit import AuditArchive
from emet.export.evidence import EvidenceChain, SourceRef
from emet.ftm.external.federation import FederatedSearch, FederationConfig
from emet.security.target_policy import (
    PublicInterestOverride,
    check_target,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/funding", tags=["funding"])

_federation: FederatedSearch | None = None


def _get_federation() -> FederatedSearch:
    """Module-level lazy singleton, mirroring the pattern used by the MCP
    tool executor's connection pool — avoids rebuilding every source client
    on every request."""
    global _federation
    if _federation is None:
        _federation = FederatedSearch(FederationConfig.from_env())
    return _federation


def _entity_name(entity: dict[str, Any]) -> str:
    names = entity.get("properties", {}).get("name", [])
    return names[0] if names else entity.get("id", "")


async def lookup_funding(
    name: str,
    federation: FederatedSearch,
    audit: AuditArchive | None = None,
    requester: str = "",
    max_depth: int = 3,
    override: PublicInterestOverride | None = None,
) -> dict[str, Any]:
    """Core funding-lookup logic: search, gate, enrich, trace, evidence.

    Framework-agnostic — takes its ``federation``/``audit`` dependencies
    injected so it can be unit-tested with mocked federation and without
    ever touching a database or the filesystem's audit directory.

    Returns a dict always shaped with ``found`` and (when found) ``allowed``
    keys so callers (the HTTP routes below, or any other caller) can map it
    onto the right response/status code without re-deriving the logic.
    """
    federated_result = await federation.search_entity(
        name, entity_type="Company", limit_per_source=10,
    )
    found_entities = federated_result.entities[:10]

    if not found_entities:
        return {
            "entity": name,
            "found": False,
            "error": f"No entity found matching '{name}'.",
        }

    target_entity = found_entities[0]
    target_id = target_entity.get("id", "")
    target_name = _entity_name(target_entity) or name

    decision = check_target(target_entity, override=override)

    if audit is not None:
        audit.record_event("funding_target_check", {
            "entity_id": target_id,
            "entity_name": target_name,
            "requester": requester,
            "allowed": decision.allowed,
            "target_type": decision.target_type.value,
            "reason": decision.reason,
        })

    if not decision.allowed:
        return {
            "entity": name,
            "entity_id": target_id,
            "found": True,
            "allowed": False,
            "target_type": decision.target_type.value,
            "reason": decision.reason,
        }

    enrichment = await federation.enrich_entity(name, entity_type="Company")
    ownership_chain = enrichment.get("ownership_chain", [])
    sanctions_matches = enrichment.get("sanctions_matches", [])

    found_ids = {e.get("id") for e in found_entities}
    all_entities = list(found_entities) + [
        e for e in ownership_chain if e.get("id") not in found_ids
    ]

    from emet.graph.engine import GraphEngine

    graph_result = GraphEngine().build_from_entities(all_entities)
    trace = graph_result.analysis.trace_beneficial_ownership(
        target_id, max_depth=max_depth,
    )

    evidence = EvidenceChain()
    for owner in trace.owners:
        node_data = graph_result.graph.nodes.get(owner.entity_id, {})
        provenance = node_data.get("_provenance") or {}
        sources = [SourceRef.from_provenance(provenance)] if provenance else []
        pct_str = (
            f"{owner.effective_pct:.0%}" if owner.effective_pct is not None
            else "an unknown share of"
        )
        evidence.add_claim(
            f"{owner.name} holds {pct_str} effective ownership of {target_name}.",
            sources=sources,
        )

    if audit is not None:
        audit.record_event("funding_lookup", {
            "entity_id": target_id,
            "entity_name": target_name,
            "requester": requester,
            "owners_found": len(trace.owners),
            "sanctions_matches": len(sanctions_matches),
        })

    owners = [
        {
            "entity_id": o.entity_id,
            "name": o.name,
            "schema": o.schema,
            "effective_pct": o.effective_pct,
            "depth": o.depth,
            "is_ultimate_beneficial_owner": o.is_terminal,
        }
        for o in trace.owners
    ]

    return {
        "entity": name,
        "entity_id": target_id,
        "found": True,
        "allowed": True,
        "target_type": decision.target_type.value,
        "owners": owners,
        "cycles_detected": trace.cycles_detected,
        "max_depth_reached": trace.max_depth_reached,
        "explanation": trace.explanation,
        "sanctions_matches": sanctions_matches,
        "evidence_markdown": evidence.to_markdown(),
        "unsupported_claims": [c.statement for c in evidence.unsupported_claims()],
    }


def _open_audit(requester: str) -> AuditArchive:
    """Open a short-lived audit archive for one funding query.

    Every funding lookup gets its own archive session — this endpoint is a
    single stateless query, not a multi-turn investigation, so there's no
    broader session to attach to. The requester's identity is recorded as
    the actor on every event.
    """
    archive = AuditArchive(base_dir="investigations/audit")
    session_id = f"funding-{uuid.uuid4().hex[:12]}"
    archive.open(
        session_id,
        goal=f"funding lookup",
        actor={"id": requester or "anonymous", "type": "service"},
    )
    return archive


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class FundingRequest(BaseModel):
    """Request body for POST /api/funding."""
    entity: str = Field(..., description="Organization or public figure name to trace")
    requester: str = Field("", description="Identity of the caller, for the audit trail")
    max_depth: int = Field(3, ge=1, le=10, description="Max ownership chain depth")
    override_reason: str = Field("", description="Public-interest justification, if targeting a private individual")
    override_authorized_by: str = Field("", description="Who authorized the override")


# ---------------------------------------------------------------------------
# GET /api/funding/{entity}
# ---------------------------------------------------------------------------


@router.get("/{entity}")
async def get_funding(
    entity: str,
    requester: str = Query("", description="Identity of the caller, for the audit trail"),
    max_depth: int = Query(3, ge=1, le=10),
) -> dict[str, Any]:
    """Look up beneficial ownership for an entity by name.

    TruthStrike calls ``GET /api/funding/{outlet}?requester=truthstrike`` for
    real-time ownership lookups on media companies.
    """
    federation = _get_federation()
    audit = _open_audit(requester)
    try:
        result = await lookup_funding(
            entity, federation, audit=audit, requester=requester, max_depth=max_depth,
        )
    finally:
        audit.close()

    if not result.get("found"):
        raise HTTPException(status_code=404, detail=result.get("error", "Entity not found"))
    if not result.get("allowed"):
        raise HTTPException(status_code=403, detail=result.get("reason", "Denied by targeting policy"))

    return result


# ---------------------------------------------------------------------------
# POST /api/funding
# ---------------------------------------------------------------------------


@router.post("")
async def post_funding(req: FundingRequest) -> dict[str, Any]:
    """Look up beneficial ownership, optionally with a public-interest override
    for targets that would otherwise be denied (e.g. a private individual with
    a documented, logged public-interest justification)."""
    override: Optional[PublicInterestOverride] = None
    if req.override_reason and req.override_authorized_by:
        override = PublicInterestOverride(
            reason=req.override_reason,
            authorized_by=req.override_authorized_by,
        )

    federation = _get_federation()
    audit = _open_audit(req.requester)
    try:
        result = await lookup_funding(
            req.entity,
            federation,
            audit=audit,
            requester=req.requester,
            max_depth=req.max_depth,
            override=override,
        )
    finally:
        audit.close()

    if not result.get("found"):
        raise HTTPException(status_code=404, detail=result.get("error", "Entity not found"))
    if not result.get("allowed"):
        raise HTTPException(status_code=403, detail=result.get("reason", "Denied by targeting policy"))

    return result
