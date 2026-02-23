"""
data_simulator.py — Synthetic Financial Dataset Generator.

Generates four interconnected datasets that mirror what a finance team
would extract from an ERP system prior to board reporting:

    1. financials.csv   — Monthly P&L by revenue line and cost department
    2. pipeline.csv     — Weekly sales pipeline by stage
    3. headcount.csv    — Monthly headcount actuals vs budget by department
    4. customers.csv    — Monthly customer ARR, churn, NPS, acquisitions

All datasets have 24 months of history with:
    - Realistic seasonality patterns
    - Budget vs actual with controlled variances
    - Prior-year comparators (YoY analysis)
    - Injected under-performance in specific months (narrative interest)
"""

import logging
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

logger = logging.getLogger(__name__)


def _load_config(config_path: str = "config.yaml") -> dict[str, Any]:
    with open(config_path, "r") as fh:
        return yaml.safe_load(fh)


def _month_range(months: int) -> list[date]:
    """Return a list of the first day of each month going back `months` months."""
    today = date.today()
    result = []
    year, month = today.year, today.month
    for _ in range(months):
        result.append(date(year, month, 1))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(result))


def _generate_financials(
    cfg: dict[str, Any],
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Generate monthly P&L data with actuals, budget, and prior-year columns.

    Each row represents one month × one revenue line.
    OpEx is aggregated at the department level and included as separate rows.

    Args:
        cfg: Full configuration dictionary.
        rng: Seeded NumPy random generator.

    Returns:
        DataFrame with columns:
            period, year, month, line_type, line_name,
            budget_gbp, actual_gbp, prior_year_gbp
    """
    sim = cfg["data_simulation"]
    months_history = sim["months_history"]
    annual_budget = sim["annual_revenue_budget"]
    growth_rate = sim["annual_revenue_growth_rate"]
    rev_mix = sim["revenue_mix"]
    cogs_rates = sim["cogs_rates"]
    opex_pct = sim["opex_budget_pct"]
    seasonality = sim["seasonality"]

    periods = _month_range(months_history)
    records = []

    for period in periods:
        m_idx = period.month - 1  # 0-based
        seasonal_factor = seasonality[m_idx]

        # ------------------------------------------------------------------
        # Revenue lines
        # ------------------------------------------------------------------
        for line_name, mix_pct in rev_mix.items():
            monthly_budget = (annual_budget * mix_pct / 12) * seasonal_factor
            # Actual: random ±6% around budget
            actual_variance = float(rng.normal(0, 0.045))
            monthly_actual = monthly_budget * (1 + actual_variance)

            # Prior year: budget deflated by growth rate, with noise
            py_budget = monthly_budget / (1 + growth_rate)
            monthly_py = py_budget * (1 + float(rng.normal(0, 0.03)))

            records.append({
                "period": period.strftime("%Y-%m"),
                "year": period.year,
                "month": period.month,
                "line_type": "Revenue",
                "line_name": line_name.replace("_", " "),
                "budget_gbp": round(monthly_budget, 2),
                "actual_gbp": round(max(0, monthly_actual), 2),
                "prior_year_gbp": round(max(0, monthly_py), 2),
            })

            # COGS for this revenue line
            cogs_rate = cogs_rates[line_name]
            cogs_budget = monthly_budget * cogs_rate
            cogs_actual = monthly_actual * (cogs_rate + float(rng.normal(0, 0.02)))
            cogs_py = monthly_py * (cogs_rate + float(rng.normal(0, 0.015)))

            records.append({
                "period": period.strftime("%Y-%m"),
                "year": period.year,
                "month": period.month,
                "line_type": "COGS",
                "line_name": f"COGS — {line_name.replace('_', ' ')}",
                "budget_gbp": round(cogs_budget, 2),
                "actual_gbp": round(max(0, cogs_actual), 2),
                "prior_year_gbp": round(max(0, cogs_py), 2),
            })

        # ------------------------------------------------------------------
        # OpEx departments
        # ------------------------------------------------------------------
        monthly_rev_budget = annual_budget / 12 * seasonal_factor
        for dept, pct in opex_pct.items():
            dept_budget = monthly_rev_budget * pct
            dept_actual = dept_budget * (1 + float(rng.normal(0.02, 0.04)))
            dept_py = dept_budget / (1 + growth_rate * 0.5) * (
                1 + float(rng.normal(0, 0.03))
            )
            records.append({
                "period": period.strftime("%Y-%m"),
                "year": period.year,
                "month": period.month,
                "line_type": "OpEx",
                "line_name": dept.replace("_", " & "),
                "budget_gbp": round(dept_budget, 2),
                "actual_gbp": round(max(0, dept_actual), 2),
                "prior_year_gbp": round(max(0, dept_py), 2),
            })

    df = pd.DataFrame(records)

    # Inject a weaker quarter (Q3 of first year) for narrative interest
    q3_mask = (df["year"] == periods[0].year) & (df["month"].isin([7, 8, 9]))
    rev_mask = df["line_type"] == "Revenue"
    df.loc[q3_mask & rev_mask, "actual_gbp"] *= 0.91  # 9% miss

    logger.info(
        "Generated financials: %d records across %d months",
        len(df),
        months_history,
    )
    return df


def _generate_pipeline(
    cfg: dict[str, Any],
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Generate weekly sales pipeline data across four pipeline stages.

    Args:
        cfg: Configuration dict.
        rng: Seeded RNG.

    Returns:
        DataFrame with weekly pipeline snapshot:
            week_start, stage, pipeline_value_gbp, deal_count,
            budget_pipeline_gbp, win_rate_actual, win_rate_budget
    """
    sim = cfg["data_simulation"]
    months = sim["months_history"]
    weekly_budget = sim["weekly_new_pipeline_budget"]
    win_rate_budget = sim["pipeline_win_rate_budget"]
    avg_deal = sim["avg_deal_size_budget"]

    weeks = months * 4
    periods = _month_range(months)
    start_date = periods[0]

    stages = {
        "Prospecting":    0.28,
        "Qualified":      0.32,
        "Proposal_Sent":  0.24,
        "Negotiation":    0.16,
    }

    records = []
    for week_idx in range(weeks):
        week_start = pd.Timestamp(start_date) + pd.Timedelta(weeks=week_idx)
        total_new_pipeline = weekly_budget * (1 + float(rng.normal(0, 0.15)))

        for stage, stage_pct in stages.items():
            stage_pipeline = total_new_pipeline * stage_pct
            stage_actual = stage_pipeline * (1 + float(rng.normal(0, 0.12)))
            n_deals = max(1, int(stage_actual / avg_deal))
            win_rate_actual = win_rate_budget + float(rng.normal(0, 0.04))

            records.append({
                "week_start": week_start.strftime("%Y-%m-%d"),
                "stage": stage.replace("_", " "),
                "pipeline_value_gbp": round(max(0, stage_actual), 2),
                "budget_pipeline_gbp": round(stage_pipeline, 2),
                "deal_count": n_deals,
                "win_rate_actual": round(max(0.05, min(0.65, win_rate_actual)), 4),
                "win_rate_budget": win_rate_budget,
            })

    logger.info("Generated pipeline: %d weekly stage records", len(records))
    return pd.DataFrame(records)


def _generate_headcount(
    cfg: dict[str, Any],
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Generate monthly headcount actuals vs budget by department.

    Args:
        cfg: Configuration dict.
        rng: Seeded RNG.

    Returns:
        DataFrame:
            period, department, headcount_budget, headcount_actual,
            headcount_prior_year, cost_budget_gbp, cost_actual_gbp
    """
    sim = cfg["data_simulation"]
    months = sim["months_history"]
    hc_budget = sim["headcount_budget"]
    salaries = sim["avg_salary_by_dept"]

    periods = _month_range(months)
    records = []

    for period in periods:
        for dept, budget_hc in hc_budget.items():
            # Headcount grows ~8% pa with monthly variation
            growth_factor = 1 + (0.08 / 12) * len(records) / len(hc_budget)
            actual_hc = max(1, int(budget_hc * growth_factor + rng.normal(0, 1)))
            py_hc = max(1, int(budget_hc * 0.88 + rng.normal(0, 1)))

            monthly_salary = salaries.get(dept, 55000) / 12
            cost_budget = budget_hc * monthly_salary
            cost_actual = actual_hc * monthly_salary * (1 + float(rng.normal(0, 0.03)))

            records.append({
                "period": period.strftime("%Y-%m"),
                "year": period.year,
                "month": period.month,
                "department": dept.replace("_", " "),
                "headcount_budget": budget_hc,
                "headcount_actual": actual_hc,
                "headcount_prior_year": py_hc,
                "cost_budget_gbp": round(cost_budget, 2),
                "cost_actual_gbp": round(max(0, cost_actual), 2),
            })

    logger.info("Generated headcount: %d records", len(records))
    return pd.DataFrame(records)


def _generate_customers(
    cfg: dict[str, Any],
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Generate monthly customer metrics: ARR, churn, NPS, acquisitions.

    Simulates ARR waterfall dynamics where new ARR net of churn drives
    month-on-month ARR movement.

    Args:
        cfg: Configuration dict.
        rng: Seeded RNG.

    Returns:
        DataFrame:
            period, arr_gbp, new_arr_gbp, churned_arr_gbp,
            arr_budget_gbp, churn_rate_actual, churn_rate_budget,
            nps_actual, nps_budget, new_customers, churned_customers
    """
    sim = cfg["data_simulation"]
    months = sim["months_history"]
    starting_arr = sim["starting_arr"]
    monthly_churn_budget = sim["monthly_churn_rate_budget"]
    monthly_new_arr = sim["monthly_new_arr_budget"]
    nps_target = sim["nps_target"]

    periods = _month_range(months)
    records = []
    arr = starting_arr
    arr_budget = starting_arr

    for period in periods:
        # Churn
        churn_rate = max(0.003, monthly_churn_budget + float(rng.normal(0, 0.004)))
        churned = arr * churn_rate
        churned_budget = arr_budget * monthly_churn_budget

        # New ARR
        new_arr = monthly_new_arr * (1 + float(rng.normal(0, 0.12)))
        new_arr_budget = monthly_new_arr

        # Update ARR
        arr = max(0, arr - churned + new_arr)
        arr_budget = max(0, arr_budget - churned_budget + new_arr_budget)

        # NPS
        nps = max(-100, min(100, int(nps_target + rng.normal(0, 8))))

        # Customer counts (approximate from ARR and avg contract value)
        avg_contract = 28000
        new_customers = max(0, int(new_arr / avg_contract))
        churned_customers = max(0, int(churned / avg_contract))

        records.append({
            "period": period.strftime("%Y-%m"),
            "year": period.year,
            "month": period.month,
            "arr_gbp": round(arr, 2),
            "arr_budget_gbp": round(arr_budget, 2),
            "new_arr_gbp": round(max(0, new_arr), 2),
            "churned_arr_gbp": round(max(0, churned), 2),
            "churn_rate_actual": round(churn_rate, 5),
            "churn_rate_budget": monthly_churn_budget,
            "nps_actual": nps,
            "nps_budget": nps_target,
            "new_customers": new_customers,
            "churned_customers": churned_customers,
        })

    logger.info("Generated customer metrics: %d monthly records", len(records))
    return pd.DataFrame(records)


def generate_all_datasets(config_path: str = "config.yaml") -> dict[str, pd.DataFrame]:
    """Orchestrate generation of all four datasets and write them to disk.

    Args:
        config_path: Path to configuration YAML.

    Returns:
        Dict with keys: 'financials', 'pipeline', 'headcount', 'customers'
    """
    cfg = _load_config(config_path)
    seed = cfg["data_simulation"]["seed"]
    rng = np.random.default_rng(seed)

    logger.info("Starting dataset generation (seed=%d)", seed)

    datasets = {
        "financials": _generate_financials(cfg, rng),
        "pipeline":   _generate_pipeline(cfg, rng),
        "headcount":  _generate_headcount(cfg, rng),
        "customers":  _generate_customers(cfg, rng),
    }

    raw_dir = Path(cfg["paths"]["raw_data_dir"])
    raw_dir.mkdir(parents=True, exist_ok=True)

    file_map = {
        "financials": cfg["paths"]["financials_file"],
        "pipeline":   cfg["paths"]["pipeline_file"],
        "headcount":  cfg["paths"]["headcount_file"],
        "customers":  cfg["paths"]["customers_file"],
    }

    for key, df in datasets.items():
        path = Path(file_map[key])
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        logger.info("Written %s: %d rows -> %s", key, len(df), path)

    return datasets
