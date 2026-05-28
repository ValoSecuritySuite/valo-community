"""Service layer for the Executive Dashboard.

Builds :class:`ExecutiveSummary`, :class:`ExecutiveTrends`, and PDF/CSV
exports from the SQLite rollups produced by
:mod:`app.services.executive_aggregator` together with live policy /
playbook configuration.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable, Optional

from app.core.config import settings
from app.core.exceptions import ServiceError
from app.core.logging import get_logger
from app.playbooks.store import list_playbooks as list_playbooks_on_disk
from app.schemas import (
    AutomationKpi,
    ComplianceTagRollup,
    CoverageKpi,
    ExecutiveBucket,
    ExecutiveExportFormat,
    ExecutiveSummary,
    ExecutiveTrendPoint,
    ExecutiveTrends,
    ExecutiveTrendSeries,
    ExecutiveWindow,
    ExposureKpi,
    RiskKpi,
    TopOffender,
)
from app.services import executive_store
from app.services.executive_aggregator import (
    DIM_ACTION,
    DIM_DECISION,
    DIM_DIRECTION,
    DIM_GLOBAL,
    DIM_MTTA,
    DIM_PLAYBOOK,
    DIM_POLICY,
    DIM_SEVERITY,
    SOURCE_ENFORCEMENT,
    SOURCE_PIPELINE,
    SOURCE_PLAYBOOKS,
)
from app.services.executive_store import (
    BUCKET_SIZE_1D,
    BUCKET_SIZE_1H,
    BUCKET_SIZE_5M,
    aggregate_to_window,
    query_buckets,
)
from app.services.policy_store import list_policies as list_policies_on_disk

logger = get_logger(__name__)

WINDOW_TO_SECONDS: dict[str, int] = {
    "24h": 24 * 3600,
    "7d": 7 * 86400,
    "30d": 30 * 86400,
    "90d": 90 * 86400,
}

BUCKET_TO_SIZE: dict[str, int] = {
    "5m": BUCKET_SIZE_5M,
    "1h": BUCKET_SIZE_1H,
    "1d": BUCKET_SIZE_1D,
}

DEFAULT_TREND_METRICS: tuple[str, ...] = (
    "requests",
    "blocked",
    "playbooks_fired",
    "actions_executed",
    "risk_score_sum",
)

def _window_seconds(window: ExecutiveWindow) -> int:
    try:
        return WINDOW_TO_SECONDS[window]
    except KeyError as exc:
        raise ServiceError(
            message=f"Unsupported window: {window}",
            detail={"valid": list(WINDOW_TO_SECONDS)},
        ) from exc


def _bucket_size(bucket: ExecutiveBucket) -> int:
    try:
        return BUCKET_TO_SIZE[bucket]
    except KeyError as exc:
        raise ServiceError(
            message=f"Unsupported bucket: {bucket}",
            detail={"valid": list(BUCKET_TO_SIZE)},
        ) from exc


def _pick_bucket_for_window(window: ExecutiveWindow) -> int:
    """Return the natural bucket size for the requested window."""
    if window == "24h":
        return BUCKET_SIZE_5M
    if window == "7d":
        return BUCKET_SIZE_1H
    return BUCKET_SIZE_1D


def _coerce_bucket_for_summary(window: ExecutiveWindow) -> int:
    """For summaries we always use the cheapest viable bucket."""
    return _pick_bucket_for_window(window)


def _exposure_from_rows(
    aggregated: dict[tuple[str, str, str, str], tuple[float, int]],
) -> ExposureKpi:
    total = blocked = would_block = 0
    by_decision: dict[str, int] = {}
    by_direction: dict[str, int] = {}
    blocking_by_policy: dict[str, int] = {}

    for (source, dim_key, dim_value, metric), (value, _count) in aggregated.items():
        if source != SOURCE_ENFORCEMENT:
            continue
        ivalue = int(value)
        if dim_key == DIM_GLOBAL:
            if metric == "requests":
                total += ivalue
            elif metric == "blocked":
                blocked += ivalue
            elif metric == "would_block":
                would_block += ivalue
        elif dim_key == DIM_DECISION and metric == "count":
            by_decision[dim_value] = by_decision.get(dim_value, 0) + ivalue
        elif dim_key == DIM_DIRECTION and metric == "count":
            by_direction[dim_value] = by_direction.get(dim_value, 0) + ivalue
        elif dim_key == DIM_POLICY and metric == "blocked":
            blocking_by_policy[dim_value] = (
                blocking_by_policy.get(dim_value, 0) + ivalue
            )

    block_rate = (blocked / total) if total > 0 else 0.0
    top_policy_id: Optional[str] = None
    top_policy_count = 0
    if blocking_by_policy:
        top_policy_id, top_policy_count = max(
            blocking_by_policy.items(), key=lambda item: item[1]
        )

    return ExposureKpi(
        total_requests=total,
        blocked=blocked,
        would_block=would_block,
        block_rate=round(block_rate, 4),
        by_decision=by_decision,
        by_direction=by_direction,
        top_blocking_policy_id=top_policy_id,
        top_blocking_policy_count=top_policy_count,
    )


def _risk_from_rows(
    aggregated: dict[tuple[str, str, str, str], tuple[float, int]],
) -> RiskKpi:
    risk_sum = 0.0
    risk_count = 0
    critical = 0
    severity: dict[str, int] = {}

    for (source, dim_key, dim_value, metric), (value, count) in aggregated.items():
        if source != SOURCE_PIPELINE:
            continue
        if dim_key == DIM_GLOBAL and metric == "risk_score_sum":
            risk_sum += float(value)
            risk_count += int(count)
        elif dim_key == DIM_GLOBAL and metric == "critical_findings":
            critical += int(value)
        elif dim_key == DIM_SEVERITY and metric == "count":
            severity[dim_value] = severity.get(dim_value, 0) + int(value)

    avg = (risk_sum / risk_count) if risk_count > 0 else 0.0
    p95 = _estimate_p95(avg=avg, severity=severity)
    return RiskKpi(
        average_risk_score=round(avg, 2),
        p95_risk_score=round(p95, 2),
        critical_findings=critical,
        severity_distribution=severity,
    )


# Lower bound of each severity band as defined by ``_safe_severity`` in the
# aggregator. Used as a floor when estimating p95 from a histogram so the
# UI never displays "average=0, p95=10" (or any value > average) just because
# the band is named "minimal".
_SEVERITY_BAND_LOWER_BOUND: dict[str, float] = {
    "minimal": 0.0,
    "low": 20.0,
    "medium": 40.0,
    "high": 60.0,
    "critical": 80.0,
}


def severity_to_score(level: str) -> float:
    """Lower bound of *level*'s severity band; 0 for unknown labels."""
    return _SEVERITY_BAND_LOWER_BOUND.get(level, 0.0)


