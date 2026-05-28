
from __future__ import annotations

import base64
import io
import re
from xml.sax.saxutils import escape
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    Image,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import Flowable

from app.core.exceptions import ServiceError
from app.core.logging import get_logger
from app.schemas import ScanReport

logger = get_logger(__name__)

_DEFAULT_COMPANY_NAME = "Valo"

# ── Palette ───────────────────────────────────────────────────────────────────
_NAVY       = colors.HexColor("#0F1F3D")
_BLUE       = colors.HexColor("#1E40AF")
_BLUE_LIGHT = colors.HexColor("#3B82F6")
_TEAL       = colors.HexColor("#0E7490")
_WHITE      = colors.white
_LIGHT_GRAY = colors.HexColor("#F1F5F9")
_MID_GRAY   = colors.HexColor("#CBD5E1")
_DARK_GRAY  = colors.HexColor("#334155")
_TEXT       = colors.HexColor("#1E293B")

# Severity colours
_SEV_COLORS = {
    1: colors.HexColor("#22C55E"),   # green    – Info
    2: colors.HexColor("#3B82F6"),   # blue     – Low
    3: colors.HexColor("#F59E0B"),   # amber    – Medium
    4: colors.HexColor("#EF4444"),   # red      – High
    5: colors.HexColor("#7F1D1D"),   # dark red – Critical
}
_SEV_LABELS = {1: "INFO", 2: "LOW", 3: "MEDIUM", 4: "HIGH", 5: "CRITICAL"}

# Risk-score bands
def _risk_color(score: float) -> colors.Color:
    if score >= 80:
        return colors.HexColor("#7F1D1D")
    if score >= 60:
        return colors.HexColor("#EF4444")
    if score >= 40:
        return colors.HexColor("#F59E0B")
    if score >= 20:
        return colors.HexColor("#3B82F6")
    return colors.HexColor("#22C55E")

def _risk_label(score: float) -> str:
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    if score >= 20:
        return "LOW"
    return "MINIMAL"


# ── Styles ────────────────────────────────────────────────────────────────────
_BASE = getSampleStyleSheet()

def _make_styles() -> dict:
    return {
        "cover_title": ParagraphStyle(
            "cover_title",
            fontName="Helvetica-Bold",
            fontSize=28,
            textColor=_WHITE,
            leading=34,
            alignment=TA_LEFT,
        ),
        "cover_sub": ParagraphStyle(
            "cover_sub",
            fontName="Helvetica",
            fontSize=11,
            textColor=colors.HexColor("#93C5FD"),
            leading=16,
            alignment=TA_LEFT,
        ),
        "cover_meta": ParagraphStyle(
            "cover_meta",
            fontName="Helvetica",
            fontSize=9,
            textColor=colors.HexColor("#CBD5E1"),
            leading=14,
            alignment=TA_LEFT,
        ),
        "cover_company": ParagraphStyle(
            "cover_company",
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=_WHITE,
            leading=16,
            alignment=TA_LEFT,
        ),
        "h1": ParagraphStyle(
            "h1",
            fontName="Helvetica-Bold",
            fontSize=16,
            textColor=_NAVY,
            leading=22,
            spaceBefore=14,
            spaceAfter=4,
        ),
        "h2": ParagraphStyle(
            "h2",
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=_BLUE,
            leading=16,
            spaceBefore=10,
            spaceAfter=2,
        ),
        "body": ParagraphStyle(
            "body",
            fontName="Helvetica",
            fontSize=9.5,
            textColor=_TEXT,
            leading=14,
            spaceAfter=4,
        ),
        "body_sm": ParagraphStyle(
            "body_sm",
            fontName="Helvetica",
            fontSize=8.5,
            textColor=_DARK_GRAY,
            leading=12,
        ),
        "code": ParagraphStyle(
            "code",
            fontName="Courier",
            fontSize=8,
            textColor=_DARK_GRAY,
            leading=11,
            backColor=_LIGHT_GRAY,
            leftIndent=6,
            rightIndent=6,
        ),
        "badge_label": ParagraphStyle(
            "badge_label",
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=_WHITE,
            alignment=TA_CENTER,
            leading=10,
        ),
        "footer": ParagraphStyle(
            "footer",
            fontName="Helvetica",
            fontSize=7.5,
            textColor=colors.HexColor("#94A3B8"),
            alignment=TA_CENTER,
        ),
        "tbl_header": ParagraphStyle(
            "tbl_header",
            fontName="Helvetica-Bold",
            fontSize=8.5,
            textColor=_WHITE,
            alignment=TA_CENTER,
        ),
        "tbl_cell": ParagraphStyle(
            "tbl_cell",
            fontName="Helvetica",
            fontSize=8,
            textColor=_TEXT,
            leading=11,
        ),
        "tbl_cell_center": ParagraphStyle(
            "tbl_cell_center",
            fontName="Helvetica",
            fontSize=8,
            textColor=_TEXT,
            alignment=TA_CENTER,
            leading=11,
        ),
        "metric_value": ParagraphStyle(
            "metric_value",
            fontName="Helvetica-Bold",
            fontSize=22,
            textColor=_NAVY,
            alignment=TA_CENTER,
            leading=26,
        ),
        "metric_label": ParagraphStyle(
            "metric_label",
            fontName="Helvetica",
            fontSize=8,
            textColor=_DARK_GRAY,
            alignment=TA_CENTER,
            leading=11,
        ),
        "recommend_title": ParagraphStyle(
            "recommend_title",
            fontName="Helvetica-Bold",
            fontSize=9.5,
            textColor=_NAVY,
            leading=14,
            spaceBefore=4,
        ),
        "recommend_body": ParagraphStyle(
            "recommend_body",
            fontName="Helvetica",
            fontSize=9,
            textColor=_TEXT,
            leading=13,
            leftIndent=12,
            spaceAfter=6,
        ),
    }


# ── Custom Flowables ──────────────────────────────────────────────────────────

class _ColorRect(Flowable):
    """A filled rounded-corner rectangle used as a coloured banner or badge."""

    def __init__(self, width: float, height: float, fill: colors.Color,
                 radius: float = 4, stroke_color: colors.Color | None = None):
        super().__init__()
        self.width = width
        self.height = height
        self._fill = fill
        self._radius = radius
        self._stroke = stroke_color

    def draw(self) -> None:
        c = self.canv
        c.saveState()
        c.setFillColor(self._fill)
        if self._stroke:
            c.setStrokeColor(self._stroke)
            c.setLineWidth(0.5)
        else:
            c.setStrokeColor(self._fill)
        c.roundRect(0, 0, self.width, self.height, self._radius, fill=1,
                    stroke=1 if self._stroke else 0)
        c.restoreState()


