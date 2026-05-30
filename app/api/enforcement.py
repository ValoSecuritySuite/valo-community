"""Admin / observability API for the enforcement layer.

Exposes the in-memory event ring buffer, aggregated stats, runtime
configuration, and a firewall playground (dry-run simulate) so the UI can
render a live AI Firewall console without parsing log files or restarting
the process to flip enforcement modes.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from app.api._rate_limits import rate_limit_for
from app.core.config import settings
from app.core.limiter import limiter
from app.schemas import (
    EnforcementConfigResponse,
    EnforcementConfigUpdateRequest,
    EnforcementDirection,
    EnforcementEventList,
    EnforcementSimulateRequest,
    EnforcementSimulateResponse,
    EnforcementStats,
    PolicyDecisionLiteral,
)
from app.services import enforcement_events
from app.services.policy_enforcement import evaluate_text_for_enforcement

router = APIRouter(prefix="/enforcement", tags=["enforcement"])


def _config_response() -> EnforcementConfigResponse:
    return EnforcementConfigResponse(
        enforcement_mode=settings.enforcement_mode,
        enforcement_protected_routes=list(settings.enforcement_protected_routes),
        enforcement_max_body_bytes=int(settings.enforcement_max_body_bytes),
        proxy_upstream_url=str(settings.proxy_upstream_url),
        proxy_request_timeout_seconds=float(settings.proxy_request_timeout_seconds),
        event_buffer_capacity=enforcement_events.buffer_capacity(),
        event_buffer_used=enforcement_events.buffer_used(),
    )


@router.get("/events", response_model=EnforcementEventList)
@limiter.limit(rate_limit_for("GET", "/enforcement/events"))
def list_events(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    decision: Optional[PolicyDecisionLiteral] = Query(default=None),
    route: Optional[str] = Query(default=None),
    direction: Optional[EnforcementDirection] = Query(default=None),
    blocked: Optional[bool] = Query(default=None),
    trace_id: Optional[str] = Query(default=None),
    since: Optional[datetime] = Query(
        default=None,
        description="ISO-8601 timestamp; only events at or after this time are returned.",
    ),
) -> EnforcementEventList:
    """List recent enforcement events (newest first) with filter support."""
    events, total = enforcement_events.query_events(
        limit=limit,
        offset=offset,
        decision=decision,
        route=route,
        direction=direction,
        blocked=blocked,
        trace_id=trace_id,
        since=since,
    )
    return EnforcementEventList(
        total=total,
        returned=len(events),
        capacity=enforcement_events.buffer_capacity(),
        events=events,
    )


@router.get("/stats", response_model=EnforcementStats)
@limiter.limit(rate_limit_for("GET", "/enforcement/stats"))
def get_stats(
    request: Request,
    window_seconds: int = Query(
        default=0,
        ge=0,
        le=24 * 60 * 60 * 7,
        description="Time window in seconds (0 = all retained events).",
    ),
    top_n: int = Query(default=5, ge=1, le=20),
) -> EnforcementStats:
    """Aggregate retained enforcement events into KPI-friendly stats."""
    return enforcement_events.aggregate_stats(window_seconds=window_seconds, top_n=top_n)


@router.get("/config", response_model=EnforcementConfigResponse)
@limiter.limit(rate_limit_for("GET", "/enforcement/config"))
def get_config(request: Request) -> EnforcementConfigResponse:
    """Return the current runtime enforcement configuration."""
    return _config_response()


@router.patch("/config", response_model=EnforcementConfigResponse)
@limiter.limit(rate_limit_for("PATCH", "/enforcement/config"))
def update_config(
    request: Request,
    payload: EnforcementConfigUpdateRequest,
) -> EnforcementConfigResponse:
    """Update enforcement settings at runtime (mode, protected routes, ...).

    Validation lives on the schema; this endpoint only commits the patch into
    the in-memory ``settings`` instance and returns the resulting view. Each
    apply emits an info log so operators can correlate the change with audit
    trails.
    """
    if payload.enforcement_mode is not None:
        if payload.enforcement_mode == "enforce":
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "feature_unavailable",
                    "message": "Enforce mode is available in Valo Enterprise only.",
                },
            )
        settings.enforcement_mode = payload.enforcement_mode
    if payload.enforcement_protected_routes is not None:
        settings.enforcement_protected_routes = list(payload.enforcement_protected_routes)
    if payload.enforcement_max_body_bytes is not None:
        settings.enforcement_max_body_bytes = int(payload.enforcement_max_body_bytes)
    if payload.proxy_upstream_url is not None:
        settings.proxy_upstream_url = payload.proxy_upstream_url
    if payload.proxy_request_timeout_seconds is not None:
        settings.proxy_request_timeout_seconds = float(payload.proxy_request_timeout_seconds)

    return _config_response()


@router.post("/simulate", response_model=EnforcementSimulateResponse)
@limiter.limit(rate_limit_for("POST", "/enforcement/simulate"))
def simulate(
    request: Request,
    payload: EnforcementSimulateRequest,
) -> EnforcementSimulateResponse:
    """Dry-run a prompt through the firewall and return the would-be outcome.

    This shares the exact code path the proxy uses, so the playground sees
    identical decisions and headers, but it does not call any upstream LLM
    and does not record an event into the ring buffer (so the live traffic
    view stays clean). Useful for trying out new policies before flipping the
    global mode to ``enforce``.
    """
    if not payload.prompt.strip():
        raise HTTPException(status_code=422, detail="prompt must not be empty")

    outcome = evaluate_text_for_enforcement(
        payload.prompt,
        target=payload.target,
        mode=payload.mode,
    )

    matched_decisions = [d for d in outcome.decisions if d.matched]
    matched_policy_ids = list(outcome.matched_policy_ids)

    headers: dict[str, str] = {
        "X-Valo-Policy-Decision": outcome.final_decision,
        "X-Valo-Trace-Id": outcome.trace_id,
        "X-Valo-Enforcement-Mode": outcome.mode,
    }
    if matched_policy_ids:
        headers["X-Valo-Matched-Policies"] = ",".join(matched_policy_ids)

    block_envelope: dict | None = None
    if outcome.blocked:
        block_envelope = {
            "error": {
                "code": "PolicyDenied",
                "message": "Request blocked by Valo governance policy.",
                "detail": {
                    "trace_id": outcome.trace_id,
                    "final_decision": outcome.final_decision,
                    "matched_policy_ids": matched_policy_ids,
                    "decisions": [d.model_dump() for d in matched_decisions],
                    "side": "request",
                    "simulated": True,
                },
            }
        }

    from app.services.enforcement_events import _outcome_to_event

    event = _outcome_to_event(outcome, route="/enforcement/simulate", direction="ingress")

    return EnforcementSimulateResponse(
        outcome=event,
        decisions=outcome.decisions,
        headers=headers,
        block_envelope=block_envelope,
    )


__all__ = ["router"]
