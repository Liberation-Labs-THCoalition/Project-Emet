"""Tests for the congressional financial disclosure adapter."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from emet.ftm.external.congress import (
    CongressAdapter,
    CongressConfig,
    member_to_ftm,
    security_to_ftm,
    transaction_to_ftm,
)


SAMPLE_TX = {
    "member": "Nancy Pelosi",
    "chamber": "house",
    "state": "CA",
    "ticker": "NVDA",
    "asset_name": "NVIDIA Corp",
    "direction": "buy",
    "amount_range": "$1,000,001 - $5,000,000",
    "transaction_date": "01/02/2026",
    "filing_date": "01/20/2026",
    "doc_id": "DOC1",
    "owner": "SP",
}


class TestConverters:
    def test_member_to_ftm(self):
        e = member_to_ftm("Nancy Pelosi", "house", "CA")
        assert e["schema"] == "Person"
        assert e["properties"]["name"] == ["Nancy Pelosi"]
        assert e["properties"]["country"] == ["us"]
        assert e["id"] == "congress:person:nancy-pelosi"

    def test_security_to_ftm(self):
        e = security_to_ftm("nvda", "NVIDIA Corp")
        assert e["schema"] == "Security"
        assert e["properties"]["ticker"] == ["NVDA"]
        assert e["id"] == "congress:asset:NVDA"

    def test_transaction_to_ftm_returns_three(self):
        ents = transaction_to_ftm(SAMPLE_TX)
        schemas = [e["schema"] for e in ents]
        assert schemas == ["Person", "Security", "Ownership"]
        ownership = ents[2]
        assert ownership["_relationship"]["owner"] == "congress:person:nancy-pelosi"
        assert ownership["_relationship"]["asset"] == "congress:asset:NVDA"
        assert "buy NVDA" in ownership["properties"]["summary"][0]

    def test_transaction_missing_ticker_skipped(self):
        assert transaction_to_ftm({"member": "X", "ticker": ""}) == []


class TestAdapter:
    def test_load_disclosures_missing_dir(self):
        adapter = CongressAdapter(CongressConfig(data_dir=""))
        assert adapter.load_disclosures() == []

    def test_load_and_search(self, tmp_path):
        (tmp_path / "transactions.json").write_text(json.dumps([SAMPLE_TX]))
        adapter = CongressAdapter(CongressConfig(data_dir=str(tmp_path)))
        entities = adapter.search_member("pelosi")
        ids = {e["id"] for e in entities}
        assert "congress:person:nancy-pelosi" in ids
        assert "congress:asset:NVDA" in ids

    def test_search_no_match(self, tmp_path):
        (tmp_path / "transactions.json").write_text(json.dumps([SAMPLE_TX]))
        adapter = CongressAdapter(CongressConfig(data_dir=str(tmp_path)))
        assert adapter.search_member("nonexistent") == []

    def test_holdings_summary(self, tmp_path):
        txs = [SAMPLE_TX, {**SAMPLE_TX, "direction": "sell", "doc_id": "DOC2"}]
        (tmp_path / "transactions.json").write_text(json.dumps(txs))
        adapter = CongressAdapter(CongressConfig(data_dir=str(tmp_path)))
        summary = adapter.holdings_summary("pelosi")
        assert summary["ticker_count"] == 1
        holding = summary["holdings"][0]
        assert holding["ticker"] == "NVDA"
        assert holding["buys"] == 1
        assert holding["sells"] == 1

    def test_parse_house_zip(self):
        xml = (
            "<FinancialDisclosure>"
            "<Member><FilingType>P</FilingType><First>Jane</First>"
            "<Last>Doe</Last><StateDst>CA12</StateDst>"
            "<FilingDate>1/2/2026</FilingDate><DocID>9</DocID></Member>"
            "<Member><FilingType>O</FilingType><First>Skip</First>"
            "<Last>Me</Last></Member>"
            "</FinancialDisclosure>"
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("2026FD.xml", xml)
        filings = CongressAdapter._parse_house_zip(buf.getvalue(), 2026)
        assert len(filings) == 1
        assert filings[0]["member"] == "Jane Doe"
        assert filings[0]["state"] == "CA"
        assert filings[0]["doc_id"] == "9"
