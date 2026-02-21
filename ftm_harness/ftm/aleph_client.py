"""Aleph API Client — wraps OpenAleph / Aleph Pro REST API.

Provides async methods for all Aleph operations that skill chips need:
search, entity CRUD, collection management, cross-referencing, document
ingest, entity streaming, and notifications.

Supports both OpenAleph (self-hosted, MIT) and Aleph Pro (SaaS) via
the shared ``/api/2/`` endpoint surface. Configuration selects the
target instance.

The client handles authentication (API key), pagination, streaming
(NDJSON), error handling, and rate limit awareness.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class AlephConfig:
    """Configuration for the Aleph API client."""

    host: str = "http://localhost:8080"
    api_key: str = ""
    api_prefix: str = "/api/2"
    timeout_seconds: float = 30.0
    max_retries: int = 3
    # Aleph Pro vs OpenAleph feature flags
    is_pro: bool = False


class AlephClient:
    """Async client for the Aleph REST API.

    All methods return raw dicts matching the Aleph API response envelope:
    ``{"status": "ok", "results": [...], "total": N, ...}``

    Skill chips consume these dicts and wrap results in
    ``InvestigationEntity`` objects via the FtM data spine.
    """

    def __init__(self, config: AlephConfig | None = None) -> None:
        self._config = config or AlephConfig()
        self._base_url = f"{self._config.host.rstrip('/')}{self._config.api_prefix}"
        self._headers: dict[str, str] = {}
        if self._config.api_key:
            self._headers["Authorization"] = f"ApiKey {self._config.api_key}"

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            timeout=self._config.timeout_seconds,
        )

    # -- Search & Entities --------------------------------------------------

    async def search(
        self,
        query: str,
        schema: str = "",
        collections: list[str] | None = None,
        countries: list[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Full-text search across Aleph's Elasticsearch index.

        Supports ElasticSearch query_string syntax: boolean operators,
        wildcards, fuzzy matching (~), proximity, and regex.
        """
        params: dict[str, Any] = {
            "q": query,
            "limit": limit,
            "offset": offset,
        }
        if schema:
            params["filter:schema"] = schema
        if collections:
            params["filter:collection_id"] = collections
        if countries:
            params["filter:countries"] = countries

        async with self._client() as client:
            resp = await client.get("/search", params=params)
            resp.raise_for_status()
            return resp.json()

    async def get_entity(self, entity_id: str) -> dict[str, Any]:
        """Retrieve a single entity by ID."""
        async with self._client() as client:
            resp = await client.get(f"/entities/{entity_id}")
            resp.raise_for_status()
            return resp.json()

    async def get_entity_references(self, entity_id: str) -> dict[str, Any]:
        """Get all entities that reference this entity."""
        async with self._client() as client:
            resp = await client.get(f"/entities/{entity_id}/references")
            resp.raise_for_status()
            return resp.json()

    async def get_entity_expand(self, entity_id: str) -> dict[str, Any]:
        """Expand entity via inverted index (find related entities)."""
        async with self._client() as client:
            resp = await client.get(f"/entities/{entity_id}/expand")
            resp.raise_for_status()
            return resp.json()

    async def get_similar_entities(self, entity_id: str) -> dict[str, Any]:
        """Find similar entities via embedding similarity."""
        async with self._client() as client:
            resp = await client.get(f"/entities/{entity_id}/similar")
            resp.raise_for_status()
            return resp.json()

    # -- Collections --------------------------------------------------------

    async def list_collections(self, limit: int = 50) -> dict[str, Any]:
        """List accessible collections."""
        async with self._client() as client:
            resp = await client.get("/collections", params={"limit": limit})
            resp.raise_for_status()
            return resp.json()

    async def get_collection(self, collection_id: str) -> dict[str, Any]:
        """Get collection metadata."""
        async with self._client() as client:
            resp = await client.get(f"/collections/{collection_id}")
            resp.raise_for_status()
            return resp.json()

    async def create_collection(
        self,
        label: str,
        summary: str = "",
        category: str = "casefile",
        languages: list[str] | None = None,
        countries: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new collection (investigation)."""
        payload: dict[str, Any] = {
            "label": label,
            "summary": summary,
            "category": category,
        }
        if languages:
            payload["languages"] = languages
        if countries:
            payload["countries"] = countries

        async with self._client() as client:
            resp = await client.post("/collections", json=payload)
            resp.raise_for_status()
            return resp.json()

    async def stream_entities(
        self, collection_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream all entities from a collection as NDJSON."""
        async with self._client() as client:
            async with client.stream(
                "GET", f"/collections/{collection_id}/_stream"
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.strip():
                        import json
                        yield json.loads(line)

    async def write_entities(
        self,
        collection_id: str,
        entities: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Bulk write FtM entities to a collection."""
        # Convert to NDJSON
        import json
        ndjson = "\n".join(json.dumps(e) for e in entities)

        async with self._client() as client:
            resp = await client.post(
                f"/collections/{collection_id}/_bulk",
                content=ndjson,
                headers={"Content-Type": "application/x-ndjson"},
            )
            resp.raise_for_status()
            return resp.json()

    # -- Cross-Referencing --------------------------------------------------

    async def trigger_xref(self, collection_id: str) -> dict[str, Any]:
        """Trigger cross-referencing for a collection."""
        async with self._client() as client:
            resp = await client.post(f"/collections/{collection_id}/xref")
            resp.raise_for_status()
            return resp.json()

    async def get_xref_results(
        self,
        collection_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Retrieve cross-reference results for a collection."""
        async with self._client() as client:
            resp = await client.get(
                f"/collections/{collection_id}/xref",
                params={"limit": limit, "offset": offset},
            )
            resp.raise_for_status()
            return resp.json()

    async def decide_xref(
        self,
        collection_id: str,
        xref_id: str,
        decision: str,
    ) -> dict[str, Any]:
        """Confirm or reject a cross-reference match.

        Parameters
        ----------
        decision:
            One of "positive" (same entity), "negative" (different),
            or "unsure".
        """
        async with self._client() as client:
            resp = await client.post(
                f"/collections/{collection_id}/xref/{xref_id}",
                json={"decision": decision},
            )
            resp.raise_for_status()
            return resp.json()

    # -- Document Ingest ----------------------------------------------------

    async def ingest_file(
        self,
        collection_id: str,
        file_path: str,
        file_name: str = "",
        language: str = "",
        foreign_id: str = "",
    ) -> dict[str, Any]:
        """Upload a file to a collection for ingestion."""
        import os
        if not file_name:
            file_name = os.path.basename(file_path)

        data: dict[str, str] = {}
        if language:
            data["language"] = language
        if foreign_id:
            data["foreign_id"] = foreign_id

        async with self._client() as client:
            with open(file_path, "rb") as f:
                resp = await client.post(
                    f"/collections/{collection_id}/ingest",
                    files={"file": (file_name, f)},
                    data=data,
                )
            resp.raise_for_status()
            return resp.json()

    # -- Entity Sets (Diagrams, Timelines, Lists) ---------------------------

    async def list_entity_sets(
        self, collection_id: str
    ) -> dict[str, Any]:
        """List entity sets (diagrams, timelines, lists) in a collection."""
        async with self._client() as client:
            resp = await client.get(
                "/entitysets",
                params={"filter:collection_id": collection_id},
            )
            resp.raise_for_status()
            return resp.json()

    async def create_entity_set(
        self,
        collection_id: str,
        label: str,
        type_: str = "diagram",
    ) -> dict[str, Any]:
        """Create an entity set (diagram, timeline, or list)."""
        async with self._client() as client:
            resp = await client.post(
                "/entitysets",
                json={
                    "collection_id": collection_id,
                    "label": label,
                    "type": type_,
                },
            )
            resp.raise_for_status()
            return resp.json()

    # -- Notifications & Exports --------------------------------------------

    async def get_notifications(self, limit: int = 20) -> dict[str, Any]:
        """Get recent notifications for the authenticated user."""
        async with self._client() as client:
            resp = await client.get("/notifications", params={"limit": limit})
            resp.raise_for_status()
            return resp.json()

    async def reingest_collection(self, collection_id: str) -> dict[str, Any]:
        """Trigger re-ingestion of all documents in a collection."""
        async with self._client() as client:
            resp = await client.post(f"/collections/{collection_id}/reingest")
            resp.raise_for_status()
            return resp.json()

    async def reindex_collection(self, collection_id: str) -> dict[str, Any]:
        """Trigger re-indexing of a collection."""
        async with self._client() as client:
            resp = await client.post(f"/collections/{collection_id}/reindex")
            resp.raise_for_status()
            return resp.json()
