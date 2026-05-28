"""rate_limit: throttle the offending source.

The Phase 3.x adapter will integrate with :mod:`app.core.limiter` (slowapi)
so a playbook can downgrade an aggressive caller without a full block.
The dry-run stub records the intended throttle.
"""

from __future__ import annotations

from typing import Any, Dict

from app.core.logging import get_logger
from app.playbooks.actions.base import ActionContext, ActionResult
from app.playbooks.registry import register_action

logger = get_logger(__name__)


@register_action("rate_limit")
def rate_limit(ctx: ActionContext, params: Dict[str, Any]) -> ActionResult:
    requests = int(params.get("requests", 1))
    window_seconds = int(params.get("window_seconds", 60))
    duration_seconds = int(params.get("duration_seconds", 600))
    if requests <= 0 or window_seconds <= 0 or duration_seconds <= 0:
        return ActionResult(
            action="rate_limit",
            status="skipped",
            message="requests, window_seconds, and duration_seconds must be positive",
            detail={
                "requests": requests,
                "window_seconds": window_seconds,
                "duration_seconds": duration_seconds,
            },
        )
    subject = ctx.event.subject
    detail = {
        "requests": requests,
        "window_seconds": window_seconds,
        "duration_seconds": duration_seconds,
        "subject_type": subject.type if subject else None,
        "subject_id": subject.id if subject else None,
        "trace_id": ctx.event.trace_id,
        "dry_run": ctx.dry_run,
    }
    logger.info(
        "playbook_action=rate_limit playbook=%s subject=%s/%s "
        "requests=%d window=%ds duration=%ds dry_run=%s",
        ctx.playbook_id,
        detail["subject_type"],
        detail["subject_id"],
        requests,
        window_seconds,
        duration_seconds,
        ctx.dry_run,
    )
    return ActionResult(
        action="rate_limit",
        status="planned",
        message=(
            f"would rate-limit to {requests} req / {window_seconds}s "
            f"for {duration_seconds}s"
        ),
        detail=detail,
    )
