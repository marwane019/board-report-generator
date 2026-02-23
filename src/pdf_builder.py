"""
pdf_builder.py — Board Report PDF Generator.

Produces a professional, multi-page PDF using ReportLab (platypus layout engine)
with embedded matplotlib charts. The output matches the design quality of a
Big-4 consulting deliverable:

    Page 1:  Cover — company name, report title, period, confidential footer
    Page 2:  Executive Summary — RAG dashboard + narrative
    Page 3:  Financial Performance — revenue/EBITDA charts + commentary
    Page 4:  Commercial Performance — pipeline chart + win-rate
    Page 5:  Customer & Retention — ARR waterfall + churn/NPS
    Page 6:  Operational Metrics — headcount chart + people cost commentary
    Page 7:  Outlook & Risk Register table

Charts are rendered as matplotlib PNG byte streams, embedded in the PDF.
No temp files written to disk — everything passes through BytesIO.
"""

import io
import logging
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")  # non-interactive backend — no display needed
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import yaml

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import HRFlowable

from src.metrics import MetricsPackage
from src.narrative import NarrativePackage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Brand constants (loaded from config at runtime)
# ---------------------------------------------------------------------------
_BRAND: dict[str, Any] = {}

PAGE_W, PAGE_H = A4
MARGIN = 1.8 * cm
CONTENT_W = PAGE_W - 2 * MARGIN


def _hex(h: str):
    """Convert a hex colour string to ReportLab Color."""
    h = h.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return colors.Color(r / 255, g / 255, b / 255)


def _mpl_hex(h: str) -> str:
    """Return hex with # for matplotlib."""
    return f"#{h.lstrip('#')}"


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------

def _build_styles(brand: dict) -> dict[str, ParagraphStyle]:
    """Create all paragraph styles used in the report.

    Args:
        brand: Brand colour dict from config.

    Returns:
        Dict of named ParagraphStyle objects.
    """
    primary = _hex(brand["primary"])
    text_col = _hex(brand["text"])
    white = colors.white

    styles = {}

    styles["cover_title"] = ParagraphStyle(
        "cover_title",
        fontName="Helvetica-Bold",
        fontSize=28,
        textColor=white,
        alignment=TA_LEFT,
        leading=34,
        spaceAfter=6,
    )
    styles["cover_subtitle"] = ParagraphStyle(
        "cover_subtitle",
        fontName="Helvetica",
        fontSize=14,
        textColor=colors.Color(0.8, 0.88, 0.95),
        alignment=TA_LEFT,
        spaceAfter=4,
    )
    styles["cover_period"] = ParagraphStyle(
        "cover_period",
        fontName="Helvetica-Bold",
        fontSize=12,
        textColor=colors.Color(0.8, 0.88, 0.95),
        alignment=TA_LEFT,
    )
    styles["section_title"] = ParagraphStyle(
        "section_title",
        fontName="Helvetica-Bold",
        fontSize=16,
        textColor=primary,
        spaceBefore=4,
        spaceAfter=8,
        borderPadding=(0, 0, 4, 0),
    )
    styles["subsection_title"] = ParagraphStyle(
        "subsection_title",
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=primary,
        spaceBefore=8,
        spaceAfter=4,
    )
    styles["body"] = ParagraphStyle(
        "body",
        fontName="Helvetica",
        fontSize=9.5,
        textColor=text_col,
        leading=14,
        spaceAfter=6,
        alignment=TA_JUSTIFY,
    )
    styles["caption"] = ParagraphStyle(
        "caption",
        fontName="Helvetica-Oblique",
        fontSize=8,
        textColor=colors.grey,
        alignment=TA_CENTER,
        spaceAfter=4,
    )
    styles["footer"] = ParagraphStyle(
        "footer",
        fontName="Helvetica",
        fontSize=7.5,
        textColor=colors.grey,
        alignment=TA_CENTER,
    )
    styles["kpi_label"] = ParagraphStyle(
        "kpi_label",
        fontName="Helvetica",
        fontSize=8,
        textColor=colors.grey,
        alignment=TA_CENTER,
        spaceAfter=1,
    )
    styles["kpi_value"] = ParagraphStyle(
        "kpi_value",
        fontName="Helvetica-Bold",
        fontSize=15,
        textColor=primary,
        alignment=TA_CENTER,
    )
    styles["kpi_rag"] = ParagraphStyle(
        "kpi_rag",
        fontName="Helvetica-Bold",
        fontSize=8,
        alignment=TA_CENTER,
    )
    styles["risk_cell"] = ParagraphStyle(
        "risk_cell",
        fontName="Helvetica",
        fontSize=8.5,
        textColor=text_col,
        leading=12,
    )
    styles["table_header"] = ParagraphStyle(
        "table_header",
        fontName="Helvetica-Bold",
        fontSize=8.5,
        textColor=white,
        alignment=TA_CENTER,
    )
    return styles


