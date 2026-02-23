"""
dashboard.py — Interactive Plotly HTML Dashboard.

Generates a self-contained, responsive HTML dashboard that mirrors the
PDF report in interactive form. Designed to be shared via internal portals
or opened directly in a browser — no server required.

Sections:
    Header KPI bar     — RAG-coded headline metrics
    Row 1:             — Revenue vs Budget (bar) | EBITDA Margin trend (line)
    Row 2:             — Pipeline by Stage (waterfall) | ARR Trend (area)
    Row 3:             — Headcount by Department (grouped bar) | Churn + NPS (dual)

All charts use the brand colour palette from config.yaml.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yaml

from src.metrics import MetricsPackage

logger = logging.getLogger(__name__)

TEMPLATE = "plotly_white"


def _mpl(h: str) -> str:
    """Ensure hex colour has # prefix."""
    return f"#{h.lstrip('#')}"


def _chart_revenue_budget(pkg: MetricsPackage, brand: dict) -> go.Figure:
    """Grouped bar: monthly revenue actuals vs budget with EBITDA line."""
    fin = pkg.financial
    periods = [p[-5:] for p in fin.monthly_periods]

    rev_budget = [
        fin.revenue_budget * (a / fin.revenue_actual) if fin.revenue_actual else 0
        for a in fin.monthly_revenue
    ]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=periods, y=[v / 1e6 for v in fin.monthly_revenue],
        name="Revenue (Actual)", marker_color=_mpl(brand["primary"]),
        opacity=0.9,
        hovertemplate="Period: %{x}<br>Revenue: £%{y:.2f}M<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=periods, y=[v / 1e6 for v in rev_budget],
        name="Revenue (Budget)", marker_color=_mpl(brand["secondary"]),
        opacity=0.5,
        hovertemplate="Period: %{x}<br>Budget: £%{y:.2f}M<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=periods, y=[v / 1e6 for v in fin.monthly_ebitda],
        name="EBITDA", mode="lines+markers",
        line=dict(color=_mpl(brand["accent"]), width=2),
        marker=dict(size=5),
        hovertemplate="Period: %{x}<br>EBITDA: £%{y:.2f}M<extra></extra>",
        yaxis="y2",
    ))
    fig.update_layout(
        title=dict(text="Revenue vs Budget — Monthly (£M)", font=dict(size=14, color=_mpl(brand["primary"]))),
        barmode="group",
        template=TEMPLATE,
        yaxis=dict(title="£M", tickformat="£.1f"),
        yaxis2=dict(title="EBITDA (£M)", overlaying="y", side="right",
                    tickformat="£.2f", showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        height=360,
        margin=dict(l=50, r=50, t=80, b=40),
    )
    return fig


def _chart_ebitda_margin(pkg: MetricsPackage, brand: dict) -> go.Figure:
    """Line chart: EBITDA margin % and gross margin % trends."""
    fin = pkg.financial
    periods = [p[-5:] for p in fin.monthly_periods]

    ebitda_margins = []
    for rev, ebitda in zip(fin.monthly_revenue, fin.monthly_ebitda):
        ebitda_margins.append(round(ebitda / rev * 100 if rev else 0, 2))

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=periods, y=fin.monthly_gross_margin,
        name="Gross Margin %", mode="lines+markers",
        line=dict(color=_mpl(brand["secondary"]), width=2),
        fill="tozeroy", fillcolor=f"rgba({int(brand['secondary'][0:2], 16)},{int(brand['secondary'][2:4], 16)},{int(brand['secondary'][4:6], 16)},0.08)",
        hovertemplate="Period: %{x}<br>Gross Margin: %{y:.1f}%<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=periods, y=ebitda_margins,
        name="EBITDA Margin %", mode="lines+markers",
        line=dict(color=_mpl(brand["accent"]), width=2, dash="dot"),
        hovertemplate="Period: %{x}<br>EBITDA Margin: %{y:.1f}%<extra></extra>",
    ))
    fig.add_hline(y=62, line_dash="dash", line_color=_mpl(brand["green"]),
                  annotation_text="Gross Margin Green (62%)", annotation_position="top right",
                  line_width=1)
    fig.add_hline(y=14, line_dash="dash", line_color=_mpl(brand["amber"]),
                  annotation_text="EBITDA Green (14%)", annotation_position="bottom right",
                  line_width=1)
    fig.update_layout(
        title=dict(text="Margin Trends (%)", font=dict(size=14, color=_mpl(brand["primary"]))),
        yaxis=dict(title="%", ticksuffix="%"),
        template=TEMPLATE,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        height=360,
        margin=dict(l=50, r=30, t=80, b=40),
    )
    return fig


