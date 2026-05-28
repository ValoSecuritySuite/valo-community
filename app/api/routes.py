"""Valo API route definitions."""

import io
import logging
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.limiter import limiter
from app.schemas import (
    AnalyzeResponse,
    BackendSettingsResponse,
    BackendSettingsUpdateRequest,
    HealthResponse,
    PipelineRequest,
    RuleEngineResult,
    RuleEvalRequest,
    RuleReloadDiff,
    RuleReloadResponse,
    RuleSetResponse,
    ScanReport,
)
from app.services.pdf_report_generator import generate_executive_pdf
from app.services.dashboard import get_scan_report, record_scan_detail
from app.services.portfolio import build_scan_result, record_scan_result
from app.services.pipeline import get_or_run_pipeline, run_pipeline
from app.services.report_generator import build_rules_info
from app.services.rule_engine import evaluate as evaluate_context_rules
from app.services.rules_loader import clear_rules_cache, get_rule_fingerprints, load_rules

from app.api._rate_limits import (
    ENDPOINT_RATE_LIMIT_MAP as _ENDPOINT_RATE_LIMIT_MAP,
    ENDPOINT_RATE_LIMIT_ORDER as _ENDPOINT_RATE_LIMIT_ORDER,
    endpoint_rate_limits_payload as _endpoint_rate_limits_payload,
    rate_limit_for as _rate_limit_for,
)

router = APIRouter()


def _apply_log_level(level: str) -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.getLogger().setLevel(numeric_level)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def _apply_default_rate_limit(limit_value: str) -> None:
    if hasattr(limiter, "_default_limits"):
        limiter._default_limits = [limit_value]


@router.get("/meta/edition")
@limiter.limit(_rate_limit_for("GET", "/health"))
def edition_meta(request: Request) -> dict:
    """Expose edition metadata for the web UI."""
    return {
        "edition": "community",
        "enforcement_mode": settings.enforcement_mode,
        "features": {
            "portfolio": False,
            "executive_dashboard": False,
            "reports_automation": False,
            "playbooks": False,
            "learning_loop": False,
            "report_branding": False,
        },
    }


@router.get("/health", response_model=HealthResponse)
@limiter.limit(_rate_limit_for("GET", "/health"))
def health(request: Request) -> HealthResponse:
    """Liveness probe: is the process running?"""
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=HealthResponse)
@limiter.limit(_rate_limit_for("GET", "/health/ready"))
def readiness(request: Request):
    """Readiness probe: can the app serve traffic? Returns 503 if not ready."""
    from fastapi.responses import JSONResponse

    if not settings.rules_path.exists():
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "reason": "rules_file_missing"},
        )
    return HealthResponse(status="ok")


@router.post("/analyze", response_model=AnalyzeResponse)
@limiter.limit(_rate_limit_for("POST", "/analyze"))
def analyze_prompt(request: Request, payload: PipelineRequest) -> AnalyzeResponse:
    """Analyze a prompt for deterministic prompt-injection risk."""
    rules = load_rules(use_cache=False)
    result = get_or_run_pipeline(request, payload, rule_set=rules)
    record_scan_result(build_scan_result(result))
    record_scan_detail(result)

    report = result.report
    sanitized_report = None
    if report is not None:
        sanitized_report = report.model_dump(exclude={"rules_info"})

    return AnalyzeResponse(
        input_prompt=result.input_prompt,
        matched_rule_details=result.matched_rule_details,
        normalized=result.normalized,
        detection=result.detection,
        matched_rules=result.matched_rules,
        context_score=result.context_score,
        passed_count=result.passed_count,
        failed_count=result.failed_count,
        combined_score=result.combined_score,
        policy_decisions=result.policy_decisions,
        final_decision=result.final_decision,
        report=sanitized_report,
    )


@router.get("/rules", response_model=RuleSetResponse)
@limiter.limit(_rate_limit_for("GET", "/rules"))
def get_rules(request: Request) -> RuleSetResponse:
    """Get loaded rules."""
    rules = load_rules()
    return RuleSetResponse(
        rules=rules.rules,
        text_scan_rules=rules.text_scan_rules,
        rules_info=build_rules_info(rules),
    )


@router.post("/rules/evaluate", response_model=RuleEngineResult)
@limiter.limit(_rate_limit_for("POST", "/rules/evaluate"))
def evaluate_rules(request: Request, payload: RuleEvalRequest) -> RuleEngineResult:
    """Evaluate an arbitrary JSON context against the loaded YAML context rules.

    Used by CI pipelines and governance tooling to dry-run policy decisions
    without running the full /analyze pipeline.
    """
    rules = load_rules(use_cache=False)
    return evaluate_context_rules(payload.context, rules)


