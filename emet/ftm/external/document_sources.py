"""Document source adapters — Datashare and DocumentCloud.

Emet does NOT perform OCR or document processing. Instead, it ingests
results from established document processing tools:

  - **Datashare** (ICIJ): Self-hosted document processing and NER.
    Journalists upload docs → Datashare extracts text + entities →
    Emet queries the Datashare API for results.

  - **DocumentCloud** (MuckRock/IRE): Cloud document analysis platform.
    Journalists upload docs → DocumentCloud processes them →
    Emet queries the public API for processed results.

Both adapters convert results to FtM entities for integration with
Emet's graph engine, federation layer, and analysis pipeline.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FtM conversion helpers
# ---------------------------------------------------------------------------


def _document_to_ftm(
    doc_id: str,
    title: str,
    source: str,
    *,
    content_hash: str = "",
    author: str = "",
    date: str = "",
    language: str = "",
    source_url: str = "",
    page_count: int = 0,
) -> dict[str, Any]:
    """Convert a document record to an FtM Document entity."""
    props: dict[str, Any] = {"title": [title]}
    if author:
        props["author"] = [author]
    if date:
        props["date"] = [date]
    if language:
        props["language"] = [language]
    if source_url:
        props["sourceUrl"] = [source_url]
    if content_hash:
        props["contentHash"] = [content_hash]

    return {
        "id": f"doc-{source}-{doc_id}",
        "schema": "Document",
        "properties": props,
        "_provenance": {
            "source": source,
            "source_url": source_url,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def _mention_to_ftm(
    entity_id: str,
    document_id: str,
    entity_name: str,
    entity_schema: str,
    source: str,
) -> dict[str, Any]:
    """Create a Mention entity linking an extracted entity to its source document."""
    return {
        "id": f"mention-{document_id}-{entity_id}",
        "schema": "UnknownLink",
        "properties": {
            "subject": [entity_id],
            "object": [document_id],
            "role": [f"mentioned_in ({entity_schema})"],
        },
        "_provenance": {"source": source},
    }


def _ner_entity_to_ftm(
    name: str,
    entity_type: str,
    source: str,
    doc_id: str,
) -> dict[str, Any]:
    """Convert an NER-extracted entity to FtM."""
    # Map NER types to FtM schemas
    schema_map = {
        "PERSON": "Person",
        "PER": "Person",
        "ORGANIZATION": "Organization",
        "ORG": "Organization",
        "LOCATION": "Address",
        "LOC": "Address",
        "GPE": "Address",
        "COMPANY": "Company",
    }
    schema = schema_map.get(entity_type.upper(), "LegalEntity")

    # Generate stable ID from name + source doc
    import hashlib
    eid = hashlib.sha256(f"{name}:{doc_id}:{source}".encode()).hexdigest()[:16]

    return {
        "id": f"ner-{source}-{eid}",
        "schema": schema,
        "properties": {"name": [name]},
        "_provenance": {
            "source": f"{source}/ner",
            "extracted_from": doc_id,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# ---------------------------------------------------------------------------
# Datashare Client
# ---------------------------------------------------------------------------


class DatashareClient:
    """Client for querying a self-hosted Datashare instance.

    Datashare is ICIJ's document processing tool. Journalists run it
    locally or on a server. This client connects to its REST API.

    Parameters
    ----------
    host:
        Datashare server URL (e.g., ``http://localhost:8080``).
    project:
        Datashare project name (default: ``local-datashare``).
    timeout:
        Request timeout in seconds.

    See: https://icij.gitbook.io/datashare/developers/api
    """

    def __init__(
        self,
        host: str = "http://localhost:8080",
        project: str = "local-datashare",
        timeout: float = 30.0,
    ) -> None:
        self._host = host.rstrip("/")
        self._project = project
        self._timeout = timeout

    async def search(
        self,
        query: str,
        *,
        size: int = 10,
        from_: int = 0,
    ) -> list[dict[str, Any]]:
        """Search documents in Datashare.

        Parameters
        ----------
        query:
            Full-text search query.
        size:
            Number of results to return.
        from_:
            Offset for pagination.

        Returns
        -------
        List of document dicts with id, title, content excerpt.
        """
        url = f"{self._host}/api/{self._project}/documents/search"
        payload = {
            "query": query,
            "size": size,
            "from": from_,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.ConnectError:
            logger.warning("Cannot connect to Datashare at %s", self._host)
            return []
        except Exception as e:
            logger.warning("Datashare search failed: %s", e)
            return []

        hits = data.get("hits", {}).get("hits", [])
        results = []
        for hit in hits:
            source = hit.get("_source", {})
            results.append({
                "id": hit.get("_id", ""),
                "title": source.get("title", source.get("path", "Untitled")),
                "content_type": source.get("contentType", ""),
                "content_length": source.get("contentLength", 0),
                "language": source.get("language", ""),
                "creation_date": source.get("creationDate", ""),
                "path": source.get("path", ""),
                "content_excerpt": source.get("content", "")[:500],
            })

        return results

    async def get_document(self, doc_id: str) -> dict[str, Any] | None:
        """Get a single document's metadata and content."""
        url = f"{self._host}/api/{self._project}/documents/{doc_id}"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.warning("Datashare get_document failed: %s", e)
            return None

    async def get_named_entities(self, doc_id: str) -> list[dict[str, Any]]:
        """Get NER results for a document."""
        url = f"{self._host}/api/{self._project}/documents/{doc_id}/namedEntities"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.warning("Datashare NER fetch failed: %s", e)
            return []

        return data.get("hits", {}).get("hits", [])

    async def search_to_ftm(
        self,
        query: str,
        *,
        size: int = 10,
        include_entities: bool = True,
    ) -> list[dict[str, Any]]:
        """Search and convert results to FtM entities.

        Returns a list of FtM entities: Document entities for each doc,
        plus Person/Organization entities from NER, linked by Mention.
        """
        docs = await self.search(query, size=size)
        ftm_entities: list[dict[str, Any]] = []

        for doc in docs:
            # Document entity
            ftm_doc = _document_to_ftm(
                doc_id=doc["id"],
                title=doc["title"],
                source="datashare",
                date=doc.get("creation_date", ""),
                language=doc.get("language", ""),
                source_url=f"{self._host}/api/{self._project}/documents/{doc['id']}",
            )
            ftm_entities.append(ftm_doc)

            # NER entities if requested
            if include_entities:
                ner_results = await self.get_named_entities(doc["id"])
                for ner_hit in ner_results:
                    ner_source = ner_hit.get("_source", {})
                    mention = ner_source.get("mention", "")
                    category = ner_source.get("category", "UNKNOWN")

                    if not mention:
                        continue

                    ner_entity = _ner_entity_to_ftm(
                        name=mention,
                        entity_type=category,
                        source="datashare",
                        doc_id=doc["id"],
                    )
                    ftm_entities.append(ner_entity)

                    # Mention link
                    ftm_entities.append(_mention_to_ftm(
                        entity_id=ner_entity["id"],
                        document_id=ftm_doc["id"],
                        entity_name=mention,
                        entity_schema=ner_entity["schema"],
                        source="datashare",
                    ))

        return ftm_entities


# ---------------------------------------------------------------------------
# DocumentCloud Client
# ---------------------------------------------------------------------------


class DocumentCloudClient:
    """Client for DocumentCloud public API.

    DocumentCloud is a public document analysis platform used by
    newsrooms worldwide. This client queries the public API.

    Parameters
    ----------
    base_url:
        API base URL.
    timeout:
        Request timeout in seconds.

    See: https://www.documentcloud.org/help/api
    """

    API_BASE = "https://api.www.documentcloud.org/api"

    def __init__(
        self,
        base_url: str = "",
        timeout: float = 30.0,
    ) -> None:
        self._base = (base_url or self.API_BASE).rstrip("/")
        self._timeout = timeout

    async def search(
        self,
        query: str,
        *,
        per_page: int = 10,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """Search documents on DocumentCloud.

        Parameters
        ----------
        query:
            Full-text or fielded search query.
        per_page:
            Results per page (max 100).
        page:
            Page number.
        """
        url = f"{self._base}/documents/search/"
        params = {
            "q": query,
            "per_page": min(per_page, 100),
            "page": page,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.ConnectError:
            logger.warning("Cannot connect to DocumentCloud API")
            return []
        except Exception as e:
            logger.warning("DocumentCloud search failed: %s", e)
            return []

        results = []
        for doc in data.get("results", []):
            results.append({
                "id": doc.get("id", ""),
                "title": doc.get("title", "Untitled"),
                "description": doc.get("description", ""),
                "source": doc.get("source", ""),
                "language": doc.get("language", ""),
                "created_at": doc.get("created_at", ""),
                "updated_at": doc.get("updated_at", ""),
                "page_count": doc.get("page_count", 0),
                "canonical_url": doc.get("canonical_url", ""),
                "organization": doc.get("organization", {}).get("name", ""),
                "access": doc.get("access", ""),
            })

        return results

    async def get_document(self, doc_id: int | str) -> dict[str, Any] | None:
        """Get a single document's full metadata."""
        url = f"{self._base}/documents/{doc_id}/"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.warning("DocumentCloud get_document failed: %s", e)
            return None

    async def get_text(self, doc_id: int | str) -> str:
        """Get full text content of a document."""
        url = f"{self._base}/documents/{doc_id}/text/"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.text
        except Exception as e:
            logger.warning("DocumentCloud get_text failed: %s", e)
            return ""

    async def search_to_ftm(
        self,
        query: str,
        *,
        per_page: int = 10,
    ) -> list[dict[str, Any]]:
        """Search and convert results to FtM Document entities."""
        docs = await self.search(query, per_page=per_page)
        ftm_entities: list[dict[str, Any]] = []

        for doc in docs:
            ftm_doc = _document_to_ftm(
                doc_id=str(doc["id"]),
                title=doc["title"],
                source="documentcloud",
                author=doc.get("source", ""),
                date=doc.get("created_at", "")[:10],
                language=doc.get("language", ""),
                source_url=doc.get("canonical_url", ""),
                page_count=doc.get("page_count", 0),
            )
            ftm_entities.append(ftm_doc)

        return ftm_entities

    async def health_check(self) -> bool:
        """Check if DocumentCloud API is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base}/documents/search/?q=test&per_page=1")
                return resp.status_code == 200
        except Exception:
            return False
