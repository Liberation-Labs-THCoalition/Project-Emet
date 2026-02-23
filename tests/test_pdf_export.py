"""Tests for PDF report generation."""

from __future__ import annotations

import os
import pytest
from pathlib import Path

from emet.export.markdown import InvestigationReport
from emet.export.pdf import PDFReport, PDFBranding


@pytest.fixture
def sample_report() -> InvestigationReport:
    return InvestigationReport(
        title="Shell Company Network Investigation",
        summary=(
            "Investigation into Acme Holdings Ltd revealed a network of "
            "shell companies across three jurisdictions with common directors "
            "and suspicious transaction patterns."
        ),
        entities=[
            {
                "schema": "Company",
                "properties": {
                    "name": ["Acme Holdings Ltd"],
                    "jurisdiction": ["GB"],
                    "registrationNumber": ["12345678"],
                },
                "_provenance": {"source": "companies_house", "confidence": 0.95},
            },
            {
                "schema": "Person",
                "properties": {
                    "name": ["John Smith"],
                    "nationality": ["GB"],
                },
                "_provenance": {"source": "opensanctions", "confidence": 0.8},
            },
        ],
        graph_findings={
            "central_entities": ["Acme Holdings Ltd"],
            "communities": [{"name": "UK Shell Network", "size": 4}],
            "risk_indicators": ["Common director pattern", "Recent incorporation"],
        },
        timeline_events=[
            {"date": "2023-01-15", "description": "Acme Holdings incorporated"},
            {"date": "2023-06-01", "description": "First suspicious transfer"},
        ],
        data_sources=[
            {"name": "UK Companies House", "url": "https://api.company-information.service.gov.uk"},
            {"name": "OpenSanctions", "url": "https://api.opensanctions.org"},
        ],
        caveats=[
            "Open-source data only; no proprietary intelligence feeds",
            "Beneficial ownership may be incomplete",
        ],
        metadata={
            "turns": 8,
            "entity_count": 12,
            "finding_count": 3,
            "duration_seconds": 14.2,
        },
    )


class TestPDFBranding:
    def test_defaults_are_navy_gold(self):
        b = PDFBranding()
        assert b.primary_color == (0, 51, 102)   # Navy
        assert b.accent_color == (212, 175, 55)    # Gold
        assert b.org_name == "Project Emet"

    def test_custom_branding(self):
        b = PDFBranding(
            primary_color=(0, 0, 0),
            accent_color=(255, 0, 0),
            org_name="My Org",
        )
        assert b.primary_color == (0, 0, 0)
        assert b.org_name == "My Org"


class TestPDFReport:
    def test_generate_creates_file(self, sample_report, tmp_path):
        output = tmp_path / "test_report.pdf"
        pdf = PDFReport()
        result = pdf.generate(sample_report, output_path=output)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_generate_default_branding(self, sample_report, tmp_path):
        output = tmp_path / "default_branding.pdf"
        pdf = PDFReport()
        result = pdf.generate(sample_report, output_path=output)
        # Just verify it generates without error
        assert result.exists()

    def test_generate_custom_branding(self, sample_report, tmp_path):
        output = tmp_path / "custom_branding.pdf"
        branding = PDFBranding(
            primary_color=(50, 50, 50),
            accent_color=(0, 128, 255),
            org_name="Custom Org",
            footer_text="TOP SECRET",
        )
        pdf = PDFReport(branding=branding)
        result = pdf.generate(sample_report, output_path=output)
        assert result.exists()

    def test_generate_minimal_report(self, tmp_path):
        """PDF should work with minimal/empty report."""
        output = tmp_path / "minimal.pdf"
        report = InvestigationReport(title="Minimal Test")
        pdf = PDFReport()
        result = pdf.generate(report, output_path=output)
        assert result.exists()

    def test_generate_no_provenance(self, sample_report, tmp_path):
        output = tmp_path / "no_prov.pdf"
        pdf = PDFReport(include_provenance=False)
        result = pdf.generate(sample_report, output_path=output)
        assert result.exists()

    def test_pdf_is_valid_header(self, sample_report, tmp_path):
        """Generated file should start with %PDF magic bytes."""
        output = tmp_path / "valid.pdf"
        pdf = PDFReport()
        pdf.generate(sample_report, output_path=output)
        with open(output, "rb") as f:
            header = f.read(5)
        assert header == b"%PDF-"

    def test_import_from_package(self):
        """PDFReport should be importable from emet.export."""
        from emet.export import PDFReport as PR, PDFBranding as PB
        assert PR is not None
        assert PB is not None
