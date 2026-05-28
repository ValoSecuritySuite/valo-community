"""Executive KPI PDF generator.

Builds a boardroom-grade KPI deliverable from
:class:`app.schemas.ExecutiveSummary` plus
:class:`app.schemas.ExecutiveTrends`, mirroring the navy branding of
:mod:`app.services.pdf_report_generator` (cover page, branded header
and footer, brand palette) but tailored to portfolio-level metrics
rather than per-scan findings.

The layout follows widely-used CISO board reporting guidance:

* Cover with company brand and trailing window
* Executive Summary: one-paragraph posture headline plus 2x2 KPI tiles
  with period-over-period delta arrows
* Recommended Actions (auto-derived from coverage and exposure)
* Trends: line chart of requests / blocked / actions and a numeric
  period-over-period table
* Exposure: bar charts of decisions and direction with the top
  blocking policy callout
* Risk: severity pie chart and Top Offenders table
* Automation: MTTA delta plus actions-by-type bar chart
* Coverage and Compliance: control inventory and per-tag rollup
* Appendix: methodology and window definitions
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Optional
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    Image,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.core.logging import get_logger
from app.schemas import ExecutiveSummary, ExecutiveTrends
from app.services.pdf_report_generator import (
    _BLUE,
    _BLUE_LIGHT,
    _DARK_GRAY,
    _LIGHT_GRAY,
    _MID_GRAY,
    _NAVY,
    _SEV_COLORS,
    _make_styles,
)

logger = get_logger(__name__)

_BRAND_NAME = "Valo"
_REPORT_TITLE = "Executive KPI Report"
_REPORT_SUBTITLE = "Portfolio-level posture, exposure, and automation"
_CONFIDENTIAL = "CONFIDENTIAL: Executive KPI Report"

_GLYPH_UP = "\u25B2"
_GLYPH_DOWN = "\u25BC"
_GLYPH_FLAT = "="

_DELTA_GREEN_HEX = "#15803D"
_DELTA_RED_HEX = "#B91C1C"
_DELTA_GRAY_HEX = "#64748B"

_SERIES_COLORS = {
    "requests": colors.HexColor("#1E40AF"),
    "blocked": colors.HexColor("#B91C1C"),
    "actions_executed": colors.HexColor("#0E7490"),
    "playbooks_fired": colors.HexColor("#7C3AED"),
}

_SEV_ORDER = ("info", "low", "medium", "high", "critical")
_SEV_NUMERIC = {"info": 1, "low": 2, "medium": 3, "high": 4, "critical": 5}


# ── Public API ───────────────────────────────────────────────────────────────


def generate_kpi_pdf(
    current: ExecutiveSummary,
    prior: ExecutiveSummary,
    trend: ExecutiveTrends,
    *,
    company_name: Optional[str] = None,
    logo_bytes: Optional[bytes] = None,
) -> bytes:
    """Render the Executive KPI report and return the PDF bytes."""
    buf = io.BytesIO()
    st = _make_styles()
    timestamp_str = current.generated_at.astimezone(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    page_w, page_h = A4
    cover_frame = Frame(
        0,
        0,
        page_w,
        page_h,
        leftPadding=18 * mm,
        rightPadding=18 * mm,
        topPadding=0,
        bottomPadding=15 * mm,
        id="cover",
    )
    body_frame = Frame(
        0,
        0,
        page_w,
        page_h,
        leftPadding=18 * mm,
        rightPadding=18 * mm,
        topPadding=32 * mm,
        bottomPadding=18 * mm,
        id="body",
    )

    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        title=f"{_BRAND_NAME} {_REPORT_TITLE}",
        author=_BRAND_NAME,
        pageTemplates=[
            PageTemplate(
                id="cover",
                frames=[cover_frame],
                onPage=_make_cover_cb(current, timestamp_str),
            ),
            PageTemplate(
                id="body",
                frames=[body_frame],
                onPage=_make_page_cb(current, timestamp_str),
            ),
        ],
    )

    logo_flow: Optional[Image] = None
    if logo_bytes:
        try:
            logo_flow = _build_logo_flowable(
                logo_bytes, max_w=24 * mm, max_h=24 * mm
            )
        except Exception:
            logger.warning("invalid logo_bytes for kpi pdf; ignoring")
            logo_flow = None

    story: list = []
    story += _cover(current, st, company_name, logo_flow)
    story += _executive_summary_section(current, prior, st)
    story += _recommended_actions(current, st)
    story.append(PageBreak())
    story += _trends_section(current, prior, trend, st)
    story.append(PageBreak())
    story += _exposure_section(current, st)
    story.append(PageBreak())
    story += _risk_section(current, st)
    story.append(PageBreak())
    story += _automation_section(current, prior, st)
    story.append(PageBreak())
    story += _coverage_compliance_section(current, st)
    story.append(PageBreak())
    story += _appendix(current, st)

    doc.build(story)
    return buf.getvalue()


# ── Page callbacks ───────────────────────────────────────────────────────────


def _make_cover_cb(summary: ExecutiveSummary, timestamp: str):
    """Canvas callback for the navy full-bleed cover."""

    def _draw(canvas, doc):  # noqa: ANN001
        w, h = A4
        canvas.saveState()
        canvas.setFillColor(_NAVY)
        canvas.rect(0, 0, w, h, fill=1, stroke=0)
        canvas.setFillColor(_BLUE_LIGHT)
        canvas.rect(0, h * 0.42, w, 3, fill=1, stroke=0)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#475569"))
        canvas.drawString(18 * mm, 10 * mm, _CONFIDENTIAL)
        canvas.drawRightString(
            w - 18 * mm,
            10 * mm,
            f"Generated: {timestamp}  |  Window: {summary.window}",
        )
        canvas.restoreState()

    return _draw


def _make_page_cb(summary: ExecutiveSummary, timestamp: str):
    """Canvas callback that paints the branded header + footer on every body page."""

    def _draw(canvas, doc):  # noqa: ANN001
        w, h = A4
        canvas.saveState()

        canvas.setFillColor(colors.white)
        canvas.rect(0, 0, w, h, fill=1, stroke=0)

        canvas.setFillColor(_NAVY)
        canvas.rect(0, h - 28 * mm, w, 28 * mm, fill=1, stroke=0)
        canvas.setFillColor(_BLUE_LIGHT)
        canvas.rect(0, h - 30 * mm, w, 2 * mm, fill=1, stroke=0)

        canvas.setFont("Helvetica-Bold", 11)
        canvas.setFillColor(colors.white)
        canvas.drawString(18 * mm, h - 16 * mm, _REPORT_TITLE)

        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#93C5FD"))
        canvas.drawRightString(
            w - 18 * mm, h - 12 * mm, f"Window: {summary.window}"
        )
        canvas.drawRightString(w - 18 * mm, h - 18 * mm, timestamp)

        canvas.setFillColor(_LIGHT_GRAY)
        canvas.rect(0, 0, w, 14 * mm, fill=1, stroke=0)
        canvas.setStrokeColor(_MID_GRAY)
        canvas.setLineWidth(0.5)
        canvas.line(18 * mm, 14 * mm, w - 18 * mm, 14 * mm)

        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(18 * mm, 5 * mm, _CONFIDENTIAL)
        canvas.drawRightString(w - 18 * mm, 5 * mm, f"Page {doc.page}")

        canvas.restoreState()

    return _draw


# ── Section: cover ───────────────────────────────────────────────────────────


def _cover(
    summary: ExecutiveSummary,
    st: dict,
    company_name: Optional[str],
    logo_flow: Optional[Image],
) -> list:
    story: list = []

    if logo_flow or company_name:
        story.append(Spacer(1, 16 * mm))
        if logo_flow is not None:
            story.append(logo_flow)
            story.append(Spacer(1, 2 * mm))
        if company_name:
            story.append(
                Paragraph(
                    f"Prepared for {escape(company_name)}",
                    st["cover_company"],
                )
            )
        story.append(Spacer(1, 24 * mm))
    else:
        story.append(Spacer(1, 68 * mm))

    story.append(
        Paragraph(
            f'<font color="#3B82F6">&#9632;</font>  '
            f'<font color="#93C5FD">{_BRAND_NAME}</font>',
            ParagraphStyle(
                "kpi_brand",
                fontName="Helvetica-Bold",
                fontSize=11,
                textColor=colors.HexColor("#93C5FD"),
                leading=14,
            ),
        )
    )
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(_REPORT_TITLE, st["cover_title"]))
    story.append(Paragraph(_REPORT_SUBTITLE, st["cover_sub"]))

    window_label = (
        f"Trailing {summary.window}: "
        f"{summary.window_start.strftime('%Y-%m-%d %H:%M UTC')} to "
        f"{summary.window_end.strftime('%Y-%m-%d %H:%M UTC')}"
    )
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(window_label, st["cover_meta"]))

    story.append(Spacer(1, 10 * mm))
    story.append(
        HRFlowable(
            width="100%",
            thickness=0.5,
            color=colors.HexColor("#1E3A5F"),
            spaceAfter=8,
        )
    )

    block_rate_pct = summary.exposure.block_rate * 100
    blocked = summary.exposure.blocked
    crit = summary.risk.critical_findings
    avg_risk = summary.risk.average_risk_score

    meta = [
        [
            Paragraph(
                f'<b><font color="#93C5FD">Blocked</font></b><br/>'
                f'<font color="#E2E8F0">{blocked:,} ({block_rate_pct:.1f}%)</font>',
                st["cover_meta"],
            ),
            Paragraph(
                f'<b><font color="#93C5FD">Critical findings</font></b><br/>'
                f'<font color="#E2E8F0">{crit:,}</font>',
                st["cover_meta"],
            ),
            Paragraph(
                f'<b><font color="#93C5FD">Avg risk score</font></b><br/>'
                f'<font color="#E2E8F0">{avg_risk:.1f}/100</font>',
                st["cover_meta"],
            ),
        ]
    ]
    meta_tbl = Table(meta, colWidths=["33%", "33%", "34%"])
    meta_tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(meta_tbl)

    story.append(NextPageTemplate("body"))
    story.append(PageBreak())
    return story


# ── Section: executive summary + recommended actions ─────────────────────────


def _executive_summary_section(
    current: ExecutiveSummary, prior: ExecutiveSummary, st: dict
) -> list:
    story: list = []
    story.append(Paragraph("Executive Summary", st["h1"]))
    story.append(
        HRFlowable(width="100%", thickness=1, color=_BLUE_LIGHT, spaceAfter=6)
    )

    headline = _compose_headline(current, prior)
    story.append(Paragraph(headline, st["body"]))
    story.append(Spacer(1, 4 * mm))

    block_rate_pct = current.exposure.block_rate * 100
    prior_block_rate_pct = prior.exposure.block_rate * 100

    tile_block = _kpi_tile(
        label="Block rate",
        value=f"{block_rate_pct:.2f}%",
        delta=_format_delta_pp(block_rate_pct, prior_block_rate_pct),
        st=st,
    )
    tile_risk = _kpi_tile(
        label="Avg risk score",
        value=f"{current.risk.average_risk_score:.1f}/100",
        delta=_format_delta(
            current.risk.average_risk_score,
            prior.risk.average_risk_score,
            invert=True,
        ),
        st=st,
    )
    tile_crit = _kpi_tile(
        label="Critical findings",
        value=f"{current.risk.critical_findings:,}",
        delta=_format_delta(
            current.risk.critical_findings,
            prior.risk.critical_findings,
            invert=True,
        ),
        st=st,
    )
    tile_mtta = _kpi_tile(
        label="Mean time-to-action",
        value=_format_ms(current.automation.mean_time_to_action_ms),
        delta=_format_delta(
            current.automation.mean_time_to_action_ms,
            prior.automation.mean_time_to_action_ms,
            invert=True,
        ),
        st=st,
    )

    grid = Table(
        [[tile_block, tile_risk], [tile_crit, tile_mtta]],
        colWidths=["50%", "50%"],
    )
    grid.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(grid)
    return story


def _recommended_actions(current: ExecutiveSummary, st: dict) -> list:
    story: list = []
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Recommended Actions", st["h2"]))
    actions = _derive_actions(current)
    for action in actions:
        story.append(Paragraph(f"&#8226;  {escape(action)}", st["recommend_body"]))
    return story


# ── Section: trends ──────────────────────────────────────────────────────────


def _trends_section(
    current: ExecutiveSummary,
    prior: ExecutiveSummary,
    trend: ExecutiveTrends,
    st: dict,
) -> list:
    story: list = []
    story.append(Paragraph("Trends", st["h1"]))
    story.append(
        HRFlowable(width="100%", thickness=1, color=_BLUE_LIGHT, spaceAfter=6)
    )
    story.append(
        Paragraph(
            f"Time series across the {trend.window} window, bucketed by "
            f"{trend.bucket}. Each line shows volume per bucket; the table "
            f"below compares totals against the prior {trend.window} period.",
            st["body"],
        )
    )

    chart = _build_trend_chart(trend)
    if chart is not None:
        story.append(chart)
    else:
        story.append(
            Paragraph(
                "No trend data is available for this window yet.",
                st["body_sm"],
            )
        )
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph("Period over period", st["h2"]))

    rows: list = [
        [
            Paragraph(s, st["tbl_header"])
            for s in (
                "Metric",
                f"Current ({current.window})",
                "Prior period",
                "Delta",
            )
        ]
    ]
    metric_rows = [
        ("Total requests", current.exposure.total_requests, prior.exposure.total_requests, _fmt_int, False),
        ("Blocked", current.exposure.blocked, prior.exposure.blocked, _fmt_int, False),
        ("Block rate", current.exposure.block_rate, prior.exposure.block_rate, _fmt_pct, False),
        ("Critical findings", current.risk.critical_findings, prior.risk.critical_findings, _fmt_int, True),
        ("Average risk score", current.risk.average_risk_score, prior.risk.average_risk_score, _fmt_score, True),
        ("Playbooks fired", current.automation.playbooks_fired, prior.automation.playbooks_fired, _fmt_int, False),
        ("Actions executed", current.automation.actions_executed, prior.automation.actions_executed, _fmt_int, False),
        ("Mean time-to-action", current.automation.mean_time_to_action_ms, prior.automation.mean_time_to_action_ms, _fmt_ms, True),
    ]
    for label, curr_val, prior_val, fmt, invert in metric_rows:
        rows.append(
            [
                Paragraph(label, st["tbl_cell"]),
                Paragraph(fmt(curr_val), st["tbl_cell_center"]),
                Paragraph(fmt(prior_val), st["tbl_cell_center"]),
                Paragraph(_delta_html(curr_val, prior_val, invert=invert), st["tbl_cell_center"]),
            ]
        )

    tbl = Table(rows, colWidths=["35%", "22%", "22%", "21%"], hAlign="LEFT")
    tbl.setStyle(_table_style())
    story.append(tbl)
    return story


def _build_trend_chart(trend: ExecutiveTrends) -> Optional[Drawing]:
    metrics_to_plot = ("requests", "blocked", "actions_executed")
    selected = [
        s for s in trend.series if s.metric in metrics_to_plot and s.points
    ]
    if not selected:
        return None

    series_data: list[list[tuple[float, float]]] = []
    series_names: list[str] = []
    for s in selected:
        pts = [(float(p.bucket_start.timestamp()), float(p.value)) for p in s.points]
        series_data.append(pts)
        series_names.append(s.metric)

    drawing_w = 480
    drawing_h = 230
    drawing = Drawing(drawing_w, drawing_h)

    plot = LinePlot()
    plot.x = 50
    plot.y = 40
    plot.width = drawing_w - 70
    plot.height = drawing_h - 80
    plot.data = series_data
    plot.lines.strokeWidth = 1.5

    for i, name in enumerate(series_names):
        plot.lines[i].strokeColor = _SERIES_COLORS.get(name, colors.gray)

    bucket = trend.bucket

    def _x_label(value: float) -> str:
        try:
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return ""
        if bucket == "1d":
            return dt.strftime("%m-%d")
        if bucket == "1h":
            return dt.strftime("%m-%d %Hh")
        return dt.strftime("%H:%M")

    plot.xValueAxis.labels.fontSize = 7
    plot.xValueAxis.labels.fontName = "Helvetica"
    plot.xValueAxis.labels.fillColor = _DARK_GRAY
    plot.xValueAxis.strokeColor = _MID_GRAY
    plot.xValueAxis.labelTextFormat = _x_label
    plot.xValueAxis.visibleGrid = False

    plot.yValueAxis.labels.fontSize = 7
    plot.yValueAxis.labels.fontName = "Helvetica"
    plot.yValueAxis.labels.fillColor = _DARK_GRAY
    plot.yValueAxis.strokeColor = _MID_GRAY
    plot.yValueAxis.visibleGrid = True
    plot.yValueAxis.gridStrokeColor = _LIGHT_GRAY
    plot.yValueAxis.gridStrokeWidth = 0.5
    plot.yValueAxis.valueMin = 0

    drawing.add(plot)

    legend_y = drawing_h - 18
    legend_x = 50
    for name in series_names:
        col = _SERIES_COLORS.get(name, colors.gray)
        drawing.add(Rect(legend_x, legend_y, 10, 8, fillColor=col, strokeColor=col))
        drawing.add(
            String(
                legend_x + 14,
                legend_y + 1,
                name.replace("_", " "),
                fontSize=8,
                fontName="Helvetica",
                fillColor=_DARK_GRAY,
            )
        )
        legend_x += 130

    return drawing


# ── Section: exposure ────────────────────────────────────────────────────────


def _exposure_section(current: ExecutiveSummary, st: dict) -> list:
    story: list = []
    story.append(Paragraph("Exposure", st["h1"]))
    story.append(
        HRFlowable(width="100%", thickness=1, color=_BLUE_LIGHT, spaceAfter=6)
    )

    exp = current.exposure
    story.append(
        Paragraph(
            f"Across {exp.total_requests:,} requests, {exp.blocked:,} were blocked "
            f"({exp.block_rate * 100:.2f}%) and {exp.would_block:,} additional "
            f"requests would have been blocked under enforcement.",
            st["body"],
        )
    )
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("Decisions", st["h2"]))
    chart_decisions = _build_horizontal_bar(exp.by_decision, color=_BLUE)
    if chart_decisions is not None:
        story.append(chart_decisions)
    else:
        story.append(
            Paragraph(
                "No decisions recorded for this window.", st["body_sm"]
            )
        )

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Direction", st["h2"]))
    chart_dir = _build_horizontal_bar(
        exp.by_direction, color=colors.HexColor("#0E7490")
    )
    if chart_dir is not None:
        story.append(chart_dir)
    else:
        story.append(
            Paragraph(
                "No direction telemetry recorded for this window.",
                st["body_sm"],
            )
        )

    if exp.top_blocking_policy_id:
        share = (
            exp.top_blocking_policy_count / exp.blocked
            if exp.blocked > 0
            else 0.0
        )
        story.append(Spacer(1, 4 * mm))
        story.append(
            Paragraph(
                f"<b>Top blocking policy:</b> "
                f"{escape(exp.top_blocking_policy_id)} "
                f"({exp.top_blocking_policy_count:,} blocks, "
                f"{share * 100:.0f}% share).",
                st["body"],
            )
        )
    return story


def _build_horizontal_bar(
    data: dict, color: colors.Color
) -> Optional[Drawing]:
    if not data:
        return None
    items = sorted(
        ((str(k), int(v)) for k, v in data.items() if int(v) > 0),
        key=lambda kv: kv[1],
        reverse=True,
    )[:10]
    if not items:
        return None

    labels = [k for k, _ in items]
    values = [v for _, v in items]
    n = len(items)

    drawing_w = 480
    drawing_h = max(80, 30 + n * 24)
    drawing = Drawing(drawing_w, drawing_h)

    chart = HorizontalBarChart()
    chart.x = 130
    chart.y = 15
    chart.width = drawing_w - 170
    chart.height = drawing_h - 30
    chart.data = [values]
    chart.categoryAxis.categoryNames = labels
    chart.categoryAxis.labels.fontSize = 8
    chart.categoryAxis.labels.fontName = "Helvetica"
    chart.categoryAxis.labels.fillColor = _DARK_GRAY
    chart.categoryAxis.labels.boxAnchor = "e"
    chart.categoryAxis.strokeColor = _MID_GRAY
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.labels.fontName = "Helvetica"
    chart.valueAxis.labels.fillColor = _DARK_GRAY
    chart.valueAxis.valueMin = 0
    chart.valueAxis.strokeColor = _MID_GRAY
    chart.valueAxis.visibleGrid = True
    chart.valueAxis.gridStrokeColor = _LIGHT_GRAY
    chart.valueAxis.gridStrokeWidth = 0.5
    chart.bars[0].fillColor = color
    chart.bars[0].strokeColor = color
    chart.barWidth = 12
    chart.groupSpacing = 6
    chart.barSpacing = 2

    drawing.add(chart)
    return drawing


# ── Section: risk ────────────────────────────────────────────────────────────


def _risk_section(current: ExecutiveSummary, st: dict) -> list:
    story: list = []
    story.append(Paragraph("Risk", st["h1"]))
    story.append(
        HRFlowable(width="100%", thickness=1, color=_BLUE_LIGHT, spaceAfter=6)
    )

    risk = current.risk
    story.append(
        Paragraph(
            f"Average pipeline risk score is "
            f"<b>{risk.average_risk_score:.1f}/100</b> with a P95 of "
            f"<b>{risk.p95_risk_score:.1f}/100</b>. "
            f"<b>{risk.critical_findings:,}</b> critical findings were "
            f"recorded over this window.",
            st["body"],
        )
    )
    story.append(Spacer(1, 3 * mm))

    pie = _build_severity_pie(risk.severity_distribution)
    if pie is not None:
        story.append(pie)
    else:
        story.append(
            Paragraph(
                "No severity-bucketed findings in this window.",
                st["body_sm"],
            )
        )

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Top offenders", st["h2"]))

    if not current.top_offenders:
        story.append(
            Paragraph(
                "No offenders recorded for this window.", st["body_sm"]
            )
        )
        return story

    rows: list = [
        [
            Paragraph(s, st["tbl_header"])
            for s in (
                "#",
                "Subject type",
                "Subject",
                "Deny count",
                "Last seen",
            )
        ]
    ]
    for i, off in enumerate(current.top_offenders[:10], start=1):
        last_seen = (
            off.last_seen.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            if off.last_seen
            else "-"
        )
        rows.append(
            [
                Paragraph(str(i), st["tbl_cell_center"]),
                Paragraph(escape(str(off.subject_type)), st["tbl_cell"]),
                Paragraph(escape(_shorten(off.subject_id, 48)), st["tbl_cell"]),
                Paragraph(f"{off.deny_count:,}", st["tbl_cell_center"]),
                Paragraph(last_seen, st["tbl_cell_center"]),
            ]
        )
    tbl = Table(
        rows,
        colWidths=["6%", "18%", "44%", "14%", "18%"],
        hAlign="LEFT",
    )
    tbl.setStyle(_table_style())
    story.append(tbl)
    return story


def _build_severity_pie(distribution: dict) -> Optional[Drawing]:
    if not distribution:
        return None

    ordered: list[tuple[str, int]] = []
    for sev_name in _SEV_ORDER:
        count = int(distribution.get(sev_name, 0))
        if count > 0:
            ordered.append((sev_name, count))

    other_total = 0
    for k, v in distribution.items():
        if k.lower() not in _SEV_ORDER:
            other_total += int(v) if v else 0
    if other_total > 0:
        ordered.append(("other", other_total))

    if not ordered:
        return None

    drawing_w = 460
    drawing_h = 180
    drawing = Drawing(drawing_w, drawing_h)

    pie = Pie()
    pie.x = 30
    pie.y = 20
    pie.width = 140
    pie.height = 140
    pie.data = [count for _, count in ordered]
    pie.labels = [""] * len(ordered)
    pie.simpleLabels = 1
    pie.sideLabels = 0
    pie.slices.strokeColor = colors.white
    pie.slices.strokeWidth = 1

    for i, (name, _count) in enumerate(ordered):
        col = _SEV_COLORS.get(_SEV_NUMERIC.get(name, 0), _MID_GRAY)
        pie.slices[i].fillColor = col
        pie.slices[i].strokeColor = colors.white

    drawing.add(pie)

    total = sum(c for _, c in ordered) or 1
    legend_x = 200
    legend_y_top = 150
    for i, (name, count) in enumerate(ordered):
        col = _SEV_COLORS.get(_SEV_NUMERIC.get(name, 0), _MID_GRAY)
        y = legend_y_top - i * 18
        drawing.add(Rect(legend_x, y, 12, 10, fillColor=col, strokeColor=col))
        share = count / total * 100
        drawing.add(
            String(
                legend_x + 18,
                y + 2,
                f"{name.capitalize()}: {count:,} ({share:.1f}%)",
                fontSize=8.5,
                fontName="Helvetica",
                fillColor=_DARK_GRAY,
            )
        )

    return drawing


# ── Section: automation ──────────────────────────────────────────────────────


def _automation_section(
    current: ExecutiveSummary, prior: ExecutiveSummary, st: dict
) -> list:
    story: list = []
    story.append(Paragraph("Automation", st["h1"]))
    story.append(
        HRFlowable(width="100%", thickness=1, color=_BLUE_LIGHT, spaceAfter=6)
    )

    auto = current.automation
    prior_auto = prior.automation

    delta_html = _delta_html(
        auto.mean_time_to_action_ms,
        prior_auto.mean_time_to_action_ms,
        invert=True,
    )
    story.append(
        Paragraph(
            f"<b>Mean time-to-action:</b> "
            f"{_format_ms(auto.mean_time_to_action_ms)} ({delta_html} vs prior period)."
            f"<br/><b>Events processed:</b> {auto.events_total:,}. "
            f"<b>Playbooks fired:</b> {auto.playbooks_fired:,}. "
            f"<b>Actions executed:</b> {auto.actions_executed:,}.",
            st["body"],
        )
    )
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("Actions by type", st["h2"]))
    chart = _build_horizontal_bar(auto.actions_by_type, color=_BLUE)
    if chart is not None:
        story.append(chart)
    else:
        story.append(
            Paragraph(
                "No automated actions executed in this window.",
                st["body_sm"],
            )
        )
    return story


# ── Section: coverage and compliance ─────────────────────────────────────────


def _coverage_compliance_section(
    current: ExecutiveSummary, st: dict
) -> list:
    story: list = []
    story.append(Paragraph("Coverage and Compliance", st["h1"]))
    story.append(
        HRFlowable(width="100%", thickness=1, color=_BLUE_LIGHT, spaceAfter=6)
    )

    cov = current.coverage
    story.append(Paragraph("Authored controls", st["h2"]))
    rows: list = [
        [
            Paragraph(s, st["tbl_header"])
            for s in (
                "Control",
                "Total",
                "Enabled",
                "Active in enforcement",
            )
        ]
    ]
    rows.append(
        [
            Paragraph("Policies", st["tbl_cell"]),
            Paragraph(f"{cov.policies_total:,}", st["tbl_cell_center"]),
            Paragraph(f"{cov.policies_enabled:,}", st["tbl_cell_center"]),
            Paragraph(
                f"{cov.policies_enforce_mode:,}", st["tbl_cell_center"]
            ),
        ]
    )
    rows.append(
        [
            Paragraph("Playbooks", st["tbl_cell"]),
            Paragraph(f"{cov.playbooks_total:,}", st["tbl_cell_center"]),
            Paragraph(f"{cov.playbooks_enabled:,}", st["tbl_cell_center"]),
            Paragraph(f"{cov.playbooks_live:,}", st["tbl_cell_center"]),
        ]
    )
    tbl = Table(
        rows,
        colWidths=["28%", "18%", "18%", "36%"],
        hAlign="LEFT",
    )
    tbl.setStyle(_table_style())
    story.append(tbl)

    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Compliance posture", st["h2"]))

    if not current.compliance:
        story.append(
            Paragraph(
                "No compliance tags configured on policies/playbooks. "
                "Add 'compliance' tags to align controls to your "
                "framework (e.g. SOC2, ISO27001, HIPAA).",
                st["body_sm"],
            )
        )
        return story

    rows = [
        [
            Paragraph(s, st["tbl_header"])
            for s in (
                "Tag",
                "Policies",
                "Playbooks",
                "Matched events",
                "Blocked events",
            )
        ]
    ]
    sorted_compliance = sorted(
        current.compliance, key=lambda t: t.matched_events, reverse=True
    )
    for tag in sorted_compliance[:10]:
        rows.append(
            [
                Paragraph(escape(tag.tag), st["tbl_cell"]),
                Paragraph(f"{tag.policies:,}", st["tbl_cell_center"]),
                Paragraph(f"{tag.playbooks:,}", st["tbl_cell_center"]),
                Paragraph(
                    f"{tag.matched_events:,}", st["tbl_cell_center"]
                ),
                Paragraph(
                    f"{tag.blocked_events:,}", st["tbl_cell_center"]
                ),
            ]
        )
    tbl = Table(
        rows,
        colWidths=["28%", "14%", "14%", "22%", "22%"],
        hAlign="LEFT",
    )
    tbl.setStyle(_table_style())
    story.append(tbl)
    return story


# ── Section: appendix ────────────────────────────────────────────────────────


def _appendix(current: ExecutiveSummary, st: dict) -> list:
    story: list = []
    story.append(Paragraph("Appendix", st["h1"]))
    story.append(
        HRFlowable(width="100%", thickness=1, color=_BLUE_LIGHT, spaceAfter=6)
    )

    story.append(Paragraph("Methodology", st["h2"]))
    story.append(
        Paragraph(
            "This report is derived from the executive metrics rollup in "
            "the Valo platform. Enforcement counters and pipeline risk "
            "scores are bucketed into 5-minute / hourly / daily SQLite "
            "tables and aggregated over the trailing window. Period-over-"
            "period deltas compare the trailing window to the equally-"
            "sized prior window immediately before it. Risk posture "
            "(improving / stable / degrading) is computed from the change "
            "in critical-finding count and block-rate percentage points.",
            st["body"],
        )
    )

    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph("Window definitions", st["h2"]))
    rows: list = [
        [
            Paragraph(s, st["tbl_header"])
            for s in ("Window", "Duration", "Default bucket")
        ]
    ]
    for window, duration, bucket in (
        ("24h", "Last 24 hours", "5 minutes"),
        ("7d", "Last 7 days", "1 hour"),
        ("30d", "Last 30 days", "1 day"),
        ("90d", "Last 90 days", "1 day"),
    ):
        rows.append(
            [
                Paragraph(window, st["tbl_cell"]),
                Paragraph(duration, st["tbl_cell"]),
                Paragraph(bucket, st["tbl_cell"]),
            ]
        )
    tbl = Table(rows, colWidths=["18%", "52%", "30%"], hAlign="LEFT")
    tbl.setStyle(_table_style())
    story.append(tbl)

    story.append(Spacer(1, 4 * mm))
    story.append(
        Paragraph(
            f"Window: {current.window} "
            f"({current.window_start.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
            f"to "
            f"{current.window_end.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}). "
            f"Generated at "
            f"{current.generated_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}.",
            st["body_sm"],
        )
    )
    return story


# ── Helpers ──────────────────────────────────────────────────────────────────


def _table_style() -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _LIGHT_GRAY]),
            ("BOX", (0, 0), (-1, -1), 0.5, _MID_GRAY),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, _MID_GRAY),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
    )


def _kpi_tile(
    *,
    label: str,
    value: str,
    delta: tuple[str, str, str],
    st: dict,
) -> Table:
    arrow, pct, color_hex = delta
    delta_para = Paragraph(
        f'<font color="{color_hex}">{arrow} {pct}</font> '
        f'<font color="{_DELTA_GRAY_HEX}">vs prior</font>',
        ParagraphStyle(
            "kpi_delta",
            fontName="Helvetica",
            fontSize=8.5,
            textColor=_DARK_GRAY,
            alignment=TA_CENTER,
            leading=11,
        ),
    )
    inner = Table(
        [
            [Paragraph(label, st["metric_label"])],
            [Paragraph(value, st["metric_value"])],
            [delta_para],
        ],
        colWidths=["100%"],
    )
    inner.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _LIGHT_GRAY),
                ("LINEBELOW", (0, 0), (-1, 0), 0.25, _MID_GRAY),
                ("BOX", (0, 0), (-1, -1), 0.5, _MID_GRAY),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return inner


def _format_delta(
    curr: float, prior: float, *, invert: bool = False
) -> tuple[str, str, str]:
    """Return (arrow_glyph, percentage_string, hex_color)."""
    if prior <= 0 and curr <= 0:
        return _GLYPH_FLAT, "0%", _DELTA_GRAY_HEX
    if prior <= 0:
        glyph = _GLYPH_UP
        good = not invert
        return glyph, "new", (_DELTA_GREEN_HEX if good else _DELTA_RED_HEX)
    delta = (curr - prior) / prior * 100
    if abs(delta) < 0.5:
        return _GLYPH_FLAT, "0%", _DELTA_GRAY_HEX
    if delta > 0:
        good = not invert
        glyph = _GLYPH_UP
    else:
        good = invert
        glyph = _GLYPH_DOWN
    color = _DELTA_GREEN_HEX if good else _DELTA_RED_HEX
    return glyph, f"{abs(delta):.0f}%", color


def _format_delta_pp(
    curr_pct: float, prior_pct: float, *, invert: bool = False
) -> tuple[str, str, str]:
    delta = curr_pct - prior_pct
    if abs(delta) < 0.05:
        return _GLYPH_FLAT, "0pp", _DELTA_GRAY_HEX
    if delta > 0:
        good = not invert
        glyph = _GLYPH_UP
    else:
        good = invert
        glyph = _GLYPH_DOWN
    color = _DELTA_GREEN_HEX if good else _DELTA_RED_HEX
    return glyph, f"{abs(delta):.1f}pp", color


def _delta_html(curr, prior, *, invert: bool = False) -> str:
    glyph, pct, color = _format_delta(float(curr), float(prior), invert=invert)
    return f'<font color="{color}">{glyph} {pct}</font>'


def _compose_headline(
    current: ExecutiveSummary, prior: ExecutiveSummary
) -> str:
    posture = _posture_label(current, prior)
    block_pp = (current.exposure.block_rate - prior.exposure.block_rate) * 100
    crit_delta = (
        current.risk.critical_findings - prior.risk.critical_findings
    )
    sign = "+" if block_pp >= 0 else ""
    block_pct = current.exposure.block_rate * 100

    pieces = [f"<b>Risk posture: {posture}.</b>"]
    if posture == "improving":
        pieces.append(
            f"Enforcement strengthened: block rate {block_pct:.1f}% "
            f"({sign}{block_pp:.1f}pp vs prior period) with no rise in "
            f"critical findings ({prior.risk.critical_findings} -> "
            f"{current.risk.critical_findings})."
        )
    elif posture == "degrading":
        if crit_delta > 0:
            pieces.append(
                f"Critical findings rose by {crit_delta} "
                f"({prior.risk.critical_findings} -> "
                f"{current.risk.critical_findings}); current block rate "
                f"is {block_pct:.1f}%."
            )
        else:
            pieces.append(
                f"Block rate fell by {abs(block_pp):.1f}pp to "
                f"{block_pct:.1f}%; investigate detection coverage."
            )
    else:
        pieces.append(
            f"Block rate is {block_pct:.1f}% on "
            f"{current.exposure.total_requests:,} requests; "
            f"{current.risk.critical_findings:,} critical findings recorded."
        )
    pieces.append(
        f"{current.automation.playbooks_fired:,} playbook executions "
        f"resulted in {current.automation.actions_executed:,} automated "
        f"actions; mean time-to-action "
        f"{_format_ms(current.automation.mean_time_to_action_ms)}."
    )
    return " ".join(pieces)


def _posture_label(
    current: ExecutiveSummary, prior: ExecutiveSummary
) -> str:
    block_pp = (current.exposure.block_rate - prior.exposure.block_rate) * 100
    crit_delta = (
        current.risk.critical_findings - prior.risk.critical_findings
    )
    if crit_delta > 0 or block_pp <= -2.0:
        return "degrading"
    if block_pp >= 2.0 and crit_delta <= 0:
        return "improving"
    return "stable"


def _derive_actions(summary: ExecutiveSummary) -> list[str]:
    actions: list[str] = []
    cov = summary.coverage
    inactive_playbooks = max(cov.playbooks_total - cov.playbooks_live, 0)
    if inactive_playbooks > 0:
        actions.append(
            f"Activate {inactive_playbooks} playbook(s) currently disabled "
            f"or in dry-run ({cov.playbooks_live}/{cov.playbooks_total} live)."
        )

    if (
        summary.exposure.top_blocking_policy_id
        and summary.exposure.blocked > 0
    ):
        share = summary.exposure.top_blocking_policy_count / max(
            summary.exposure.blocked, 1
        )
        if share >= 0.5:
            actions.append(
                f"Investigate over-broad policy "
                f"'{summary.exposure.top_blocking_policy_id}', responsible "
                f"for {share * 100:.0f}% of blocks; tune scope to reduce "
                f"false positives."
            )

    if summary.risk.critical_findings > 0:
        actions.append(
            f"Triage {summary.risk.critical_findings:,} critical finding(s); "
            f"see Top Offenders for the most active subjects."
        )

    observe_only = max(
        cov.policies_enabled - cov.policies_enforce_mode, 0
    )
    if observe_only > 0:
        actions.append(
            f"Promote {observe_only} policy/policies from observe to "
            f"enforce mode to convert detections into prevention."
        )

    if not summary.compliance:
        actions.append(
            "Tag policies and playbooks with compliance frameworks "
            "(e.g. SOC2, ISO27001) to enable per-tag posture reporting."
        )

    if not actions:
        actions.append(
            "Posture is healthy across enforcement, automation, and "
            "coverage. Consider widening rule coverage to surface latent "
            "risks."
        )
    return actions


def _format_ms(ms: float) -> str:
    if ms is None or ms <= 0:
        return "0 ms"
    if ms < 1_000:
        return f"{ms:.0f} ms"
    if ms < 60_000:
        return f"{ms / 1_000:.1f} s"
    return f"{ms / 60_000:.1f} min"


def _fmt_int(v) -> str:
    return f"{int(v):,}"


def _fmt_pct(v) -> str:
    return f"{float(v) * 100:.2f}%"


def _fmt_score(v) -> str:
    return f"{float(v):.1f}/100"


def _fmt_ms(v) -> str:
    return _format_ms(float(v))


def _shorten(s, max_len: int = 48) -> str:
    text = str(s)
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "..."


def _build_logo_flowable(
    logo_bytes: bytes, *, max_w: float, max_h: float
) -> Optional[Image]:
    reader = ImageReader(io.BytesIO(logo_bytes))
    try:
        w_px, h_px = reader.getSize()
    except Exception:
        return None
    if w_px <= 0 or h_px <= 0:
        return None
    scale = min(max_w / float(w_px), max_h / float(h_px), 1.0)
    return Image(
        io.BytesIO(logo_bytes),
        width=float(w_px) * scale,
        height=float(h_px) * scale,
    )


__all__ = ["generate_kpi_pdf"]
