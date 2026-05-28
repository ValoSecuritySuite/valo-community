"""Typed event consumed by the playbook engine.

A :class:`PlaybookEvent` is the single input shape every action sees. It
flattens the heterogeneous detection pipeline (in-process enforcement
outcomes, correlation findings, future external sources) into a uniform
record so playbook conditions and actions can be written once.

Construction helpers (e.g. :func:`from_enforcement_outcome`) live next to
the model so callers do not need to know the field layout.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

EventSource = Literal["valo", "correlation_engine", "external"]
EventSeverity = Literal["info", "low", "medium", "high", "critical"]
EventDecision = Literal["allow", "warn", "deny"]


class EventSubject(BaseModel):
    """The entity an action would target (session, ip, api_key, ...)."""

    model_config = ConfigDict(extra="allow")

    type: str = Field(
        description="Subject kind: session, ip, user, api_key, repo, connector, ...",
    )
    id: str = Field(min_length=1, description="Stable identifier of the subject")


class PlaybookEvent(BaseModel):
    """Uniform event passed to the playbook engine.

    Conditions in YAML reference fields with dot-paths; nested dicts are
    walked the same way as the policy engine does on its context, so
    ``subject.type`` and ``raw.combined_score`` are both addressable.
    """

    model_config = ConfigDict(extra="allow")

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: EventSource = Field(default="valo")
    event_type: str = Field(default="enforcement.outcome")
    tenant_id: Optional[str] = None
    severity: EventSeverity = "info"
    decision: Optional[EventDecision] = None
    blocked: bool = False
    matched_policy_ids: List[str] = Field(default_factory=list)
    combined_score: Optional[float] = None
    trace_id: Optional[str] = None
    subject: Optional[EventSubject] = None
    raw: Dict[str, Any] = Field(default_factory=dict)


def _severity_from_outcome(outcome: Any) -> EventSeverity:
    """Map an ``EnforcementOutcome``-like object to a coarse severity bucket."""
    if getattr(outcome, "blocked", False):
        return "high"
    if getattr(outcome, "would_block", False):
        return "medium"
    if getattr(outcome, "matched_policy_ids", None):
        return "low"
    return "info"


def from_enforcement_outcome(
    outcome: Any,
    *,
    route: str = "",
    direction: str = "ingress",
    tenant_id: Optional[str] = None,
    subject: Optional[EventSubject] = None,
) -> PlaybookEvent:
    """Build a :class:`PlaybookEvent` from an ``EnforcementOutcome``.

    Accepts a duck-typed object so the playbook engine has no hard
    dependency on the enforcement layer's exact class. Anything exposing
    ``trace_id``, ``final_decision``, ``blocked``, ``would_block``,
    ``matched_policy_ids``, ``combined_score`` works.
    """
    matched: List[str] = list(getattr(outcome, "matched_policy_ids", []) or [])
    combined = getattr(outcome, "combined_score", None)
    decision_raw = getattr(outcome, "final_decision", None)
    decision: Optional[EventDecision] = (
        decision_raw if decision_raw in ("allow", "warn", "deny") else None
    )
    return PlaybookEvent(
        source="valo",
        event_type="enforcement.outcome",
        tenant_id=tenant_id,
        severity=_severity_from_outcome(outcome),
        decision=decision,
        blocked=bool(getattr(outcome, "blocked", False)),
        matched_policy_ids=matched,
        combined_score=float(combined) if combined is not None else None,
        trace_id=getattr(outcome, "trace_id", None),
        subject=subject,
        raw={
            "route": route,
            "direction": direction,
            "would_block": bool(getattr(outcome, "would_block", False)),
            "max_severity_found": getattr(outcome, "max_severity_found", None),
        },
    )


__all__ = [
    "EventDecision",
    "EventSeverity",
    "EventSource",
    "EventSubject",
    "PlaybookEvent",
    "from_enforcement_outcome",
]
