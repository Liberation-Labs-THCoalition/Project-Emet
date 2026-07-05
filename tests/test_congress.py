"""Tests for the Congress STOCK Act PTR adapter."""

from __future__ import annotations

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from emet.ftm.external.congress import CongressAdapter, CongressConfig


SAMPLE_RECORD = {
    "member": "Hon. Gilbert Cisneros",
    "chamber": "house",
    "state": "CA",
    "ticker": "ADBE",
    "asset_name": "Adobe Inc. - Common Stock",
    "direction": "sell",
    "amount_range": "$1,001 - $15,000",
    "amount_low": 1001,
    "amount_high": 15000,
    "transaction_date": "05/15/2026",
    "filing_date": "6/8/2026",
    "doc_id": "20034713",
    "owner": "",
}


class TestCongressConfig:
    def test_defaults(self):
        config = CongressConfig(data_dir="/tmp/x")
        assert config.data_dir == "/tmp/x"
        assert config.resolved_data_dir() == "/tmp/x"
        assert config.house_index_url == (
            "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"
        )
        assert config.timeout_seconds == 20.0

    def test_resolved_data_dir_falls_back_when_empty(self, monkeypatch):
        monkeypatch.delenv("EMET_CONGRESS_DATA_DIR", raising=False)
        config = CongressConfig()
        assert config.data_dir == ""
        assert config.resolved_data_dir() == "congress_data"

    def test_resolved_data_dir_uses_env_var(self, monkeypatch):
        monkeypatch.setenv("EMET_CONGRESS_DATA_DIR", "/custom/dir")
        config = CongressConfig()
        assert config.resolved_data_dir() == "/custom/dir"


class TestLoadDisclosures:
    def _write_transactions(self, tmp_path, records):
        path = tmp_path / "transactions.json"
        path.write_text(json.dumps(records))
        return path

    def test_load_disclosures_returns_records(self, tmp_path):
        records = [
            SAMPLE_RECORD,
            {**SAMPLE_RECORD, "doc_id": "20034714", "direction": "buy", "ticker": "MSFT"},
        ]
        self._write_transactions(tmp_path, records)

        adapter = CongressAdapter(CongressConfig(data_dir=str(tmp_path)))
        loaded = adapter.load_disclosures()

        assert loaded == records

    def test_load_disclosures_missing_file_returns_empty(self, tmp_path):
        adapter = CongressAdapter(CongressConfig(data_dir=str(tmp_path)))
        assert adapter.load_disclosures() == []

    def test_load_disclosures_malformed_json_returns_empty(self, tmp_path):
        path = tmp_path / "transactions.json"
        path.write_text("{not valid json")

        adapter = CongressAdapter(CongressConfig(data_dir=str(tmp_path)))
        assert adapter.load_disclosures() == []

    def test_load_disclosures_non_list_json_returns_empty(self, tmp_path):
        path = tmp_path / "transactions.json"
        path.write_text(json.dumps({"not": "a list"}))

        adapter = CongressAdapter(CongressConfig(data_dir=str(tmp_path)))
        assert adapter.load_disclosures() == []


class TestSearchMember:
    def _adapter_with(self, tmp_path, records):
        path = tmp_path / "transactions.json"
        path.write_text(json.dumps(records))
        return CongressAdapter(CongressConfig(data_dir=str(tmp_path)))

    def test_substring_case_insensitive_match(self, tmp_path):
        records = [
            {**SAMPLE_RECORD, "member": "Hon. Gilbert Cisneros"},
            {**SAMPLE_RECORD, "member": "Hon. Nancy Pelosi", "doc_id": "999"},
        ]
        adapter = self._adapter_with(tmp_path, records)

        results = adapter.search_member("cisneros")
        assert len(results) == 1
        assert results[0]["member"] == "Hon. Gilbert Cisneros"

        results_upper = adapter.search_member("PELOSI")
        assert len(results_upper) == 1
        assert results_upper[0]["member"] == "Hon. Nancy Pelosi"

    def test_no_match_returns_empty(self, tmp_path):
        adapter = self._adapter_with(tmp_path, [SAMPLE_RECORD])
        assert adapter.search_member("nonexistent") == []

    def test_respects_limit(self, tmp_path):
        records = [{**SAMPLE_RECORD, "doc_id": str(i)} for i in range(5)]
        adapter = self._adapter_with(tmp_path, records)
        results = adapter.search_member("cisneros", limit=2)
        assert len(results) == 2


