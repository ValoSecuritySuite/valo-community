"""ticket: open a Jira / Linear / GitHub issue capturing the finding.

Phase 3.x adapter dispatches to whichever issue tracker is configured. The
dry-run stub renders the planned payload and logs it.
"""

from __future__ import annotations

from typing import Any, Dict

from app.core.logging import get_logger
from app.playbooks.actions.base import ActionContext, ActionResult
from app.playbooks.registry import register_action

logger = get_logger(__name__)

_VALID_PROVIDERS = {"jira", "linear", "github"}


@register_action("ticket")
def ticket(ctx: ActionContext, params: Dict[str, Any]) -> ActionResult:
    provider = str(params.get("provider", "github")).lower()
    if provider not in _VALID_PROVIDERS:
        return ActionResult(
            action="ticket",
            status="skipped",
            message=f"unknown ticket provider: {provider}",
            detail={"provider": provider, "valid_providers": sorted(_VALID_PROVIDERS)},
        )
    project = str(params.get("project", "valo-incidents"))
    title = str(
        params.get(
            "title",
            f"[Valo] Playbook {ctx.playbook_id} fired: {ctx.event.event_type}",
        )
    )
    labels = list(params.get("labels", [])) or ["valo", "ai-firewall"]
    body_lines = [
        f"trace_id: {ctx.event.trace_id}",
        f"event_id: {ctx.event.event_id}",
        f"playbook: {ctx.playbook_id}",
        f"severity: {ctx.event.severity}",
        f"matched_policy_ids: {', '.join(ctx.event.matched_policy_ids) or '(none)'}",
    ]
    body = "\n".join(body_lines)
    detail = {
        "provider": provider,
        "project": project,
        "title": title,
        "labels": labels,
        "body": body,
        "dry_run": ctx.dry_run,
    }
    logger.info(
        "playbook_action=ticket playbook=%s provider=%s project=%s title=%r dry_run=%s",
        ctx.playbook_id,
        provider,
        project,
        title,
        ctx.dry_run,
    )
    return ActionResult(
        action="ticket",
        status="planned",
        message=f"would open {provider} ticket in {project}",
        detail=detail,
    )