def _chart_pipeline_waterfall(pkg: MetricsPackage, brand: dict) -> go.Figure:
    """Waterfall chart: pipeline by stage."""
    comm = pkg.commercial
    stages = list(comm.pipeline_by_stage.keys())
    values = [comm.pipeline_by_stage[s] / 1e6 for s in stages]
    total = sum(values)

    stage_colours = [
        _mpl(brand["primary"]),
        _mpl(brand["secondary"]),
        _mpl(brand["amber"]),
        _mpl(brand["accent"]),
    ]

    fig = go.Figure(go.Waterfall(
        name="Pipeline",
        orientation="v",
        measure=["relative"] * len(stages) + ["total"],
        x=stages + ["Total"],
        y=values + [None],
        text=[f"£{v:.1f}M" for v in values] + [f"£{total:.1f}M"],
        textposition="outside",
        connector=dict(line=dict(color="rgb(63,63,63)")),
        increasing=dict(marker=dict(color=_mpl(brand["primary"]))),
        totals=dict(marker=dict(color=_mpl(brand["secondary"]))),
        hovertemplate="Stage: %{x}<br>Value: £%{y:.2f}M<extra></extra>",
    ))
    fig.add_hline(
        y=total, line_dash="dot", line_color=_mpl(brand["green"]),
        annotation_text=f"Total: £{total:.1f}M | Coverage: {pkg.commercial.pipeline_coverage_ratio:.1f}x",
    )
    fig.update_layout(
        title=dict(text="Sales Pipeline by Stage (£M)", font=dict(size=14, color=_mpl(brand["primary"]))),
        yaxis=dict(title="£M"),
        template=TEMPLATE,
        showlegend=False,
        height=360,
        margin=dict(l=50, r=30, t=80, b=40),
    )
    return fig


def _chart_arr_trend(pkg: MetricsPackage, brand: dict) -> go.Figure:
    """Area chart: ARR trend vs budget with new/churned ARR bars."""
    cust = pkg.customers
    periods = [p[-5:] for p in cust.arr_trend_periods]

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(
        x=periods, y=[v / 1e6 for v in cust.arr_trend],
        name="ARR (Actual)", mode="lines", fill="tozeroy",
        line=dict(color=_mpl(brand["secondary"]), width=2.5),
        fillcolor=f"rgba({int(brand['secondary'][0:2],16)},{int(brand['secondary'][2:4],16)},{int(brand['secondary'][4:6],16)},0.15)",
        hovertemplate="Period: %{x}<br>ARR: £%{y:.2f}M<extra></extra>",
    ), secondary_y=False)
    fig.add_hline(
        y=cust.arr_budget / 1e6, line_dash="dash",
        line_color=_mpl(brand["accent"]),
        annotation_text=f"Budget: £{cust.arr_budget/1e6:.1f}M",
    )
    fig.update_layout(
        title=dict(text="ARR Trend vs Budget (£M)", font=dict(size=14, color=_mpl(brand["primary"]))),
        template=TEMPLATE,
        height=360,
        margin=dict(l=50, r=50, t=80, b=40),
        legend=dict(orientation="h", y=1.08),
    )
    fig.update_yaxes(title_text="ARR (£M)", tickprefix="£", ticksuffix="M", secondary_y=False)
    return fig