class _RiskGauge(Flowable):
    """Horizontal segmented risk gauge (0-100) with a marker at *score*."""

    def __init__(self, score: float, width: float = 300, height: float = 18):
        super().__init__()
        self.score = score
        self.width = width
        self.height = height

    def draw(self) -> None:
        c = self.canv
        c.saveState()
        segments = [
            (0, 20,  colors.HexColor("#22C55E")),
            (20, 40, colors.HexColor("#3B82F6")),
            (40, 60, colors.HexColor("#F59E0B")),
            (60, 80, colors.HexColor("#EF4444")),
            (80, 100, colors.HexColor("#7F1D1D")),
        ]
        seg_w = self.width / 5
        for i, (lo, hi, col) in enumerate(segments):
            c.setFillColor(col)
            c.setStrokeColor(_WHITE)
            c.setLineWidth(1)
            c.roundRect(i * seg_w, 0, seg_w, self.height, 2, fill=1, stroke=1)

        # Marker line – kept strictly within the flowable bounds so it isn't clipped
        marker_x = (self.score / 100.0) * self.width
        marker_x = max(3, min(self.width - 3, marker_x))
        c.setFillColor(_NAVY)
        c.setStrokeColor(_NAVY)
        c.setLineWidth(2.5)
        c.line(marker_x, 1, marker_x, self.height - 1)
        c.restoreState()


class _DefaultLogo(Flowable):
    """Simple placeholder logo when no custom logo is provided."""

    def __init__(self, size: float = 14 * mm):
        super().__init__()
        self.size = size

    def draw(self) -> None:
        c = self.canv
        c.saveState()
        c.setFillColor(_BLUE)
        c.roundRect(0, 0, self.size, self.size, 2, fill=1, stroke=0)
        c.setFillColor(_WHITE)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(self.size / 2, self.size / 2 - 3, "V")
        c.restoreState()


# ── Canvas callbacks (header / footer) ───────────────────────────────────────

def _make_page_cb(scan_id: str, timestamp: str, report_title: str):
    """Return a canvas callback that draws a branded header + footer."""

    def _draw(canvas, doc):  # noqa: ANN001
        w, h = A4
        canvas.saveState()

        # ── Explicit white page background (cover page handles its own) ──────
        canvas.setFillColor(colors.white)
        canvas.rect(0, 0, w, h, fill=1, stroke=0)

        # ── Header bar ──────────────────────────────────────────────────────
        canvas.setFillColor(_NAVY)
        canvas.rect(0, h - 28 * mm, w, 28 * mm, fill=1, stroke=0)

        canvas.setFillColor(_BLUE_LIGHT)
        canvas.rect(0, h - 30 * mm, w, 2 * mm, fill=1, stroke=0)

        canvas.setFont("Helvetica-Bold", 11)
        canvas.setFillColor(_WHITE)
        canvas.drawString(18 * mm, h - 16 * mm, report_title)

        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#93C5FD"))
        canvas.drawRightString(w - 18 * mm, h - 12 * mm, f"Scan ID: {scan_id}")
        canvas.drawRightString(w - 18 * mm, h - 18 * mm, timestamp)

        # ── Footer bar ───────────────────────────────────────────────────────
        canvas.setFillColor(_LIGHT_GRAY)
        canvas.rect(0, 0, w, 14 * mm, fill=1, stroke=0)

        canvas.setStrokeColor(_MID_GRAY)
        canvas.setLineWidth(0.5)
        canvas.line(18 * mm, 14 * mm, w - 18 * mm, 14 * mm)

        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(18 * mm, 5 * mm, "CONFIDENTIAL – Security Scan Report")
        canvas.drawRightString(w - 18 * mm, 5 * mm,
                               f"Page {doc.page}")

        canvas.restoreState()

    return _draw


def _make_cover_cb(scan_id: str, timestamp: str):
    """Canvas callback for the cover page — full-bleed navy background."""

    def _draw(canvas, doc):  # noqa: ANN001
        w, h = A4
        canvas.saveState()

        # Full background
        canvas.setFillColor(_NAVY)
        canvas.rect(0, 0, w, h, fill=1, stroke=0)

        # Accent stripe
        canvas.setFillColor(_BLUE_LIGHT)
        canvas.rect(0, h * 0.42, w, 3, fill=1, stroke=0)

        # Bottom footer
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#475569"))
        canvas.drawString(18 * mm, 10 * mm, "CONFIDENTIAL – Security Scan Report")
        canvas.drawRightString(w - 18 * mm, 10 * mm,
                               f"Generated: {timestamp}  |  Scan ID: {scan_id}")

        canvas.restoreState()

    return _draw


def _decode_logo_bytes(raw: str) -> Optional[bytes]:
    value = raw.strip()
    if value.startswith("data:"):
        match = re.match(r"^data:[^;]+;base64,(.+)$", value, re.DOTALL)
        if not match:
            return None
        value = match.group(1)
    try:
        return base64.b64decode(value, validate=True)
    except Exception:
        return None


def _extract_branding(report: ScanReport) -> Tuple[Optional[str], Optional[bytes]]:
    branding = report.metadata.get("report_branding")
    if not isinstance(branding, dict):
        return None, None
    company_name = branding.get("company_name") or None
    logo_raw = branding.get("logo_base64") or None
    if not logo_raw:
        return company_name, None
    logo_bytes = _decode_logo_bytes(str(logo_raw))
    if logo_bytes is None:
        logger.warning("Invalid report logo_base64 provided; ignoring logo")
    return company_name, logo_bytes


def _scale_to_fit(width: float, height: float, max_w: float, max_h: float) -> tuple[float, float]:
    if width <= 0 or height <= 0:
        return max_w, max_h
    scale = min(max_w / width, max_h / height, 1.0)
    return width * scale, height * scale


def _build_logo_flowable(logo_bytes: bytes, max_w: float, max_h: float) -> Image:
    reader = ImageReader(io.BytesIO(logo_bytes))
    w_px, h_px = reader.getSize()
    draw_w, draw_h = _scale_to_fit(float(w_px), float(h_px), max_w, max_h)
    return Image(io.BytesIO(logo_bytes), width=draw_w, height=draw_h)


# ── Section builders ──────────────────────────────────────────────────────────

