"""
test_narrative.py — Unit tests for the narrative generation engine.

Tests cover:
    - Formatting helpers (_gbp, _pct, _pp)
    - NarrativePackage structure
    - Section content quality checks (not empty, contains key values)
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.narrative import _gbp, _pct, _pp, _above_below


class TestFormattingHelpers:
    """Tests for the GBP/percentage formatting helper functions."""

    def test_gbp_full_positive(self):
        assert _gbp(1_234_567) == "£1,234,567"

    def test_gbp_millions(self):
        assert _gbp(1_500_000, "m") == "£1.5M"

    def test_gbp_thousands(self):
        assert _gbp(42_000, "k") == "£42k"

    def test_gbp_negative_millions(self):
        result = _gbp(-500_000, "m")
        assert result == "-£0.5M"

    def test_gbp_zero(self):
        assert _gbp(0) == "£0"

    def test_pct_positive_with_sign(self):
        result = _pct(0.142)
        assert result == "+14.2%"

    def test_pct_negative(self):
        result = _pct(-0.05)
        assert result == "-5.0%"

    def test_pct_no_sign(self):
        result = _pct(0.142, sign=False)
        assert result == "14.2%"

    def test_pct_zero(self):
        result = _pct(0.0)
        assert result == "+0.0%"

    def test_pp_positive(self):
        result = _pp(0.023)
        assert result == "2.3pp"

    def test_pp_negative_treated_as_absolute(self):
        # _pp takes absolute value
        result = _pp(-0.015)
        assert result == "1.5pp"

    def test_above_below_above(self):
        assert _above_below(110, 100) == "above"

    def test_above_below_equal(self):
        assert _above_below(100, 100) == "above"

    def test_above_below_below(self):
        assert _above_below(90, 100) == "below"


class TestNarrativeGeneration:
    """Integration tests for the full narrative pipeline."""

    @pytest.fixture(autouse=True)
    def ensure_data(self):
        """Ensure datasets exist before running narrative tests."""
        raw_path = Path("data/raw/financials.csv")
        if not raw_path.exists():
            from src.data_simulator import generate_all_datasets
            generate_all_datasets("config.yaml")

    def test_narrative_package_structure(self):
        from src.metrics import compute_metrics
        from src.narrative import generate_narrative, NarrativePackage

        pkg = compute_metrics("config.yaml")
        narrative = generate_narrative(pkg, "config.yaml")

        assert isinstance(narrative, NarrativePackage)

    def test_all_sections_non_empty(self):
        from src.metrics import compute_metrics
        from src.narrative import generate_narrative

        pkg = compute_metrics("config.yaml")
        narrative = generate_narrative(pkg, "config.yaml")

        for field in [
            "executive_summary", "financial_performance",
            "commercial_performance", "customer_metrics",
            "operational_metrics", "outlook_and_risks",
        ]:
            value = getattr(narrative, field)
            assert value, f"Narrative section '{field}' is empty"
            assert len(value) > 50, f"Section '{field}' is too short ({len(value)} chars)"

    def test_executive_summary_contains_company_name(self):
        from src.metrics import compute_metrics
        from src.narrative import generate_narrative

        pkg = compute_metrics("config.yaml")
        narrative = generate_narrative(pkg, "config.yaml")

        assert pkg.company_name in narrative.executive_summary

    def test_risk_register_has_entries(self):
        from src.metrics import compute_metrics
        from src.narrative import generate_narrative

        pkg = compute_metrics("config.yaml")
        narrative = generate_narrative(pkg, "config.yaml")

        assert isinstance(narrative.risk_register, list)
        assert len(narrative.risk_register) >= 1
        for risk in narrative.risk_register:
            assert "risk" in risk
            assert "rating" in risk

    def test_financial_section_contains_gbp_values(self):
        from src.metrics import compute_metrics
        from src.narrative import generate_narrative

        pkg = compute_metrics("config.yaml")
        narrative = generate_narrative(pkg, "config.yaml")

        # Should contain pound signs (currency formatting worked)
        assert "£" in narrative.financial_performance

    def test_period_in_narrative(self):
        from src.metrics import compute_metrics
        from src.narrative import generate_narrative

        pkg = compute_metrics("config.yaml")
        narrative = generate_narrative(pkg, "config.yaml")

        assert pkg.report_period in narrative.executive_summary
