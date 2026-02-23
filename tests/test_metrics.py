"""
test_metrics.py — Unit tests for the KPI metrics engine.

Tests cover:
    - RAG status helper functions (boundary values)
    - Financial KPI calculation correctness
    - MetricsPackage dataclass structure
    - Metrics computation with real config
"""

import sys
from pathlib import Path
from datetime import date

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.metrics import (
    _rag_higher_is_better,
    _rag_absolute_higher_is_better,
    _rag_lower_is_better,
    RagStatus,
)


# ---------------------------------------------------------------------------
# RAG helpers
# ---------------------------------------------------------------------------

class TestRagHigherIsBetter:
    """Tests for _rag_higher_is_better."""

    def test_above_green_threshold_returns_green(self):
        result = _rag_higher_is_better(1020, 1000, green_threshold=-0.02, amber_threshold=-0.08)
        assert result.status == "Green"

    def test_within_green_band_returns_green(self):
        # -1.5% variance, green threshold = -2%, should be Green
        result = _rag_higher_is_better(985, 1000, green_threshold=-0.02, amber_threshold=-0.08)
        assert result.status == "Green"

    def test_amber_band_returns_amber(self):
        # -5% variance, between -2% and -8%
        result = _rag_higher_is_better(950, 1000, green_threshold=-0.02, amber_threshold=-0.08)
        assert result.status == "Amber"

    def test_below_amber_threshold_returns_red(self):
        # -10% variance, below -8% amber threshold
        result = _rag_higher_is_better(900, 1000, green_threshold=-0.02, amber_threshold=-0.08)
        assert result.status == "Red"

    def test_exact_green_boundary_returns_green(self):
        # Exactly -2% = green threshold (>= comparison)
        result = _rag_higher_is_better(980, 1000, green_threshold=-0.02, amber_threshold=-0.08)
        assert result.status == "Green"

    def test_variance_values_computed_correctly(self):
        result = _rag_higher_is_better(1100, 1000, green_threshold=-0.02, amber_threshold=-0.08)
        assert abs(result.variance_abs - 100) < 0.01
        assert abs(result.variance_pct - 0.10) < 0.001

    def test_zero_budget_does_not_raise(self):
        result = _rag_higher_is_better(100, 0, green_threshold=-0.02, amber_threshold=-0.08)
        assert result.variance_pct == 0


class TestRagAbsoluteHigherIsBetter:
    """Tests for _rag_absolute_higher_is_better."""

    def test_above_green_threshold(self):
        result = _rag_absolute_higher_is_better(0.65, green_threshold=0.62, amber_threshold=0.55)
        assert result.status == "Green"

    def test_at_green_threshold(self):
        result = _rag_absolute_higher_is_better(0.62, green_threshold=0.62, amber_threshold=0.55)
        assert result.status == "Green"

    def test_between_thresholds_is_amber(self):
        result = _rag_absolute_higher_is_better(0.58, green_threshold=0.62, amber_threshold=0.55)
        assert result.status == "Amber"

    def test_below_amber_threshold_is_red(self):
        result = _rag_absolute_higher_is_better(0.50, green_threshold=0.62, amber_threshold=0.55)
        assert result.status == "Red"

    def test_nps_positive_above_threshold(self):
        # NPS of 45, green=35, amber=20 -> Green
        result = _rag_absolute_higher_is_better(45.0, 35.0, 20.0)
        assert result.status == "Green"

    def test_nps_below_amber(self):
        result = _rag_absolute_higher_is_better(15.0, 35.0, 20.0)
        assert result.status == "Red"


class TestRagLowerIsBetter:
    """Tests for _rag_lower_is_better (churn, costs)."""

    def test_below_green_threshold_is_green(self):
        # Churn 1.0%, green threshold 1.5% -> Green
        result = _rag_lower_is_better(0.010, budget=0.012, green_threshold=0.015, amber_threshold=0.022)
        assert result.status == "Green"

    def test_above_amber_threshold_is_red(self):
        # Churn 2.5%, amber 2.2% -> Red
        result = _rag_lower_is_better(0.025, budget=0.012, green_threshold=0.015, amber_threshold=0.022)
        assert result.status == "Red"

    def test_between_thresholds_is_amber(self):
        result = _rag_lower_is_better(0.018, budget=0.012, green_threshold=0.015, amber_threshold=0.022)
        assert result.status == "Amber"


# ---------------------------------------------------------------------------
# Integration: full metrics computation (requires generated data)
# ---------------------------------------------------------------------------

class TestComputeMetricsIntegration:
    """Integration tests that run the full metrics computation."""

    @pytest.fixture(autouse=True)
    def generate_data_once(self, tmp_path, monkeypatch):
        """Generate datasets into a temp directory and patch config paths."""
        from src.data_simulator import generate_all_datasets
        # Only run if real data doesn't exist
        config_path = "config.yaml"
        raw_path = Path("data/raw/financials.csv")
        if not raw_path.exists():
            generate_all_datasets(config_path)

    def test_compute_metrics_returns_metrics_package(self):
        from src.metrics import compute_metrics, MetricsPackage
        pkg = compute_metrics("config.yaml")
        assert isinstance(pkg, MetricsPackage)

    def test_period_is_set(self):
        from src.metrics import compute_metrics
        pkg = compute_metrics("config.yaml")
        assert pkg.report_period is not None
        assert len(pkg.report_period) == 7  # YYYY-MM

    def test_revenue_is_positive(self):
        from src.metrics import compute_metrics
        pkg = compute_metrics("config.yaml")
        assert pkg.financial.revenue_actual > 0

    def test_ebitda_margin_in_reasonable_range(self):
        from src.metrics import compute_metrics
        pkg = compute_metrics("config.yaml")
        margin = pkg.financial.ebitda_margin_pct_actual
        assert -0.5 <= margin <= 0.5, f"EBITDA margin {margin} outside reasonable range"

    def test_rag_statuses_are_valid(self):
        from src.metrics import compute_metrics
        pkg = compute_metrics("config.yaml")
        valid = {"Green", "Amber", "Red"}
        rag = pkg.rag
        for attr in ["revenue", "gross_margin", "ebitda_margin",
                     "pipeline_coverage", "win_rate", "churn_rate", "nps"]:
            status = getattr(rag, attr).status
            assert status in valid, f"RAG.{attr} = '{status}' not in {valid}"

    def test_arr_is_positive(self):
        from src.metrics import compute_metrics
        pkg = compute_metrics("config.yaml")
        assert pkg.customers.arr_actual > 0

    def test_headcount_budget_positive(self):
        from src.metrics import compute_metrics
        pkg = compute_metrics("config.yaml")
        assert pkg.headcount.total_hc_budget > 0

    def test_pipeline_coverage_ratio_positive(self):
        from src.metrics import compute_metrics
        pkg = compute_metrics("config.yaml")
        assert pkg.commercial.pipeline_coverage_ratio > 0

    def test_monthly_trend_length(self):
        from src.metrics import compute_metrics
        pkg = compute_metrics("config.yaml")
        assert len(pkg.financial.monthly_revenue) == 12
        assert len(pkg.financial.monthly_periods) == 12