def _estimate_p95(*, avg: float, severity: dict[str, int]) -> float:
    """Best-effort p95 from aggregate-only data.

    We do not persist per-scan risk scores in the rollup, only ``sum`` and a
    severity histogram, so a true percentile is impossible. Instead we:

    1. Find the highest severity band that has any scans.
    2. Use that band's lower bound as a floor.
    3. Return ``max(avg, floor)`` so the displayed p95 can never be lower
       than the average and never pretend to be higher than the worst band
       observed.
    """
    if not severity:
        return avg
    populated = [level for level, n in severity.items() if n > 0]
    if not populated:
        return avg
    floor = max(severity_to_score(level) for level in populated)
    return max(avg, floor)


# Action statuses (see ``app.playbooks.schemas.ActionResult.status``) that
# count as a real action outcome for dashboard purposes. ``error`` is
# excluded because we don't want a flapping integration to inflate the
# "actions executed" tile.
_ACTION_OUTCOME_METRICS: frozenset[str] = frozenset(
    {"planned", "executed", "skipped"}
)


def _automation_from_rows(
    aggregated: dict[tuple[str, str, str, str], tuple[float, int]],
) -> AutomationKpi:
    events_total = 0
    playbooks_fired = 0
    actions_executed = 0
    actions_by_type: dict[str, int] = {}
    mtta_sum = 0.0
    mtta_count = 0

    for (source, dim_key, dim_value, metric), (value, count) in aggregated.items():
        if source != SOURCE_PLAYBOOKS:
            continue
        ivalue = int(value)
        if dim_key == DIM_GLOBAL and metric == "events_total":
            events_total += ivalue
        elif dim_key == DIM_GLOBAL and metric == "playbooks_fired":
            playbooks_fired += ivalue
        elif dim_key == DIM_PLAYBOOK and metric == "actions_executed":
            actions_executed += ivalue
        elif dim_key == DIM_ACTION and metric in _ACTION_OUTCOME_METRICS:
            # ActionResult.status is one of "planned" (dry-run), "executed",
            # "skipped", "error". The aggregator emits the row with metric
            # set to the status value, so we count any non-failure outcome
            # toward the per-action breakdown. Without this, a default-secure
            # deployment (dry_run=True) shows actions_executed > 0 but an
            # empty actions_by_type, which looks like a bug.
            actions_by_type[dim_value] = actions_by_type.get(dim_value, 0) + ivalue
        elif dim_key == DIM_MTTA and metric == "duration_ms_sum":
            mtta_sum += float(value)
            mtta_count += int(count)

    mtta = (mtta_sum / mtta_count) if mtta_count > 0 else 0.0
    return AutomationKpi(
        events_total=events_total,
        playbooks_fired=playbooks_fired,
        actions_executed=actions_executed,
        actions_by_type=actions_by_type,
        mean_time_to_action_ms=round(mtta, 2),
    )


