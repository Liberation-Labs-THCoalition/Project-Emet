"""Tests for SEC EDGAR API adapter."""

from __future__ import annotations

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from emet.ftm.external.edgar import (
    EDGARClient,
    EDGARConfig,
    EDGARCompany,
    EDGARFiling,
)

_ATOM_FEED_ALL = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>SEC EDGAR Current Events</title>
  <entry>
    <title>4 - ACME CORP (0001234567) (Reporting)</title>
    <link href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;CIK=0001234567&amp;type=4" rel="alternate" type="text/html"/>
    <summary type="html">&lt;b&gt;Filed:&lt;/b&gt; 2024-03-15 &lt;b&gt;AccNo:&lt;/b&gt; 0001234567-24-000001 &lt;b&gt;Size:&lt;/b&gt; 4 KB</summary>
    <updated>2024-03-15T16:30:00-04:00</updated>
    <id>urn:tag:sec.gov,2008:accession-number=0001234567-24-000001</id>
  </entry>
  <entry>
    <title>SC 13D - BETA HOLDINGS INC (0009876543) (Subject)</title>
    <link href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;CIK=0009876543&amp;type=SC+13D" rel="alternate" type="text/html"/>
    <summary type="html">&lt;b&gt;Filed:&lt;/b&gt; 2024-03-14 &lt;b&gt;AccNo:&lt;/b&gt; 0009876543-24-000009 &lt;b&gt;Size:&lt;/b&gt; 12 KB</summary>
    <updated>2024-03-14T09:15:00-04:00</updated>
    <id>urn:tag:sec.gov,2008:accession-number=0009876543-24-000009</id>
  </entry>
  <entry>
    <title>8-K - GAMMA CO (1234567) (Filer)</title>
    <link href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;CIK=1234567&amp;type=8-K" rel="alternate" type="text/html"/>
    <summary type="html">&lt;b&gt;Filed:&lt;/b&gt; 2024-03-16 &lt;b&gt;AccNo:&lt;/b&gt; 0001234567-24-000002 &lt;b&gt;Size:&lt;/b&gt; 8 KB</summary>
    <updated>2024-03-16T11:00:00-04:00</updated>
    <id>urn:tag:sec.gov,2008:accession-number=0001234567-24-000002</id>
  </entry>
</feed>
"""

_ATOM_FEED_FORM_4 = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>SEC EDGAR Current Events - Form 4</title>
  <entry>
    <title>4 - ACME CORP (0001234567) (Reporting)</title>
    <link href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;CIK=0001234567&amp;type=4" rel="alternate" type="text/html"/>
    <summary type="html">&lt;b&gt;Filed:&lt;/b&gt; 2024-03-15 &lt;b&gt;AccNo:&lt;/b&gt; 0001234567-24-000001 &lt;b&gt;Size:&lt;/b&gt; 4 KB</summary>
    <updated>2024-03-15T16:30:00-04:00</updated>
    <id>urn:tag:sec.gov,2008:accession-number=0001234567-24-000001</id>
  </entry>
  <entry>
    <title>4 - DELTA INC (0001111111) (Reporting)</title>
    <link href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;CIK=0001111111&amp;type=4" rel="alternate" type="text/html"/>
    <summary type="html">&lt;b&gt;Filed:&lt;/b&gt; 2024-03-17 &lt;b&gt;AccNo:&lt;/b&gt; 0001111111-24-000005 &lt;b&gt;Size:&lt;/b&gt; 4 KB</summary>
    <updated>2024-03-17T10:00:00-04:00</updated>
    <id>urn:tag:sec.gov,2008:accession-number=0001111111-24-000005</id>
  </entry>
</feed>
"""

