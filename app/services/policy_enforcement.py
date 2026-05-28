"""Shared policy enforcement logic.

Used by both the ingress :class:`PolicyEnforcementMiddleware` and the egress
LLM proxy (:mod:`app.api.proxy`) so the global mode + per-policy ``enforce``
gating lives in exactly one place.
"""

from __future__ import annotations

import time
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas import (
    EnforcementDirection,
    EnforcementMode,
    EnforcementOutcome,
    PipelineRequest,
    PipelineResult,
    Policy,
    PolicyDecision,
    PolicySet,
    RuleSet,
)
from app.playbooks.events import from_enforcement_outcome as _build_playbook_event
from app.playbooks.runtime import dispatch as _dispatch_playbooks
from app.services.correlation_emitter import emit_outcome as _emit_correlation
from app.services.enforcement_events import record_event
from app.services.pipeline import run_pipeline, run_pipeline_raw
from app.services.policy_engine import aggregate_decision, policies_by_id
from app.services.policy_store import load_policies
from app.services.rules_loader import load_rules

logger = get_logger(__name__)


def _gate(
    decisions: list[PolicyDecision],
    policy_lookup: dict[str, Policy],
    mode: EnforcementMode,
) -> tuple[bool, bool]:
    """Apply mode + per-policy ``enforce`` gating.

    Returns ``(blocked, would_block)`` where ``blocked`` is the actual edge
    decision (HTTP 403) and ``would_block`` is ``True`` whenever a deny policy
    matched (regardless of mode or the per-policy ``enforce`` flag), so audit
    logs / dashboards can surface "what we would have done in enforce mode".
    """
    deny_matches = [
        decision
        for decision in decisions
        if decision.matched and decision.decision == "deny"
    ]
    if not deny_matches:
        return False, False

    would_block = True

    if mode != "enforce":
        return False, would_block

    enforced_deny = any(
        policy_lookup.get(decision.policy_id) is None
        or policy_lookup[decision.policy_id].enforce
        for decision in deny_matches
    )
    return enforced_deny, would_block


def _build_outcome(
    result: PipelineResult,
    policy_lookup: dict[str, Policy],
    mode: EnforcementMode,
    started_at: float,
) -> EnforcementOutcome:
    decisions = list(result.policy_decisions)
    blocked, would_block = _gate(decisions, policy_lookup, mode)
    matched_ids = [d.policy_id for d in decisions if d.matched]
    duration_ms = (time.perf_counter() - started_at) * 1000.0

    return EnforcementOutcome(
        mode=mode,
        final_decision=aggregate_decision(decisions),
        decisions=decisions,
        matched_policy_ids=matched_ids,
        blocked=blocked,
        would_block=would_block,
        pipeline_result=result,
        duration_ms=duration_ms,
    )


def evaluate_request_for_enforcement(
    payload: PipelineRequest,
    *,
    rule_set: RuleSet | None = None,
    policy_set: PolicySet | None = None,
    mode: EnforcementMode | None = None,
) -> EnforcementOutcome:
    """Run the full pipeline and produce an :class:`EnforcementOutcome`.

    The returned outcome carries the ``PipelineResult`` so handlers downstream
    of the middleware can reuse it instead of re-running the pipeline.
    """
    started_at = time.perf_counter()
    if rule_set is None:
        rule_set = load_rules()
    if policy_set is None:
        policy_set = load_policies()
    effective_mode: EnforcementMode = mode or settings.enforcement_mode

    result = run_pipeline(payload, rule_set=rule_set, policy_set=policy_set)
    return _build_outcome(result, policies_by_id(policy_set), effective_mode, started_at)


def evaluate_text_for_enforcement(
    text: str,
    *,
    target: str = "proxy-inbound",
    metadata: dict[str, Any] | None = None,
    rule_set: RuleSet | None = None,
    policy_set: PolicySet | None = None,
    mode: EnforcementMode | None = None,
) -> EnforcementOutcome:
    """Convenience wrapper for non-PipelineRequest callers (e.g. the LLM proxy).

    The proxy concatenates ``messages[].content`` and calls this directly so it
    does not need to construct a ``PipelineRequest`` for every inbound prompt.
    """
    started_at = time.perf_counter()
    if rule_set is None:
        rule_set = load_rules()
    if policy_set is None:
        policy_set = load_policies()
    effective_mode: EnforcementMode = mode or settings.enforcement_mode

    result = run_pipeline_raw(
        text,
        target=target,
        metadata=metadata,
        rule_set=rule_set,
        policy_set=policy_set,
    )
    return _build_outcome(result, policies_by_id(policy_set), effective_mode, started_at)


def log_enforcement_outcome(
    outcome: EnforcementOutcome,
    *,
    route: str,
    direction: EnforcementDirection = "ingress",
) -> None:
    """Emit a structured audit log line and persist the event in the ring buffer.

    ``direction`` distinguishes ingress (request-side) from egress (LLM proxy
    response-side) decisions so SIEMs can filter cleanly. The event is also
    appended to the in-memory ``enforcement_events`` ring buffer so the UI's
    live-traffic view can render it without parsing log files.
    """
    logger.info(
        "policy_enforcement",
        extra={
            "event": "policy_enforcement",
            "trace_id": outcome.trace_id,
            "route": route,
            "direction": direction,
            "mode": outcome.mode,
            "final_decision": outcome.final_decision,
            "blocked": outcome.blocked,
            "would_block": outcome.would_block,
            "matched_policy_ids": outcome.matched_policy_ids,
            "duration_ms": round(outcome.duration_ms, 3),
        },
    )
    try:
        record_event(outcome, route=route, direction=direction)
    except Exception:
        logger.exception("enforcement_event_record_failed trace_id=%s", outcome.trace_id)
    try:
        _emit_correlation(outcome, route=route, direction=direction)
    except Exception:
        logger.exception("correlation_emit_dispatch_failed trace_id=%s", outcome.trace_id)
    try:
        playbook_event = _build_playbook_event(
            outcome, route=route, direction=direction
        )
        _dispatch_playbooks(playbook_event)
    except Exception:
        logger.exception(
            "playbook_dispatch_failed trace_id=%s", outcome.trace_id
        )


__all__ = [
    "evaluate_request_for_enforcement",
    "evaluate_text_for_enforcement",
    "log_enforcement_outcome",
]