def _chart_headcount(pkg: MetricsPackage, brand: dict) -> go.Figure:
    """Grouped bar: headcount actual vs budget by department."""
    hc = pkg.headcount
    depts = list(hc.by_department.keys())
    actuals = [hc.by_department[d]["actual"] for d in depts]
    budgets = [hc.by_department[d]["budget"] for d in depts]
    variances = [hc.by_department[d]["variance"] for d in depts]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=depts, y=actuals, name="Actual", marker_color=_mpl(brand["primary"]),
        text=actuals, textposition="outside",
        hovertemplate="Dept: %{x}<br>Actual HC: %{y}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=depts, y=budgets, name="Budget", marker_color=_mpl(brand["secondary"]),
        opacity=0.6,
        hovertemplate="Dept: %{x}<br>Budget HC: %{y}<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="Headcount by Department — Actual vs Budget", font=dict(size=14, color=_mpl(brand["primary"]))),
        barmode="group",
        yaxis=dict(title="FTEs"),
        template=TEMPLATE,
        legend=dict(orientation="h", y=1.08),
        height=360,
        margin=dict(l=50, r=30, t=80, b=80),
    )
    return fig


def _chart_churn_nps(pkg: MetricsPackage, brand: dict) -> go.Figure:
    """Dual-axis: churn rate trend + NPS scatter."""
    cust = pkg.customers

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(
        x=[cust.period], y=[cust.churn_rate_actual * 100],
        name="Churn Rate %", mode="markers+lines",
        line=dict(color=_mpl(brand["accent"]), width=2),
        marker=dict(size=10),
        hovertemplate="Churn: %{y:.2f}%<extra></extra>",
    ), secondary_y=False)
    fig.add_hline(
        y=cust.churn_rate_budget * 100,
        line_dash="dash", line_color=_mpl(brand["amber"]),
        annotation_text=f"Budget churn: {cust.churn_rate_budget*100:.2f}%",
        secondary_y=False,
    )
    fig.add_trace(go.Scatter(
        x=[cust.period], y=[cust.nps_actual],
        name="NPS", mode="markers",
        marker=dict(size=18, color=_mpl(brand["primary"]), symbol="star"),
        hovertemplate="NPS: %{y}<extra></extra>",
    ), secondary_y=True)
    fig.add_hline(
        y=cust.nps_budget, line_dash="dot",
        line_color=_mpl(brand["green"]),
        annotation_text=f"NPS Target: {cust.nps_budget}",
        secondary_y=True,
    )
    fig.update_layout(
        title=dict(text="Churn Rate & NPS — Current Period", font=dict(size=14, color=_mpl(brand["primary"]))),
        template=TEMPLATE,
        height=360,
        margin=dict(l=50, r=60, t=80, b=40),
        legend=dict(orientation="h", y=1.08),
    )
    fig.update_yaxes(title_text="Churn Rate (%)", secondary_y=False, ticksuffix="%")
    fig.update_yaxes(title_text="NPS Score", secondary_y=True)
    return fig