class TestHoldingsSummary:
    def test_aggregates_buy_and_sell(self, tmp_path):
        records = [
            {
                **SAMPLE_RECORD,
                "member": "Hon. Gilbert Cisneros",
                "ticker": "ADBE",
                "direction": "sell",
                "amount_low": 1001,
                "amount_high": 15000,
                "transaction_date": "05/15/2026",
                "doc_id": "1",
            },
            {
                **SAMPLE_RECORD,
                "member": "Hon. Nancy Pelosi",
                "ticker": "ADBE",
                "direction": "buy",
                "amount_low": 15001,
                "amount_high": 50000,
                "transaction_date": "06/01/2026",
                "doc_id": "2",
            },
        ]
        path = tmp_path / "transactions.json"
        path.write_text(json.dumps(records))
        adapter = CongressAdapter(CongressConfig(data_dir=str(tmp_path)))

        summary = adapter.holdings_summary("adbe")

        assert summary["ticker"] == "ADBE"
        assert summary["buy_count"] == 1
        assert summary["sell_count"] == 1
        assert sorted(summary["members"]) == sorted(
            ["Hon. Gilbert Cisneros", "Hon. Nancy Pelosi"]
        )
        # net = buy(15001..50000) - sell(1001..15000)
        assert summary["net_amount_low"] == 15001 - 1001
        assert summary["net_amount_high"] == 50000 - 15000
        assert summary["most_recent_transaction_date"] == "06/01/2026"

    def test_no_records_for_ticker(self, tmp_path):
        path = tmp_path / "transactions.json"
        path.write_text(json.dumps([SAMPLE_RECORD]))
        adapter = CongressAdapter(CongressConfig(data_dir=str(tmp_path)))

        summary = adapter.holdings_summary("ZZZZ")
        assert summary["buy_count"] == 0
        assert summary["sell_count"] == 0
        assert summary["members"] == []
        assert summary["most_recent_transaction_date"] is None


class TestFetchHouseIndex:
    @pytest.mark.asyncio
    async def test_fetch_house_index_zip_response(self):
        mock_response = MagicMock()
        mock_response.content = b"PK\x03\x04" + b"\x00" * 100
        mock_response.headers = {"content-type": "application/zip"}
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            adapter = CongressAdapter()
            result = await adapter.fetch_house_index(year=2026)

        assert result == [
            {
                "note": "zip_index_fetched",
                "year": 2026,
                "size_bytes": len(mock_response.content),
            }
        ]

    @pytest.mark.asyncio
    async def test_fetch_house_index_raises_returns_empty(self):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx_module_error()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            adapter = CongressAdapter()
            result = await adapter.fetch_house_index(year=2026)

        assert result == []


def httpx_module_error():
    import httpx

    return httpx.ConnectError("boom")


class TestDisclosureToFtM:
    def test_converts_to_three_entities(self):
        entities = CongressAdapter.disclosure_to_ftm(SAMPLE_RECORD)

        assert len(entities) == 3
        schemas = {e["schema"] for e in entities}
        assert schemas == {"Person", "Security", "Ownership"}

        person = next(e for e in entities if e["schema"] == "Person")
        security = next(e for e in entities if e["schema"] == "Security")
        ownership = next(e for e in entities if e["schema"] == "Ownership")

        assert person["properties"]["name"] == ["Hon. Gilbert Cisneros"]
        assert person["properties"]["position"] == ["U.S. House of Representatives"]
        assert person["id"] == "congress-member:hon-gilbert-cisneros"

        assert security["properties"]["ticker"] == ["ADBE"]
        assert security["properties"]["name"] == ["Adobe Inc. - Common Stock"]
        assert security["id"] == "congress-security:ADBE"

        assert ownership["properties"]["owner"] == [person["id"]]
        assert ownership["properties"]["asset"] == [security["id"]]
        assert ownership["properties"]["role"] == ["sell"]
        assert ownership["properties"]["startDate"] == ["2026-05-15"]
        assert ownership["properties"]["summary"] == ["$1,001 - $15,000"]

        for entity in entities:
            assert entity["_provenance"]["source"] == "congress_stock_act"
            assert entity["_provenance"]["source_id"] == "20034713"
            assert entity["_provenance"]["confidence"] == 0.9

    def test_senate_chamber_position(self):
        record = {**SAMPLE_RECORD, "chamber": "senate"}
        entities = CongressAdapter.disclosure_to_ftm(record)
        person = next(e for e in entities if e["schema"] == "Person")
        assert person["properties"]["position"] == ["U.S. Senate"]

    def test_single_digit_date_parses(self):
        record = {**SAMPLE_RECORD, "transaction_date": "6/8/2026"}
        entities = CongressAdapter.disclosure_to_ftm(record)
        ownership = next(e for e in entities if e["schema"] == "Ownership")
        assert ownership["properties"]["startDate"] == ["2026-06-08"]