# ---------------------------------------------------------------------------
# Page templates (header/footer)
# ---------------------------------------------------------------------------

class _HeaderFooterCanvas:
    """Mixin to add running header and footer to every page except the cover."""

    def __init__(self, brand: dict, company_name: str, report_period: str):
        self.brand = brand
        self.company_name = company_name
        self.report_period = report_period

    def draw_header_footer(self, canvas, doc):
        """Draw header bar and footer on non-cover pages."""
        if doc.page == 1:
            return  # Cover has its own full-page design

        canvas.saveState()
        # Header bar
        canvas.setFillColor(_hex(self.brand["primary"]))
        canvas.rect(0, PAGE_H - 1.2 * cm, PAGE_W, 1.2 * cm, fill=1, stroke=0)

        canvas.setFont("Helvetica-Bold", 9)
        canvas.setFillColor(colors.white)
        canvas.drawString(MARGIN, PAGE_H - 0.85 * cm, self.company_name)

        canvas.setFont("Helvetica", 9)
        period_str = f"Board Report — {self.report_period}   |   CONFIDENTIAL"
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.85 * cm, period_str)

        # Footer line
        canvas.setStrokeColor(_hex(self.brand["primary"]))
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, 1.2 * cm, PAGE_W - MARGIN, 1.2 * cm)

        # Page number
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.grey)
        page_label = f"Page {doc.page}"
        canvas.drawRightString(PAGE_W - MARGIN, 0.7 * cm, page_label)
        canvas.drawString(MARGIN, 0.7 * cm, "For Board Use Only — Strictly Confidential")
        canvas.restoreState()


# ---------------------------------------------------------------------------
# Chart generators (matplotlib → BytesIO)
# ---------------------------------------------------------------------------

def _fig_to_image(fig, width: float, height: float) -> Image:
    """Render a matplotlib figure to a ReportLab Image via BytesIO.

    Args:
        fig: Matplotlib Figure object.
        width: Target width in points for the PDF.
        height: Target height in points for the PDF.

    Returns:
        ReportLab Image flowable.
    """
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return Image(buf, width=width, height=height)