def _cover_section(report: ScanReport, st: dict, company_name: Optional[str], logo: Optional[Image]) -> list:
    """Build cover-page flowables (placed on the navy background)."""
    score_col = _risk_color(report.risk_score)
    risk_label = _risk_label(report.risk_score)
    target = report.metadata.get("target", "—")
    input_kind = report.metadata.get("input_kind", "—")
    ts = report.timestamp.strftime("%Y-%m-%d %H:%M UTC") if report.timestamp else "—"

    story: list = []
    if logo or company_name:
        story.append(Spacer(1, 16 * mm))
        if logo:
            story.append(logo)
            story.append(Spacer(1, 2 * mm))
        if company_name:
            story.append(Paragraph(f"Prepared for {escape(company_name)}", st["cover_company"]))
        story.append(Spacer(1, 24 * mm))
    else:
        story.append(Spacer(1, 68 * mm))

    # Product branding
    brand_name = _DEFAULT_COMPANY_NAME
    story.append(Paragraph(
        f'<font color="#3B82F6">■</font>  <font color="#93C5FD">{brand_name}</font>',
        ParagraphStyle("brand", fontName="Helvetica-Bold", fontSize=11,
                       textColor=colors.HexColor("#93C5FD"), leading=14),
    ))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("Security Scan Report", st["cover_title"]))
    story.append(Paragraph("Valo Deterministic AI Prompt Security Engine", st["cover_sub"]))
    story.append(Spacer(1, 10 * mm))

    # Divider
    story.append(HRFlowable(width="100%", thickness=0.5,
                             color=colors.HexColor("#1E3A5F"), spaceAfter=8))

    # Metadata row
    meta_data = [
        [
            Paragraph(f'<b><font color="#93C5FD">Target</font></b><br/>'
                      f'<font color="#E2E8F0">{target}</font>', st["cover_meta"]),
            Paragraph(f'<b><font color="#93C5FD">Input Kind</font></b><br/>'
                      f'<font color="#E2E8F0">{input_kind.upper()}</font>', st["cover_meta"]),
            Paragraph(f'<b><font color="#93C5FD">Scan Date</font></b><br/>'
                      f'<font color="#E2E8F0">{ts}</font>', st["cover_meta"]),
        ]
    ]
    meta_tbl = Table(meta_data, colWidths=["33%", "33%", "34%"])
    meta_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 12 * mm))

    # Big risk-score badge
    badge_data = [[
        Paragraph(
            f'<font size="36"><b>{report.risk_score:.1f}</b></font><br/>'
            f'<font size="12"> / 100</font>',
            ParagraphStyle("rs_num", fontName="Helvetica-Bold", fontSize=36,
                           textColor=_WHITE, alignment=TA_CENTER, leading=42),
        ),
        Paragraph(
            f'<b><font size="18">{risk_label}</font></b><br/>'
            f'<font color="#CBD5E1" size="9">Combined Risk Score</font>',
            ParagraphStyle("rs_lbl", fontName="Helvetica-Bold", fontSize=18,
                           textColor=_WHITE, leading=24),
        ),
    ]]
    badge_tbl = Table(badge_data, colWidths=[50 * mm, 100 * mm])
    badge_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), score_col),
        ("ROUNDEDCORNERS", [6]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(badge_tbl)
    story.append(NextPageTemplate("body"))
    story.append(PageBreak())
    return story


def _executive_summary(report: ScanReport, st: dict) -> list:
    story: list = []
    story.append(Paragraph("Executive Summary", st["h1"]))
    story.append(HRFlowable(width="100%", thickness=1, color=_BLUE_LIGHT, spaceAfter=6))

    target      = report.metadata.get("target", "—")
    input_kind  = report.metadata.get("input_kind", "—")
    content_len = report.metadata.get("content_length", "—")
    det_flags   = report.metadata.get("detection_flags", [])
    ts          = report.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC") if report.timestamp else "—"
    risk_label  = _risk_label(report.risk_score)
    risk_col    = _risk_color(report.risk_score)
    sev_label   = _SEV_LABELS.get(report.max_severity_found, "NONE")
    sev_col     = _SEV_COLORS.get(report.max_severity_found, _MID_GRAY)

    intro = (
        f"This report presents the results of an automated security scan performed on "
        f"<b>{target}</b> at <b>{ts}</b>. Valo is a deterministic AI Prompt Security Engine "
        f"differentiated by explainable risk scoring, an open-source architecture, and "
        f"governance-aligned documentation. The scan evaluated the prompt against the "
        f"active YAML prompt-injection rule set using text-scan detection "
        f"(regex, keyword, entropy). The findings and recommendations below are derived "
        f"dynamically from the rules that triggered during this scan."
    )
    story.append(Paragraph(intro, st["body"]))
    story.append(Spacer(1, 5 * mm))

    # ── Key metrics row ──────────────────────────────────────────────────────
    metrics = [
        (f"{report.risk_score:.1f}", "Combined Risk Score", risk_col),
        (risk_label, "Risk Level", risk_col),
        (sev_label, "Max Severity", sev_col),
        (str(len(report.findings)), "Total Findings", _BLUE),
        (str(len(report.matched_rules)), "Matched Rules", _TEAL),
    ]

    metric_cells = []
    for val, lbl, col in metrics:
        cell = [
            Paragraph(f'<font color="{col.hexval()}" size="18"><b>{val}</b></font>',
                      st["metric_value"]),
            Paragraph(lbl, st["metric_label"]),
        ]
        metric_cells.append(cell)

    # Build 5-column metrics table
    row_vals  = [[Paragraph(f'<font size="18"><b>{v}</b></font>',
                             ParagraphStyle("mv2", fontName="Helvetica-Bold", fontSize=18,
                                             textColor=c, alignment=TA_CENTER, leading=22))
                  for v, _, c in metrics]]
    row_labels = [[Paragraph(l, st["metric_label"]) for _, l, _ in metrics]]

    col_w = [38 * mm] * 5
    mt = Table(row_vals + row_labels, colWidths=col_w)
    mt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _LIGHT_GRAY),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [_LIGHT_GRAY, _WHITE]),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
        ("TOPPADDING", (0, 1), (-1, 1), 2),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
        ("BOX", (0, 0), (-1, -1), 0.5, _MID_GRAY),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, _MID_GRAY),
        ("ROUNDEDCORNERS", [4]),
    ]))
    story.append(mt)
    story.append(Spacer(1, 5 * mm))

    # Detection flags
    if det_flags:
        story.append(Paragraph("Detection Signals", st["h2"]))
        flags_str = "  ·  ".join(f'<font color="#1E40AF"><b>{f}</b></font>'
                                 for f in det_flags)
        story.append(Paragraph(flags_str, st["body_sm"]))

    # Scan metadata mini-table
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("Scan Metadata", st["h2"]))
    meta_rows = [
        [Paragraph("<b>Scan ID</b>", st["tbl_cell"]),      Paragraph(str(report.scan_id),  st["tbl_cell"])],
        [Paragraph("<b>Target</b>", st["tbl_cell"]),        Paragraph(target,               st["tbl_cell"])],
        [Paragraph("<b>Input Kind</b>", st["tbl_cell"]),    Paragraph(input_kind.upper(),   st["tbl_cell"])],
        [Paragraph("<b>Content Length</b>", st["tbl_cell"]), Paragraph(f"{content_len} chars", st["tbl_cell"])],
        [Paragraph("<b>Timestamp</b>", st["tbl_cell"]),     Paragraph(ts,                  st["tbl_cell"])],
        [Paragraph("<b>Severity Ceiling</b>", st["tbl_cell"]),
         Paragraph("Applied" if report.severity_ceiling_applied else "Not applied", st["tbl_cell"])],
    ]
    meta_tbl = Table(meta_rows, colWidths=[52 * mm, 120 * mm])
    meta_tbl.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [_LIGHT_GRAY, _WHITE]),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BOX", (0, 0), (-1, -1), 0.5, _MID_GRAY),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, _MID_GRAY),
    ]))
    story.append(meta_tbl)
    return story