def _coverage_kpi() -> CoverageKpi:
    try:
        policies = list_policies_on_disk()
    except Exception:
        logger.exception("executive_coverage_policies_failed")
        policies = []
    try:
        playbooks = list_playbooks_on_disk()
    except Exception:
        logger.exception("executive_coverage_playbooks_failed")
        playbooks = []

    enabled_policies = sum(1 for p in policies if p.enabled)
    enforce_policies = sum(1 for p in policies if p.enabled and p.enforce)
    enabled_playbooks = sum(1 for pb in playbooks if pb.enabled)
    playbooks_live = (
        enabled_playbooks
        if (settings.playbooks_enabled and not settings.playbooks_dry_run)
        else 0
    )
    return CoverageKpi(
        policies_total=len(policies),
        policies_enabled=enabled_policies,
        policies_enforce_mode=enforce_policies,
        playbooks_total=len(playbooks),
        playbooks_enabled=enabled_playbooks,
        playbooks_live=playbooks_live,
    )


def _compliance_rollups(
    aggregated: dict[tuple[str, str, str, str], tuple[float, int]],
) -> list[ComplianceTagRollup]:
    """Join policy / playbook tags onto enforcement matches and blocks."""
    try:
        policies = list_policies_on_disk()
    except Exception:
        logger.exception("executive_compliance_policies_failed")
        policies = []
    try:
        playbooks = list_playbooks_on_disk()
    except Exception:
        logger.exception("executive_compliance_playbooks_failed")
        playbooks = []

    policy_tags: dict[str, list[str]] = {p.id: list(p.tags or []) for p in policies}
    playbook_tags: dict[str, list[str]] = {
        pb.id: list(pb.tags or []) for pb in playbooks
    }

    matched_by_policy: dict[str, int] = defaultdict(int)
    blocked_by_policy: dict[str, int] = defaultdict(int)
    for (source, dim_key, dim_value, metric), (value, _count) in aggregated.items():
        if source != SOURCE_ENFORCEMENT or dim_key != DIM_POLICY:
            continue
        if metric == "matches":
            matched_by_policy[dim_value] += int(value)
        elif metric == "blocked":
            blocked_by_policy[dim_value] += int(value)

    tag_payload: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "policies": 0,
            "playbooks": 0,
            "matched_events": 0,
            "blocked_events": 0,
        }
    )
    for policy_id, tags in policy_tags.items():
        for tag in tags:
            tag_payload[tag]["policies"] += 1
            tag_payload[tag]["matched_events"] += matched_by_policy.get(policy_id, 0)
            tag_payload[tag]["blocked_events"] += blocked_by_policy.get(policy_id, 0)
    for _pb_id, tags in playbook_tags.items():
        for tag in tags:
            tag_payload[tag]["playbooks"] += 1

    rollups = [
        ComplianceTagRollup(
            tag=tag,
            policies=values["policies"],
            playbooks=values["playbooks"],
            matched_events=values["matched_events"],
            blocked_events=values["blocked_events"],
        )
        for tag, values in tag_payload.items()
    ]
    rollups.sort(
        key=lambda r: (
            -r.blocked_events,
            -r.matched_events,
            -(r.policies + r.playbooks),
            r.tag,
        )
    )
    return rollups


