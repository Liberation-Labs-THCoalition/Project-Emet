"""GDELT real-time news and event feed adapter.

Integrates with the GDELT Project (Global Database of Events,
Language, and Tone) to provide real-time news monitoring and
event feeds for investigation enrichment.

GDELT APIs used:
  - GDELT DOC 2.0 API: Full-text news search across 100+ languages
  - GDELT GEO 2.0 API: Geospatial event queries
  - GDELT TV 2.0 API: Television news monitoring (optional)

The adapter converts GDELT articles and events into FtM entities
(Mention, Document, Event) for integration with Emet's graph engine.

Reference:
  GDELT: https://www.gdeltproject.org/ (Free, no auth required)
  DOC API: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_GEO_API = "https://api.gdeltproject.org/api/v2/geo/geo"
GDELT_TV_API = "https://api.gdeltproject.org/api/v2/tv/tv"


@dataclass
class GDELTConfig:
    """Configuration for GDELT adapter."""
    timeout: float = 30.0
    max_records: int = 75        # GDELT default max
    default_timespan: str = "24h"  # Lookback window
    source_countries: list[str] = field(default_factory=list)  # e.g. ["US", "UK"]
    language: str = ""           # Filter by source language
    domain_filter: str = ""      # e.g. "bbc.co.uk" or "-tabloid.com"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class GDELTArticle:
    """A news article from GDELT."""
    url: str
    title: str
    source_domain: str
    source_country: str = ""
    language: str = ""
    published_at: str = ""
    tone: float = 0.0            # Average tone (-100 to +100)
    image_url: str = ""
    social_shares: int = 0
    themes: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    persons: list[str] = field(default_factory=list)
    organizations: list[str] = field(default_factory=list)


@dataclass
class GDELTFeedResult:
    """Result from a GDELT feed query."""
    query: str
    articles: list[GDELTArticle] = field(default_factory=list)
    article_count: int = 0
    timespan: str = ""

    @property
    def unique_sources(self) -> list[str]:
        return sorted({a.source_domain for a in self.articles})

    @property
    def average_tone(self) -> float:
        if not self.articles:
            return 0.0
        return sum(a.tone for a in self.articles) / len(self.articles)


# ---------------------------------------------------------------------------
# FtM converter
# ---------------------------------------------------------------------------


class GDELTFtMConverter:
    """Convert GDELT articles to FtM entities."""

    def convert_articles(
        self,
        articles: list[GDELTArticle],
        query: str = "",
    ) -> list[dict[str, Any]]:
        """Convert GDELT articles to FtM entities.

        Produces:
          - Mention entity for each article
          - Person/Organization entities from GDELT's NER
        """
        entities: list[dict[str, Any]] = []
        seen_entities: set[str] = set()

        for article in articles:
            # Mention entity for the article
            article_id = _stable_id(article.url)
            entities.append({
                "id": article_id,
                "schema": "Mention",
                "properties": {
                    "title": [article.title],
                    "sourceUrl": [article.url],
                    "publisher": [article.source_domain],
                    "date": [article.published_at] if article.published_at else [],
                    "language": [article.language] if article.language else [],
                    "description": [
                        f"Tone: {article.tone:.1f}" + (
                            f" | Themes: {', '.join(article.themes[:5])}"
                            if article.themes else ""
                        )
                    ],
                },
                "_provenance": {
                    "source": "gdelt",
                    "query": query,
                    "tone": article.tone,
                    "social_shares": article.social_shares,
                    "source_country": article.source_country,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                },
            })

            # Person entities from GDELT NER
            for person_name in article.persons:
                if person_name in seen_entities or len(person_name) < 3:
                    continue
                seen_entities.add(person_name)
                entities.append({
                    "id": f"gdelt-person-{_stable_id(person_name)}",
                    "schema": "Person",
                    "properties": {
                        "name": [person_name],
                    },
                    "_provenance": {
                        "source": "gdelt_ner",
                        "confidence": 0.6,
                        "article_url": article.url,
                        "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    },
                })

            # Organization entities
            for org_name in article.organizations:
                if org_name in seen_entities or len(org_name) < 3:
                    continue
                seen_entities.add(org_name)
                entities.append({
                    "id": f"gdelt-org-{_stable_id(org_name)}",
                    "schema": "Organization",
                    "properties": {
                        "name": [org_name],
                    },
                    "_provenance": {
                        "source": "gdelt_ner",
                        "confidence": 0.6,
                        "article_url": article.url,
                        "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    },
                })

        return entities


# ---------------------------------------------------------------------------
# GDELT client
# ---------------------------------------------------------------------------


class GDELTClient:
    """Async client for GDELT APIs.

    Provides news search, geo queries, and real-time feed monitoring.
    No authentication required — GDELT is free and open.
    """

    def __init__(self, config: GDELTConfig | None = None) -> None:
        self._config = config or GDELTConfig()
        self._converter = GDELTFtMConverter()

    async def search_news(
        self,
        query: str,
        timespan: str = "",
        max_records: int = 0,
        mode: str = "artlist",
        tone_filter: str = "",
        source_country: str = "",
    ) -> GDELTFeedResult:
        """Search GDELT news articles.

        Args:
            query: Search terms (supports boolean operators)
            timespan: Lookback window (e.g. "24h", "7d", "3m")
            max_records: Max results (default from config)
            mode: artlist (articles), timelinevol (volume timeline),
                  timelinetone (tone timeline)
            tone_filter: e.g. "tone>5" or "tone<-5"
            source_country: Two-letter country code

        Returns:
            GDELTFeedResult with articles and metadata
        """
        ts = timespan or self._config.default_timespan
        max_rec = max_records or self._config.max_records

        params = {
            "query": query,
            "mode": mode,
            "maxrecords": str(max_rec),
            "timespan": ts,
            "format": "json",
            "sort": "DateDesc",
        }

        if tone_filter:
            params["query"] += f" {tone_filter}"
        if source_country or self._config.source_countries:
            country = source_country or ",".join(self._config.source_countries)
            params["sourcecountry"] = country
        if self._config.language:
            params["sourcelang"] = self._config.language
        if self._config.domain_filter:
            params["domain"] = self._config.domain_filter

        articles = await self._fetch_articles(params)

        return GDELTFeedResult(
            query=query,
            articles=articles,
            article_count=len(articles),
            timespan=ts,
        )

    async def search_news_ftm(
        self,
        query: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Search and convert to FtM in one call."""
        result = await self.search_news(query, **kwargs)
        entities = self._converter.convert_articles(result.articles, query)

        return {
            "query": query,
            "article_count": result.article_count,
            "entity_count": len(entities),
            "unique_sources": result.unique_sources,
            "average_tone": round(result.average_tone, 2),
            "entities": entities,
        }

    async def monitor_entity(
        self,
        entity_name: str,
        timespan: str = "1h",
        max_records: int = 25,
    ) -> GDELTFeedResult:
        """Monitor news about a specific entity.

        Short timespan for near-real-time alerting.
        """
        return await self.search_news(
            query=f'"{entity_name}"',
            timespan=timespan,
            max_records=max_records,
        )

    async def _fetch_articles(
        self,
        params: dict[str, str],
    ) -> list[GDELTArticle]:
        """Fetch and parse GDELT DOC API response."""
        url = f"{GDELT_DOC_API}?{urlencode(params)}"

        async with httpx.AsyncClient(timeout=self._config.timeout) as client:
            response = await client.get(url)
            response.raise_for_status()

            data = response.json()

        articles = []
        for item in data.get("articles", []):
            articles.append(GDELTArticle(
                url=item.get("url", ""),
                title=item.get("title", ""),
                source_domain=item.get("domain", ""),
                source_country=item.get("sourcecountry", ""),
                language=item.get("language", ""),
                published_at=item.get("seendate", ""),
                tone=float(item.get("tone", 0)),
                image_url=item.get("socialimage", ""),
                social_shares=int(item.get("socialsharecount", 0)),
                themes=_parse_semicolon_list(item.get("themes", "")),
                locations=_parse_semicolon_list(item.get("locations", "")),
                persons=_parse_semicolon_list(item.get("persons", "")),
                organizations=_parse_semicolon_list(item.get("organizations", "")),
            ))

        return articles


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stable_id(value: str) -> str:
    """Generate a stable short ID from a string."""
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def _parse_semicolon_list(value: str | list) -> list[str]:
    """Parse GDELT semicolon-separated field into list."""
    if isinstance(value, list):
        return value
    if not value or not isinstance(value, str):
        return []
    return [item.strip() for item in value.split(";") if item.strip()]