def _risk_breakdown(report: ScanReport, st: dict) -> list:
    story: list = []
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Risk Score Breakdown", st["h1"]))
    story.append(HRFlowable(width="100%", thickness=1, color=_BLUE_LIGHT, spaceAfter=6))

    comb_score = report.risk_score
    rules = report.matched_rules or []
    enabled_weight_total = sum(r.weight for r in rules if r.weight and r.weight > 0)

    rules_count = len(rules)
    story.append(Paragraph(
        "Per-rule risk scores are normalized by rule weight across the enabled prompt-injection "
        "rules. The <b>Combined Risk Score</b> applies Valo's deterministic scoring model "
        "(base severity, breadth, and repetition) and represents the overall prompt risk.",
        st["body"],
    ))
    if rules_count == 1:
        story.append(Paragraph(
            "Only one rule is enabled in this ruleset, so the combined score will align with "
            "the single rule's contribution when it matches.",
            st["body_sm"],
        ))
    story.append(Spacer(1, 4 * mm))

    # Score bars
    _score_label_style = ParagraphStyle(
        "score_lbl",
        fontName="Helvetica-Bold",
        fontSize=9,
        textColor=_TEXT,
        leading=13,
    )
    rule_rows: list[tuple[str, float]] = []
    for rule in rules:
        weight = rule.weight or 0.0
        matched = bool(rule.matched)
        score = 0.0
        if matched and enabled_weight_total > 0:
            score = min((weight / enabled_weight_total) * 100.0, 100.0)
        label_suffix = "matched" if matched else "not matched"
        rule_rows.append((f"Rule Risk Score - {rule.rule_name} ({label_suffix})", score))

    if not rule_rows:
        rule_rows = [("Combined Risk Score", comb_score)]
    else:
        rule_rows.append(("Combined Risk Score", comb_score))

    for label, score in rule_rows:
        bar_col = _risk_color(score)
        score_val_style = ParagraphStyle(
            "score_val",
            fontName="Helvetica-Bold",
            fontSize=13,
            textColor=bar_col,
            alignment=TA_CENTER,
            leading=16,
        )
        row = [
            Paragraph(label, _score_label_style),
            _RiskGauge(score, width=90 * mm, height=16),
            Paragraph(f"<b>{score:.1f}</b>", score_val_style),
        ]
        tbl = Table([row], colWidths=[72 * mm, 90 * mm, 25 * mm])
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), _WHITE),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING",   (0, 0), (0,  -1), 10),
            ("LEFTPADDING",   (1, 0), (1,  -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("BOX",           (0, 0), (-1, -1), 0.5, _MID_GRAY),
            ("LINEBEFORE",    (1, 0), (1,  -1), 0.3, _MID_GRAY),
            ("LINEBEFORE",    (2, 0), (2,  -1), 0.3, _MID_GRAY),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 2 * mm))

    return story


def _matched_rules_section(report: ScanReport, st: dict) -> list:
    story: list = []
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Matched Rules", st["h1"]))
    story.append(HRFlowable(width="100%", thickness=1, color=_BLUE_LIGHT, spaceAfter=6))

    if not report.matched_rules:
        story.append(Paragraph("No rules matched during this scan.", st["body"]))
        return story

    header = [
        Paragraph("Rule Name", st["tbl_header"]),
        Paragraph("Severity", st["tbl_header"]),
        Paragraph("Weight", st["tbl_header"]),
    ]
    rows = [header]
    for i, rule in enumerate(report.matched_rules):
        sev_col = _SEV_COLORS.get(rule.severity, _MID_GRAY)
        sev_lbl = _SEV_LABELS.get(rule.severity, str(rule.severity))
        bg = _LIGHT_GRAY if i % 2 == 0 else _WHITE
        rows.append([
            Paragraph(rule.rule_name, st["tbl_cell"]),
            Paragraph(
                f'<font color="{sev_col.hexval()}"><b>{sev_lbl}</b></font>',
                st["tbl_cell_center"],
            ),
            Paragraph(str(rule.weight), st["tbl_cell_center"]),
        ])

    col_widths = [120 * mm, 35 * mm, 22 * mm]
    tbl = Table(rows, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), _WHITE),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_LIGHT_GRAY, _WHITE]),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BOX", (0, 0), (-1, -1), 0.5, _MID_GRAY),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, _MID_GRAY),
    ]))
    story.append(tbl)
    return story


def _findings_section(report: ScanReport, st: dict) -> list:
    story: list = []
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Findings", st["h1"]))
    story.append(HRFlowable(width="100%", thickness=1, color=_BLUE_LIGHT, spaceAfter=6))

    if not report.findings:
        story.append(Paragraph("No prompt-injection findings were detected in this scan.", st["body"]))
        return story

    story.append(Paragraph(
        f"Valo identified <b>{len(report.findings)}</b> finding(s) across the scanned prompt. "
        "Each finding includes the triggering rule, severity classification, and an evidence "
        "snippet showing the matched content.",
        st["body"],
    ))
    story.append(Spacer(1, 3 * mm))

    header = [
        Paragraph("#", st["tbl_header"]),
        Paragraph("Rule ID", st["tbl_header"]),
        Paragraph("Category", st["tbl_header"]),
        Paragraph("Severity", st["tbl_header"]),
        Paragraph("Evidence Snippet", st["tbl_header"]),
    ]
    rows = [header]
    for i, f in enumerate(report.findings, 1):
        sev_col = _SEV_COLORS.get(f.severity, _MID_GRAY)
        sev_lbl = _SEV_LABELS.get(f.severity, str(f.severity))
        evidence = f.evidence.replace("\n", " ").replace("\r", "")
        if len(evidence) > 120:
            evidence = evidence[:117] + "..."
        rows.append([
            Paragraph(str(i), st["tbl_cell_center"]),
            Paragraph(f.rule_id, st["tbl_cell"]),
            Paragraph(f.category.upper(), st["tbl_cell_center"]),
            Paragraph(
                f'<font color="{sev_col.hexval()}"><b>{sev_lbl}</b></font>',
                st["tbl_cell_center"],
            ),
            Paragraph(f'<font face="Courier" size="7.5">{evidence}</font>',
                      st["tbl_cell"]),
        ])

    col_widths = [9 * mm, 36 * mm, 22 * mm, 22 * mm, 88 * mm]
    tbl = Table(rows, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), _WHITE),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_LIGHT_GRAY, _WHITE]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BOX", (0, 0), (-1, -1), 0.5, _MID_GRAY),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, _MID_GRAY),
    ]))
    story.append(tbl)
    return story