def _top_offenders(
    *,
    bucket_size_seconds: int,
    bucket_start_gte: int,
    bucket_start_lt: int,
    top_n: int = 10,
    db_path=None,
) -> list[TopOffender]:
    """Surface entities with the most denies in the window."""
    rows = query_buckets(
        bucket_size_seconds=bucket_size_seconds,
        bucket_start_gte=bucket_start_gte,
        bucket_start_lt=bucket_start_lt,
        source=SOURCE_ENFORCEMENT,
        dimension_key="subject",
        metric="deny_count",
        path=db_path,
    )
    aggregated: dict[str, dict[str, object]] = {}
    for row in rows:
        sid = str(row["dimension_value"])
        bucket = aggregated.setdefault(
            sid,
            {"deny": 0, "last_seen": 0},
        )
        bucket["deny"] = int(bucket["deny"]) + int(row["value"])
        if int(row["bucket_start"]) > int(bucket["last_seen"]):
            bucket["last_seen"] = int(row["bucket_start"]) + bucket_size_seconds

    out: list[TopOffender] = []
    for sid, payload in aggregated.items():
        if ":" in sid:
            stype, ident = sid.split(":", 1)
        else:
            stype, ident = "unknown", sid
        last_seen_ts = int(payload["last_seen"])
        last_seen_dt = (
            datetime.fromtimestamp(last_seen_ts, tz=timezone.utc)
            if last_seen_ts > 0
            else None
        )
        out.append(
            TopOffender(
                subject_type=stype,
                subject_id=ident,
                deny_count=int(payload["deny"]),
                last_seen=last_seen_dt,
            )
        )
    out.sort(key=lambda o: (-o.deny_count, o.subject_id))
    return out[:top_n]


def _window_bounds(window: ExecutiveWindow, *, now: Optional[float] = None) -> tuple[int, int]:
    end = int(now if now is not None else datetime.now(timezone.utc).timestamp())
    start = end - _window_seconds(window)
    return start, end


def summary(
    window: ExecutiveWindow = "7d",
    *,
    now: Optional[float] = None,
    db_path=None,
) -> ExecutiveSummary:
    """Return all KPI families for *window*."""
    bucket_size = _coerce_bucket_for_summary(window)
    start, end = _window_bounds(window, now=now)

    aggregated = aggregate_to_window(
        bucket_size_seconds=bucket_size,
        bucket_start_gte=start,
        bucket_start_lt=end,
        path=db_path,
    )

    return ExecutiveSummary(
        window=window,
        window_start=datetime.fromtimestamp(start, tz=timezone.utc),
        window_end=datetime.fromtimestamp(end, tz=timezone.utc),
        exposure=_exposure_from_rows(aggregated),
        risk=_risk_from_rows(aggregated),
        automation=_automation_from_rows(aggregated),
        coverage=_coverage_kpi(),
        compliance=_compliance_rollups(aggregated),
        top_offenders=_top_offenders(
            bucket_size_seconds=bucket_size,
            bucket_start_gte=start,
            bucket_start_lt=end,
            db_path=db_path,
        ),
    )