def _chart_revenue_vs_budget(pkg: MetricsPackage, brand: dict) -> Image:
    """Bar chart: monthly revenue actuals vs budget (12 months)."""
    fin = pkg.financial
    periods = [p[-5:] for p in fin.monthly_periods]  # MM-DD → last 5 chars

    # Re-build budget from actual ratio for chart purposes
    rev_budget_monthly = [
        pkg.financial.revenue_budget * (a / pkg.financial.revenue_actual)
        if pkg.financial.revenue_actual > 0 else 0
        for a in fin.monthly_revenue
    ]

    x = np.arange(len(periods))
    width = 0.38

    fig, ax = plt.subplots(figsize=(8, 3.5))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    bars1 = ax.bar(x - width / 2, [v / 1e6 for v in fin.monthly_revenue],
                   width, label="Actual", color=_mpl_hex(brand["primary"]), alpha=0.9, zorder=3)
    bars2 = ax.bar(x + width / 2, [v / 1e6 for v in rev_budget_monthly],
                   width, label="Budget", color=_mpl_hex(brand["secondary"]),
                   alpha=0.5, zorder=3)

    ax.plot(x, [v / 1e6 for v in fin.monthly_ebitda],
            color=_mpl_hex(brand["accent"]), marker="o", markersize=4,
            linewidth=1.8, label="EBITDA", zorder=4)

    ax.set_xticks(x)
    ax.set_xticklabels(periods, rotation=45, ha="right", fontsize=7.5)
    ax.set_ylabel("£M", fontsize=8)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"£{v:.1f}M"))
    ax.legend(fontsize=8, loc="upper left", framealpha=0.5)
    ax.set_title("Monthly Revenue vs Budget with EBITDA Trend", fontsize=10,
                 color=_mpl_hex(brand["primary"]), fontweight="bold", pad=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", linestyle="--", alpha=0.4, zorder=0)
    fig.tight_layout()

    return _fig_to_image(fig, CONTENT_W * 0.98, 195)


def _chart_gross_margin_trend(pkg: MetricsPackage, brand: dict) -> Image:
    """Line chart: gross margin % trend (12 months)."""
    fin = pkg.financial
    periods = [p[-5:] for p in fin.monthly_periods]

    fig, ax = plt.subplots(figsize=(8, 2.8))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    ax.fill_between(range(len(periods)), fin.monthly_gross_margin,
                    alpha=0.15, color=_mpl_hex(brand["primary"]))
    ax.plot(range(len(periods)), fin.monthly_gross_margin,
            color=_mpl_hex(brand["primary"]), linewidth=2, marker="o", markersize=4)
    ax.axhline(y=fin.gross_margin_pct_budget * 100,
               color=_mpl_hex(brand["accent"]), linestyle="--",
               linewidth=1.2, label=f"Budget ({fin.gross_margin_pct_budget*100:.1f}%)")
    ax.axhline(y=62, color=_mpl_hex(brand["green"]),
               linestyle=":", linewidth=1.0, alpha=0.6, label="Green threshold (62%)")

    ax.set_xticks(range(len(periods)))
    ax.set_xticklabels(periods, rotation=45, ha="right", fontsize=7.5)
    ax.set_ylabel("Gross Margin %", fontsize=8)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.legend(fontsize=7.5, framealpha=0.5)
    ax.set_title("Gross Margin % Trend", fontsize=10,
                 color=_mpl_hex(brand["primary"]), fontweight="bold", pad=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    fig.tight_layout()

    return _fig_to_image(fig, CONTENT_W * 0.98, 155)


def _chart_pipeline_by_stage(pkg: MetricsPackage, brand: dict) -> Image:
    """Horizontal stacked bar: pipeline by stage."""
    comm = pkg.commercial
    stages = list(comm.pipeline_by_stage.keys())
    values = [comm.pipeline_by_stage[s] / 1e6 for s in stages]

    stage_colours = [
        _mpl_hex(brand["primary"]),
        _mpl_hex(brand["secondary"]),
        _mpl_hex(brand["amber"]),
        _mpl_hex(brand["accent"]),
    ]

    fig, ax = plt.subplots(figsize=(8, 2.6))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    left = 0
    for i, (stage, val) in enumerate(zip(stages, values)):
        ax.barh(0, val, left=left, color=stage_colours[i % len(stage_colours)],
                label=f"{stage} (£{val:.1f}M)", height=0.5, alpha=0.9)
        if val > 0.05:
            ax.text(left + val / 2, 0, f"£{val:.1f}M",
                    ha="center", va="center", fontsize=8, color="white",
                    fontweight="bold")
        left += val

    ax.set_xlim(0, left * 1.05)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"£{v:.1f}M"))
    ax.set_yticks([])
    ax.legend(fontsize=8, loc="upper right", framealpha=0.5)
    ax.set_title("Pipeline by Stage (4-Week Snapshot)", fontsize=10,
                 color=_mpl_hex(brand["primary"]), fontweight="bold", pad=8)
    ax.spines[["top", "right", "left"]].set_visible(False)
    fig.tight_layout()

    return _fig_to_image(fig, CONTENT_W * 0.98, 140)


