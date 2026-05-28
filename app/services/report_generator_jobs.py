"""Dispatch table for the Phase 4 reporting pipeline.

Every report kind exposed by the API or the weekly scheduler is a thin
adapter around one of the existing report engines:

- :func:`app.services.executive_metrics.export` for executive PDFs/CSVs.
- :func:`app.services.pdf_report_generator.generate_executive_pdf`
  combined with :func:`app.services.dashboard.build_dashboard_payload`
  for portfolio rollup PDFs (mirroring the inline logic of
  ``GET /report/pdf/rollup``).
- :func:`app.services.dashboard.get_scan_report` +
  :func:`app.services.pdf_report_generator.generate_executive_pdf`
  for per-scan PDFs (mirrors ``GET /report/pdf/scan/{scan_id}``).

The single entrypoint is :func:`run_kind` which returns the raw bytes
together with a default filename and the lower-cased format, so callers
can either stream the payload directly or hand it to
:func:`app.services.report_store.save_report` to persist.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from app.core.exceptions import ServiceError
from app.core.logging import get_logger
from app.schemas import ScanReport
from app.services import executive_metrics
from app.services.dashboard import build_dashboard_payload, get_scan_report
from app.services.pdf_report_generator import generate_executive_pdf

logger = get_logger(__name__)


class ReportJobError(ServiceError):
    """Raised when a report kind cannot be produced."""


@dataclass(frozen=True)
class JobResult:
    """Output of a single report job run."""

    payload: bytes
    filename: str
    format: str
    window: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class ReportKind:
    """Metadata describing a report kind for the API + UI catalogue."""

    name: str
    label: str
    format: str
    window: Optional[str]
    description: str
    requires_scan_id: bool = False


REGISTRY: dict[str, ReportKind] = {
    "executive_pdf_7d": ReportKind(
        name="executive_pdf_7d",
        label="Executive summary (7-day, PDF)",
        format="pdf",
        window="7d",
        description=(
            "Executive KPI summary rendered as a branded PDF, sourced "
            "from the executive metrics rollup over the last 7 days."
        ),
    ),
    "executive_csv_7d": ReportKind(
        name="executive_csv_7d",
        label="Executive summary (7-day, CSV)",
        format="csv",
        window="7d",
        description=(
            "Executive KPI summary as CSV. Same data source as the PDF "
            "variant; useful for spreadsheet pivoting."
        ),
    ),
    "executive_pdf_30d": ReportKind(
        name="executive_pdf_30d",
        label="Executive summary (30-day, PDF)",
        format="pdf",
        window="30d",
        description=(
            "30-day executive KPI summary PDF for monthly board / "
            "leadership review."
        ),
    ),
    "executive_csv_30d": ReportKind(
        name="executive_csv_30d",
        label="Executive summary (30-day, CSV)",
        format="csv",
        window="30d",
        description="30-day executive KPI summary as CSV.",
    ),
    "portfolio_rollup_pdf": ReportKind(
        name="portfolio_rollup_pdf",
        label="Portfolio rollup (PDF)",
        format="pdf",
        window=None,
        description=(
            "Portfolio rollup PDF assembled from the in-memory dashboard "
            "payload. Mirrors GET /report/pdf/rollup."
        ),
    ),
    "scan_pdf": ReportKind(
        name="scan_pdf",
        label="Scan report (PDF)",
        format="pdf",
        window=None,
        description=(
            "Detailed PDF for a single scan_id. Requires a scan_id "
            "parameter at run time."
        ),
        requires_scan_id=True,
    ),
}


def list_kinds() -> list[ReportKind]:
    """Return the catalogue of supported report kinds (sorted by name)."""
    return [REGISTRY[name] for name in sorted(REGISTRY)]


def get_kind(name: str) -> ReportKind:
    try:
        return REGISTRY[name]
    except KeyError as exc:
        raise ReportJobError(
            message=f"unknown report kind: {name!r}",
            detail={"valid": sorted(REGISTRY)},
        ) from exc


def run_kind(
    name: str,
    *,
    scan_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> JobResult:
    """Generate the report bytes for *name*.

    Raises :class:`ReportJobError` if the kind is unknown or the
    underlying engine fails. Otherwise returns the bytes plus a default
    filename suitable for ``Content-Disposition``.
    """
    kind = get_kind(name)
    runner = _RUNNERS.get(kind.name)
    if runner is None:  # pragma: no cover - registry / runner drift safeguard
        raise ReportJobError(
            message=f"no runner registered for report kind {kind.name!r}",
        )
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        return runner(kind, stamp=stamp, scan_id=scan_id)
    except ReportJobError:
        raise
    except ServiceError as exc:
        raise ReportJobError(
            message=f"report kind {kind.name!r} failed: {exc.message}",
            detail=exc.detail,
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("report_job_failed kind=%s", kind.name)
        raise ReportJobError(
            message=f"report kind {kind.name!r} failed: {exc}",
        ) from exc


def _executive_runner(
    kind: ReportKind,
    *,
    stamp: datetime,
    scan_id: Optional[str],
) -> JobResult:
    if kind.window is None:
        raise ReportJobError(
            message=f"report kind {kind.name!r} is missing a window",
        )
    payload, filename = executive_metrics.export(
        window=kind.window,  # type: ignore[arg-type]
        fmt=kind.format,  # type: ignore[arg-type]
    )
    return JobResult(
        payload=payload,
        filename=filename,
        format=kind.format,
        window=kind.window,
        metadata={"engine": "executive_metrics", "stamp": stamp.isoformat()},
    )


def _portfolio_rollup_runner(
    kind: ReportKind,
    *,
    stamp: datetime,
    scan_id: Optional[str],
) -> JobResult:
    payload = build_dashboard_payload()
    summary = payload.get("executive_summary", {})
    placeholder_report = ScanReport(
        risk_score=float(summary.get("average_risk", 0.0)),
        max_severity_found=0,
        severity_ceiling_applied=False,
        input_prompt="",
        matched_rule_details=[],
        findings=[],
        matched_rules=[],
        metadata={
            "target": "portfolio-rollup",
            "input_kind": "rollup",
            "content_length": 0,
            "detection_flags": [],
        },
    )
    pdf_bytes = generate_executive_pdf(
        placeholder_report,
        dashboard_payload=payload,
        include_scan_sections=False,
    )
    filename = f"valo-portfolio-rollup-{stamp.strftime('%Y%m%d')}.pdf"
    return JobResult(
        payload=pdf_bytes,
        filename=filename,
        format=kind.format,
        window=None,
        metadata={
            "engine": "portfolio_rollup",
            "scan_count": int(summary.get("total_scans", 0) or 0),
            "stamp": stamp.isoformat(),
        },
    )


def _scan_pdf_runner(
    kind: ReportKind,
    *,
    stamp: datetime,
    scan_id: Optional[str],
) -> JobResult:
    if not scan_id:
        raise ReportJobError(
            message="report kind 'scan_pdf' requires scan_id",
            detail={"missing": ["scan_id"]},
        )
    report = get_scan_report(scan_id)
    if report is None:
        raise ReportJobError(
            message=f"scan_id not found: {scan_id!r}",
            detail={"scan_id": scan_id},
        )
    pdf_bytes = generate_executive_pdf(report)
    filename = f"valo-scan-{str(scan_id)[:8]}-{stamp.strftime('%Y%m%d')}.pdf"
    return JobResult(
        payload=pdf_bytes,
        filename=filename,
        format=kind.format,
        window=None,
        metadata={
            "engine": "scan_pdf",
            "scan_id": str(scan_id),
            "stamp": stamp.isoformat(),
        },
    )


_Runner = Callable[..., JobResult]
_RUNNERS: dict[str, _Runner] = {
    "executive_pdf_7d": _executive_runner,
    "executive_csv_7d": _executive_runner,
    "executive_pdf_30d": _executive_runner,
    "executive_csv_30d": _executive_runner,
    "portfolio_rollup_pdf": _portfolio_rollup_runner,
    "scan_pdf": _scan_pdf_runner,
}


__all__ = [
    "JobResult",
    "REGISTRY",
    "ReportJobError",
    "ReportKind",
    "get_kind",
    "list_kinds",
    "run_kind",
]