def _normalize_metrics(metrics: Optional[Iterable[str]]) -> list[str]:
    if metrics is None:
        return list(DEFAULT_TREND_METRICS)
    cleaned = [str(m).strip() for m in metrics if str(m).strip()]
    return cleaned or list(DEFAULT_TREND_METRICS)


def _series_key_for(metric: str) -> tuple[str, str, str]:
    """Map a trend metric name to ``(source, dimension_key, metric)``."""
    mapping: dict[str, tuple[str, str, str]] = {
        "requests": (SOURCE_ENFORCEMENT, DIM_GLOBAL, "requests"),
        "blocked": (SOURCE_ENFORCEMENT, DIM_GLOBAL, "blocked"),
        "would_block": (SOURCE_ENFORCEMENT, DIM_GLOBAL, "would_block"),
        "duration_ms_sum": (SOURCE_ENFORCEMENT, DIM_GLOBAL, "duration_ms_sum"),
        "playbooks_fired": (SOURCE_PLAYBOOKS, DIM_GLOBAL, "playbooks_fired"),
        "actions_executed": (SOURCE_PLAYBOOKS, DIM_PLAYBOOK, "actions_executed"),
        "events_total": (SOURCE_PLAYBOOKS, DIM_GLOBAL, "events_total"),
        "risk_score_sum": (SOURCE_PIPELINE, DIM_GLOBAL, "risk_score_sum"),
        "scans": (SOURCE_PIPELINE, DIM_GLOBAL, "scans"),
        "critical_findings": (SOURCE_PIPELINE, DIM_GLOBAL, "critical_findings"),
    }
    return mapping.get(metric, (SOURCE_ENFORCEMENT, DIM_GLOBAL, metric))


def trends(
    window: ExecutiveWindow = "7d",
    bucket: Optional[ExecutiveBucket] = None,
    metrics: Optional[Iterable[str]] = None,
    *,
    now: Optional[float] = None,
    db_path=None,
) -> ExecutiveTrends:
    """Return time-series for the requested metrics."""
    metric_names = _normalize_metrics(metrics)
    if bucket is None:
        bucket = _bucket_label_for(_pick_bucket_for_window(window))
    bucket_size = _bucket_size(bucket)
    start, end = _window_bounds(window, now=now)

    series: list[ExecutiveTrendSeries] = []
    for metric_name in metric_names:
        source, dim_key, metric = _series_key_for(metric_name)
        kwargs = {
            "bucket_size_seconds": bucket_size,
            "bucket_start_gte": start,
            "bucket_start_lt": end,
            "source": source,
            "metric": metric,
            "path": db_path,
        }
        if dim_key == DIM_GLOBAL:
            kwargs["dimension_key"] = DIM_GLOBAL
        rows = query_buckets(**kwargs)
        bucket_totals: dict[int, float] = defaultdict(float)
        for row in rows:
            if dim_key != DIM_GLOBAL and row["dimension_key"] != dim_key:
                continue
            bucket_totals[int(row["bucket_start"])] += float(row["value"])
        points = [
            ExecutiveTrendPoint(
                bucket_start=datetime.fromtimestamp(bs, tz=timezone.utc),
                metric=metric_name,
                value=round(value, 4),
            )
            for bs, value in sorted(bucket_totals.items())
        ]
        series.append(ExecutiveTrendSeries(metric=metric_name, points=points))

    return ExecutiveTrends(
        window=window,
        bucket=bucket,
        window_start=datetime.fromtimestamp(start, tz=timezone.utc),
        window_end=datetime.fromtimestamp(end, tz=timezone.utc),
        series=series,
    )