def _chart_arr_trend(pkg: MetricsPackage, brand: dict) -> Image:
    """Area chart: ARR trend with budget overlay."""
    cust = pkg.customers
    periods = [p[-5:] for p in cust.arr_trend_periods]
    arr_m = [v / 1e6 for v in cust.arr_trend]

    arr_budget_m = pkg.customers.arr_budget / 1e6

    fig, ax = plt.subplots(figsize=(8, 2.8))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    ax.fill_between(range(len(periods)), arr_m, alpha=0.2,
                    color=_mpl_hex(brand["secondary"]))
    ax.plot(range(len(periods)), arr_m, color=_mpl_hex(brand["secondary"]),
            linewidth=2, marker="o", markersize=4, label="ARR (Actual)")
    ax.axhline(y=arr_budget_m, color=_mpl_hex(brand["accent"]),
               linestyle="--", linewidth=1.2, label=f"Budget (£{arr_budget_m:.1f}M)")

    ax.set_xticks(range(len(periods)))
    ax.set_xticklabels(periods, rotation=45, ha="right", fontsize=7.5)
    ax.set_ylabel("ARR (£M)", fontsize=8)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"£{v:.1f}M"))
    ax.legend(fontsize=8, framealpha=0.5)
    ax.set_title("Annual Recurring Revenue (ARR) Trend", fontsize=10,
                 color=_mpl_hex(brand["primary"]), fontweight="bold", pad=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    fig.tight_layout()

    return _fig_to_image(fig, CONTENT_W * 0.98, 155)


def _chart_headcount(pkg: MetricsPackage, brand: dict) -> Image:
    """Grouped bar chart: headcount by department (actual vs budget)."""
    hc = pkg.headcount
    depts = list(hc.by_department.keys())
    actuals = [hc.by_department[d]["actual"] for d in depts]
    budgets = [hc.by_department[d]["budget"] for d in depts]

    x = np.arange(len(depts))
    width = 0.38

    fig, ax = plt.subplots(figsize=(8, 3.2))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    ax.bar(x - width / 2, actuals, width, label="Actual",
           color=_mpl_hex(brand["primary"]), alpha=0.9, zorder=3)
    ax.bar(x + width / 2, budgets, width, label="Budget",
           color=_mpl_hex(brand["secondary"]), alpha=0.5, zorder=3)

    for i, (a, b) in enumerate(zip(actuals, budgets)):
        ax.text(i - width / 2, a + 0.3, str(a), ha="center", fontsize=7.5,
                color=_mpl_hex(brand["primary"]), fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(
        [d.replace(" ", "\n") for d in depts], fontsize=8
    )
    ax.set_ylabel("FTEs", fontsize=8)
    ax.legend(fontsize=8, framealpha=0.5)
    ax.set_title("Headcount by Department — Actual vs Budget", fontsize=10,
                 color=_mpl_hex(brand["primary"]), fontweight="bold", pad=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", linestyle="--", alpha=0.3, zorder=0)
    fig.tight_layout()

    return _fig_to_image(fig, CONTENT_W * 0.98, 175)


# ---------------------------------------------------------------------------
# RAG KPI table
# ---------------------------------------------------------------------------

def _rag_colour(status: str, brand: dict):
    """Map RAG status to ReportLab colour."""
    m = {"Green": brand["green"], "Amber": brand["amber"], "Red": brand["red"]}
    return _hex(m.get(status, brand["text"]))


def _build_rag_table(pkg: MetricsPackage, styles: dict, brand: dict) -> Table:
    """Build the executive RAG dashboard as a ReportLab Table.

    Args:
        pkg: MetricsPackage.
        styles: Paragraph style dict.
        brand: Brand colour dict.

    Returns:
        Styled ReportLab Table.
    """
    fin = pkg.financial
    comm = pkg.commercial
    cust = pkg.customers
    hc = pkg.headcount
    rag = pkg.rag

    kpis = [
        ("Revenue", f"£{fin.revenue_actual/1e6:.1f}M",
         f"{rag.revenue.variance_pct*100:+.1f}% vs budget", rag.revenue.status),
        ("Gross Margin", f"{fin.gross_margin_pct_actual*100:.1f}%",
         f"Budget: {fin.gross_margin_pct_budget*100:.1f}%", rag.gross_margin.status),
        ("EBITDA Margin", f"{fin.ebitda_margin_pct_actual*100:.1f}%",
         f"Budget: {fin.ebitda_margin_pct_budget*100:.1f}%", rag.ebitda_margin.status),
        ("ARR", f"£{cust.arr_actual/1e6:.1f}M",
         f"Net movement: £{cust.net_arr_movement/1000:+.0f}k", rag.churn_rate.status),
        ("Pipeline Coverage", f"{comm.pipeline_coverage_ratio:.1f}x",
         "Target: 3.0x", rag.pipeline_coverage.status),
        ("Win Rate", f"{comm.win_rate_actual*100:.1f}%",
         f"Budget: {comm.win_rate_budget*100:.1f}%", rag.win_rate.status),
        ("Churn Rate", f"{cust.churn_rate_actual*100:.2f}%",
         f"Budget: {cust.churn_rate_budget*100:.2f}%", rag.churn_rate.status),
        ("NPS", str(cust.nps_actual),
         f"Target: {cust.nps_budget}", rag.nps.status),
    ]

    # Build 4 columns × 2 rows of KPI tiles
    n_cols = 4
    rows = []
    for row_start in range(0, len(kpis), n_cols):
        chunk = kpis[row_start:row_start + n_cols]
        # Pad if needed
        while len(chunk) < n_cols:
            chunk.append(("", "", "", "Green"))

        label_row = []
        value_row = []
        rag_row = []
        for label, value, sub, status in chunk:
            label_row.append(Paragraph(label, styles["kpi_label"]))
            value_row.append(Paragraph(value, styles["kpi_value"]))
            rag_colour = _rag_colour(status, brand)
            rag_row.append(Paragraph(
                f'<font color="#{brand[status.lower() if status.lower() in brand else "text"]}">'
                f'{status}</font>' if status else "",
                styles["kpi_rag"]
            ))

        rows.append(label_row)
        rows.append(value_row)
        rows.append(rag_row)

    col_w = CONTENT_W / n_cols

    table = Table(rows, colWidths=[col_w] * n_cols)
    ts = TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _hex(brand["light"])),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.white),
        ("ROWBACKGROUND", (0, 0), (-1, 0), _hex(brand["light"])),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ])

    # Colour the RAG rows
    for row_idx in [2, 5]:  # rag_row positions (0-indexed: 2 and 5)
        if row_idx < len(rows):
            for col_idx, (_, _, _, status) in enumerate(kpis[
                (row_idx // 3) * n_cols:((row_idx // 3) + 1) * n_cols
            ]):
                c = _rag_colour(status, brand)
                ts.add("TEXTCOLOR", (col_idx, row_idx), (col_idx, row_idx), c)

    table.setStyle(ts)
    return table


# ---------------------------------------------------------------------------
# Risk register table
# ---------------------------------------------------------------------------

def _build_risk_table(risk_register: list[dict], styles: dict, brand: dict) -> Table:
    """Build the risk register as a formatted ReportLab table.

    Args:
        risk_register: List of risk dicts from narrative templates.
        styles: Paragraph style dict.
        brand: Brand colour dict.

    Returns:
        Styled ReportLab Table.
    """
    rating_colours = {
        "High":   brand["red"],
        "Medium": brand["amber"],
        "Low":    brand["green"],
    }

    header = [
        Paragraph("Risk", styles["table_header"]),
        Paragraph("Detail", styles["table_header"]),
        Paragraph("Mitigation", styles["table_header"]),
        Paragraph("Rating", styles["table_header"]),
    ]
    data = [header]

    for risk in risk_register:
        rating = risk.get("rating", "Low")
        r_colour = _hex(rating_colours.get(rating, brand["text"]))
        data.append([
            Paragraph(risk.get("risk", ""), styles["risk_cell"]),
            Paragraph(risk.get("detail", ""), styles["risk_cell"]),
            Paragraph(risk.get("mitigation", ""), styles["risk_cell"]),
            Paragraph(f'<b><font color="#{rating_colours.get(rating, brand["text"])}">{rating}</font></b>',
                      styles["risk_cell"]),
        ])

    col_widths = [
        CONTENT_W * 0.20,
        CONTENT_W * 0.32,
        CONTENT_W * 0.38,
        CONTENT_W * 0.10,
    ]

    table = Table(data, colWidths=col_widths, repeatRows=1)
    ts = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _hex(brand["primary"])),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("ROWBACKGROUND", (0, 1), (-1, -1), colors.white),
        ("ROWBACKGROUND", (0, 2), (-1, 2), _hex(brand["light"])),
        ("ROWBACKGROUND", (0, 4), (-1, 4), _hex(brand["light"])),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ])
    table.setStyle(ts)
    return table


