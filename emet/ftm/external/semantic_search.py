"""Semantic search and RAG adapter using ChromaDB.

Embeds FtM entities and investigation documents into a vector store
for semantic retrieval.  Enables natural-language queries over
investigation data ("who is connected to the Panama deal?").

Pipeline:
  FtM entities → text chunks → embeddings → ChromaDB collection
  Query → embedding → similarity search → ranked results → context for LLM

ChromaDB (Apache 2.0) provides:
  - In-process vector store (no external service needed)
  - Persistent storage on disk
  - Metadata filtering
  - Multiple distance metrics

Reference:
  ChromaDB: https://github.com/chroma-core/chroma (Apache 2.0)
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class SemanticSearchConfig:
    """Configuration for semantic search."""
    collection_name: str = "emet_investigation"
    persist_directory: str = ""           # Empty = in-memory
    embedding_model: str = "default"      # "default" uses Chroma's built-in
    distance_metric: str = "cosine"       # cosine, l2, ip
    chunk_size: int = 500                 # Max chars per text chunk
    chunk_overlap: int = 50               # Overlap between chunks
    max_results: int = 10                 # Default results per query


# ---------------------------------------------------------------------------
# Text chunking
# ---------------------------------------------------------------------------


def entity_to_text(entity: dict[str, Any]) -> str:
    """Convert an FtM entity to searchable text.

    Produces a natural-language description from the entity's
    schema and properties for embedding.
    """
    schema = entity.get("schema", "Entity")
    props = entity.get("properties", {})
    entity_id = entity.get("id", "")

    parts = [f"[{schema}]"]

    # Name/title
    names = props.get("name", props.get("title", []))
    if names:
        parts.append(f"Name: {', '.join(names)}")

    # Key properties by schema
    prop_map = {
        "birthDate": "Born",
        "deathDate": "Died",
        "nationality": "Nationality",
        "country": "Country",
        "jurisdiction": "Jurisdiction",
        "address": "Address",
        "registrationNumber": "Registration",
        "idNumber": "ID",
        "description": "Description",
        "notes": "Notes",
        "bodyText": "Content",
        "summary": "Summary",
        "email": "Email",
        "phone": "Phone",
        "website": "Website",
        "role": "Role",
        "position": "Position",
        "program": "Program",
        "reason": "Reason",
        "authority": "Authority",
        "sourceUrl": "Source",
    }

    for prop_key, label in prop_map.items():
        values = props.get(prop_key, [])
        if values:
            parts.append(f"{label}: {', '.join(str(v) for v in values)}")

    # Provenance
    prov = entity.get("_provenance", {})
    source = prov.get("source", "")
    if source:
        parts.append(f"Source: {source}")

    return " | ".join(parts)


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split text into overlapping chunks for embedding.

    Tries to split on sentence boundaries when possible.
    """
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size

        # Try to break at sentence boundary
        if end < len(text):
            # Look for sentence-ending punctuation near the boundary
            for sep in [". ", ".\n", "! ", "? ", "| "]:
                boundary = text.rfind(sep, start + chunk_size // 2, end)
                if boundary > start:
                    end = boundary + len(sep)
                    break

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        start = end - overlap

    return chunks


# ---------------------------------------------------------------------------
# Search results
# ---------------------------------------------------------------------------


@dataclass
class SearchResult:
    """A single semantic search result."""
    entity_id: str
    text: str
    score: float                  # Similarity score (0-1 for cosine)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema: str = ""
    chunk_index: int = 0


@dataclass
class SearchResponse:
    """Response from a semantic search query."""
    query: str
    results: list[SearchResult] = field(default_factory=list)
    total_results: int = 0
    search_time_ms: float = 0.0

    @property
    def context_text(self) -> str:
        """Concatenate results into context for RAG."""
        parts = []
        for r in self.results:
            parts.append(f"[{r.schema} | score={r.score:.3f}] {r.text}")
        return "\n\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "total_results": self.total_results,
            "search_time_ms": self.search_time_ms,
            "results": [
                {
                    "entity_id": r.entity_id,
                    "text": r.text,
                    "score": r.score,
                    "schema": r.schema,
                    "metadata": r.metadata,
                }
                for r in self.results
            ],
        }


# ---------------------------------------------------------------------------
# Semantic search engine
# ---------------------------------------------------------------------------


