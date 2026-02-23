"""PDF investigation report generator.

Produces branded PDF reports from InvestigationReport data. Navy/gold
default branding with configurable colors and logo.

Uses reportlab (already installed). No external dependencies.

Usage:
    from emet.export.pdf import PDFReport, PDFBranding
    from emet.export.markdown import InvestigationReport

    report = InvestigationReport(title="Shell Company Network", ...)
    pdf = PDFReport()
    pdf.generate(report, output_path="investigation.pdf")

    # Custom branding
    branding = PDFBranding(
        primary_color=(0, 51, 102),   # Navy
        accent_color=(212, 175, 55),   # Gold
        org_name="Your Org",
    )
    pdf = PDFReport(branding=branding)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from emet.export.markdown import InvestigationReport

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Branding configuration
# ---------------------------------------------------------------------------


@dataclass
class PDFBranding:
    """Branding configuration for PDF reports.

    Colors are RGB tuples (0-255).
    """
    # Navy/gold defaults
    primary_color: tuple[int, int, int] = (0, 51, 102)      # Navy
    accent_color: tuple[int, int, int] = (212, 175, 55)      # Gold
    text_color: tuple[int, int, int] = (33, 33, 33)          # Dark gray
    light_bg: tuple[int, int, int] = (245, 245, 250)         # Light gray-blue
    white: tuple[int, int, int] = (255, 255, 255)

    org_name: str = "Project Emet"
    subtitle: str = "Investigation Report"
    logo_path: str = ""  # Optional path to logo image
    footer_text: str = "CONFIDENTIAL — Not for public distribution"

    # Fonts (built-in reportlab fonts)
    title_font: str = "Helvetica-Bold"
    heading_font: str = "Helvetica-Bold"
    body_font: str = "Helvetica"
    mono_font: str = "Courier"

    # Sizing
    page_margin: float = 50.0  # points
    title_size: float = 24.0
    heading_size: float = 14.0
    subheading_size: float = 11.0
    body_size: float = 10.0
    small_size: float = 8.0


# ---------------------------------------------------------------------------
# PDF report generator
# ---------------------------------------------------------------------------


class PDFReport:
    """Generate branded PDF investigation reports.

    Parameters
    ----------
    branding:
        Visual branding configuration. Defaults to navy/gold.
    include_provenance:
        Include data source provenance for each entity.
    include_confidence:
        Include confidence scores in findings.
    """

    def __init__(
        self,
        branding: PDFBranding | None = None,
        include_provenance: bool = True,
        include_confidence: bool = True,
    ) -> None:
        self._brand = branding or PDFBranding()
        self._include_provenance = include_provenance
        self._include_confidence = include_confidence

    def generate(
        self,
        report: InvestigationReport,
        output_path: str | Path = "investigation_report.pdf",
    ) -> Path:
        """Generate PDF report and write to file.

        Returns path to generated PDF.
        """
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.units import mm
            from reportlab.pdfgen.canvas import Canvas
            from reportlab.lib.colors import Color
        except ImportError:
            raise ImportError(
                "reportlab is required for PDF export. "
                "Install with: pip install reportlab"
            )

        output = Path(output_path)
        b = self._brand

        c = Canvas(str(output), pagesize=A4)
        width, height = A4
        margin = b.page_margin
        usable_w = width - 2 * margin

        # State tracking
        y = height - margin

        def _color(rgb: tuple[int, int, int]) -> Color:
            return Color(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)

        def _new_page() -> float:
            """Start a new page with footer, return y position."""
            _draw_footer(c, width, b)
            c.showPage()
            return height - margin

        def _check_space(needed: float, current_y: float) -> float:
            """If not enough space, start new page."""
            if current_y - needed < margin + 40:
                return _new_page()
            return current_y

        # ===== COVER / HEADER =====

        # Navy header band
        c.setFillColor(_color(b.primary_color))
        c.rect(0, height - 120, width, 120, fill=True, stroke=False)

        # Gold accent line
        c.setFillColor(_color(b.accent_color))
        c.rect(0, height - 124, width, 4, fill=True, stroke=False)

        # Title text
        c.setFillColor(_color(b.white))
        c.setFont(b.title_font, b.title_size)
        c.drawString(margin, height - 55, report.title[:60])

        # Subtitle
        c.setFont(b.body_font, b.subheading_size)
        c.drawString(margin, height - 78, b.subtitle)

        # Date + org
        c.setFont(b.body_font, b.small_size)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        c.drawString(margin, height - 100, f"{b.org_name}  •  {now}")

        y = height - 150

        # ===== EXECUTIVE SUMMARY =====
        if report.summary:
            y = _check_space(80, y)
            y = self._draw_section_header(c, "Executive Summary", margin, y, b)
            y = self._draw_wrapped_text(
                c, report.summary, margin, y, usable_w, b,
                font=b.body_font, size=b.body_size,
            )
            y -= 15

        # ===== METADATA BOX =====
        meta = report.metadata
        if meta:
            y = _check_space(80, y)
            y = self._draw_section_header(c, "Investigation Details", margin, y, b)

            # Light background box
            box_items = []
            if meta.get("turns"):
                box_items.append(f"Agent turns: {meta['turns']}")
            if meta.get("entity_count"):
                box_items.append(f"Entities found: {meta['entity_count']}")
            if meta.get("finding_count"):
                box_items.append(f"Findings: {meta['finding_count']}")
            if meta.get("duration_seconds"):
                box_items.append(f"Duration: {meta['duration_seconds']:.1f}s")

            if box_items:
                box_h = len(box_items) * 16 + 16
                c.setFillColor(_color(b.light_bg))
                c.rect(margin, y - box_h, usable_w, box_h, fill=True, stroke=False)

                # Gold left border
                c.setFillColor(_color(b.accent_color))
                c.rect(margin, y - box_h, 3, box_h, fill=True, stroke=False)

                c.setFillColor(_color(b.text_color))
                c.setFont(b.body_font, b.body_size)
                text_y = y - 14
                for item in box_items:
                    c.drawString(margin + 12, text_y, item)
                    text_y -= 16
                y = y - box_h - 10

        # ===== ENTITIES =====
        if report.entities:
            y = _check_space(60, y)
            y = self._draw_section_header(
                c, f"Entities ({len(report.entities)})", margin, y, b,
            )

            for entity in report.entities:
                y = _check_space(50, y)
                schema = entity.get("schema", "Unknown")
                props = entity.get("properties", {})
                name = ", ".join(props.get("name", ["Unnamed"]))

                # Entity name with schema badge
                c.setFillColor(_color(b.primary_color))
                c.setFont(b.heading_font, b.subheading_size)
                c.drawString(margin + 5, y, f"[{schema}]")

                badge_w = c.stringWidth(f"[{schema}]", b.heading_font, b.subheading_size)
                c.setFillColor(_color(b.text_color))
                c.setFont(b.body_font, b.subheading_size)
                c.drawString(margin + 5 + badge_w + 8, y, name[:70])
                y -= 16

                # Key properties
                skip_keys = {"name", "id"}
                for key, vals in props.items():
                    if key in skip_keys or not vals:
                        continue
                    y = _check_space(16, y)
                    c.setFont(b.body_font, b.small_size)
                    c.setFillColor(_color((100, 100, 100)))
                    val_str = ", ".join(str(v) for v in vals[:3])
                    c.drawString(margin + 15, y, f"{key}: {val_str[:80]}")
                    y -= 13

                # Provenance
                prov = entity.get("_provenance", {})
                if prov and self._include_provenance:
                    y = _check_space(14, y)
                    c.setFont(b.mono_font, 7)
                    c.setFillColor(_color((140, 140, 140)))
                    src = prov.get("source", "")
                    conf = prov.get("confidence", "")
                    c.drawString(margin + 15, y, f"Source: {src}  Confidence: {conf}")
                    y -= 13

                y -= 8  # spacing between entities

        # ===== GRAPH FINDINGS =====
        gf = report.graph_findings
        if gf:
            y = _check_space(60, y)
            y = self._draw_section_header(c, "Graph Analysis Findings", margin, y, b)

            for key in ("central_entities", "communities", "risk_indicators"):
                items = gf.get(key, [])
                if not items:
                    continue
                y = _check_space(30, y)
                c.setFont(b.heading_font, b.body_size)
                c.setFillColor(_color(b.primary_color))
                c.drawString(margin + 5, y, key.replace("_", " ").title())
                y -= 14

                for item in items[:5]:
                    y = _check_space(14, y)
                    c.setFont(b.body_font, b.small_size)
                    c.setFillColor(_color(b.text_color))
                    text = str(item) if isinstance(item, str) else str(item.get("name", item))
                    c.drawString(margin + 15, y, f"• {text[:90]}")
                    y -= 13

        # ===== TIMELINE =====
        if report.timeline_events:
            y = _check_space(60, y)
            y = self._draw_section_header(
                c, f"Timeline ({len(report.timeline_events)} events)", margin, y, b,
            )

            for event in report.timeline_events[:20]:
                y = _check_space(30, y)
                date_str = event.get("date", "")
                desc = event.get("description", event.get("summary", ""))

                c.setFont(b.mono_font, b.small_size)
                c.setFillColor(_color(b.accent_color))
                c.drawString(margin + 5, y, date_str[:12])

                c.setFont(b.body_font, b.small_size)
                c.setFillColor(_color(b.text_color))
                c.drawString(margin + 85, y, desc[:80])
                y -= 14

        # ===== DATA SOURCES =====
        if report.data_sources:
            y = _check_space(60, y)
            y = self._draw_section_header(c, "Data Sources", margin, y, b)

            for src in report.data_sources:
                y = _check_space(14, y)
                c.setFont(b.body_font, b.small_size)
                c.setFillColor(_color(b.text_color))
                name = src.get("name", "Unknown")
                url = src.get("url", "")
                c.drawString(margin + 5, y, f"• {name}: {url}"[:90])
                y -= 13

        # ===== CAVEATS =====
        if report.caveats:
            y = _check_space(60, y)
            y = self._draw_section_header(c, "Caveats & Limitations", margin, y, b)

            for caveat in report.caveats:
                y = _check_space(14, y)
                c.setFont(b.body_font, b.small_size)
                c.setFillColor(_color((120, 120, 120)))
                c.drawString(margin + 5, y, f"⚠ {caveat[:90]}")
                y -= 13

        # Final footer
        _draw_footer(c, width, b)
        c.save()

        logger.info("PDF report generated: %s", output)
        return output

    # -----------------------------------------------------------------------
    # Drawing helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _draw_section_header(
        c: Any,
        title: str,
        x: float,
        y: float,
        b: PDFBranding,
    ) -> float:
        """Draw a section heading with gold underline. Returns new y."""
        from reportlab.lib.colors import Color

        c.setFont(b.heading_font, b.heading_size)
        c.setFillColor(Color(b.primary_color[0]/255, b.primary_color[1]/255, b.primary_color[2]/255))
        c.drawString(x, y, title)
        y -= 4

        # Gold underline
        c.setStrokeColor(Color(b.accent_color[0]/255, b.accent_color[1]/255, b.accent_color[2]/255))
        c.setLineWidth(1.5)
        c.line(x, y, x + 200, y)
        y -= 16
        return y

    @staticmethod
    def _draw_wrapped_text(
        c: Any,
        text: str,
        x: float,
        y: float,
        max_width: float,
        b: PDFBranding,
        font: str = "",
        size: float = 0,
    ) -> float:
        """Draw text with word wrapping. Returns new y."""
        from reportlab.lib.colors import Color

        font = font or b.body_font
        size = size or b.body_size
        c.setFont(font, size)
        c.setFillColor(Color(b.text_color[0]/255, b.text_color[1]/255, b.text_color[2]/255))

        words = text.split()
        line = ""
        line_height = size + 3

        for word in words:
            test = f"{line} {word}".strip()
            if c.stringWidth(test, font, size) > max_width:
                if line:
                    c.drawString(x, y, line)
                    y -= line_height
                line = word
            else:
                line = test

        if line:
            c.drawString(x, y, line)
            y -= line_height

        return y


def _draw_footer(c: Any, page_width: float, b: PDFBranding) -> None:
    """Draw page footer with confidentiality notice."""
    from reportlab.lib.colors import Color

    c.setFont(b.body_font, 7)
    c.setFillColor(Color(0.6, 0.6, 0.6))
    c.drawCentredString(page_width / 2, 25, b.footer_text)

    # Gold bottom line
    c.setStrokeColor(Color(b.accent_color[0]/255, b.accent_color[1]/255, b.accent_color[2]/255))
    c.setLineWidth(1)
    c.line(b.page_margin, 35, page_width - b.page_margin, 35)