# ---------------------------------------------------------------------------
# Page content builders
# ---------------------------------------------------------------------------

def _page_cover(
    pkg: MetricsPackage,
    styles: dict,
    brand: dict,
) -> list:
    """Build the cover page content list."""
    story = []

    # Full-page navy background — achieved via a coloured Table cell
    cover_content = [
        Spacer(1, 5 * cm),
        Paragraph(pkg.company_name, styles["cover_title"]),
        Paragraph("Board Performance Report", styles["cover_subtitle"]),
        Spacer(1, 0.5 * cm),
        HRFlowable(width=CONTENT_W, thickness=1.5, color=_hex("2196A6"), spaceAfter=10),
        Paragraph(f"Reporting Period: {pkg.report_period}", styles["cover_period"]),
        Paragraph(
            f"Generated: {datetime.today().strftime('%A, %d %B %Y at %H:%M')}",
            styles["cover_period"],
        ),
        Spacer(1, 2 * cm),
        Paragraph(
            "This document is prepared for the exclusive use of the Board of Directors "
            "and is strictly confidential. It must not be copied, distributed, or shared "
            "without the prior written consent of the Chief Financial Officer.",
            ParagraphStyle(
                "cover_legal",
                fontName="Helvetica-Oblique",
                fontSize=8,
                textColor=colors.Color(0.6, 0.7, 0.8),
                leading=12,
                alignment=TA_LEFT,
            ),
        ),
    ]

    # Wrap everything in a navy table cell to achieve full-page background
    cover_table = Table(
        [[cover_content]],
        colWidths=[PAGE_W],
        rowHeights=[PAGE_H],
    )
    cover_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), _hex(brand["primary"])),
        ("LEFTPADDING", (0, 0), (0, 0), MARGIN + 0.5 * cm),
        ("TOPPADDING", (0, 0), (0, 0), 0),
        ("VALIGN", (0, 0), (0, 0), "TOP"),
    ]))
    story.append(cover_table)
    story.append(PageBreak())
    return story