def _bucket_label_for(size: int) -> ExecutiveBucket:
    if size == BUCKET_SIZE_5M:
        return "5m"
    if size == BUCKET_SIZE_1H:
        return "1h"
    return "1d"


# ── Exports ──────────────────────────────────────────────────────────────────


def _summary_csv(summary_payload: ExecutiveSummary) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    writer.writerow(["section", "metric", "value"])
    writer.writerow(["meta", "window", summary_payload.window])
    writer.writerow(["meta", "generated_at", summary_payload.generated_at.isoformat()])
    writer.writerow(["meta", "window_start", summary_payload.window_start.isoformat()])
    writer.writerow(["meta", "window_end", summary_payload.window_end.isoformat()])

    exp = summary_payload.exposure
    writer.writerow(["exposure", "total_requests", exp.total_requests])
    writer.writerow(["exposure", "blocked", exp.blocked])
    writer.writerow(["exposure", "would_block", exp.would_block])
    writer.writerow(["exposure", "block_rate", exp.block_rate])
    for decision, count in exp.by_decision.items():
        writer.writerow(["exposure_by_decision", decision, count])
    for direction, count in exp.by_direction.items():
        writer.writerow(["exposure_by_direction", direction, count])
    if exp.top_blocking_policy_id:
        writer.writerow([
            "exposure",
            f"top_blocking_policy:{exp.top_blocking_policy_id}",
            exp.top_blocking_policy_count,
        ])

    risk = summary_payload.risk
    writer.writerow(["risk", "average_risk_score", risk.average_risk_score])
    writer.writerow(["risk", "p95_risk_score", risk.p95_risk_score])
    writer.writerow(["risk", "critical_findings", risk.critical_findings])
    for sev, count in risk.severity_distribution.items():
        writer.writerow(["risk_severity", sev, count])

    auto = summary_payload.automation
    writer.writerow(["automation", "events_total", auto.events_total])
    writer.writerow(["automation", "playbooks_fired", auto.playbooks_fired])
    writer.writerow(["automation", "actions_executed", auto.actions_executed])
    writer.writerow(
        ["automation", "mean_time_to_action_ms", auto.mean_time_to_action_ms]
    )
    for action, count in auto.actions_by_type.items():
        writer.writerow(["automation_actions", action, count])

    cov = summary_payload.coverage
    writer.writerow(["coverage", "policies_total", cov.policies_total])
    writer.writerow(["coverage", "policies_enabled", cov.policies_enabled])
    writer.writerow(["coverage", "policies_enforce_mode", cov.policies_enforce_mode])
    writer.writerow(["coverage", "playbooks_total", cov.playbooks_total])
    writer.writerow(["coverage", "playbooks_enabled", cov.playbooks_enabled])
    writer.writerow(["coverage", "playbooks_live", cov.playbooks_live])

    for tag in summary_payload.compliance:
        writer.writerow(
            [
                f"compliance:{tag.tag}",
                "policies",
                tag.policies,
            ]
        )
        writer.writerow([f"compliance:{tag.tag}", "playbooks", tag.playbooks])
        writer.writerow(
            [f"compliance:{tag.tag}", "matched_events", tag.matched_events]
        )
        writer.writerow(
            [f"compliance:{tag.tag}", "blocked_events", tag.blocked_events]
        )

    for offender in summary_payload.top_offenders:
        writer.writerow(
            [
                "top_offenders",
                f"{offender.subject_type}:{offender.subject_id}",
                offender.deny_count,
            ]
        )

    return buffer.getvalue().encode("utf-8")