_ATOM_FEED_FORM_8K = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>SEC EDGAR Current Events - Form 8-K</title>
  <entry>
    <title>8-K - GAMMA CO (1234567) (Filer)</title>
    <link href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;CIK=1234567&amp;type=8-K" rel="alternate" type="text/html"/>
    <summary type="html">&lt;b&gt;Filed:&lt;/b&gt; 2024-03-16 &lt;b&gt;AccNo:&lt;/b&gt; 0001234567-24-000002 &lt;b&gt;Size:&lt;/b&gt; 8 KB</summary>
    <updated>2024-03-16T11:00:00-04:00</updated>
    <id>urn:tag:sec.gov,2008:accession-number=0001234567-24-000002</id>
  </entry>
  <entry>
    <!-- Duplicate accession number across forms should be deduped -->
    <title>4 - ACME CORP (0001234567) (Reporting)</title>
    <link href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;CIK=0001234567&amp;type=4" rel="alternate" type="text/html"/>
    <summary type="html">&lt;b&gt;Filed:&lt;/b&gt; 2024-03-15 &lt;b&gt;AccNo:&lt;/b&gt; 0001234567-24-000001 &lt;b&gt;Size:&lt;/b&gt; 4 KB</summary>
    <updated>2024-03-15T16:30:00-04:00</updated>
    <id>urn:tag:sec.gov,2008:accession-number=0001234567-24-000001</id>
  </entry>