def _page_exec_summary(
    pkg: MetricsPackage,
    narrative: NarrativePackage,
    styles: dict,
    brand: dict,
) -> list:
    """Build the executive summary page."""
    story = []
    story.append(Paragraph("Executive Summary", styles["section_title"]))
    story.append(HRFlowable(width=CONTENT_W, thickness=1, color=_hex(brand["primary"]), spaceAfter=10))
    story.append(_build_rag_table(pkg, styles, brand))
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph("Summary Commentary", styles["subsection_title"]))
    for para in narrative.executive_summary.split("\n\n"):
        story.append(Paragraph(para.strip(), styles["body"]))
    story.append(PageBreak())
    return story


def _page_financial(
    pkg: MetricsPackage,
    narrative: NarrativePackage,
    styles: dict,
    brand: dict,
) -> list:
    """Build the financial performance page."""
    story = []
    story.append(Paragraph("Financial Performance", styles["section_title"]))
    story.append(HRFlowable(width=CONTENT_W, thickness=1, color=_hex(brand["primary"]), spaceAfter=8))
    story.append(_chart_revenue_vs_budget(pkg, brand))
    story.append(Paragraph("Fig 1: Monthly revenue vs budget with EBITDA overlay (12 months)", styles["caption"]))
    story.append(_chart_gross_margin_trend(pkg, brand))
    story.append(Paragraph("Fig 2: Gross margin % trend vs budget and Green threshold", styles["caption"]))
    story.append(Paragraph("Financial Commentary", styles["subsection_title"]))
    for para in narrative.financial_performance.split("\n\n"):
        story.append(Paragraph(para.strip(), styles["body"]))
    story.append(PageBreak())
    return story


