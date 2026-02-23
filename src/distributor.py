"""
distributor.py — Report Distribution Engine.

Handles delivery of the board report pack via two channels:
    1. Email (SMTP) — PDF + Excel attached, HTML dashboard linked
    2. Slack webhook — KPI summary with RAG status blocks

Both channels support dry-run mode when credentials are absent —
the payload is logged rather than sent, making local development safe.

SMTP credentials and Slack webhook URL are read exclusively from
environment variables (.env file). No credentials in config.yaml.
"""

import json
import logging
import os
import smtplib
import time
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import requests
import yaml

from src.metrics import MetricsPackage

logger = logging.getLogger(__name__)


def _load_env() -> dict[str, str]:
    """Load environment variables, falling back to .env file parsing.

    Returns:
        Dict of environment variable name → value.
    """
    env = dict(os.environ)

    env_path = Path(".env")
    if env_path.exists():
        with open(env_path, "r") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key not in env and val:
                        env[key] = val
    return env


# ---------------------------------------------------------------------------
# Email distribution
# ---------------------------------------------------------------------------

def _build_email_body(pkg: MetricsPackage, cfg: dict[str, Any]) -> str:
    """Build an HTML email body with inline KPI summary.

    Args:
        pkg: MetricsPackage.
        cfg: Full configuration dict.

    Returns:
        HTML string for the email body.
    """
    fin = pkg.financial
    comm = pkg.commercial
    cust = pkg.customers
    rag = pkg.rag
    brand = cfg["report"]["brand"]

    rag_colours = {
        "Green": f"#{brand['green']}",
        "Amber": f"#{brand['amber']}",
        "Red":   f"#{brand['red']}",
    }

    kpis_html = ""
    kpis = [
        ("Revenue",       f"&pound;{fin.revenue_actual/1e6:.1f}M", rag.revenue.status),
        ("Gross Margin",  f"{fin.gross_margin_pct_actual*100:.1f}%", rag.gross_margin.status),
        ("EBITDA Margin", f"{fin.ebitda_margin_pct_actual*100:.1f}%", rag.ebitda_margin.status),
        ("ARR",           f"&pound;{cust.arr_actual/1e6:.1f}M", "Green"),
        ("Pipeline Cov.", f"{comm.pipeline_coverage_ratio:.1f}x", rag.pipeline_coverage.status),
        ("Churn Rate",    f"{cust.churn_rate_actual*100:.2f}%", rag.churn_rate.status),
    ]
    for label, value, status in kpis:
        bg = rag_colours.get(status, "#1B3A5C")
        kpis_html += f"""
        <td style="background:{bg};color:#fff;padding:10px 14px;text-align:center;border-radius:4px;">
            <div style="font-size:10px;opacity:.8;">{label}</div>
            <div style="font-size:18px;font-weight:bold;">{value}</div>
        </td>
        <td style="width:8px;"></td>"""

    return f"""
    <html><body style="font-family:Arial,sans-serif;color:#2D3748;max-width:700px;margin:auto;">
    <div style="background:#{brand['primary']};padding:24px 28px;border-radius:6px 6px 0 0;">
        <h2 style="color:#fff;margin:0;">{pkg.company_name}</h2>
        <p style="color:rgba(255,255,255,.75);margin:4px 0 0;">
            Board Performance Report — {pkg.report_period} | Strictly Confidential
        </p>
    </div>
    <div style="background:#F4F7FA;padding:20px 28px;">
        <table style="border-spacing:0;"><tr>{kpis_html}</tr></table>
        <p style="margin-top:18px;font-size:13px;line-height:1.6;">
            Please find attached the Board Report pack for <strong>{pkg.report_period}</strong>,
            comprising the PDF narrative report and the Excel data pack.
        </p>
        <p style="font-size:13px;line-height:1.6;">
            This report was generated automatically by the Board Report Generator pipeline
            and delivered at {__import__('datetime').datetime.now().strftime('%H:%M on %A %d %B %Y')}.
        </p>
        <hr style="border:none;border-top:1px solid #D1D5DB;margin:16px 0;">
        <p style="font-size:11px;color:#888;">
            This email and its attachments are intended solely for the named recipients.
            If you have received this in error, please delete it immediately and notify the sender.
        </p>
    </div>
    </body></html>"""