def _build_kpi_header(pkg: MetricsPackage, brand: dict) -> str:
    """Generate the HTML KPI banner."""
    fin = pkg.financial
    comm = pkg.commercial
    cust = pkg.customers
    rag = pkg.rag

    rag_bg = {"Green": brand["green"], "Amber": brand["amber"], "Red": brand["red"]}

    tiles = [
        ("Revenue",        f"£{fin.revenue_actual/1e6:.1f}M", rag.revenue.status),
        ("Gross Margin",   f"{fin.gross_margin_pct_actual*100:.1f}%", rag.gross_margin.status),
        ("EBITDA Margin",  f"{fin.ebitda_margin_pct_actual*100:.1f}%", rag.ebitda_margin.status),
        ("ARR",            f"£{cust.arr_actual/1e6:.1f}M", "Green"),
        ("Pipeline Cover", f"{comm.pipeline_coverage_ratio:.1f}x", rag.pipeline_coverage.status),
        ("Win Rate",       f"{comm.win_rate_actual*100:.1f}%", rag.win_rate.status),
        ("Churn",          f"{cust.churn_rate_actual*100:.2f}%", rag.churn_rate.status),
        ("NPS",            str(cust.nps_actual), rag.nps.status),
    ]

    tile_html = ""
    for label, value, status in tiles:
        bg = f"#{rag_bg.get(status, brand['primary'])}"
        tile_html += f"""
        <div style="background:{bg};color:#fff;border-radius:8px;padding:10px 16px;
                    min-width:110px;text-align:center;box-shadow:2px 2px 6px rgba(0,0,0,.2);">
            <div style="font-size:10px;font-weight:600;letter-spacing:.8px;opacity:.85;">{label.upper()}</div>
            <div style="font-size:22px;font-weight:700;margin-top:2px;">{value}</div>
            <div style="font-size:9px;opacity:.8;margin-top:1px;">{status}</div>
        </div>"""

    return f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;background:#{brand['primary']};padding:20px 28px;">
        <h1 style="color:#fff;margin:0 0 3px;font-size:20px;">{pkg.company_name}</h1>
        <p style="color:rgba(255,255,255,.7);margin:0 0 14px;font-size:12px;">
            Board Performance Report — {pkg.report_period} &nbsp;|&nbsp;
            Generated: {datetime.today().strftime('%Y-%m-%d %H:%M')}
        </p>
        <div style="display:flex;gap:10px;flex-wrap:wrap;">{tile_html}</div>
    </div>"""


def generate_dashboard(
    pkg: MetricsPackage,
    config_path: str = "config.yaml",
) -> Path:
    """Assemble the interactive HTML dashboard and write to disk.

    Args:
        pkg: Computed MetricsPackage.
        config_path: Path to configuration YAML.

    Returns:
        Path to the generated .html file.
    """
    with open(config_path, "r") as fh:
        cfg = yaml.safe_load(fh)

    brand = cfg["report"]["brand"]
    output_dir = Path(cfg["paths"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = cfg["paths"]["dashboard_filename"].format(period=pkg.report_period)
    output_path = output_dir / filename

    logger.info("Building dashboard for period %s", pkg.report_period)

    charts = {
        "rev_budget":   _chart_revenue_budget(pkg, brand),
        "ebitda_margin": _chart_ebitda_margin(pkg, brand),
        "pipeline":     _chart_pipeline_waterfall(pkg, brand),
        "arr":          _chart_arr_trend(pkg, brand),
        "headcount":    _chart_headcount(pkg, brand),
        "churn_nps":    _chart_churn_nps(pkg, brand),
    }

    chart_args = {"include_plotlyjs": False, "full_html": False}
    divs = {k: v.to_html(**chart_args) for k, v in charts.items()}

    kpi_header = _build_kpi_header(pkg, brand)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>Board Report — {pkg.report_period}</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        *{{box-sizing:border-box;margin:0;padding:0;}}
        body{{font-family:'Segoe UI',Arial,sans-serif;background:#F4F7FA;}}
        .grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px;padding:18px;}}
        .card{{background:#fff;border-radius:8px;padding:6px;
               box-shadow:0 2px 8px rgba(0,0,0,.07);}}
        .full{{grid-column:1/-1;}}
        .footer{{text-align:center;padding:14px;color:#888;font-size:11px;}}
        @media(max-width:880px){{.grid{{grid-template-columns:1fr;}}.full{{grid-column:1;}}}}
    </style>
</head>
<body>
    {kpi_header}
    <div class="grid">
        <div class="card">{divs['rev_budget']}</div>
        <div class="card">{divs['ebitda_margin']}</div>
        <div class="card">{divs['pipeline']}</div>
        <div class="card">{divs['arr']}</div>
        <div class="card">{divs['headcount']}</div>
        <div class="card">{divs['churn_nps']}</div>
    </div>
    <div class="footer">
        Automated Board Report Generator v1.0 &nbsp;|&nbsp; {pkg.company_name} &nbsp;|&nbsp;
        {datetime.today().strftime('%Y-%m-%d %H:%M')} &nbsp;|&nbsp; STRICTLY CONFIDENTIAL
    </div>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
    logger.info("Dashboard saved to %s", output_path)
    return output_path