def _page_commercial(
    pkg: MetricsPackage,
    narrative: NarrativePackage,
    styles: dict,
    brand: dict,
) -> list:
    """Build the commercial performance page."""
    story = []
    story.append(Paragraph("Commercial Performance", styles["section_title"]))
    story.append(HRFlowable(width=CONTENT_W, thickness=1, color=_hex(brand["primary"]), spaceAfter=8))
    story.append(_chart_pipeline_by_stage(pkg, brand))
    story.append(Paragraph("Fig 3: Sales pipeline by stage — 4-week snapshot (£M)", styles["caption"]))
    story.append(Paragraph("Commercial Commentary", styles["subsection_title"]))
    for para in narrative.commercial_performance.split("\n\n"):
        story.append(Paragraph(para.strip(), styles["body"]))
    story.append(Spacer(1, 0.3 * cm))

    # Win rate and coverage summary table
    comm = pkg.commercial
    summary_data = [
        [Paragraph("Metric", styles["table_header"]),
         Paragraph("Actual", styles["table_header"]),
         Paragraph("Budget", styles["table_header"]),
         Paragraph("Status", styles["table_header"])],
        ["Pipeline Coverage", f"{comm.pipeline_coverage_ratio:.1f}x", "3.0x",
         pkg.rag.pipeline_coverage.status],
        ["Win Rate", f"{comm.win_rate_actual*100:.1f}%",
         f"{comm.win_rate_budget*100:.1f}%", pkg.rag.win_rate.status],
        ["Avg Deal Size", f"£{comm.avg_deal_size_gbp/1000:.0f}k", "—", "—"],
    ]
    col_w = CONTENT_W / 4
    summary_table = Table(summary_data, colWidths=[col_w] * 4)
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _hex(brand["primary"])),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("ROWBACKGROUND", (0, 2), (-1, 2), _hex(brand["light"])),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(summary_table)
    story.append(PageBreak())
    return story


def _page_customers(
    pkg: MetricsPackage,
    narrative: NarrativePackage,
    styles: dict,
    brand: dict,
) -> list:
    """Build the customer metrics page."""
    story = []
    story.append(Paragraph("Customer & Retention Metrics", styles["section_title"]))
    story.append(HRFlowable(width=CONTENT_W, thickness=1, color=_hex(brand["primary"]), spaceAfter=8))
    story.append(_chart_arr_trend(pkg, brand))
    story.append(Paragraph("Fig 4: ARR trend vs budget (12 months, £M)", styles["caption"]))
    story.append(Paragraph("Customer Commentary", styles["subsection_title"]))
    for para in narrative.customer_metrics.split("\n\n"):
        story.append(Paragraph(para.strip(), styles["body"]))
    story.append(PageBreak())
    return story


