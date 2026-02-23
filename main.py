"""
main.py — Automated Board Report Generator — CLI Entry Point.

Provides a full command-line interface for running any combination of
pipeline stages. Stages share data in memory (no intermediate disk reads).

Usage:
    python main.py --full-run                   # Monday morning pack
    python main.py --generate-data              # Refresh synthetic data
    python main.py --report --dashboard         # Rebuild outputs only
    python main.py --full-run --config custom.yaml --log-level DEBUG

Outputs (data/output/):
    board_report_{period}.pdf           — 7-page PDF narrative
    board_data_pack_{period}.xlsx       — 6-tab Excel data pack
    board_dashboard_{period}.html       — Interactive Plotly dashboard
"""

import argparse
import logging
import logging.handlers
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml


def _configure_logging(log_dir: str = "logs", level: str = "INFO") -> None:
    """Configure rotating file handler + stream handler.

    Args:
        log_dir: Directory for log files.
        level: Log level string.
    """
    effective_level = os.environ.get("LOG_LEVEL", level).upper()
    numeric = getattr(logging, effective_level, logging.INFO)

    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = Path(log_dir) / f"pipeline_{datetime.today().strftime('%Y%m%d')}.log"

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-35s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=7, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(numeric)
    root.addHandler(fh)
    root.addHandler(sh)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="board-report-generator",
        description="Automated Board Report Generator — PDF + Excel + Dashboard pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --full-run
  python main.py --generate-data
  python main.py --report --dashboard
  python main.py --full-run --distribute
  python main.py --full-run --config custom.yaml --log-level DEBUG
        """,
    )
    parser.add_argument("--config", default="config.yaml",
                        help="Path to config.yaml (default: config.yaml)")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    stages = parser.add_argument_group("Pipeline Stages")
    stages.add_argument("--generate-data", action="store_true",
                        help="Generate synthetic financial dataset")
    stages.add_argument("--report", action="store_true",
                        help="Generate PDF report")
    stages.add_argument("--excel", action="store_true",
                        help="Generate Excel data pack")
    stages.add_argument("--dashboard", action="store_true",
                        help="Generate interactive HTML dashboard")
    stages.add_argument("--distribute", action="store_true",
                        help="Distribute via email and Slack")
    stages.add_argument("--full-run", action="store_true",
                        help="Run all stages: generate -> report -> excel -> dashboard -> distribute")
    return parser.parse_args()


def run_pipeline(args: argparse.Namespace, logger: logging.Logger) -> int:
    """Execute the requested pipeline stages.

    Args:
        args: Parsed CLI arguments.
        logger: Configured root logger.

    Returns:
        0 on success, 1 on error.
    """
    from src.data_simulator import generate_all_datasets
    from src.metrics import compute_metrics
    from src.narrative import generate_narrative
    from src.pdf_builder import generate_pdf
    from src.excel_pack import generate_excel_pack
    from src.dashboard import generate_dashboard
    from src.distributor import send_email, send_slack_summary

    config_path = args.config
    do_all = args.full_run

    pkg = None
    narrative = None
    pdf_path = None
    excel_path = None

    # -------------------------------------------------------------------------
    # Stage 1: Data generation
    # -------------------------------------------------------------------------
    if do_all or args.generate_data:
        logger.info("=" * 65)
        logger.info("STAGE 1: Data Generation")
        logger.info("=" * 65)
        try:
            datasets = generate_all_datasets(config_path)
            total_rows = sum(len(df) for df in datasets.values())
            logger.info("Data generation complete -- %d total rows across 4 datasets", total_rows)
        except Exception as exc:
            logger.error("Data generation failed: %s", exc, exc_info=True)
            return 1

    # -------------------------------------------------------------------------
    # Stage 2: Metrics computation (always needed for outputs)
    # -------------------------------------------------------------------------
    if do_all or args.report or args.excel or args.dashboard or args.distribute:
        logger.info("=" * 65)
        logger.info("STAGE 2: KPI Computation")
        logger.info("=" * 65)
        try:
            pkg = compute_metrics(config_path)
            logger.info(
                "Metrics computed -- Period: %s | Revenue: £%.0f | EBITDA margin: %.1f%%",
                pkg.report_period,
                pkg.financial.revenue_actual,
                pkg.financial.ebitda_margin_pct_actual * 100,
            )
        except FileNotFoundError as exc:
            logger.error("Dataset missing. Run --generate-data first.\n%s", exc)
            return 1
        except Exception as exc:
            logger.error("Metrics computation failed: %s", exc, exc_info=True)
            return 1

    # -------------------------------------------------------------------------
    # Stage 3: Narrative generation (needed for PDF)
    # -------------------------------------------------------------------------
    if pkg and (do_all or args.report):
        logger.info("=" * 65)
        logger.info("STAGE 3: Narrative Generation")
        logger.info("=" * 65)
        try:
            narrative = generate_narrative(pkg, config_path)
            logger.info("Narrative generated -- %d chars in executive summary",
                        len(narrative.executive_summary))
        except Exception as exc:
            logger.error("Narrative generation failed: %s", exc, exc_info=True)
            return 1

    # -------------------------------------------------------------------------
    # Stage 4: PDF report
    # -------------------------------------------------------------------------
    if do_all or args.report:
        if pkg and narrative:
            logger.info("=" * 65)
            logger.info("STAGE 4: PDF Report")
            logger.info("=" * 65)
            try:
                pdf_path = generate_pdf(pkg, narrative, config_path)
                logger.info("PDF report generated: %s", pdf_path)
            except Exception as exc:
                logger.error("PDF generation failed: %s", exc, exc_info=True)
                return 1

    # -------------------------------------------------------------------------
    # Stage 5: Excel data pack
    # -------------------------------------------------------------------------
    if do_all or args.excel:
        if pkg:
            logger.info("=" * 65)
            logger.info("STAGE 5: Excel Data Pack")
            logger.info("=" * 65)
            try:
                excel_path = generate_excel_pack(pkg, config_path)
                logger.info("Excel data pack generated: %s", excel_path)
            except Exception as exc:
                logger.error("Excel generation failed: %s", exc, exc_info=True)
                return 1

    # -------------------------------------------------------------------------
    # Stage 6: Interactive dashboard
    # -------------------------------------------------------------------------
    if do_all or args.dashboard:
        if pkg:
            logger.info("=" * 65)
            logger.info("STAGE 6: Interactive Dashboard")
            logger.info("=" * 65)
            try:
                dash_path = generate_dashboard(pkg, config_path)
                logger.info("Dashboard generated: %s", dash_path)
            except Exception as exc:
                logger.error("Dashboard generation failed: %s", exc, exc_info=True)
                return 1

    # -------------------------------------------------------------------------
    # Stage 7: Distribution
    # -------------------------------------------------------------------------
    if do_all or args.distribute:
        if pkg:
            logger.info("=" * 65)
            logger.info("STAGE 7: Distribution")
            logger.info("=" * 65)
            try:
                send_email(pkg, pdf_path, excel_path, config_path)
                send_slack_summary(pkg, config_path)
                logger.info("Distribution complete")
            except Exception as exc:
                logger.error("Distribution failed: %s", exc, exc_info=True)
                # Non-fatal

    # Final summary
    logger.info("=" * 65)
    logger.info("PIPELINE COMPLETE")
    if pkg:
        rag = pkg.rag
        logger.info(
            "  Revenue:       £%.0f (%s)",
            pkg.financial.revenue_actual, rag.revenue.status,
        )
        logger.info(
            "  EBITDA margin: %.1f%% (%s)",
            pkg.financial.ebitda_margin_pct_actual * 100, rag.ebitda_margin.status,
        )
        logger.info(
            "  ARR:           £%.0f | Churn: %.2f%% (%s)",
            pkg.customers.arr_actual,
            pkg.customers.churn_rate_actual * 100,
            rag.churn_rate.status,
        )
    logger.info("=" * 65)
    return 0


def main() -> None:
    """Parse args, configure logging, and run pipeline."""
    args = _parse_args()

    try:
        with open(args.config, "r") as fh:
            cfg = yaml.safe_load(fh)
        log_dir = cfg.get("paths", {}).get("log_dir", "logs")
    except Exception:
        log_dir = "logs"

    _configure_logging(log_dir=log_dir, level=args.log_level)
    logger = logging.getLogger(__name__)

    no_stage = not any([
        args.full_run, args.generate_data, args.report,
        args.excel, args.dashboard, args.distribute,
    ])
    if no_stage:
        import subprocess
        subprocess.run([sys.executable, __file__, "--help"])
        sys.exit(0)

    logger.info(
        "Automated Board Report Generator v1.0 | %s",
        datetime.today().strftime("%Y-%m-%d %H:%M:%S"),
    )
    sys.exit(run_pipeline(args, logger))


if __name__ == "__main__":
    main()
