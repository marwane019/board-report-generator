"""
scheduler.py — Weekly Board Report Scheduler.

Runs the full pipeline every Monday at 06:00 London time so the board
pack arrives in inboxes before the working day begins.

Usage:
    python scheduler.py              # Start daemon (blocking)
    python scheduler.py --run-now   # One immediate run, then exit
    python scheduler.py --config custom.yaml
"""

import argparse
import logging
import logging.handlers
import signal
import sys
from pathlib import Path

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger


logger = logging.getLogger(__name__)


def _configure_logging(log_dir: str) -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-35s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = logging.handlers.RotatingFileHandler(
        Path(log_dir) / "scheduler.log",
        maxBytes=5 * 1024 * 1024, backupCount=14, encoding="utf-8",
    )
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(fh)
    root.addHandler(sh)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)


def _run_full_pipeline(config_path: str, max_retries: int, retry_delay: int) -> None:
    """Execute the board report pipeline with retry logic.

    Args:
        config_path: Path to configuration YAML.
        max_retries: Maximum retry attempts.
        retry_delay: Seconds between retries.
    """
    import time
    import argparse as _ap
    from main import run_pipeline, _configure_logging as _cfg_log

    logger.info("Starting scheduled board report pipeline run")

    args = _ap.Namespace(
        config=config_path,
        log_level="INFO",
        full_run=True,
        generate_data=False,
        report=False,
        excel=False,
        dashboard=False,
        distribute=False,
    )

    for attempt in range(1, max_retries + 1):
        try:
            exit_code = run_pipeline(args, logger)
            if exit_code == 0:
                logger.info("Scheduled run succeeded (attempt %d)", attempt)
                return
            logger.error("Pipeline returned non-zero exit code (attempt %d)", attempt)
        except Exception as exc:
            logger.error("Pipeline exception (attempt %d): %s", attempt, exc, exc_info=True)

        if attempt < max_retries:
            logger.info("Retrying in %ds...", retry_delay)
            time.sleep(retry_delay)

    logger.error("Pipeline failed after %d attempts", max_retries)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="scheduler",
        description="Weekly Board Report Generator scheduler (Monday 06:00).",
    )
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--run-now", action="store_true",
                        help="Run immediately then exit (testing)")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        with open(args.config, "r") as fh:
            cfg = yaml.safe_load(fh)
    except FileNotFoundError:
        print(f"ERROR: Config not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    log_dir = cfg.get("paths", {}).get("log_dir", "logs")
    _configure_logging(log_dir)

    sched_cfg = cfg.get("scheduler", {})
    run_day = sched_cfg.get("run_day_of_week", "mon")
    run_time = sched_cfg.get("run_time", "06:00")
    timezone = sched_cfg.get("timezone", "Europe/London")
    max_retries = sched_cfg.get("max_retries", 3)
    retry_delay = sched_cfg.get("retry_delay_seconds", 300)

    run_hour, run_minute = map(int, run_time.split(":"))

    if args.run_now:
        logger.info("--run-now: executing pipeline immediately")
        _run_full_pipeline(args.config, max_retries, retry_delay)
        logger.info("Immediate run complete")
        return

    scheduler = BlockingScheduler(timezone=timezone)
    scheduler.add_job(
        _run_full_pipeline,
        trigger=CronTrigger(
            day_of_week=run_day,
            hour=run_hour,
            minute=run_minute,
            timezone=timezone,
        ),
        kwargs={"config_path": args.config, "max_retries": max_retries,
                "retry_delay": retry_delay},
        id="weekly_board_report",
        name="Weekly Board Report Generation",
        replace_existing=True,
        misfire_grace_time=600,
    )

    def _shutdown(sig, frame):
        logger.info("Shutdown signal — stopping scheduler")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info(
        "Scheduler started -- weekly run: %s at %s (%s)",
        run_day.upper(), run_time, timezone,
    )
    scheduler.start()


if __name__ == "__main__":
    main()