def _page_operational(
    pkg: MetricsPackage,
    narrative: NarrativePackage,
    styles: dict,
    brand: dict,
) -> list:
    """Build the operational / headcount page."""
    story = []
    story.append(Paragraph("Operational Metrics", styles["section_title"]))
    story.append(HRFlowable(width=CONTENT_W, thickness=1, color=_hex(brand["primary"]), spaceAfter=8))
    story.append(_chart_headcount(pkg, brand))
    story.append(Paragraph("Fig 5: Headcount by department — actual vs budget (FTEs)", styles["caption"]))
    story.append(Paragraph("Headcount Commentary", styles["subsection_title"]))
    for para in narrative.operational_metrics.split("\n\n"):
        story.append(Paragraph(para.strip(), styles["body"]))
    story.append(PageBreak())
    return story


def _page_outlook(
    narrative: NarrativePackage,
    styles: dict,
    brand: dict,
) -> list:
    """Build the outlook and risk register page."""
    story = []
    story.append(Paragraph("Outlook & Risk Register", styles["section_title"]))
    story.append(HRFlowable(width=CONTENT_W, thickness=1, color=_hex(brand["primary"]), spaceAfter=8))
    story.append(Paragraph("Management Outlook", styles["subsection_title"]))
    for para in narrative.outlook_and_risks.split("\n\n"):
        story.append(Paragraph(para.strip(), styles["body"]))
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph("Risk Register", styles["subsection_title"]))
    story.append(_build_risk_table(narrative.risk_register, styles, brand))
    return story


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_pdf(
    pkg: MetricsPackage,
    narrative: NarrativePackage,
    config_path: str = "config.yaml",
) -> Path:
    """Assemble and write the board report PDF.

    Args:
        pkg: Computed metrics package.
        narrative: Generated narrative package.
        config_path: Path to configuration YAML.

    Returns:
        Path to the generated PDF file.
    """
    with open(config_path, "r") as fh:
        cfg = yaml.safe_load(fh)

    global _BRAND
    _BRAND = cfg["report"]["brand"]
    brand = _BRAND

    output_dir = Path(cfg["paths"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = cfg["paths"]["pdf_filename"].format(period=pkg.report_period)
    output_path = output_dir / filename

    styles = _build_styles(brand)
    hf = _HeaderFooterCanvas(brand, pkg.company_name, pkg.report_period)

    def on_page(canvas, doc):
        hf.draw_header_footer(canvas, doc)

    doc = BaseDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=1.6 * cm,
        bottomMargin=1.8 * cm,
    )

    # Cover page: full bleed (no margins)
    cover_frame = Frame(0, 0, PAGE_W, PAGE_H, leftPadding=0, rightPadding=0,
                        topPadding=0, bottomPadding=0)
    content_frame = Frame(MARGIN, 1.8 * cm, CONTENT_W, PAGE_H - 3.4 * cm)

    doc.addPageTemplates([
        PageTemplate(id="Cover", frames=[cover_frame]),
        PageTemplate(id="Content", frames=[content_frame], onPage=on_page),
    ])

    story = []
    story.append(NextPageTemplate("Cover"))
    story += _page_cover(pkg, styles, brand)
    story.append(NextPageTemplate("Content"))
    story += _page_exec_summary(pkg, narrative, styles, brand)
    story += _page_financial(pkg, narrative, styles, brand)
    story += _page_commercial(pkg, narrative, styles, brand)
    story += _page_customers(pkg, narrative, styles, brand)
    story += _page_operational(pkg, narrative, styles, brand)
    story += _page_outlook(narrative, styles, brand)

    doc.build(story)
    logger.info("PDF report saved to %s (%d pages)", output_path, 7)
    return output_path
