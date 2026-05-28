"""alert: notify a human channel (SOC webhook / Slack / email).

The Phase 3 stub never opens a network connection. It emits a structured
log line containing the channel and the canonical event payload so an
operator can confirm the playbook is wired correctly. The Phase 3.x
adapter will route the same payload to the configured channel.
"""

from __future__ import annotations

from typing import Any, Dict

from app.core.logging import get_logger
from app.playbooks.actions.base import ActionContext, ActionResult
from app.playbooks.registry import register_action

logger = get_logger(__name__)

_VALID_SEVERITIES = {"info", "low", "medium", "high", "critical"}


@register_action("alert")
def alert(ctx: ActionContext, params: Dict[str, Any]) -> ActionResult:
    channel = str(params.get("channel", "default"))
    severity = str(params.get("severity", ctx.event.severity))
    if severity not in _VALID_SEVERITIES:
        severity = "info"
    title = str(
        params.get(
            "title",
            f"Valo playbook {ctx.playbook_id}: {ctx.event.event_type}",
        )
    )
    detail = {
        "channel": channel,
        "severity": severity,
        "title": title,
        "trace_id": ctx.event.trace_id,
        "matched_policy_ids": ctx.event.matched_policy_ids,
        "summary": ctx.event.raw,
        "dry_run": ctx.dry_run,
    }
    logger.info(
        "playbook_action=alert playbook=%s channel=%s severity=%s title=%r trace_id=%s dry_run=%s",
        ctx.playbook_id,
        channel,
        severity,
        title,
        ctx.event.trace_id,
        ctx.dry_run,
    )
    return ActionResult(
        action="alert",
        status="planned",
        message=f"would alert channel '{channel}' at severity '{severity}'",
        detail=detail,
    )
