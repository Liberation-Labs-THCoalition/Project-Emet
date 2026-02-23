"""Tests for GDELT real-time feed adapter — Sprint 15.

Tests configuration, FtM conversion, article parsing, and client behavior.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from emet.ftm.external.gdelt import (
    GDELTConfig,
    GDELTArticle,
    GDELTFeedResult,
    GDELTFtMConverter,
    GDELTClient,
    _stable_id,
    _parse_semicolon_list,
)


# ===========================================================================
# Configuration
# ===========================================================================


class TestGDELTConfig:
    def test_defaults(self):
        cfg = GDELTConfig()
        assert cfg.timeout == 30.0
        assert cfg.max_records == 75
        assert cfg.default_timespan == "24h"

    def test_custom(self):
        cfg = GDELTConfig(
            max_records=100,
            source_countries=["US", "UK"],
            language="English",
        )
        assert cfg.max_records == 100
        assert len(cfg.source_countries) == 2


# ===========================================================================
# Helpers
# ===========================================================================


class TestHelpers:
    def test_stable_id_deterministic(self):
        assert _stable_id("test") == _stable_id("test")
        assert _stable_id("a") != _stable_id("b")

    def test_stable_id_length(self):
        assert len(_stable_id("test")) == 16

    def test_parse_semicolon_list(self):
        assert _parse_semicolon_list("a;b;c") == ["a", "b", "c"]
        assert _parse_semicolon_list("  a ; b ; c  ") == ["a", "b", "c"]
        assert _parse_semicolon_list("") == []
        assert _parse_semicolon_list(None) == []

    def test_parse_semicolon_list_already_list(self):
        assert _parse_semicolon_list(["a", "b"]) == ["a", "b"]

    def test_parse_semicolon_empty_items(self):
        assert _parse_semicolon_list("a;;b") == ["a", "b"]


# ===========================================================================
# Article & feed result
# ===========================================================================


class TestGDELTArticle:
    def test_basic(self):
        article = GDELTArticle(
            url="https://example.com/news/1",
            title="Breaking News",
            source_domain="example.com",
            tone=5.2,
        )
        assert article.title == "Breaking News"
        assert article.tone == 5.2


class TestGDELTFeedResult:
    def test_unique_sources(self):
        result = GDELTFeedResult(
            query="test",
            articles=[
                GDELTArticle(url="a", title="A", source_domain="bbc.co.uk"),
                GDELTArticle(url="b", title="B", source_domain="cnn.com"),
                GDELTArticle(url="c", title="C", source_domain="bbc.co.uk"),
            ],
            article_count=3,
        )
        assert result.unique_sources == ["bbc.co.uk", "cnn.com"]

    def test_average_tone(self):
        result = GDELTFeedResult(
            query="test",
            articles=[
                GDELTArticle(url="a", title="A", source_domain="x", tone=10.0),
                GDELTArticle(url="b", title="B", source_domain="y", tone=-5.0),
            ],
            article_count=2,
        )
        assert result.average_tone == pytest.approx(2.5)

    def test_empty_average_tone(self):
        result = GDELTFeedResult(query="test")
        assert result.average_tone == 0.0


# ===========================================================================
# FtM converter
# ===========================================================================


class TestGDELTFtMConverter:
    def _sample_article(self, **kwargs) -> GDELTArticle:
        defaults = {
            "url": "https://example.com/news/corruption-probe",
            "title": "Major Corruption Probe Launched",
            "source_domain": "example.com",
            "source_country": "US",
            "language": "English",
            "published_at": "20250220T120000Z",
            "tone": -3.5,
            "themes": ["CORRUPTION", "GOVERNMENT"],
            "persons": ["John Smith", "Jane Doe"],
            "organizations": ["Acme Corp", "Big Bank"],
        }
        defaults.update(kwargs)
        return GDELTArticle(**defaults)

    def test_article_to_mention(self):
        converter = GDELTFtMConverter()
        entities = converter.convert_articles([self._sample_article()], query="corruption")

        mentions = [e for e in entities if e["schema"] == "Mention"]
        assert len(mentions) == 1

        mention = mentions[0]
        assert mention["properties"]["title"] == ["Major Corruption Probe Launched"]
        assert mention["properties"]["sourceUrl"] == ["https://example.com/news/corruption-probe"]
        assert mention["properties"]["publisher"] == ["example.com"]
        assert mention["_provenance"]["source"] == "gdelt"
        assert mention["_provenance"]["query"] == "corruption"
        assert mention["_provenance"]["tone"] == -3.5

    def test_persons_extracted(self):
        converter = GDELTFtMConverter()
        entities = converter.convert_articles([self._sample_article()])

        persons = [e for e in entities if e["schema"] == "Person"]
        assert len(persons) == 2
        names = {e["properties"]["name"][0] for e in persons}
        assert names == {"John Smith", "Jane Doe"}

    def test_organizations_extracted(self):
        converter = GDELTFtMConverter()
        entities = converter.convert_articles([self._sample_article()])

        orgs = [e for e in entities if e["schema"] == "Organization"]
        assert len(orgs) == 2
        names = {e["properties"]["name"][0] for e in orgs}
        assert names == {"Acme Corp", "Big Bank"}

    def test_deduplication_across_articles(self):
        converter = GDELTFtMConverter()
        articles = [
            self._sample_article(url="https://a.com/1", persons=["John Smith"]),
            self._sample_article(url="https://b.com/2", persons=["John Smith"]),
        ]
        entities = converter.convert_articles(articles)

        persons = [e for e in entities if e["schema"] == "Person"]
        assert len(persons) == 1  # Deduplicated

    def test_short_names_skipped(self):
        converter = GDELTFtMConverter()
        entities = converter.convert_articles([
            self._sample_article(persons=["AB", "CD"], organizations=["X"]),
        ])
        persons = [e for e in entities if e["schema"] == "Person"]
        orgs = [e for e in entities if e["schema"] == "Organization"]
        assert len(persons) == 0
        assert len(orgs) == 0

    def test_empty_articles(self):
        converter = GDELTFtMConverter()
        entities = converter.convert_articles([])
        assert entities == []

    def test_provenance_on_ner_entities(self):
        converter = GDELTFtMConverter()
        entities = converter.convert_articles([self._sample_article()])
        person = next(e for e in entities if e["schema"] == "Person")
        assert person["_provenance"]["source"] == "gdelt_ner"
        assert person["_provenance"]["confidence"] == 0.6

    def test_themes_in_description(self):
        converter = GDELTFtMConverter()
        entities = converter.convert_articles([self._sample_article()])
        mention = next(e for e in entities if e["schema"] == "Mention")
        desc = mention["properties"]["description"][0]
        assert "CORRUPTION" in desc
        assert "Tone: -3.5" in desc


# ===========================================================================
# Client (mocked HTTP)
# ===========================================================================


def _mock_gdelt_response():
    """Mock GDELT DOC API JSON response."""
    return {
        "articles": [
            {
                "url": "https://bbc.co.uk/news/1",
                "title": "Sanctions Hit Company",
                "domain": "bbc.co.uk",
                "sourcecountry": "UK",
                "language": "English",
                "seendate": "20250220T150000Z",
                "tone": -2.1,
                "socialimage": "https://bbc.co.uk/img.jpg",
                "socialsharecount": 150,
                "themes": "SANCTIONS;FINANCE",
                "locations": "London;New York",
                "persons": "John Doe;Jane Smith",
                "organizations": "Acme Corp;World Bank",
            },
            {
                "url": "https://cnn.com/news/2",
                "title": "Market Reaction",
                "domain": "cnn.com",
                "sourcecountry": "US",
                "language": "English",
                "seendate": "20250220T140000Z",
                "tone": 1.5,
                "socialsharecount": 80,
                "themes": "FINANCE",
                "persons": "",
                "organizations": "",
            },
        ]
    }


class TestGDELTClient:
    @pytest.mark.asyncio
    async def test_search_news(self):
        mock_response = MagicMock()
        mock_response.json.return_value = _mock_gdelt_response()
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            client = GDELTClient()
            result = await client.search_news("sanctions")

        assert result.article_count == 2
        assert result.articles[0].title == "Sanctions Hit Company"
        assert result.articles[0].source_domain == "bbc.co.uk"
        assert result.articles[0].tone == -2.1
        assert result.articles[0].persons == ["John Doe", "Jane Smith"]
        assert result.articles[1].title == "Market Reaction"

    @pytest.mark.asyncio
    async def test_search_news_ftm(self):
        mock_response = MagicMock()
        mock_response.json.return_value = _mock_gdelt_response()
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            client = GDELTClient()
            result = await client.search_news_ftm("sanctions")

        assert result["article_count"] == 2
        assert result["entity_count"] >= 2  # At least 2 mentions
        assert "bbc.co.uk" in result["unique_sources"]

    @pytest.mark.asyncio
    async def test_monitor_entity(self):
        mock_response = MagicMock()
        mock_response.json.return_value = _mock_gdelt_response()
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            client = GDELTClient()
            result = await client.monitor_entity("Acme Corp")

        assert result.query == '"Acme Corp"'
        assert result.article_count == 2

    @pytest.mark.asyncio
    async def test_empty_response(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"articles": []}
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            client = GDELTClient()
            result = await client.search_news("obscure query")

        assert result.article_count == 0
        assert result.average_tone == 0.0

    @pytest.mark.asyncio
    async def test_config_country_filter(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"articles": []}
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            config = GDELTConfig(source_countries=["US", "UK"])
            client = GDELTClient(config=config)
            await client.search_news("test")

            # Verify URL includes sourcecountry
            call_args = mock_client.get.call_args[0][0]
            assert "sourcecountry=US%2CUK" in call_args or "sourcecountry=US,UK" in call_args


# ---------------------------------------------------------------------------
# MCP tool wiring: monitor_entity should call GDELT + register change monitor
# ---------------------------------------------------------------------------


class TestMonitorEntityToolWiring:
    """Verify monitor_entity tool calls GDELT and registers change monitoring."""

    @pytest.mark.asyncio
    async def test_monitor_entity_calls_gdelt(self):
        """Tool should call GDELTClient.search_news_ftm, not just ChangeDetector."""
        from emet.mcp.tools import EmetToolExecutor

        executor = EmetToolExecutor()

        gdelt_result = {
            "query": "Acme Corp",
            "article_count": 3,
            "entity_count": 2,
            "unique_sources": ["reuters.com", "bbc.co.uk"],
            "average_tone": 1.5,
            "entities": [{"id": "e1", "schema": "Article"}],
        }

        mock_gdelt = AsyncMock()
        mock_gdelt.search_news_ftm.return_value = gdelt_result
        executor._pool["gdelt"] = mock_gdelt

        result = await executor.execute_raw(
            "monitor_entity",
            {"entity_name": "Acme Corp", "timespan": "7d"},
        )

        assert result["article_count"] == 3
        assert result["monitoring_registered"] is True
        assert len(result["unique_sources"]) == 2
        assert result["entities"] == [{"id": "e1", "schema": "Article"}]
        mock_gdelt.search_news_ftm.assert_called_once()

    @pytest.mark.asyncio
    async def test_monitor_entity_gdelt_failure_graceful(self):
        """If GDELT fails, tool should still register monitoring and return 0 articles."""
        from emet.mcp.tools import EmetToolExecutor

        executor = EmetToolExecutor()

        mock_gdelt = AsyncMock()
        mock_gdelt.search_news_ftm.side_effect = Exception("GDELT timeout")
        executor._pool["gdelt"] = mock_gdelt

        result = await executor.execute_raw(
            "monitor_entity",
            {"entity_name": "Acme Corp"},
        )

        assert result["article_count"] == 0
        assert result["monitoring_registered"] is True
        assert result["entities"] == []

    @pytest.mark.asyncio
    async def test_monitor_entity_passes_timespan(self):
        """Timespan param should be forwarded to GDELT."""
        from emet.mcp.tools import EmetToolExecutor

        executor = EmetToolExecutor()

        mock_gdelt = AsyncMock()
        mock_gdelt.search_news_ftm.return_value = {
            "article_count": 0, "entity_count": 0,
            "unique_sources": [], "average_tone": 0.0,
            "entities": [],
        }
        executor._pool["gdelt"] = mock_gdelt

        await executor.execute_raw(
            "monitor_entity",
            {"entity_name": "Acme Corp", "timespan": "24h"},
        )

        mock_gdelt.search_news_ftm.assert_called_once_with(
            query="Acme Corp",
            timespan="24h",
        )
