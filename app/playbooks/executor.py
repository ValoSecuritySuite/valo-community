"""Playbook executor: match an event, run actions, return a trace.

Pure-Python, side-effect free except via the actions themselves. Never
raises into the caller; failures inside an action become an
``ActionResult{status: "error"}`` so the audit trail stays well-formed.

Phase model
-----------
The executor supports three :data:`~app.playbooks.schemas.ActionPhase`
values so the runtime layer can split work across the request hot path
and a background worker:

- ``"all"``: run every action defined in matched playbooks (manual /evaluate).
- ``"inline"``: run only actions in :data:`INLINE_ACTIONS` (currently
  ``"block"``). The synchronous response side of the runtime hook uses
  this so a 'block' action can affect what the proxy returns.
- ``"background"``: run every other action. The runtime fires this in a
  daemon thread so slow integrations cannot stall the request.
"""

from __future__ import annotations

import time
import uuid
from typing import FrozenSet, Optional

from app.core.logging import get_logger
from app.playbooks.actions.base import ActionContext
from app.playbooks.events import PlaybookEvent
from app.playbooks.matcher import matches_playbook
from app.playbooks.registry import get_action
from app.playbooks.schemas import (
    ActionPhase,
    ActionResult,
    ActionSpec,
    ExecutionTrace,
    Playbook,
    PlaybookMatch,
    PlaybookSet,
)

logger = get_logger(__name__)


INLINE_ACTIONS: FrozenSet[str] = frozenset({"block"})
"""Names of actions that must run on the synchronous request hot path."""


def _should_run_action(action_name: str, phase: ActionPhase) -> bool:
    if phase == "all":
        return True
    if phase == "inline":
        return action_name in INLINE_ACTIONS
    return action_name not in INLINE_ACTIONS


def _execute_action(
    spec_action: str,
    spec_params: dict,
    ctx: ActionContext,
) -> ActionResult:
    """Dispatch one action, capturing exceptions as a structured failure."""
    impl = get_action(spec_action)
    started = time.perf_counter()
    if impl is None:
        return ActionResult(
            action=spec_action,
            status="skipped",
            message=f"unknown action: {spec_action}",
            detail={"action": spec_action},
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )
    try:
        result = impl(ctx, dict(spec_params))
        if not isinstance(result, ActionResult):
            return ActionResult(
                action=spec_action,
                status="error",
                message="action did not return ActionResult",
                detail={"got_type": type(result).__name__},
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )
        if not result.duration_ms:
            result.duration_ms = (time.perf_counter() - started) * 1000.0
        return result
    except Exception as exc:
        logger.exception(
            "playbook_action_error playbook=%s action=%s err=%s",
            ctx.playbook_id,
            spec_action,
            exc,
        )
        return ActionResult(
            action=spec_action,
            status="error",
            message=str(exc),
            detail={"exception_type": type(exc).__name__},
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )


def _sorted_enabled(playbooks: PlaybookSet) -> list[Playbook]:
    """Enabled playbooks sorted by descending priority then id (stable)."""
    return sorted(
        (p for p in playbooks.playbooks if p.enabled),
        key=lambda p: (-p.priority, p.id),
    )


def process_event(
    event: PlaybookEvent,
    playbooks: PlaybookSet,
    *,
    enabled: bool = True,
    dry_run: bool = True,
    correlation_id: Optional[str] = None,
    phase: ActionPhase = "all",
) -> ExecutionTrace:
    """Run *event* through *playbooks* and return an :class:`ExecutionTrace`.

    When ``enabled`` is False the engine short-circuits with an empty
    trace (kill switch). When ``dry_run`` is True (default), every action
    MUST refuse to perform real side effects.

    ``phase`` filters which action specs actually run. When set to
    ``"inline"`` or ``"background"``, only the matching subset runs;
    actions outside the phase are simply omitted from the trace (their
    results will appear in the other phase's trace, and the runtime
    layer merges the two before persisting).
    """
    started = time.perf_counter()
    trace = ExecutionTrace(
        event_id=event.event_id,
        dry_run=dry_run,
        enabled=enabled,
        phase=phase,
        correlation_id=correlation_id or "",
        trace_id=event.trace_id,
    )
    if not enabled:
        trace.duration_ms = (time.perf_counter() - started) * 1000.0
        return trace

    context = event.model_dump(mode="python")
    correlation = correlation_id or str(uuid.uuid4())
    trace.correlation_id = correlation

    for playbook in _sorted_enabled(playbooks):
        ok, reasons = matches_playbook(context, playbook)
        if not ok:
            trace.matches.append(
                PlaybookMatch(
                    playbook_id=playbook.id,
                    name=playbook.name,
                    priority=playbook.priority,
                    matched=False,
                    reasons=reasons,
                )
            )
            continue

        ctx = ActionContext(
            event=event,
            playbook_id=playbook.id,
            dry_run=dry_run,
            correlation_id=correlation,
        )
        results: list[ActionResult] = []
        ran_any = False
        for spec in playbook.then:
            if not _should_run_action(spec.action, phase):
                continue
            ran_any = True
            results.append(_execute_action(spec.action, spec.params, ctx))
        if ran_any:
            trace.matched_playbook_ids.append(playbook.id)
        trace.matches.append(
            PlaybookMatch(
                playbook_id=playbook.id,
                name=playbook.name,
                priority=playbook.priority,
                matched=True,
                reasons=reasons,
                results=results,
            )
        )

    trace.duration_ms = (time.perf_counter() - started) * 1000.0
    return trace


def merge_traces(
    inline: ExecutionTrace,
    background: ExecutionTrace,
) -> ExecutionTrace:
    """Combine an inline and a background trace into one final record.

    Both inputs must share the same ``event_id``. When a playbook fired
    in both phases its ``results`` lists are concatenated (inline first,
    then background) inside a single :class:`PlaybookMatch`.
    """
    if inline.event_id != background.event_id:
        raise ValueError(
            "cannot merge traces with different event_ids: "
            f"{inline.event_id!r} vs {background.event_id!r}"
        )

    merged_matches_by_id: dict[str, PlaybookMatch] = {}
    order: list[str] = []
    for match in list(inline.matches) + list(background.matches):
        if match.playbook_id in merged_matches_by_id:
            existing = merged_matches_by_id[match.playbook_id]
            existing.results = list(existing.results) + list(match.results)
            existing.matched = existing.matched or match.matched
            seen = set(existing.reasons)
            for r in match.reasons:
                if r not in seen:
                    existing.reasons.append(r)
        else:
            merged_matches_by_id[match.playbook_id] = match.model_copy(deep=True)
            order.append(match.playbook_id)

    merged_ids: list[str] = []
    seen_ids: set[str] = set()
    for pid in list(inline.matched_playbook_ids) + list(background.matched_playbook_ids):
        if pid not in seen_ids:
            seen_ids.add(pid)
            merged_ids.append(pid)

    return ExecutionTrace(
        event_id=inline.event_id,
        started_at=inline.started_at,
        duration_ms=inline.duration_ms + background.duration_ms,
        matched_playbook_ids=merged_ids,
        matches=[merged_matches_by_id[pid] for pid in order],
        dry_run=inline.dry_run and background.dry_run,
        enabled=inline.enabled and background.enabled,
        phase="all",
        correlation_id=inline.correlation_id or background.correlation_id,
        trace_id=inline.trace_id or background.trace_id,
    )


__all__ = ["INLINE_ACTIONS", "merge_traces", "process_event"]
