# Automated Board Report Generator

> **Turns raw financial data into a CFO-ready board pack — PDF narrative, Excel data pack, and interactive dashboard — every Monday morning, fully unattended.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![View Live Demo](https://img.shields.io/badge/View_Live_Demo-%E2%96%B6_Interactive_Dashboard-58a6ff?style=flat-square)](https://marwane019.github.io/board-report-generator/)

---

## The Problem

Every Monday morning, finance teams at UK mid-market companies spend 2–4 hours manually:

- Pulling numbers from multiple spreadsheets
- Writing the same commentary templates with different figures plugged in
- Formatting charts in PowerPoint
- Emailing the pack to 12 board members one attachment at a time

This project eliminates all of that with a single command.

---

## What It Produces

One `python main.py --full-run` generates three artefacts:

| Artefact | Format | Contents |
|----------|--------|----------|
| **Board Pack PDF** | 7-page ReportLab PDF | Cover page · Executive Summary + RAG Dashboard · Financial Performance · Commercial Pipeline · Customer Metrics · Operational · Outlook & Risk Register |
| **Data Pack** | 6-tab Excel workbook | Summary Dashboard · P&L (with conditional formatting) · Pipeline · Customers · Headcount · Data Dictionary |
| **Interactive Dashboard** | Self-contained HTML | 6 Plotly charts · RAG KPI tiles · No server required · Opens in any browser |

Then — if configured — it emails the PDF + Excel pack to your distribution list and posts a Block Kit summary to Slack.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     board-report-generator pipeline                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐  │
│  │  data_simulator  │───>│    metrics.py    │───>│   narrative.py   │  │
│  │                  │    │                  │    │                  │  │
│  │ 24-month P&L     │    │ Revenue vs budget│    │ Template-driven  │  │
│  │ Pipeline stages  │    │ EBITDA margin    │    │ RAG-conditional  │  │
│  │ ARR waterfall    │    │ Pipeline coverage│    │ commentary with  │  │
│  │ Headcount by     │    │ ARR growth       │    │ auto-populated   │  │
│  │   department     │    │ Churn rate       │    │ figures          │  │
│  │ NPS & churn      │    │ RAG status all   │    │                  │  │
│  └──────────────────┘    └──────────────────┘    └────────┬─────────┘  │
│                                                            │            │
│           ┌────────────────────────────────────────────────┤            │
│           │                    │                           │            │
│           v                    v                           v            │
│  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────────┐   │
│  │   pdf_builder    │ │   excel_pack     │ │     dashboard        │   │
│  │                  │ │                  │ │                      │   │
│  │ ReportLab Platypus│ │ openpyxl 6 tabs │ │ Plotly 6 charts      │   │
│  │ Embedded matplotlib│ │ Conditional fmt  │ │ RAG KPI header       │   │
│  │ charts (BytesIO) │ │ ColorScaleRule   │ │ Self-contained HTML  │   │
│  │ Running header + │ │ Auto-filter +    │ │ No server required   │   │
│  │ footer all pages │ │ freeze panes     │ │                      │   │
│  └────────┬─────────┘ └────────┬─────────┘ └──────────┬───────────┘   │
│           │                    │                       │               │
│           └────────────────────┴───────────────────────┘               │
│                                        │                               │
│                                        v                               │
│                          ┌──────────────────────┐                      │
│                          │     distributor       │                      │
│                          │                       │                      │
│                          │ SMTP email (PDF+Excel) │                     │
│                          │ Slack Block Kit post   │                     │
│                          │ Dry-run if unconfigured│                     │
│                          └──────────────────────┘                      │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  scheduler.py  │  APScheduler  │  Every Monday 06:00 London     │  │
│  │  n8n_workflow.json  │  Cron trigger + Slack alerts on outcome   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Quickstart (under 10 minutes)

### 1. Clone and set up

```bash
git clone https://github.com/marwane019/board-report-generator.git
cd board-report-generator

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Create output directories

```bash
mkdir -p data/raw data/processed outputs/pdf outputs/excel outputs/dashboard logs
```

### 3. (Optional) Configure email and Slack

```bash
cp .env.example .env
# Edit .env and add your SMTP credentials and Slack webhook URL
```

If you skip this step, the pipeline runs in dry-run mode — it generates all files but doesn't send anything.

### 4. Run the full pipeline

```bash
python main.py --full-run
```

You'll see structured log output like this:

```
2024-01-15 06:00:01 | INFO     | main          | ── Stage 1/7: Generating synthetic financial data
2024-01-15 06:00:02 | INFO     | data_simulator| Generated 24-month P&L dataset (288 rows)
2024-01-15 06:00:02 | INFO     | main          | ── Stage 2/7: Computing KPI metrics
2024-01-15 06:00:02 | INFO     | metrics       | Revenue vs budget: 97.3% (RAG: AMBER)
2024-01-15 06:00:02 | INFO     | metrics       | EBITDA margin: 18.4% (RAG: GREEN)
2024-01-15 06:00:02 | INFO     | metrics       | Pipeline coverage: 3.2x (RAG: GREEN)
2024-01-15 06:00:03 | INFO     | main          | ── Stage 3/7: Generating board narrative
2024-01-15 06:00:03 | INFO     | main          | ── Stage 4/7: Building PDF report
2024-01-15 06:00:05 | INFO     | pdf_builder   | PDF written → outputs/pdf/board_report_2024_W03.pdf (7 pages)
2024-01-15 06:00:05 | INFO     | main          | ── Stage 5/7: Building Excel data pack
2024-01-15 06:00:06 | INFO     | excel_pack    | Excel written → outputs/excel/board_data_pack_2024_W03.xlsx (6 sheets)
2024-01-15 06:00:06 | INFO     | main          | ── Stage 6/7: Building interactive dashboard
2024-01-15 06:00:07 | INFO     | dashboard     | Dashboard written → outputs/dashboard/dashboard_2024_W03.html
2024-01-15 06:00:07 | INFO     | main          | ── Stage 7/7: Distributing board pack
2024-01-15 06:00:07 | INFO     | distributor   | [DRY RUN] Email — would send to 3 recipients
2024-01-15 06:00:07 | INFO     | distributor   | [DRY RUN] Slack — board summary (no webhook configured)
2024-01-15 06:00:07 | INFO     | main          | Pipeline complete in 6.1s
```

### 5. Open your outputs

```bash
# Interactive dashboard (open in browser)
start outputs/dashboard/dashboard_2024_W03.html   # Windows
open outputs/dashboard/dashboard_2024_W03.html    # macOS

# Board pack PDF
start outputs/pdf/board_report_2024_W03.pdf       # Windows
```

---

## CLI Reference

```
python main.py [OPTIONS]

Pipeline stages:
  --full-run          Run all 7 stages end-to-end (default)
  --generate-data     Stage 1: Generate/refresh synthetic financial data only
  --report            Stage 4: Regenerate PDF from existing metrics (requires --generate-data first)
  --excel             Stage 5: Regenerate Excel pack only
  --dashboard         Stage 6: Regenerate HTML dashboard only
  --distribute        Stage 7: Re-send distribution (email + Slack) only

Configuration:
  --config FILE       Path to config YAML (default: config.yaml)
  --log-level LEVEL   DEBUG / INFO / WARNING (default: INFO)

Examples:
  python main.py --full-run
  python main.py --full-run --log-level DEBUG
  python main.py --dashboard --config staging.yaml
  python main.py --distribute
```

---

## Project Structure

```
board-report-generator/
├── config.yaml                 # Master configuration (company, KPIs, RAG thresholds)
├── .env.example                # Environment variable template
├── main.py                     # CLI entry point and pipeline orchestrator
├── scheduler.py                # APScheduler weekly daemon
├── requirements.txt
├── n8n_workflow.json           # Import into n8n for cron + alerting
│
├── src/
│   ├── __init__.py
│   ├── data_simulator.py       # Synthetic 24-month financial dataset generator
│   ├── metrics.py              # KPI engine with RAG classification
│   ├── narrative.py            # Template-based board commentary generator
│   ├── pdf_builder.py          # 7-page ReportLab PDF with embedded charts
│   ├── excel_pack.py           # 6-tab openpyxl workbook with formatting
│   ├── dashboard.py            # 6-chart Plotly self-contained HTML dashboard
│   └── distributor.py          # SMTP email + Slack Block Kit distribution
│
├── templates/
│   └── narrative.yaml          # Commentary templates (RAG-conditional variants)
│
├── tests/
│   ├── __init__.py
│   ├── test_metrics.py         # 17 unit tests for KPI engine and RAG logic
│   └── test_narrative.py       # 13 unit tests for narrative generation
│
├── data/
│   ├── raw/                    # Generated CSV datasets (gitignored)
│   └── processed/              # Intermediate outputs (gitignored)
│
└── outputs/
    ├── pdf/                    # Generated PDFs (gitignored)
    ├── excel/                  # Generated Excel packs (gitignored)
    └── dashboard/              # Generated HTML dashboards (gitignored)
```

---

## Configuration Reference

All configuration lives in `config.yaml`. No values are hardcoded.

### Company profile

```yaml
company:
  name: "Acme Group plc"
  reporting_currency: "GBP"
  annual_revenue_budget: 18_500_000
  growth_rate: 0.14
  revenue_mix:
    saas: 0.55          # Recurring software licences
    professional_services: 0.28
    support_maintenance: 0.17
```

### RAG thresholds

```yaml
rag_thresholds:
  revenue_vs_budget:
    green: 0.98         # >= 98% of budget
    amber: 0.93         # >= 93% of budget (else RED)
  ebitda_margin:
    green: 0.15         # >= 15%
    amber: 0.10         # >= 10% (else RED)
  pipeline_coverage:
    green: 3.0          # >= 3x quarterly revenue target
    amber: 2.0          # >= 2x (else RED)
  arr_growth:
    green: 0.10         # >= 10% YoY
    amber: 0.05         # >= 5% (else RED)
  churn_rate:
    green: 0.05         # <= 5% (lower is better)
    amber: 0.08         # <= 8% (else RED)
```

### Scheduler

```yaml
scheduler:
  run_day_of_week: "mon"
  run_time: "06:00"
  timezone: "Europe/London"
  max_retries: 3
  retry_delay_seconds: 300
```

### Distribution

```yaml
distribution:
  email:
    recipients:
      - "cfo@example.com"
      - "ceo@example.com"
      - "board@example.com"
    subject_template: "Board Report — Week {week_number} | {company_name}"
  slack:
    channel: "#board-reporting"
```

---

## KPI Metrics

| KPI | Description | RAG Logic |
|-----|-------------|-----------|
| **Revenue vs Budget** | Actual YTD / Budget YTD | Green ≥ 98% · Amber ≥ 93% · Red < 93% |
| **EBITDA Margin** | EBITDA / Revenue (latest month) | Green ≥ 15% · Amber ≥ 10% · Red < 10% |
| **Gross Margin** | Gross Profit / Revenue (latest month) | Green ≥ 65% · Amber ≥ 55% · Red < 55% |
| **Pipeline Coverage** | Total pipeline / (quarterly target × 3) | Green ≥ 3× · Amber ≥ 2× · Red < 2× |
| **ARR Growth** | ARR YoY change | Green ≥ 10% · Amber ≥ 5% · Red < 5% |
| **Churn Rate** | Churned ARR / Opening ARR (LTM) | Green ≤ 5% · Amber ≤ 8% · Red > 8% |
| **Headcount vs Budget** | Actual FTE / Budget FTE | Green ≤ 100% · Amber ≤ 105% · Red > 105% |
| **NPS Score** | Latest monthly NPS | Green ≥ 40 · Amber ≥ 25 · Red < 25 |

---

## PDF Report: Page-by-Page

| Page | Title | Contents |
|------|-------|----------|
| 1 | Cover | Company name · Report date · "Strictly Confidential" watermark |
| 2 | Executive Summary | 200-word RAG-conditional narrative · 8-KPI RAG status table |
| 3 | Financial Performance | Revenue vs budget grouped bar + EBITDA margin line · Gross margin trend chart · YTD commentary |
| 4 | Commercial Pipeline | Pipeline by stage (stacked bar) · Coverage ratio · Win rate · Stage commentary |
| 5 | Customer Metrics | ARR waterfall trend · Churn + NPS dual-axis · ARR commentary |
| 6 | Operational | Headcount by department grouped bar · Productivity commentary |
| 7 | Outlook & Risks | 12-month outlook narrative · 4-row risk register (Risk · Owner · Likelihood · Mitigation) |

---

## Excel Pack: Sheet-by-Sheet

| Sheet | Contents |
|-------|----------|
| **Summary** | RAG-colour KPI tile dashboard · All 8 KPIs with status, value, and threshold |
| **P&L** | Full 24-month P&L · Actual / Budget / Prior Year columns · Variance column with ColorScaleRule conditional formatting |
| **Pipeline** | Weekly pipeline by stage · Coverage ratio trend · Win rate |
| **Customers** | Monthly ARR waterfall · Churn rate · NPS trend |
| **Headcount** | Monthly headcount by department · Vacancy analysis |
| **Data Dictionary** | Column definitions for all datasets · Unit / data type · Source |

---

## Dashboard: Chart Inventory

| Chart | Type | Key insight |
|-------|------|-------------|
| Revenue vs Budget | Grouped bar + EBITDA line (dual y-axis) | Monthly performance vs plan |
| EBITDA & Gross Margin | Dual line with threshold markers | Profitability trend |
| Pipeline Waterfall | Plotly Waterfall | Stage-by-stage pipeline movement |
| ARR Trend | Area + budget reference line | Recurring revenue trajectory |
| Headcount | Grouped bar by department | Capacity vs plan |
| Churn + NPS | Dual-axis line + scatter | Customer health composite |

---

## Scheduling

### Option A: APScheduler daemon

```bash
# Start the weekly scheduler (blocking, Monday 06:00 London time)
python scheduler.py

# Run immediately (one shot, for testing)
python scheduler.py --run-now

# Custom config
python scheduler.py --config /path/to/config.yaml
```

### Option B: System cron

```cron
# /etc/cron.d/board-report
0 6 * * 1 /opt/board-report-generator/.venv/bin/python /opt/board-report-generator/main.py --full-run >> /var/log/board-report.log 2>&1
```

### Option C: n8n workflow

1. Open your n8n instance
2. Import `n8n_workflow.json`
3. Set environment variables: `SLACK_WEBHOOK_URL`, `SLACK_EXEC_WEBHOOK_URL`
4. Activate the workflow

The n8n workflow adds:
- Slack success notification after each run
- Slack failure alert with last 500 chars of stderr
- Separate executive Slack alert when any KPI is RED

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SMTP_HOST` | Optional | SMTP server hostname (e.g. `smtp.gmail.com`) |
| `SMTP_PORT` | Optional | SMTP port (default: `587`) |
| `SMTP_USER` | Optional | SMTP username / email address |
| `SMTP_PASSWORD` | Optional | SMTP password or app password |
| `SMTP_FROM` | Optional | From address (defaults to `SMTP_USER`) |
| `SLACK_WEBHOOK_URL` | Optional | Incoming webhook URL for ops channel |
| `SLACK_EXEC_WEBHOOK_URL` | Optional | Separate webhook for executive RED alerts |

All optional — omitting them enables dry-run mode (files generated, nothing sent).

---

## Running Tests

```bash
# All tests
pytest tests/ -v

# With coverage report
pytest tests/ -v --cov=src --cov-report=term-missing

# Specific test class
pytest tests/test_metrics.py::TestComputeMetricsIntegration -v
```

Expected output:

```
tests/test_metrics.py::TestRagHigherIsBetter::test_above_green_threshold PASSED
tests/test_metrics.py::TestRagHigherIsBetter::test_exactly_at_green_threshold PASSED
...
tests/test_narrative.py::TestNarrativeGeneration::test_generate_narrative_returns_package PASSED

=================== 30 passed in 3.21s ===================
```

---

## Tech Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| Data simulation | pandas + NumPy (seed=42) | Reproducible, realistic multi-dataset generation |
| KPI engine | Pure Python dataclasses | Typed, testable, zero ORM overhead |
| Narrative | YAML templates + string formatting | Non-technical users can edit copy without touching code |
| PDF generation | ReportLab Platypus | Pure Python, no headless browser, no system deps — runs anywhere |
| Chart embedding | matplotlib (Agg) → BytesIO | Zero temp files, no display required, deterministic output |
| Excel | openpyxl | Full formatting control; no Excel installation required |
| Dashboard | Plotly (offline) | Self-contained HTML — shareable without a server |
| Distribution | smtplib + requests | No third-party email SDK; works with any SMTP relay |
| Scheduling | APScheduler | Python-native cron; timezone-aware; no system cron required |
| Orchestration | n8n | Visual workflow with conditional Slack alerting |
| Configuration | PyYAML | Human-readable, version-controlled, no env var clutter |
| Logging | Python logging + RotatingFileHandler | Structured, persistent, production-grade |

**Deliberately excluded:**

| Technology | Reason |
|------------|--------|
| Django / FastAPI | No HTTP interface needed — this is a CLI pipeline tool |
| Celery | APScheduler is sufficient; Celery adds Redis/RabbitMQ dependency |
| SQLAlchemy | Flat files are appropriate for this data volume and use case |
| Docker | Kept scope portable; a Dockerfile would be a trivial addition |
| Sphinx | Inline docstrings preferred over generated docs for this project size |

---

## Scalability Roadmap

This project is architected to grow in 5 phases:

**Phase 1 (current): Local CLI**
- Single-machine execution
- Synthetic dataset
- File-based outputs

**Phase 2: Real data connectors**
- Replace `data_simulator.py` with adapters for your ERP/CRM (Salesforce, Xero, NetSuite)
- Each adapter returns the same DataFrame schema — pipeline unchanged

**Phase 3: Cloud storage**
- Write outputs to Azure Blob / S3 instead of local filesystem
- Email links instead of attachments for large files

**Phase 4: BI platform integration**
- Push processed metrics to Power BI dataset via REST API
- Dashboard becomes an embedded Power BI report

**Phase 5: ML augmentation**
- Add forecast module: Prophet for revenue, ARIMA for pipeline
- Replace static templates with LLM-generated commentary (Claude API)
- Anomaly detection on KPI movements (links to cost-leakage-detector architecture)

---

## Related Projects

- [**Operations Cost Leakage Detector**](https://github.com/marwane019/cost-leakage-detector) — Multi-rule anomaly detection engine for procurement/ops data. Companion project: while this system reports on what happened, the leakage detector alerts on what shouldn't have happened.
- [**AutoReport**](https://github.com/marwane019/autoreport) — Automated KPI reporting pipeline (upstream project in this portfolio series).

---

## Licence

MIT — use freely, attribution appreciated.

---

*Built as part of a portfolio demonstrating end-to-end automation of enterprise reporting workflows in Python.*