def _recommendations_section(report: ScanReport, st: dict) -> list:
    """Generate dynamic recommendations based on findings and matched rules."""
    story: list = []
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Recommendations", st["h1"]))
    story.append(HRFlowable(width="100%", thickness=1, color=_BLUE_LIGHT, spaceAfter=6))

    recs: list[tuple[int, str, str]] = []  # (priority, title, body)

    # Build from matched rule names and prompt-injection families
    matched_ids = {r.rule_name for r in report.matched_rules if r.matched}

    def _has(prefix: str) -> bool:
        return any(prefix in name for name in matched_ids)

    if _has("instruction_override"):
        recs.append((1, "Enforce Instruction Hierarchy",
            "Instruction-override patterns were detected. Enforce strict system/developer "
            "instruction precedence, strip user attempts to nullify prior guidance, and "
            "separate user content from control instructions."))

    if _has("role_confusion"):
        recs.append((2, "Lock Model Role and Persona",
            "Role-confusion attempts were detected. Prevent user inputs from changing the "
            "assistant's role or safety mode, and validate that role assumptions only come "
            "from trusted configuration."))

    if _has("system_prompt_extraction"):
        recs.append((1, "Prevent System Prompt Disclosure",
            "System prompt extraction attempts were detected. Ensure sensitive system "
            "instructions and hidden policies are never surfaced in responses and are "
            "excluded from user-visible logs or debugging traces."))

    if _has("tool_misuse"):
        recs.append((1, "Restrict Tool Invocation",
            "Tool misuse prompts were detected. Enforce allowlists for tools and commands, "
            "require explicit authorization for any action, and sandbox tool outputs."))

    if _has("encoded_payload") or _has("filter_bypass"):
        recs.append((2, "Normalize and Decode Before Evaluation",
            "Obfuscated or encoded payloads were detected. Normalize input (Unicode, "
            "whitespace, encoding) before analysis and block attempts to decode-and-execute."))

    if _has("data_exfiltration"):
        recs.append((1, "Harden Data Access Controls",
            "Data exfiltration attempts were detected. Enforce least-privilege access, "
            "redact secrets in model context, and prevent responses from including sensitive data."))

    if _has("output_manipulation"):
        recs.append((3, "Server-Side Output Contracts",
            "Output-format manipulation was detected. Enforce server-side response schemas "
            "and ignore user instructions that alter safety-critical output formatting."))

    if _has("context_injection") or _has("structured_data_injection") or _has("indirect_injection"):
        recs.append((2, "Isolate Untrusted Content",
            "Context/indirect injection indicators were detected. Treat external content as "
            "untrusted, strip instructions from documents/HTML/JSON, and label sources explicitly."))

    if _has("jailbreak"):
        recs.append((2, "Defend Against Jailbreak Framing",
            "Jailbreak framing was detected. Refuse roleplay or disclaimer-based bypasses "
            "and maintain consistent safety policies across turns."))

    if _has("access_control"):
        recs.append((1, "Enforce Access Control on the Server",
            "Access-control bypass attempts were detected. Ensure authorization checks are "
            "performed server-side and never derived from model output."))

    if _has("code_execution"):
        recs.append((1, "Block Command/Code Injection",
            "Code-execution patterns were detected. Do not execute model outputs as commands, "
            "and sandbox any code generation or parsing pipelines."))

    if _has("dos"):
        recs.append((3, "Limit Output Size and Runtime",
            "Denial-of-service prompts were detected. Enforce output caps, timeouts, and "
            "rate limits to prevent resource exhaustion."))

    if _has("multi_turn"):
        recs.append((3, "Reset Instruction State per Turn",
            "Multi-turn persistence attempts were detected. Clear transient instructions "
            "between turns and avoid storing untrusted memory."))

    # Fallback if no specific rules fired
    if not recs and report.findings:
        recs.append((2, "Investigate Detected Prompt Injection Signals",
            "One or more prompt-injection patterns triggered during the scan. Review the "
            "findings table and tighten input handling and instruction hierarchy controls."))

    if not recs and not report.findings:
        story.append(Paragraph(
            "No critical patterns were detected in this scan. Continue to monitor regularly "
            "and ensure the YAML rule set is kept up to date with emerging threat patterns.",
            st["body"],
        ))
        return story

    # Sort by priority then render
    recs.sort(key=lambda x: x[0])
    priority_labels = {1: ("CRITICAL ACTION", colors.HexColor("#7F1D1D")),
                       2: ("IMPORTANT", colors.HexColor("#EF4444")),
                       3: ("ADVISORY", colors.HexColor("#F59E0B"))}

    for idx, (pri, title, body) in enumerate(recs, 1):
        p_label, p_color = priority_labels.get(pri, ("ADVISORY", _BLUE))
        badge_tbl = Table([[
            Paragraph(f'<font color="white"><b>{p_label}</b></font>',
                      ParagraphStyle("pb", fontName="Helvetica-Bold", fontSize=7.5,
                                     textColor=_WHITE, alignment=TA_CENTER)),
            Paragraph(f'<b>{idx}. {title}</b>', st["recommend_title"]),
        ]], colWidths=[28 * mm, 149 * mm])
        badge_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), p_color),
            ("BACKGROUND", (1, 0), (1, 0), _LIGHT_GRAY),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        body_para = Paragraph(body, st["recommend_body"])
        story.append(KeepTogether([badge_tbl, body_para, Spacer(1, 2 * mm)]))

    return story


def _rules_appendix(report: ScanReport, st: dict) -> list:
    """Appendix: full rules inventory from rules_info."""
    story: list = []
    if not report.rules_info:
        return story

    story.append(PageBreak())
    story.append(Paragraph("Appendix — Active Rules Inventory", st["h1"]))
    story.append(HRFlowable(width="100%", thickness=1, color=_BLUE_LIGHT, spaceAfter=6))
    summary_parts = [
        f"Rules file: <b>{report.rules_info.filename}</b>",
        f"Prompt-injection rules: <b>{report.rules_info.text_scan_rule_count}</b>",
        f"Total: <b>{report.rules_info.total_rule_count}</b>",
    ]
    if report.rules_info.context_rule_count:
        summary_parts.insert(1, f"Context rules: <b>{report.rules_info.context_rule_count}</b>")
    story.append(Paragraph("  ·  ".join(summary_parts), st["body"]))
    story.append(Spacer(1, 3 * mm))

    if report.rules_info.context_rules:
        story.append(Paragraph("Context (Pattern) Rules", st["h2"]))
        h = [Paragraph(x, st["tbl_header"]) for x in
             ["Rule Name", "Severity", "Weight", "Patterns", "Enabled"]]
        rows = [h]
        for i, r in enumerate(report.rules_info.context_rules):
            sev_col = _SEV_COLORS.get(r.severity, _MID_GRAY)
            rows.append([
                Paragraph(r.name, st["tbl_cell"]),
                Paragraph(f'<font color="{sev_col.hexval()}"><b>{r.severity}</b></font>',
                          st["tbl_cell_center"]),
                Paragraph(str(r.weight), st["tbl_cell_center"]),
                Paragraph(str(r.pattern_count), st["tbl_cell_center"]),
                Paragraph("✓" if r.enabled else "✗", st["tbl_cell_center"]),
            ])
        tbl = Table(rows, colWidths=[90 * mm, 22 * mm, 22 * mm, 22 * mm, 21 * mm],
                    repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _BLUE),
            ("TEXTCOLOR", (0, 0), (-1, 0), _WHITE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_LIGHT_GRAY, _WHITE]),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("BOX", (0, 0), (-1, -1), 0.5, _MID_GRAY),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, _MID_GRAY),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 4 * mm))

    if report.rules_info.text_scan_rules:
        story.append(Paragraph("Prompt-Injection Rules (Text-Scan)", st["h2"]))
        h = [Paragraph(x, st["tbl_header"]) for x in
             ["Rule ID", "Category", "Severity", "Weight", "Enabled", "Description"]]
        rows = [h]
        for i, r in enumerate(report.rules_info.text_scan_rules):
            sev_col = _SEV_COLORS.get(r.severity, _MID_GRAY)
            rows.append([
                Paragraph(r.id, st["tbl_cell"]),
                Paragraph(r.category.upper(), st["tbl_cell_center"]),
                Paragraph(f'<font color="{sev_col.hexval()}"><b>{r.severity}</b></font>',
                          st["tbl_cell_center"]),
                Paragraph(str(r.weight), st["tbl_cell_center"]),
                Paragraph("✓" if r.enabled else "✗", st["tbl_cell_center"]),
                Paragraph(r.description or "—", st["body_sm"]),
            ])
        tbl = Table(rows,
                    colWidths=[38 * mm, 22 * mm, 16 * mm, 16 * mm, 14 * mm, 71 * mm],
                    repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _TEAL),
            ("TEXTCOLOR", (0, 0), (-1, 0), _WHITE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_LIGHT_GRAY, _WHITE]),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("ALIGN", (5, 0), (5, -1), "LEFT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("BOX", (0, 0), (-1, -1), 0.5, _MID_GRAY),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, _MID_GRAY),
        ]))
        story.append(tbl)

    return story