def _summary_pdf(
    summary_payload: ExecutiveSummary,
    *,
    prior_payload: ExecutiveSummary,
    trend_payload: ExecutiveTrends,
    branding: Optional[dict] = None,
) -> bytes:
    """Render the executive KPI report into a branded multi-page PDF.

    Delegates to :func:`app.services.executive_kpi_pdf.generate_kpi_pdf`
    so the layout (cover, KPI tiles, trend chart, exposure / risk /
    automation / coverage sections, top offenders, compliance posture,
    appendix) is shared with the platypus-based scan report. The
    *prior_payload* drives period-over-period deltas; *trend_payload*
    drives the line chart. The signature stays minimal: the public
    entrypoint remains :func:`export`.
    """
    try:
        from app.services.executive_kpi_pdf import generate_kpi_pdf
    except ImportError as exc:
        raise ServiceError(
            message="PDF export requires reportlab",
            detail={"missing": "reportlab"},
        ) from exc

    branding = branding or {}
    return generate_kpi_pdf(
        current=summary_payload,
        prior=prior_payload,
        trend=trend_payload,
        company_name=branding.get("company_name"),
        logo_bytes=branding.get("logo_bytes"),
    )


def _resolve_branding() -> dict:
    """Resolve optional report branding for global executive PDFs.

    The executive report has no per-call request body (unlike per-scan
    PDFs), so branding is sourced from admin-controlled settings. The
    company name is bounded by Pydantic (max_length=200) and the logo
    file read is capped by ``report_branding_logo_max_bytes`` to defend
    against misconfiguration where a non-image (or huge) file is
    accidentally pointed at. Failures degrade silently: the cover
    gracefully omits the brand block when neither value resolves.
    """
    company_name = getattr(settings, "report_branding_company_name", "") or ""
    company_name = company_name.strip()

    logo_bytes: Optional[bytes] = None
    logo_path = getattr(settings, "report_branding_logo_path", None)
    max_bytes = int(
        getattr(settings, "report_branding_logo_max_bytes", 4 * 1024 * 1024)
    )

    if logo_path:
        try:
            with open(logo_path, "rb") as fh:
                # Cap the read so a misconfigured huge file cannot exhaust
                # memory; any image practical for a cover is well under
                # max_bytes.
                logo_bytes = fh.read(max_bytes + 1)
            if logo_bytes is not None and len(logo_bytes) > max_bytes:
                logger.warning(
                    "report_branding_logo_path exceeds size cap; ignoring",
                    extra={
                        "logo_path": str(logo_path),
                        "max_bytes": max_bytes,
                    },
                )
                logo_bytes = None
        except (OSError, TypeError, ValueError):
            logger.warning(
                "report_branding_logo_path unreadable; ignoring",
                extra={"logo_path": str(logo_path)},
            )
            logo_bytes = None

    return {
        "company_name": company_name or None,
        "logo_bytes": logo_bytes,
    }


def export(
    window: ExecutiveWindow = "30d",
    fmt: ExecutiveExportFormat = "pdf",
    *,
    now: Optional[float] = None,
    db_path=None,
) -> tuple[bytes, str]:
    """Render the executive summary to *fmt*. Returns ``(payload, filename)``."""
    summary_payload = summary(window=window, now=now, db_path=db_path)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    if fmt == "pdf":
        prior_now = summary_payload.window_start.timestamp() - 1.0
        prior_payload = summary(window=window, now=prior_now, db_path=db_path)
        trend_payload = trends(window=window, now=now, db_path=db_path)
        pdf_bytes = _summary_pdf(
            summary_payload,
            prior_payload=prior_payload,
            trend_payload=trend_payload,
            branding=_resolve_branding(),
        )
        return pdf_bytes, f"valo-executive-{window}-{today}.pdf"
    if fmt == "csv":
        return _summary_csv(summary_payload), f"valo-executive-{window}-{today}.csv"
    raise ServiceError(
        message=f"Unsupported export format: {fmt}",
        detail={"valid": ["pdf", "csv"]},
    )


def is_enabled() -> bool:
    return bool(settings.executive_metrics_enabled)


__all__ = [
    "DEFAULT_TREND_METRICS",
    "WINDOW_TO_SECONDS",
    "BUCKET_TO_SIZE",
    "export",
    "is_enabled",
    "summary",
    "trends",
]


# Re-export executive_store for tests that need a fresh DB path.
__store__ = executive_store
