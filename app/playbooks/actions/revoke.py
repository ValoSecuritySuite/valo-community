"""revoke: invalidate a session, OAuth grant, or leaked credential.

Real adapter (Phase 3.x) will dispatch to one of:

- session store (delete session row, push tombstone)
- IdP / OAuth provider (revoke refresh token)
- secret manager (rotate exposed key)

The dry-run stub records what would have been revoked so SOC can audit
the intended action without any system change.
"""

from __future__ import annotations

from typing import Any, Dict

from app.core.logging import get_logger
from app.playbooks.actions.base import ActionContext, ActionResult
from app.playbooks.registry import register_action

logger = get_logger(__name__)

_VALID_TARGETS = {"session", "oauth_token", "api_key", "secret"}


@register_action("revoke")
def revoke(ctx: ActionContext, params: Dict[str, Any]) -> ActionResult:
    target = str(params.get("target", "session"))
    reason = str(params.get("reason", "playbook_triggered"))
    subject = ctx.event.subject
    if target not in _VALID_TARGETS:
        return ActionResult(
            action="revoke",
            status="skipped",
            message=f"unknown revoke target: {target}",
            detail={"target": target, "valid_targets": sorted(_VALID_TARGETS)},
        )
    detail = {
        "target": target,
        "reason": reason,
        "subject_type": subject.type if subject else None,
        "subject_id": subject.id if subject else None,
        "trace_id": ctx.event.trace_id,
        "dry_run": ctx.dry_run,
    }
    logger.info(
        "playbook_action=revoke playbook=%s target=%s subject=%s/%s reason=%s dry_run=%s",
        ctx.playbook_id,
        target,
        detail["subject_type"],
        detail["subject_id"],
        reason,
        ctx.dry_run,
    )
    return ActionResult(
        action="revoke",
        status="planned",
        message=f"would revoke {target}: {reason}",
        detail=detail,
    )