</feed>
"""


def _make_atom_response(xml_text: str) -> MagicMock:
    resp = MagicMock()
    resp.text = xml_text
    resp.raise_for_status.return_value = None
    return resp


class TestEDGARConfig:
    def test_defaults(self):
        config = EDGARConfig()
        assert "Emet" in config.user_agent
        assert config.timeout_seconds == 20.0
        assert config.max_results == 40


class TestEDGARFtMConversion:
    def test_company_to_ftm(self):
        company = EDGARCompany(
            cik="0001234567",
            name="Acme Corp",
            ticker="ACME",
            sic_description="Manufacturing",
            state_of_incorporation="DE",
        )
        entity = EDGARClient.company_to_ftm(company)
        assert entity["schema"] == "Company"
        assert "Acme Corp" in entity["properties"]["name"]
        assert "ACME" in entity["properties"]["ticker"]
        assert entity["datasets"] == ["sec_edgar"]

    def test_filing_to_ftm(self):
        filing = EDGARFiling(
            accession_number="0001234567-24-000001",
            filing_type="10-K",
            filing_date="2024-03-15",
            company_name="Acme Corp",
            cik="0001234567",
            description="Annual report",
            document_url="https://www.sec.gov/Archives/edgar/data/0001234567/filing.htm",
        )
        entity = EDGARClient.filing_to_ftm(filing)
        assert entity["schema"] == "Document"
        assert "10-K" in entity["properties"]["title"][0]
        assert entity["properties"]["date"] == ["2024-03-15"]

    def test_company_to_ftm_minimal(self):
        company = EDGARCompany(cik="", name="Unknown")
        entity = EDGARClient.company_to_ftm(company)
        assert entity["schema"] == "Company"
        assert "registrationNumber" not in entity["properties"]


class TestEDGARClient:
    @pytest.mark.asyncio
    async def test_search_companies(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "0": {"cik_str": 1234567, "ticker": "ACME", "title": "ACME CORP"},
            "1": {"cik_str": 7654321, "ticker": "FOO", "title": "FOO INDUSTRIES"},
        }
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = EDGARClient()
            results = await client.search_companies("acme")

        assert len(results) == 1
        assert results[0].name == "ACME CORP"
        assert results[0].ticker == "ACME"

    @pytest.mark.asyncio
    async def test_search_companies_ftm(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "0": {"cik_str": 1234567, "ticker": "ACME", "title": "ACME CORP"},
        }
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = EDGARClient()
            result = await client.search_companies_ftm("acme")

        assert result["result_count"] == 1
        assert result["entities"][0]["schema"] == "Company"

    @pytest.mark.asyncio
    async def test_get_company_filings(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "name": "ACME CORP",
            "filings": {
                "recent": {
                    "form": ["10-K", "8-K", "10-Q"],
                    "filingDate": ["2024-03-15", "2024-02-01", "2024-01-10"],
                    "accessionNumber": ["001-24-000001", "001-24-000002", "001-24-000003"],
                    "primaryDocument": ["filing.htm", "report.htm", "quarterly.htm"],
                    "primaryDocDescription": ["Annual report", "Current report", "Quarterly"],
                },
            },
        }
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = EDGARClient()
            filings = await client.get_company_filings("1234567", filing_types=["10-K"], limit=5)

        assert len(filings) == 1
        assert filings[0].filing_type == "10-K"
        assert filings[0].company_name == "ACME CORP"


class TestEDGARFederation:
    """Test that EDGAR is wired into federation."""

    def test_federation_includes_edgar(self):
        from emet.ftm.external.federation import FederatedSearch, FederationConfig

        fed = FederatedSearch(FederationConfig())
        assert "edgar" in fed._clients

    def test_federation_can_disable_edgar(self):
        from emet.ftm.external.federation import FederatedSearch, FederationConfig

        fed = FederatedSearch(FederationConfig(enable_edgar=False))
        assert "edgar" not in fed._clients


class TestEDGARRecentFilings:
    """Tests for the real-time EDGAR 'getcurrent' Atom firehose."""

    @pytest.mark.asyncio
    async def test_fetch_recent_filings_parses_entries(self):
        mock_response = _make_atom_response(_ATOM_FEED_ALL)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = EDGARClient()
            filings = await client.fetch_recent_filings()

        assert len(filings) == 3

        by_acc = {f.accession_number: f for f in filings}

        form4 = by_acc["0001234567-24-000001"]
        assert form4.filing_type == "4"
        assert form4.company_name == "ACME CORP"
        assert form4.cik == "0001234567"
        assert form4.filing_date == "2024-03-15"

        # Multi-word form type "SC 13D" should be parsed correctly (not truncated).
        sc13d = by_acc["0009876543-24-000009"]
        assert sc13d.filing_type == "SC 13D"
        assert sc13d.company_name == "BETA HOLDINGS INC"
        assert sc13d.cik == "0009876543"
        assert sc13d.filing_date == "2024-03-14"

        # Short, non-zero-padded CIK in the title should be zero-padded to 10 digits.
        gamma = by_acc["0001234567-24-000002"]
        assert gamma.filing_type == "8-K"
        assert gamma.company_name == "GAMMA CO"
        assert gamma.cik == "0001234567"

        # Results should be sorted by filing_date descending.
        assert [f.filing_date for f in filings] == sorted(
            (f.filing_date for f in filings), reverse=True
        )

    @pytest.mark.asyncio
    async def test_fetch_recent_filings_multiple_forms_merged_and_deduped(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=[
                    _make_atom_response(_ATOM_FEED_FORM_4),
                    _make_atom_response(_ATOM_FEED_FORM_8K),
                ]
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = EDGARClient()
            filings = await client.fetch_recent_filings(forms=["4", "8-K"])

        assert mock_client.get.call_count == 2

        accessions = [f.accession_number for f in filings]
        # 0001234567-24-000001 appears in both feeds and must be deduped.
        assert accessions.count("0001234567-24-000001") == 1
        assert set(accessions) == {
            "0001234567-24-000001",
            "0001111111-24-000005",
            "0001234567-24-000002",
        }

    @pytest.mark.asyncio
    async def test_fetch_recent_filings_partial_degradation(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=[
                    _make_atom_response(_ATOM_FEED_FORM_4),
                    httpx.HTTPError("boom"),
                ]
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = EDGARClient()
            filings = await client.fetch_recent_filings(forms=["4", "8-K"])

        assert mock_client.get.call_count == 2
        accessions = {f.accession_number for f in filings}
        # Form "4" results should still come back despite form "8-K" failing.
        assert accessions == {"0001234567-24-000001", "0001111111-24-000005"}

    @pytest.mark.asyncio
    async def test_fetch_recent_filings_ftm(self):
        mock_response = _make_atom_response(_ATOM_FEED_ALL)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            client = EDGARClient()
            result = await client.fetch_recent_filings_ftm()

        assert result["filing_count"] == 3
        assert len(result["entities"]) == 3
        for entity in result["entities"]:
            assert entity["schema"] == "Document"
            assert entity["datasets"] == ["sec_edgar"]