@router.post("/rules/reload", response_model=RuleReloadResponse)
@limiter.limit(_rate_limit_for("POST", "/rules/reload"))
def reload_rules(request: Request) -> RuleReloadResponse:
    """Clear the in-memory rules cache and reload rules from disk."""
    old_rules = load_rules()
    old_fp = get_rule_fingerprints(old_rules)
    old_ids = set(old_fp)

    clear_rules_cache()
    new_rules = load_rules(use_cache=False)

    new_fp = get_rule_fingerprints(new_rules)
    new_ids = set(new_fp)

    added = sorted(new_ids - old_ids)
    removed = sorted(old_ids - new_ids)
    changed = sorted(rid for rid in old_ids & new_ids if old_fp[rid] != new_fp[rid])
    unchanged = max(len(new_ids) - len(added) - len(changed), 0)

    return RuleReloadResponse(
        rules_file=settings.rules_path.name,
        previous_rule_count=len(old_ids),
        new_rule_count=len(new_ids),
        diff=RuleReloadDiff(
            added=added,
            removed=removed,
            changed=changed,
            unchanged=unchanged,
        ),
    )


@router.post("/scan/report", response_model=ScanReport)
@limiter.limit(_rate_limit_for("POST", "/scan/report"))
def export_scan_report(request: Request, payload: PipelineRequest) -> ScanReport:
    """Run the full pipeline and return only the standardised JSON report."""
    rules = load_rules(use_cache=False)
    result = get_or_run_pipeline(request, payload, rule_set=rules)
    record_scan_result(build_scan_result(result))
    record_scan_detail(result)
    assert result.report is not None  # noqa: S101
    return result.report


@router.post("/report/pdf", response_class=StreamingResponse)
@limiter.limit(_rate_limit_for("POST", "/report/pdf"))
def export_pdf_report(request: Request, payload: PipelineRequest) -> StreamingResponse:
    """Run the full scan pipeline and return a PDF report."""
    rules = load_rules(use_cache=False)
    result = get_or_run_pipeline(request, payload, rule_set=rules)
    record_scan_result(build_scan_result(result))
    record_scan_detail(result)
    assert result.report is not None  # noqa: S101
    pdf_bytes = generate_executive_pdf(result.report)
    filename = f"scan_report_{str(result.report.scan_id)[:8]}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/report/pdf/scan/{scan_id}", response_class=StreamingResponse)
@limiter.limit(_rate_limit_for("GET", "/report/pdf/scan/{scan_id}"))
def export_single_scan_pdf(request: Request, scan_id: str) -> StreamingResponse:
    """Export a PDF for one existing scan result by scan_id."""
    report = get_scan_report(scan_id)
    if report is None:
        raise HTTPException(status_code=404, detail="scan_id not found")

    pdf_bytes = generate_executive_pdf(report)
    filename = f"scan_report_{scan_id[:8]}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/settings", response_model=BackendSettingsResponse)
@limiter.limit(_rate_limit_for("GET", "/settings"))
def backend_settings(request: Request) -> BackendSettingsResponse:
    """Expose key backend runtime settings for UI observability."""
    return BackendSettingsResponse(
        rules_path=str(settings.rules_path),
        rules_file_exists=settings.rules_path.exists(),
        log_level=settings.log_level.upper(),
        default_rate_limit=settings.rate_limit,
        rules_cache_ttl_seconds=settings.rules_cache_ttl_seconds,
        rules_cache_enabled=settings.rules_cache_ttl_seconds > 0,
        endpoint_rate_limits=_endpoint_rate_limits_payload(),
    )


@router.patch("/settings", response_model=BackendSettingsResponse)
@limiter.limit(_rate_limit_for("PATCH", "/settings"))
def update_backend_settings(request: Request, payload: BackendSettingsUpdateRequest) -> BackendSettingsResponse:
    """Update runtime backend settings and endpoint rate limits."""
    if payload.log_level is not None:
        settings.log_level = payload.log_level
        _apply_log_level(payload.log_level)

    if payload.default_rate_limit is not None:
        settings.rate_limit = payload.default_rate_limit
        _apply_default_rate_limit(payload.default_rate_limit)

    if payload.rules_cache_enabled is False:
        settings.rules_cache_ttl_seconds = 0

    if payload.rules_cache_ttl_seconds is not None:
        settings.rules_cache_ttl_seconds = payload.rules_cache_ttl_seconds

    if payload.endpoint_rate_limits is not None:
        for item in payload.endpoint_rate_limits:
            key = (item.method, item.path)
            if key not in _ENDPOINT_RATE_LIMIT_MAP:
                raise HTTPException(
                    status_code=422,
                    detail=f"Unknown endpoint for rate limit update: {item.method} {item.path}",
                )
            _ENDPOINT_RATE_LIMIT_MAP[key] = item.limit

    return backend_settings(request)