def _dashboard_rollup_section(dashboard_payload: Optional[dict[str, Any]], st: dict) -> list:
    """Append dashboard rollup values and scan table into the executive PDF."""
    if not dashboard_payload:
        return []

    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _parse_iso_timestamp(raw: Any) -> Optional[datetime]:
        if not isinstance(raw, str) or not raw.strip():
            return None
        normal = raw.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normal)
        except ValueError:
            return None

    def _format_rollup_datetime(raw: Any) -> str:
        if isinstance(raw, datetime):
            parsed = raw
        else:
            parsed = _parse_iso_timestamp(raw)

        if parsed is None:
            return str(raw) if raw is not None else "-"

        # Keep rollup report timestamps at minute precision.
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc)
        return parsed.strftime("%Y-%m-%d %H:%M")

    def _collect_rule_ids(rows: list[dict[str, Any]]) -> set[str]:
        rule_ids: set[str] = set()
        for row in rows:
            for rule in row.get("rule_explanations", []):
                rid = str(rule.get("rule_id", "")).strip().lower()
                if rid:
                    rule_ids.add(rid)
        return rule_ids

    def _has_integration_source(rows: list[dict[str, Any]]) -> bool:
        markers = ("integration", "connector", "plugin", "api", "tool", "workflow", "agent", "external")
        for row in rows:
            source = str(row.get("source", "")).lower()
            if any(marker in source for marker in markers):
                return True
        return False

    def _trend_summary(rows: list[dict[str, Any]]) -> str:
        points: list[tuple[datetime, float]] = []
        for row in rows:
            parsed = _parse_iso_timestamp(row.get("date"))
            if parsed is None:
                continue
            points.append((parsed, _safe_float(row.get("score"), 0.0)))

        if len(points) < 2:
            return "Trend insight unavailable (need at least two dated scans)."

        points.sort(key=lambda item: item[0])
        delta = points[-1][1] - points[0][1]
        abs_delta = abs(delta)
        if abs_delta < 2.0:
            direction = "stable"
        elif delta > 0:
            direction = "rising"
        else:
            direction = "improving"
        return f"Risk trend is {direction} over available scan history (change: {delta:+.2f})."

    def _priority_actions(
        summary_data: dict[str, Any],
        distribution_data: dict[str, Any],
        rows: list[dict[str, Any]],
    ) -> list[tuple[str, str, str, str, str]]:
        actions: list[tuple[str, str, str, str, str]] = []
        used_titles: set[str] = set()
        rules = _collect_rule_ids(rows)
        critical = _safe_int(distribution_data.get("critical"))
        high = _safe_int(distribution_data.get("high"))
        avg_risk = _safe_float(summary_data.get("average_risk"))
        top_scan = None
        if rows:
            top_scan = max(rows, key=lambda row: _safe_float(row.get("score"), 0.0))

        def add(priority: str, title: str, owner: str, due: str, reason: str) -> None:
            if title in used_titles:
                return
            used_titles.add(title)
            actions.append((priority, title, owner, due, reason))

        if critical > 0:
            top_name = str(top_scan.get("source", "top target")) if top_scan else "top target"
            add(
                "P1",
                "Contain critical prompt-injection exposure",
                "Security Lead",
                "24h",
                f"{critical} critical targets found; start with {top_name}.",
            )

        if critical + high > 0:
            add(
                "P1",
                "Assign owners to highest-risk targets",
                "Engineering Manager",
                "48h",
                f"High+critical target count is {critical + high}; owner accountability is required.",
            )

        if any(rule.startswith("access_control") or rule.startswith("tool_misuse") for rule in rules):
            add(
                "P1",
                "Harden access control and tool permissions",
                "Platform Owner",
                "7d",
                "Signals indicate privilege or workflow bypass attempts.",
            )

        if any(rule.startswith("system_prompt_extraction") or rule.startswith("data_exfil") for rule in rules):
            add(
                "P1",
                "Add response redaction and data guardrails",
                "AppSec",
                "7d",
                "System prompt and sensitive-data extraction patterns were detected.",
            )

        if any(rule.startswith("instruction_override") or rule.startswith("role_confusion") for rule in rules):
            add(
                "P2",
                "Strengthen instruction hierarchy controls",
                "LLM Product Owner",
                "14d",
                "Prompt attempts to override role/instructions are present.",
            )

        if _has_integration_source(rows):
            add(
                "P2",
                "Review cross-system prompt trust boundaries",
                "Platform Security",
                "14d",
                "Portfolio includes integration-oriented sources where indirect prompt paths can bypass controls.",
            )

        if avg_risk >= 40.0:
            add(
                "P2",
                "Run AI red-team prompt simulation",
                "AppSec",
                "14d",
                "Portfolio average risk is medium or above and warrants targeted adversarial prompt testing.",
            )

        add(
            "P3",
            "Publish governance evidence snapshot",
            "Governance Lead",
            "30d",
            "Capture policy mappings, remediation ownership, and closure evidence for leadership and audit workflows.",
        )

        return actions[:5]

    def _control_health_rows(
        summary_data: dict[str, Any],
        distribution_data: dict[str, Any],
        rows: list[dict[str, Any]],
    ) -> list[tuple[str, str, str, str]]:
        rules = _collect_rule_ids(rows)
        critical = _safe_int(distribution_data.get("critical"))
        high = _safe_int(distribution_data.get("high"))

        def status(condition: bool, good: str = "Monitor", bad: str = "Needs Attention") -> str:
            return bad if condition else good

        governance_risk = any(
            rid.startswith("instruction_override")
            or rid.startswith("role_confusion")
            or rid.startswith("system_prompt_extraction")
            for rid in rules
        )
        access_risk = any(rid.startswith("access_control") or rid.startswith("tool_misuse") for rid in rules)
        exfil_risk = any(rid.startswith("data_exfil") or rid.startswith("system_prompt_extraction") for rid in rules)
        prompt_injection_risk = any(
            rid.startswith("instruction_override")
            or rid.startswith("role_confusion")
            or rid.startswith("indirect_injection")
            for rid in rules
        )
        integration_risk = _has_integration_source(rows) or any(rid.startswith("indirect_injection") for rid in rules)
        evidence_gap = (critical + high) > 0 and len(rows) < 2

        return [
            (
                "Prompt Injection Prevention",
                status(prompt_injection_risk),
                "Direct/indirect prompt-injection family activity",
                "Deploy layered prompt sanitization and deny high-risk instruction patterns before execution.",
            ),
            (
                "Instruction Hierarchy Governance",
                status(governance_risk),
                "Override and role-reassignment attempts observed",
                "Enforce immutable system/developer policy precedence with explicit conflict handling.",
            ),
            (
                "Sensitive Data & System Prompt Protection",
                status(exfil_risk),
                "System-prompt extraction and secret exfiltration signals",
                "Apply output filtering, secret redaction, and blocked token classes for responses.",
            ),
            (
                "Tool Invocation Governance",
                status(access_risk),
                "Tool misuse and authorization bypass indicators",
                "Gate dangerous tool actions with policy checks and human approval for high-risk operations.",
            ),
            (
                "Access Control Enforcement",
                status(access_risk),
                "Access-control bypass prompts detected",
                "Keep authorization server-side and scope least-privilege access for model-integrated workflows.",
            ),
            (
                "Cross-System Prompt Trust Boundaries",
                status(integration_risk),
                "Integration-oriented sources in scope",
                "Validate untrusted inputs from connectors/plugins before they reach model orchestration layers.",
            ),
            (
                "AI Governance Evidence & Auditability",
                "Needs Attention" if evidence_gap else ("Review Due" if (critical + high) > 0 else "Monitor"),
                f"High+critical targets: {critical + high}; scans observed: {len(rows)}",
                "Maintain policy-to-finding traceability, owner assignment, and remediation evidence in each cycle.",
            ),
        ]

    summary = dashboard_payload.get("executive_summary", {})
    distribution = dashboard_payload.get("risk_distribution", {})
    scans = dashboard_payload.get("scans", [])

    now_utc = datetime.now(timezone.utc)
    daily_label = f"Daily Project Update  {now_utc.strftime('%Y-%m-%d %H:%M')}"

    story: list = [
        Spacer(1, 6 * mm),
        Paragraph(daily_label, st["h2"]),
        Paragraph("Portfolio Rollup", st["h1"]),
        HRFlowable(width="100%", thickness=1, color=_BLUE_LIGHT, spaceAfter=6),
    ]

    summary_rows = [
        [
            Paragraph("Combined Portfolio Risk", st["tbl_header"]),
            Paragraph("Highest Risk", st["tbl_header"]),
            Paragraph("Critical Count", st["tbl_header"]),
            Paragraph("Total Scans", st["tbl_header"]),
        ],
        [
            Paragraph(f"{float(summary.get('average_risk', 0.0)):.2f}", st["tbl_cell_center"]),
            Paragraph(f"{float(summary.get('highest_risk', 0.0)):.2f}", st["tbl_cell_center"]),
            Paragraph(str(int(summary.get("critical_count", 0))), st["tbl_cell_center"]),
            Paragraph(str(int(summary.get("total_scans", 0))), st["tbl_cell_center"]),
        ],
    ]
    summary_table = Table(summary_rows, colWidths=[42 * mm, 42 * mm, 42 * mm, 42 * mm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), _WHITE),
        ("BACKGROUND", (0, 1), (-1, 1), _LIGHT_GRAY),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BOX", (0, 0), (-1, -1), 0.5, _MID_GRAY),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, _MID_GRAY),
    ]))
    story.extend([summary_table, Spacer(1, 4 * mm), Paragraph("Risk Distribution", st["h2"])])

    distribution_rows = [
        [
            Paragraph("Low", st["tbl_header"]),
            Paragraph("Medium", st["tbl_header"]),
            Paragraph("High", st["tbl_header"]),
            Paragraph("Critical", st["tbl_header"]),
        ],
        [
            Paragraph(str(int(distribution.get("low", 0))), st["tbl_cell_center"]),
            Paragraph(str(int(distribution.get("medium", 0))), st["tbl_cell_center"]),
            Paragraph(str(int(distribution.get("high", 0))), st["tbl_cell_center"]),
            Paragraph(str(int(distribution.get("critical", 0))), st["tbl_cell_center"]),
        ],
    ]
    distribution_table = Table(distribution_rows, colWidths=[42 * mm, 42 * mm, 42 * mm, 42 * mm])
    distribution_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _TEAL),
        ("TEXTCOLOR", (0, 0), (-1, 0), _WHITE),
        ("BACKGROUND", (0, 1), (-1, 1), _WHITE),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BOX", (0, 0), (-1, -1), 0.5, _MID_GRAY),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, _MID_GRAY),
    ]))
    top_scan = None
    if scans:
        top_scan = max(scans, key=lambda row: _safe_float(row.get("score"), 0.0))

    governance_context = (
        f"{_trend_summary(scans)} "
        f"Current portfolio average risk is {_safe_float(summary.get('average_risk'), 0.0):.2f}."
    )
    if top_scan is not None:
        governance_context += (
            f" Highest-risk target is {top_scan.get('source', '-')}, "
            f"score {_safe_float(top_scan.get('score'), 0.0):.2f}, "
            f"severity {str(top_scan.get('severity', '-')).upper()}."
        )

    story.extend([
        distribution_table,
        Spacer(1, 4 * mm),
        Paragraph("AI Governance Context", st["h2"]),
        Paragraph(
            "Valo focuses on AI governance posture by detecting prompt-injection attack paths, "
            "classifying severity, and prioritizing remediation across model-enabled workflows.",
            st["body"],
        ),
        Paragraph(
            "This portfolio rollup is designed for security engineering and governance leaders who need "
            "actionable ownership, policy alignment, and evidence-ready reporting.",
            st["body"],
        ),
        Paragraph(governance_context, st["body"]),
    ])

    actions = _priority_actions(summary, distribution, scans)
    story.extend([Spacer(1, 3 * mm), Paragraph("Priority Action Plan (Top 5)", st["h2"])])
    action_rows = [[
        Paragraph("Priority", st["tbl_header"]),
        Paragraph("Action", st["tbl_header"]),
        Paragraph("Owner", st["tbl_header"]),
        Paragraph("Due", st["tbl_header"]),
        Paragraph("Governance Reason", st["tbl_header"]),
    ]]
    for priority, action, owner, due, reason in actions:
        action_rows.append([
            Paragraph(priority, st["tbl_cell_center"]),
            Paragraph(action, st["tbl_cell"]),
            Paragraph(owner, st["tbl_cell_center"]),
            Paragraph(due, st["tbl_cell_center"]),
            Paragraph(reason, st["body_sm"]),
        ])

    action_table = Table(action_rows, colWidths=[12 * mm, 46 * mm, 24 * mm, 16 * mm, 76 * mm], repeatRows=1)
    action_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), _WHITE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_LIGHT_GRAY, _WHITE]),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("ALIGN", (2, 1), (3, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BOX", (0, 0), (-1, -1), 0.5, _MID_GRAY),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, _MID_GRAY),
    ]))
    story.append(action_table)

    control_rows = _control_health_rows(summary, distribution, scans)
    story.extend([Spacer(1, 3 * mm), Paragraph("Control Health Snapshot", st["h2"])])
    control_table_rows = [[
        Paragraph("Control Area", st["tbl_header"]),
        Paragraph("Status", st["tbl_header"]),
        Paragraph("Observed Signal", st["tbl_header"]),
        Paragraph("Recommended Next Step", st["tbl_header"]),
    ]]
    for area, control_status, signal, recommendation in control_rows:
        control_table_rows.append([
            Paragraph(area, st["tbl_cell"]),
            Paragraph(control_status, st["tbl_cell_center"]),
            Paragraph(signal, st["body_sm"]),
            Paragraph(recommendation, st["body_sm"]),
        ])

    control_table = Table(control_table_rows, colWidths=[44 * mm, 28 * mm, 42 * mm, 60 * mm], repeatRows=1)
    control_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _TEAL),
        ("TEXTCOLOR", (0, 0), (-1, 0), _WHITE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_LIGHT_GRAY, _WHITE]),
        ("ALIGN", (1, 1), (1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BOX", (0, 0), (-1, -1), 0.5, _MID_GRAY),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, _MID_GRAY),
    ]))
    story.extend([
        control_table,
        Spacer(1, 2 * mm),
        Paragraph(
            "Note: control statuses are inferred from scan findings and should be validated against "
            "governance evidence (policy mappings, approval checkpoints, and remediation closure records).",
            st["body_sm"],
        ),
        Spacer(1, 3 * mm),
        Paragraph("Risk by Target", st["h2"]),
    ])

    if scans:
        scan_rows = [[
            Paragraph("Scan ID", st["tbl_header"]),
            Paragraph("Source", st["tbl_header"]),
            Paragraph("Score", st["tbl_header"]),
            Paragraph("Severity", st["tbl_header"]),
            Paragraph("Date", st["tbl_header"]),
        ]]
        for scan in scans:
            scan_rows.append([
                Paragraph(str(scan.get("scan_id", "-")), st["body_sm"]),
                Paragraph(str(scan.get("source", "-")), st["body_sm"]),
                Paragraph(f"{float(scan.get('score', 0.0)):.2f}", st["tbl_cell_center"]),
                Paragraph(str(scan.get("severity", "-")), st["tbl_cell_center"]),
                Paragraph(_format_rollup_datetime(scan.get("date", "-")), st["body_sm"]),
            ])

        scans_table = Table(
            scan_rows,
            colWidths=[32 * mm, 34 * mm, 20 * mm, 24 * mm, 62 * mm],
            repeatRows=1,
        )
        scans_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _BLUE),
            ("TEXTCOLOR", (0, 0), (-1, 0), _WHITE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_LIGHT_GRAY, _WHITE]),
            ("ALIGN", (2, 1), (3, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("BOX", (0, 0), (-1, -1), 0.5, _MID_GRAY),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, _MID_GRAY),
        ]))
        story.append(scans_table)
    else:
        story.append(Paragraph("No scans available for this report.", st["body"]))

    return story