def send_email(
    pkg: MetricsPackage,
    pdf_path: Path,
    excel_path: Path,
    config_path: str = "config.yaml",
) -> bool:
    """Send the board report via SMTP email with PDF and Excel attachments.

    Args:
        pkg: MetricsPackage (for KPI summary in email body).
        pdf_path: Path to the PDF report.
        excel_path: Path to the Excel data pack.
        config_path: Path to configuration YAML.

    Returns:
        True if sent (or dry-run completed), False on delivery failure.
    """
    with open(config_path, "r") as fh:
        cfg = yaml.safe_load(fh)

    env = _load_env()
    smtp_host = env.get("SMTP_HOST", "")
    smtp_port = int(env.get("SMTP_PORT", "587"))
    smtp_user = env.get("SMTP_USER", "")
    smtp_password = env.get("SMTP_PASSWORD", "")
    from_addr = env.get("EMAIL_FROM", smtp_user)

    dist_cfg = cfg["distribution"]
    recipients = dist_cfg["email_recipients"]
    subject = dist_cfg["email_subject"].format(
        period=pkg.report_period,
        company=pkg.company_name,
    )

    if not all([smtp_host, smtp_user, smtp_password]):
        logger.warning(
            "SMTP credentials not set — email dry-run mode.\n"
            "  Subject: %s\n  Recipients: %s\n  Attachments: %s, %s",
            subject,
            ", ".join(recipients),
            pdf_path.name if pdf_path else "N/A",
            excel_path.name if excel_path else "N/A",
        )
        return True

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)

    html_body = _build_email_body(pkg, cfg)
    msg.attach(MIMEText(html_body, "html"))

    for attach_path in [pdf_path, excel_path]:
        if attach_path and attach_path.exists():
            with open(attach_path, "rb") as fh:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(fh.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{attach_path.name}"',
            )
            msg.attach(part)

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(from_addr, recipients, msg.as_string())
        logger.info("Email sent to %d recipients", len(recipients))
        return True
    except smtplib.SMTPException as exc:
        logger.error("Email delivery failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Slack distribution
# ---------------------------------------------------------------------------

def _build_slack_payload(
    pkg: MetricsPackage,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Build a Slack Block Kit payload with KPI summary.

    Args:
        pkg: MetricsPackage.
        cfg: Full configuration dict.

    Returns:
        Slack Block Kit payload dict.
    """
    fin = pkg.financial
    comm = pkg.commercial
    cust = pkg.customers
    rag = pkg.rag
    dist_cfg = cfg["distribution"]

    def rag_emoji(status: str) -> str:
        return {"Green": ":large_green_circle:", "Amber": ":large_yellow_circle:",
                "Red": ":red_circle:"}.get(status, ":white_circle:")

    kpi_lines = (
        f"{rag_emoji(rag.revenue.status)} *Revenue:* "
        f"£{fin.revenue_actual/1e6:.1f}M ({rag.revenue.variance_pct*100:+.1f}% vs budget)\n"
        f"{rag_emoji(rag.gross_margin.status)} *Gross Margin:* "
        f"{fin.gross_margin_pct_actual*100:.1f}%\n"
        f"{rag_emoji(rag.ebitda_margin.status)} *EBITDA Margin:* "
        f"{fin.ebitda_margin_pct_actual*100:.1f}%\n"
        f":chart_with_upwards_trend: *ARR:* £{cust.arr_actual/1e6:.1f}M "
        f"(net movement: £{cust.net_arr_movement/1000:+.0f}k)\n"
        f"{rag_emoji(rag.pipeline_coverage.status)} *Pipeline Coverage:* "
        f"{comm.pipeline_coverage_ratio:.1f}x\n"
        f"{rag_emoji(rag.churn_rate.status)} *Churn Rate:* "
        f"{cust.churn_rate_actual*100:.2f}% (budget: {cust.churn_rate_budget*100:.2f}%)\n"
        f":star: *NPS:* {cust.nps_actual} (target: {cust.nps_budget})"
    )

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f":bar_chart: Board Report — {pkg.report_period} | {pkg.company_name}",
                "emoji": True,
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": kpi_lines},
        },
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f":information_source: Board Report Generator v1.0 | "
                        f"Channel: {dist_cfg['slack_channel']} | "
                        "Full PDF and Excel pack delivered by email to board recipients."
                    ),
                }
            ],
        },
    ]

    return {
        "username": dist_cfg["slack_username"],
        "icon_emoji": dist_cfg["slack_icon_emoji"],
        "channel": dist_cfg["slack_channel"],
        "blocks": blocks,
    }


def send_slack_summary(
    pkg: MetricsPackage,
    config_path: str = "config.yaml",
) -> bool:
    """Post a KPI summary to Slack.

    Args:
        pkg: MetricsPackage.
        config_path: Path to configuration YAML.

    Returns:
        True if sent (or dry-run), False on failure.
    """
    with open(config_path, "r") as fh:
        cfg = yaml.safe_load(fh)

    env = _load_env()
    webhook_url = env.get("SLACK_WEBHOOK_URL", "").strip()

    payload = _build_slack_payload(pkg, cfg)

    if not webhook_url:
        logger.warning(
            "SLACK_WEBHOOK_URL not set — Slack dry-run mode.\n%s",
            json.dumps(payload, indent=2),
        )
        return True

    for attempt in range(1, 4):
        try:
            resp = requests.post(webhook_url, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info("Slack summary sent (attempt %d)", attempt)
                return True
            logger.warning("Slack returned %s (attempt %d)", resp.status_code, attempt)
        except requests.RequestException as exc:
            logger.warning("Slack request failed (attempt %d): %s", attempt, exc)
        if attempt < 3:
            time.sleep(2 ** attempt)

    logger.error("Slack delivery failed after 3 attempts")
    return False
