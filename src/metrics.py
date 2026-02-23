"""
metrics.py — KPI Calculation Engine.

Reads the four raw datasets and computes all KPIs for the most recent
reporting period (current month) plus prior-period comparators.

Returns a structured `MetricsPackage` dataclass used by every downstream
module (narrative, PDF, Excel, dashboard) as the single source of truth.

KPIs computed:
    Financial:   Revenue, Gross Profit, Gross Margin %, EBITDA, EBITDA Margin %
    Variance:    vs Budget (£ and %), vs Prior Year (£ and %)
    Commercial:  Pipeline value, coverage ratio, win rate, avg deal size
    Customer:    ARR, net ARR movement, churn rate, NPS
    Headcount:   Total HC, vs budget, cost per head, run-rate salary cost
    RAG:         Red/Amber/Green status for each headline KPI
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RagStatus:
    """RAG (Red/Amber/Green) status with a value for a single KPI."""
    status: str       # 'Green', 'Amber', 'Red'
    value: float
    budget: float
    variance_abs: float
    variance_pct: float


@dataclass
class FinancialMetrics:
    """Monthly financial P&L KPIs."""
    period: str
    revenue_actual: float
    revenue_budget: float
    revenue_prior_year: float
    gross_profit_actual: float
    gross_profit_budget: float
    gross_margin_pct_actual: float
    gross_margin_pct_budget: float
    opex_actual: float
    opex_budget: float
    ebitda_actual: float
    ebitda_budget: float
    ebitda_margin_pct_actual: float
    ebitda_margin_pct_budget: float
    # YTD
    ytd_revenue_actual: float
    ytd_revenue_budget: float
    ytd_ebitda_actual: float
    ytd_ebitda_budget: float
    # Trend (last 12 months for charts)
    monthly_revenue: list = field(default_factory=list)
    monthly_ebitda: list = field(default_factory=list)
    monthly_gross_margin: list = field(default_factory=list)
    monthly_periods: list = field(default_factory=list)


@dataclass
class CommercialMetrics:
    """Sales pipeline and win-rate KPIs."""
    period: str
    total_pipeline_gbp: float
    pipeline_budget_gbp: float
    pipeline_coverage_ratio: float
    win_rate_actual: float
    win_rate_budget: float
    avg_deal_size_gbp: float
    new_pipeline_4w_gbp: float
    pipeline_by_stage: dict = field(default_factory=dict)
    pipeline_trend: list = field(default_factory=list)
    pipeline_trend_periods: list = field(default_factory=list)


@dataclass
class CustomerMetrics:
    """ARR, churn, NPS KPIs."""
    period: str
    arr_actual: float
    arr_budget: float
    arr_prior_year: float
    new_arr_gbp: float
    churned_arr_gbp: float
    net_arr_movement: float
    churn_rate_actual: float
    churn_rate_budget: float
    nps_actual: int
    nps_budget: int
    new_customers: int
    churned_customers: int
    arr_trend: list = field(default_factory=list)
    arr_trend_periods: list = field(default_factory=list)


@dataclass
class HeadcountMetrics:
    """Headcount and people-cost KPIs."""
    period: str
    total_hc_actual: int
    total_hc_budget: int
    total_hc_prior_year: int
    total_cost_actual: float
    total_cost_budget: float
    cost_per_head_actual: float
    cost_per_head_budget: float
    by_department: dict = field(default_factory=dict)
    hc_trend: list = field(default_factory=list)
    hc_trend_periods: list = field(default_factory=list)


@dataclass
class RagDashboard:
    """RAG status for all headline KPIs."""
    revenue: RagStatus
    gross_margin: RagStatus
    ebitda_margin: RagStatus
    pipeline_coverage: RagStatus
    win_rate: RagStatus
    churn_rate: RagStatus
    nps: RagStatus
    headcount: RagStatus


@dataclass
class MetricsPackage:
    """Complete metrics pack for one reporting period."""
    report_period: str
    company_name: str
    financial: FinancialMetrics
    commercial: CommercialMetrics
    customers: CustomerMetrics
    headcount: HeadcountMetrics
    rag: RagDashboard


# ---------------------------------------------------------------------------
# RAG helpers
# ---------------------------------------------------------------------------

def _rag_higher_is_better(
    value: float,
    budget: float,
    green_threshold: float,
    amber_threshold: float,
) -> RagStatus:
    """Assign RAG where higher value relative to budget is better.

    Args:
        value: Actual value.
        budget: Budget / target value.
        green_threshold: Variance ratio above which result is Green (e.g. -0.02 = within 2% miss).
        amber_threshold: Variance ratio below which result is Red.

    Returns:
        RagStatus instance.
    """
    variance_abs = value - budget
    variance_pct = round((value / budget - 1), 10) if budget != 0 else 0
    if variance_pct >= green_threshold:
        status = "Green"
    elif variance_pct >= amber_threshold:
        status = "Amber"
    else:
        status = "Red"
    return RagStatus(status, value, budget, round(variance_abs, 2), round(variance_pct, 4))


def _rag_absolute_higher_is_better(
    value: float,
    green_threshold: float,
    amber_threshold: float,
    budget: float = 0,
) -> RagStatus:
    """Assign RAG based on absolute value thresholds (not vs budget ratio).

    Args:
        value: Actual metric value.
        green_threshold: Minimum value for Green.
        amber_threshold: Minimum value for Amber (below = Red).
        budget: Budget / target (for reference only).

    Returns:
        RagStatus instance.
    """
    variance_abs = value - budget
    variance_pct = (value / budget - 1) if budget != 0 else 0
    if value >= green_threshold:
        status = "Green"
    elif value >= amber_threshold:
        status = "Amber"
    else:
        status = "Red"
    return RagStatus(status, value, budget, round(variance_abs, 2), round(variance_pct, 4))


def _rag_lower_is_better(
    value: float,
    budget: float,
    green_threshold: float,
    amber_threshold: float,
) -> RagStatus:
    """Assign RAG where lower actual vs budget is better (e.g. churn, costs).

    Args:
        value: Actual value.
        budget: Budget / target value.
        green_threshold: Ratio of actual/budget below which result is Green.
        amber_threshold: Ratio above which result is Red.

    Returns:
        RagStatus instance.
    """
    variance_abs = value - budget
    variance_pct = (value / budget - 1) if budget != 0 else 0
    if value <= green_threshold:
        status = "Green"
    elif value <= amber_threshold:
        status = "Amber"
    else:
        status = "Red"
    return RagStatus(status, value, budget, round(variance_abs, 5), round(variance_pct, 4))


# ---------------------------------------------------------------------------
# Dataset loaders
# ---------------------------------------------------------------------------

def _load_datasets(cfg: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """Load all four CSVs from disk.

    Args:
        cfg: Configuration dict.

    Returns:
        Dict of DataFrames keyed by name.

    Raises:
        FileNotFoundError: If any dataset is missing.
    """
    files = {
        "financials": cfg["paths"]["financials_file"],
        "pipeline":   cfg["paths"]["pipeline_file"],
        "headcount":  cfg["paths"]["headcount_file"],
        "customers":  cfg["paths"]["customers_file"],
    }
    datasets = {}
    for name, path in files.items():
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(
                f"{name} dataset not found at {p}. Run --generate-data first."
            )
        datasets[name] = pd.read_csv(p)
        logger.debug("Loaded %s: %d rows", name, len(datasets[name]))
    return datasets


# ---------------------------------------------------------------------------
# KPI calculators
# ---------------------------------------------------------------------------

def _calc_financial(
    fin: pd.DataFrame,
    cfg: dict[str, Any],
) -> FinancialMetrics:
    """Calculate financial P&L KPIs for the most recent period.

    Args:
        fin: Financials DataFrame.
        cfg: Configuration dict.

    Returns:
        FinancialMetrics dataclass.
    """
    latest_period = fin["period"].max()
    current_year = pd.to_datetime(latest_period).year
    fy_start_month = cfg["project"]["fiscal_year_start_month"]

    current = fin[fin["period"] == latest_period]
    ytd_mask = (
        (fin["year"] == current_year)
        & (fin["month"] >= fy_start_month)
        & (fin["period"] <= latest_period)
    )
    ytd = fin[ytd_mask]

    def _sum(df, line_type, col): return df[df["line_type"] == line_type][col].sum()

    rev_act = _sum(current, "Revenue", "actual_gbp")
    rev_bud = _sum(current, "Revenue", "budget_gbp")
    rev_py  = _sum(current, "Revenue", "prior_year_gbp")

    cogs_act = _sum(current, "COGS", "actual_gbp")
    cogs_bud = _sum(current, "COGS", "budget_gbp")

    gross_act = rev_act - cogs_act
    gross_bud = rev_bud - cogs_bud
    gm_act = gross_act / rev_act if rev_act else 0
    gm_bud = gross_bud / rev_bud if rev_bud else 0

    opex_act = _sum(current, "OpEx", "actual_gbp")
    opex_bud = _sum(current, "OpEx", "budget_gbp")

    ebitda_act = gross_act - opex_act
    ebitda_bud = gross_bud - opex_bud
    em_act = ebitda_act / rev_act if rev_act else 0
    em_bud = ebitda_bud / rev_bud if rev_bud else 0

    # YTD
    ytd_rev_act = _sum(ytd, "Revenue", "actual_gbp")
    ytd_rev_bud = _sum(ytd, "Revenue", "budget_gbp")
    ytd_ebitda_act = (_sum(ytd, "Revenue", "actual_gbp")
                      - _sum(ytd, "COGS", "actual_gbp")
                      - _sum(ytd, "OpEx", "actual_gbp"))
    ytd_ebitda_bud = (_sum(ytd, "Revenue", "budget_gbp")
                      - _sum(ytd, "COGS", "budget_gbp")
                      - _sum(ytd, "OpEx", "budget_gbp"))

    # 12-month trend for charts
    trend_periods = sorted(fin["period"].unique())[-12:]
    monthly_rev, monthly_ebitda, monthly_gm = [], [], []
    for p in trend_periods:
        pf = fin[fin["period"] == p]
        r = _sum(pf, "Revenue", "actual_gbp")
        c = _sum(pf, "COGS", "actual_gbp")
        o = _sum(pf, "OpEx", "actual_gbp")
        monthly_rev.append(round(r, 2))
        monthly_ebitda.append(round(r - c - o, 2))
        monthly_gm.append(round((r - c) / r * 100 if r else 0, 2))

    return FinancialMetrics(
        period=latest_period,
        revenue_actual=round(rev_act, 2),
        revenue_budget=round(rev_bud, 2),
        revenue_prior_year=round(rev_py, 2),
        gross_profit_actual=round(gross_act, 2),
        gross_profit_budget=round(gross_bud, 2),
        gross_margin_pct_actual=round(gm_act, 4),
        gross_margin_pct_budget=round(gm_bud, 4),
        opex_actual=round(opex_act, 2),
        opex_budget=round(opex_bud, 2),
        ebitda_actual=round(ebitda_act, 2),
        ebitda_budget=round(ebitda_bud, 2),
        ebitda_margin_pct_actual=round(em_act, 4),
        ebitda_margin_pct_budget=round(em_bud, 4),
        ytd_revenue_actual=round(ytd_rev_act, 2),
        ytd_revenue_budget=round(ytd_rev_bud, 2),
        ytd_ebitda_actual=round(ytd_ebitda_act, 2),
        ytd_ebitda_budget=round(ytd_ebitda_bud, 2),
        monthly_revenue=monthly_rev,
        monthly_ebitda=monthly_ebitda,
        monthly_gross_margin=monthly_gm,
        monthly_periods=list(trend_periods),
    )


def _calc_commercial(
    pipeline_df: pd.DataFrame,
    fin: pd.DataFrame,
    cfg: dict[str, Any],
) -> CommercialMetrics:
    """Calculate sales pipeline KPIs from the last 4 weeks of data.

    Args:
        pipeline_df: Pipeline DataFrame.
        fin: Financials DataFrame (for coverage ratio denominator).
        cfg: Configuration dict.

    Returns:
        CommercialMetrics dataclass.
    """
    sim = cfg["data_simulation"]
    pipeline_df = pipeline_df.copy()
    pipeline_df["week_start"] = pd.to_datetime(pipeline_df["week_start"])

    latest_week = pipeline_df["week_start"].max()
    recent_4w = pipeline_df[
        pipeline_df["week_start"] >= latest_week - pd.Timedelta(weeks=3)
    ]

    total_pipe = recent_4w["pipeline_value_gbp"].sum()
    total_pipe_budget = recent_4w["budget_pipeline_gbp"].sum()
    total_deals = recent_4w["deal_count"].sum()
    avg_deal = total_pipe / total_deals if total_deals else 0
    win_rate = recent_4w["win_rate_actual"].mean()

    # Pipeline coverage = total pipeline / quarterly revenue target
    latest_period = fin["period"].max()
    current_rev = fin[
        (fin["period"] == latest_period) & (fin["line_type"] == "Revenue")
    ]["budget_gbp"].sum()
    quarterly_rev_target = current_rev * 3
    coverage = total_pipe / quarterly_rev_target if quarterly_rev_target else 0

    pipeline_by_stage = (
        recent_4w.groupby("stage")["pipeline_value_gbp"].sum().round(2).to_dict()
    )

    # 12-week trend
    weeks_12 = pipeline_df["week_start"].unique()
    weeks_12 = sorted(weeks_12)[-12:]
    trend_vals, trend_labels = [], []
    for w in weeks_12:
        wf = pipeline_df[pipeline_df["week_start"] == w]
        trend_vals.append(round(wf["pipeline_value_gbp"].sum(), 2))
        trend_labels.append(pd.Timestamp(w).strftime("%Y-%m-%d"))

    return CommercialMetrics(
        period=latest_week.strftime("%Y-%m-%d"),
        total_pipeline_gbp=round(total_pipe, 2),
        pipeline_budget_gbp=round(total_pipe_budget, 2),
        pipeline_coverage_ratio=round(coverage, 2),
        win_rate_actual=round(win_rate, 4),
        win_rate_budget=sim["pipeline_win_rate_budget"],
        avg_deal_size_gbp=round(avg_deal, 2),
        new_pipeline_4w_gbp=round(total_pipe, 2),
        pipeline_by_stage=pipeline_by_stage,
        pipeline_trend=trend_vals,
        pipeline_trend_periods=trend_labels,
    )


def _calc_customers(
    cust: pd.DataFrame,
    cfg: dict[str, Any],
) -> CustomerMetrics:
    """Calculate ARR and customer health KPIs.

    Args:
        cust: Customers DataFrame.
        cfg: Configuration dict.

    Returns:
        CustomerMetrics dataclass.
    """
    latest_period = cust["period"].max()
    current = cust[cust["period"] == latest_period].iloc[0]
    prior_period = sorted(cust["period"].unique())[-2] if len(cust) > 1 else None
    prior_year = cust[cust["period"] == cust["period"].min()].iloc[0] if len(cust) else None

    arr_py = float(prior_year["arr_gbp"]) if prior_year is not None else 0

    trend_periods = sorted(cust["period"].unique())[-12:]
    arr_trend = [
        round(float(cust[cust["period"] == p]["arr_gbp"].iloc[0]), 2)
        for p in trend_periods
    ]

    return CustomerMetrics(
        period=latest_period,
        arr_actual=round(float(current["arr_gbp"]), 2),
        arr_budget=round(float(current["arr_budget_gbp"]), 2),
        arr_prior_year=round(arr_py, 2),
        new_arr_gbp=round(float(current["new_arr_gbp"]), 2),
        churned_arr_gbp=round(float(current["churned_arr_gbp"]), 2),
        net_arr_movement=round(float(current["new_arr_gbp"]) - float(current["churned_arr_gbp"]), 2),
        churn_rate_actual=round(float(current["churn_rate_actual"]), 5),
        churn_rate_budget=float(current["churn_rate_budget"]),
        nps_actual=int(current["nps_actual"]),
        nps_budget=int(current["nps_budget"]),
        new_customers=int(current["new_customers"]),
        churned_customers=int(current["churned_customers"]),
        arr_trend=arr_trend,
        arr_trend_periods=list(trend_periods),
    )


def _calc_headcount(
    hc: pd.DataFrame,
    cfg: dict[str, Any],
) -> HeadcountMetrics:
    """Calculate headcount and people-cost KPIs.

    Args:
        hc: Headcount DataFrame.
        cfg: Configuration dict.

    Returns:
        HeadcountMetrics dataclass.
    """
    latest_period = hc["period"].max()
    current = hc[hc["period"] == latest_period]
    prior_year_period = sorted(hc["period"].unique())[0]
    prior_year = hc[hc["period"] == prior_year_period]

    total_act = int(current["headcount_actual"].sum())
    total_bud = int(current["headcount_budget"].sum())
    total_py = int(prior_year["headcount_prior_year"].sum())

    cost_act = float(current["cost_actual_gbp"].sum())
    cost_bud = float(current["cost_budget_gbp"].sum())

    cph_act = cost_act / total_act if total_act else 0
    cph_bud = cost_bud / total_bud if total_bud else 0

    by_dept = {}
    for _, row in current.iterrows():
        by_dept[row["department"]] = {
            "actual": int(row["headcount_actual"]),
            "budget": int(row["headcount_budget"]),
            "variance": int(row["headcount_actual"]) - int(row["headcount_budget"]),
        }

    # 12-month trend
    trend_periods = sorted(hc["period"].unique())[-12:]
    hc_trend = [
        int(hc[hc["period"] == p]["headcount_actual"].sum())
        for p in trend_periods
    ]

    return HeadcountMetrics(
        period=latest_period,
        total_hc_actual=total_act,
        total_hc_budget=total_bud,
        total_hc_prior_year=total_py,
        total_cost_actual=round(cost_act, 2),
        total_cost_budget=round(cost_bud, 2),
        cost_per_head_actual=round(cph_act, 2),
        cost_per_head_budget=round(cph_bud, 2),
        by_department=by_dept,
        hc_trend=hc_trend,
        hc_trend_periods=list(trend_periods),
    )


def _build_rag_dashboard(
    fin: FinancialMetrics,
    comm: CommercialMetrics,
    cust: CustomerMetrics,
    hc: HeadcountMetrics,
    cfg: dict[str, Any],
) -> RagDashboard:
    """Assemble the full RAG status dashboard from computed KPIs.

    Args:
        fin: Financial metrics.
        comm: Commercial metrics.
        cust: Customer metrics.
        hc: Headcount metrics.
        cfg: Configuration dict.

    Returns:
        RagDashboard instance.
    """
    t = cfg["rag_thresholds"]
    return RagDashboard(
        revenue=_rag_higher_is_better(
            fin.revenue_actual, fin.revenue_budget,
            t["revenue_variance_pct"]["green"],
            t["revenue_variance_pct"]["amber"],
        ),
        gross_margin=_rag_absolute_higher_is_better(
            fin.gross_margin_pct_actual,
            t["gross_margin"]["green"],
            t["gross_margin"]["amber"],
            budget=fin.gross_margin_pct_budget,
        ),
        ebitda_margin=_rag_absolute_higher_is_better(
            fin.ebitda_margin_pct_actual,
            t["ebitda_margin"]["green"],
            t["ebitda_margin"]["amber"],
            budget=fin.ebitda_margin_pct_budget,
        ),
        pipeline_coverage=_rag_absolute_higher_is_better(
            comm.pipeline_coverage_ratio,
            t["pipeline_coverage"]["green"],
            t["pipeline_coverage"]["amber"],
        ),
        win_rate=_rag_absolute_higher_is_better(
            comm.win_rate_actual,
            t["win_rate"]["green"],
            t["win_rate"]["amber"],
            budget=comm.win_rate_budget,
        ),
        churn_rate=_rag_lower_is_better(
            cust.churn_rate_actual,
            cust.churn_rate_budget,
            t["churn_rate"]["green"],
            t["churn_rate"]["amber"],
        ),
        nps=_rag_absolute_higher_is_better(
            float(cust.nps_actual),
            float(t["nps"]["green"]),
            float(t["nps"]["amber"]),
            budget=float(cust.nps_budget),
        ),
        headcount=_rag_higher_is_better(
            float(hc.total_hc_actual),
            float(hc.total_hc_budget),
            green_threshold=-t["headcount_variance_pct"]["green"],
            amber_threshold=-t["headcount_variance_pct"]["amber"],
        ),
    )


def compute_metrics(config_path: str = "config.yaml") -> MetricsPackage:
    """Load datasets and compute the full metrics package.

    This is the single public entry point for the metrics module.

    Args:
        config_path: Path to configuration YAML.

    Returns:
        Complete MetricsPackage for the most recent reporting period.
    """
    with open(config_path, "r") as fh:
        cfg = yaml.safe_load(fh)

    datasets = _load_datasets(cfg)
    fin_df = datasets["financials"]
    pipe_df = datasets["pipeline"]
    hc_df = datasets["headcount"]
    cust_df = datasets["customers"]

    logger.info("Computing KPIs for period: %s", fin_df["period"].max())

    fin = _calc_financial(fin_df, cfg)
    comm = _calc_commercial(pipe_df, fin_df, cfg)
    cust = _calc_customers(cust_df, cfg)
    hc = _calc_headcount(hc_df, cfg)
    rag = _build_rag_dashboard(fin, comm, cust, hc, cfg)

    pkg = MetricsPackage(
        report_period=fin.period,
        company_name=cfg["project"]["company_name"],
        financial=fin,
        commercial=comm,
        customers=cust,
        headcount=hc,
        rag=rag,
    )

    logger.info(
        "Metrics computed — Revenue: £%.0f (vs budget: %+.1f%%) | "
        "EBITDA margin: %.1f%% | ARR: £%.0f",
        fin.revenue_actual,
        rag.revenue.variance_pct * 100,
        fin.ebitda_margin_pct_actual * 100,
        cust.arr_actual,
    )
    return pkg