# ── Public entry point ────────────────────────────────────────────────────────

def generate_executive_pdf(
    report: ScanReport,
    dashboard_payload: Optional[dict[str, Any]] = None,
    include_scan_sections: bool = True,
) -> bytes:
    """Generate a professional executive-grade PDF from *report*.

    Returns the PDF as raw bytes ready for streaming.
    """
    try:
        buf = io.BytesIO()
        w, h = A4
        st = _make_styles()

        ts_str = (report.timestamp.strftime("%Y-%m-%d %H:%M UTC")
                  if report.timestamp else datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
        scan_id_short = str(report.scan_id)[:18] + "…"
        company_name, logo_bytes = _extract_branding(report)
        report_title = f"{_DEFAULT_COMPANY_NAME} Security Scan Report"
        if company_name:
            report_title = f"{company_name} Security Scan Report - {_DEFAULT_COMPANY_NAME}"
        logo_flowable = None
        if logo_bytes:
            try:
                logo_flowable = _build_logo_flowable(logo_bytes, max_w=45 * mm, max_h=16 * mm)
            except Exception:
                logger.warning("Failed to decode logo image; proceeding without logo", exc_info=True)
                logo_flowable = None
        if logo_flowable is None:
            logo_flowable = _DefaultLogo()

        # ── Document with two page templates ─────────────────────────────────
        cover_frame = Frame(0, 0, w, h, leftPadding=18 * mm, rightPadding=18 * mm,
                            topPadding=0, bottomPadding=15 * mm, id="cover")
        body_frame  = Frame(0, 0, w, h, leftPadding=18 * mm, rightPadding=18 * mm,
                            topPadding=32 * mm, bottomPadding=18 * mm, id="body")

        doc = BaseDocTemplate(
            buf,
            pagesize=A4,
            pageTemplates=[
                PageTemplate(id="cover", frames=[cover_frame],
                             onPage=_make_cover_cb(scan_id_short, ts_str)),
                PageTemplate(id="body",  frames=[body_frame],
                             onPage=_make_page_cb(scan_id_short, ts_str, report_title)),
            ],
        )

        # ── Story assembly ────────────────────────────────────────────────────
        story: list = []
        story += _cover_section(report, st, company_name, logo_flowable)

        if include_scan_sections:
            story += _executive_summary(report, st)
            story += _risk_breakdown(report, st)
            story += _matched_rules_section(report, st)
            story += _findings_section(report, st)
            story += _recommendations_section(report, st)
            story += _rules_appendix(report, st)

        if dashboard_payload:
            story += _dashboard_rollup_section(dashboard_payload, st)

        doc.build(story)
        pdf_bytes = buf.getvalue()
        logger.debug("Executive PDF generated: %d bytes, scan_id=%s",
                     len(pdf_bytes), report.scan_id)
        return pdf_bytes

    except Exception as e:
        logger.error("Executive PDF generation failed", exc_info=True)
        raise ServiceError(
            message="Executive PDF generation failed",
            detail={"error": str(e)},
        ) from e
