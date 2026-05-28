"""quarantine: mark a scan / connector / repo as unsafe.

Phase 3.x adapter targets:

- ``scan_store``: flag a ``scan_id`` so it is excluded from auto-runs.
- ``connector_registry``: disable a SaaS connector until manual review.
- ``repo_inventory``: tag a repository as quarantined.

The dry-run stub records the intended target and reason for audit.
"""

from __future__ import annotations

from typing import Any, Dict

from app.core.logging import get_logger
from app.playbooks.actions.base import ActionContext, ActionResult
from app.playbooks.registry import register_action

logger = get_logger(__name__)

_VALID_KINDS = {"scan", "connector", "repo", "tenant"}


@register_action("quarantine")
def quarantine(ctx: ActionContext, params: Dict[str, Any]) -> ActionResult:
    kind = str(params.get("kind", "scan"))
    reason = str(params.get("reason", "playbook_triggered"))
    target_id = params.get("target_id") or (ctx.event.subject.id if ctx.event.subject else None)
    if kind not in _VALID_KINDS:
        return ActionResult(
            action="quarantine",
            status="skipped",
            message=f"unknown quarantine kind: {kind}",
            detail={"kind": kind, "valid_kinds": sorted(_VALID_KINDS)},
        )
    if not target_id:
        return ActionResult(
            action="quarantine",
            status="skipped",
            message="no target_id provided and event has no subject",
            detail={"kind": kind, "reason": reason},
        )
    detail = {
        "kind": kind,
        "target_id": str(target_id),
        "reason": reason,
        "trace_id": ctx.event.trace_id,
        "dry_run": ctx.dry_run,
    }
    logger.info(
        "playbook_action=quarantine playbook=%s kind=%s target=%s reason=%s dry_run=%s",
        ctx.playbook_id,
        kind,
        target_id,
        reason,
        ctx.dry_run,
    )
    return ActionResult(
        action="quarantine",
        status="planned",
        message=f"would quarantine {kind} {target_id}: {reason}",
        detail=detail,
    )