class SemanticSearchEngine:
    """ChromaDB-backed semantic search over investigation data.

    Indexes FtM entities as text chunks with metadata.
    Supports natural-language queries, metadata filtering,
    and context generation for RAG.
    """

    def __init__(self, config: SemanticSearchConfig | None = None) -> None:
        self._config = config or SemanticSearchConfig()
        self._client = None
        self._collection = None

    def _get_collection(self) -> Any:
        """Lazy-initialize ChromaDB client and collection."""
        if self._collection is not None:
            return self._collection

        try:
            import chromadb
        except ImportError:
            raise ImportError(
                "ChromaDB not installed. "
                "Install with: pip install chromadb"
            )

        if self._config.persist_directory:
            self._client = chromadb.PersistentClient(
                path=self._config.persist_directory
            )
        else:
            self._client = chromadb.Client()

        self._collection = self._client.get_or_create_collection(
            name=self._config.collection_name,
            metadata={"hnsw:space": self._config.distance_metric},
        )

        return self._collection

    def index_entities(
        self,
        entities: list[dict[str, Any]],
        batch_size: int = 100,
    ) -> dict[str, Any]:
        """Index FtM entities into the vector store.

        Converts entities to text, chunks them, and adds to ChromaDB
        with metadata for filtered retrieval.
        """
        collection = self._get_collection()

        documents = []
        metadatas = []
        ids = []
        total_chunks = 0

        for entity in entities:
            text = entity_to_text(entity)
            if not text.strip():
                continue

            chunks = chunk_text(
                text,
                self._config.chunk_size,
                self._config.chunk_overlap,
            )

            entity_id = entity.get("id", str(uuid.uuid4()))
            schema = entity.get("schema", "Entity")
            prov = entity.get("_provenance", {})

            for i, chunk in enumerate(chunks):
                chunk_id = f"{entity_id}_chunk_{i}"
                documents.append(chunk)
                metadatas.append({
                    "entity_id": entity_id,
                    "schema": schema,
                    "source": prov.get("source", "unknown"),
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "indexed_at": datetime.now(timezone.utc).isoformat(),
                })
                ids.append(chunk_id)
                total_chunks += 1

        # Add in batches
        for i in range(0, len(documents), batch_size):
            batch_end = min(i + batch_size, len(documents))
            collection.add(
                documents=documents[i:batch_end],
                metadatas=metadatas[i:batch_end],
                ids=ids[i:batch_end],
            )

        logger.info(
            "Indexed %d entities (%d chunks) into '%s'",
            len(entities), total_chunks, self._config.collection_name,
        )

        return {
            "entity_count": len(entities),
            "chunk_count": total_chunks,
            "collection": self._config.collection_name,
        }

    def search(
        self,
        query: str,
        max_results: int | None = None,
        schema_filter: str = "",
        source_filter: str = "",
    ) -> SearchResponse:
        """Search the vector store with a natural-language query.

        Args:
            query: Natural language search query
            max_results: Override default max results
            schema_filter: Filter by FtM schema (e.g., "Person")
            source_filter: Filter by data source

        Returns:
            SearchResponse with ranked results
        """
        import time
        start = time.monotonic()

        collection = self._get_collection()
        n_results = max_results or self._config.max_results

        # Build metadata filter
        where_filter = None
        conditions = []
        if schema_filter:
            conditions.append({"schema": schema_filter})
        if source_filter:
            conditions.append({"source": source_filter})

        if len(conditions) == 1:
            where_filter = conditions[0]
        elif len(conditions) > 1:
            where_filter = {"$and": conditions}

        # Query
        query_params: dict[str, Any] = {
            "query_texts": [query],
            "n_results": n_results,
        }
        if where_filter:
            query_params["where"] = where_filter

        raw = collection.query(**query_params)

        # Parse results
        results = []
        if raw.get("documents") and raw["documents"][0]:
            docs = raw["documents"][0]
            distances = raw.get("distances", [[]])[0]
            metas = raw.get("metadatas", [[]])[0]
            result_ids = raw.get("ids", [[]])[0]

            for j, doc in enumerate(docs):
                meta = metas[j] if j < len(metas) else {}
                distance = distances[j] if j < len(distances) else 1.0

                # Convert distance to similarity score
                if self._config.distance_metric == "cosine":
                    score = 1.0 - distance
                elif self._config.distance_metric == "l2":
                    score = 1.0 / (1.0 + distance)
                else:
                    score = 1.0 - distance

                results.append(SearchResult(
                    entity_id=meta.get("entity_id", ""),
                    text=doc,
                    score=round(max(0, min(1, score)), 4),
                    metadata=meta,
                    schema=meta.get("schema", ""),
                    chunk_index=meta.get("chunk_index", 0),
                ))

        elapsed_ms = (time.monotonic() - start) * 1000

        return SearchResponse(
            query=query,
            results=results,
            total_results=len(results),
            search_time_ms=round(elapsed_ms, 2),
        )

    def delete_collection(self) -> None:
        """Delete the current collection."""
        if self._client and self._collection:
            self._client.delete_collection(self._config.collection_name)
            self._collection = None

    def collection_stats(self) -> dict[str, Any]:
        """Get collection statistics."""
        collection = self._get_collection()
        return {
            "collection": self._config.collection_name,
            "count": collection.count(),
            "distance_metric": self._config.distance_metric,
        }


# ---------------------------------------------------------------------------
# RAG context builder
# ---------------------------------------------------------------------------


def build_rag_context(
    query: str,
    engine: SemanticSearchEngine,
    max_results: int = 5,
    max_context_chars: int = 4000,
) -> dict[str, Any]:
    """Build RAG context from semantic search results.

    Returns context suitable for injection into an LLM prompt.
    """
    response = engine.search(query, max_results=max_results)

    context_parts = []
    total_chars = 0
    used_results = 0

    for result in response.results:
        text = result.text
        if total_chars + len(text) > max_context_chars:
            break
        context_parts.append(text)
        total_chars += len(text)
        used_results += 1

    return {
        "query": query,
        "context": "\n\n".join(context_parts),
        "context_chars": total_chars,
        "results_used": used_results,
        "total_available": response.total_results,
        "search_time_ms": response.search_time_ms,
    }
