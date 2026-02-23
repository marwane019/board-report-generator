"""
board-report-generator — Source package.

Modules:
    data_simulator  — 24-month synthetic financial dataset (P&L, pipeline, headcount, customers)
    metrics         — KPI calculation engine with RAG status
    narrative       — Template-based board commentary generator
    pdf_builder     — ReportLab PDF: cover + narrative + embedded charts
    excel_pack      — Multi-tab openpyxl Excel data pack
    dashboard       — Interactive Plotly HTML dashboard
    distributor     — Email (SMTP) + Slack distribution
"""
