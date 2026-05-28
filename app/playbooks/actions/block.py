"""block: deny the request inline.

In Valo, the egress proxy already returns ``403 PolicyDenied`` when a
governance policy denies the call. This action re-affirms that decision
in the playbook trace, so a single audit record describes the full
ingest -> playbook -> action chain.

In dry-run mode this is purely an accounting entry: the request was
already (or will be) blocked by the inline enforcement layer; the
playbook engine does not duplicate that block.
"""

from __future__ import annotations

from typing import Any, Dict

from app.core.logging import get_logger
from app.playbooks.actions.base import ActionContext, ActionResult
from app.playbooks.registry import register_action

logger = get_logger(__name__)


@register_action("block")
def block(ctx: ActionContext, params: Dict[str, Any]) -> ActionResult:
    reason = str(params.get("reason", "policy_denied"))
    detail = {
        "reason": reason,
        "trace_id": ctx.event.trace_id,
        "matched_policy_ids": ctx.event.matched_policy_ids,
        "would_block_inline": ctx.event.blocked or ctx.event.severity in ("high", "critical"),
        "dry_run": ctx.dry_run,
    }
    logger.info(
        "playbook_action=block playbook=%s trace_id=%s reason=%s dry_run=%s",
        ctx.playbook_id,
        ctx.event.trace_id,
        reason,
        ctx.dry_run,
    )
    return ActionResult(
        action="block",
        status="planned",
        message=f"would block request: {reason}",
        detail=detail,
    )
