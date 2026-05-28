"""Pydantic schemas for the Automated Response Playbooks (Phase 3).

Mirrors the YAML-first dialect already used by ``app.services.policy_engine``
so operators can carry over the same conditions vocabulary.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

PlaybookConditionOp = Literal[
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "contains",
    "matches",
    "exists",
    "not_exists",
]

ActionStatus = Literal["planned", "executed", "skipped", "error"]

BUILTIN_ACTIONS: tuple[str, ...] = (
    "block",
    "revoke",
    "alert",
    "quarantine",
    "ticket",
    "rate_limit",
)


class PlaybookCondition(BaseModel):
    """One AND-conjoined predicate evaluated against the PlaybookEvent dict."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, description="Dot-path into the PlaybookEvent")
    op: PlaybookConditionOp = Field(description="Comparison operator")
    value: Any | None = Field(
        default=None,
        description="Value to compare (omit for exists / not_exists)",
    )


class ActionSpec(BaseModel):
    """One action to run when a Playbook matches.

    ``action`` is a string identifier resolved at execution time via
    :class:`app.playbooks.registry.ActionRegistry`. Built-in identifiers are
    listed in :data:`BUILTIN_ACTIONS`. Custom actions live under the
    ``custom.<name>`` namespace.
    """

    model_config = ConfigDict(extra="forbid")

    action: str = Field(
        min_length=1,
        max_length=120,
        description="Action identifier (built-in name or 'custom.<name>')",
    )
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form parameters passed to the action implementation",
    )


class Playbook(BaseModel):
    """A single automated response playbook persisted as YAML."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        min_length=1,
        max_length=80,
        description="Unique slug-style identifier (also used as the YAML filename)",
    )
    name: str = Field(min_length=1, description="Display name")
    description: Optional[str] = Field(
        default=None, description="Free-form description"
    )
    enabled: bool = Field(
        default=True, description="Disabled playbooks are skipped at evaluation time"
    )
    priority: int = Field(
        default=50,
        ge=0,
        le=1000,
        description="Higher fires first; ties broken by id (stable order)",
    )
    when: List[PlaybookCondition] = Field(
        default_factory=list,
        description="AND-conjoined conditions; empty list matches every event",
    )
    then: List[ActionSpec] = Field(
        min_length=1,
        description="Actions to run, in declared order, when all when-conditions match",
    )
    tags: List[str] = Field(default_factory=list)
    version: int = Field(default=1, ge=1)


class PlaybookSet(BaseModel):
    """Collection of playbooks loaded from disk."""

    playbooks: List[Playbook] = Field(default_factory=list)

    def enabled(self) -> List[Playbook]:
        return [p for p in self.playbooks if p.enabled]


class ActionResult(BaseModel):
    """Outcome of a single action invocation."""

    action: str = Field(description="Action identifier that produced this result")
    status: ActionStatus = Field(description="planned | executed | skipped | error")
    message: str = Field(default="", description="Operator-readable summary")
    detail: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured payload for the audit trail",
    )
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the action began execution",
    )
    duration_ms: float = Field(
        default=0.0,
        ge=0,
        description="Wall-clock duration of the action in milliseconds",
    )


class PlaybookMatch(BaseModel):
    """A playbook that matched, paired with its per-action results."""

    playbook_id: str
    name: str
    priority: int
    matched: bool
    reasons: List[str] = Field(
        default_factory=list,
        description="Per-condition trace describing which fields matched",
    )
    results: List[ActionResult] = Field(default_factory=list)


ActionPhase = Literal["all", "inline", "background"]


class ExecutionTrace(BaseModel):
    """Result of running an event through the playbook executor."""

    event_id: str
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    duration_ms: float = Field(default=0.0, ge=0)
    matched_playbook_ids: List[str] = Field(default_factory=list)
    matches: List[PlaybookMatch] = Field(default_factory=list)
    dry_run: bool = Field(
        default=True,
        description="True when no real side effects were performed (engine-wide flag)",
    )
    enabled: bool = Field(
        default=True,
        description="False when the playbook engine kill switch was off",
    )
    phase: ActionPhase = Field(
        default="all",
        description=(
            "Which action phase produced this trace. Inline traces carry only "
            "blocking actions; background traces carry the rest; 'all' is the "
            "merged trace persisted in the ring buffer."
        ),
    )
    correlation_id: str = Field(
        default="",
        description="Stable id used to join inline and background traces for one event",
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Source trace id from the originating event (e.g. enforcement trace_id)",
    )


# ---- API request / response models ----------------------------------------


class PlaybookListResponse(BaseModel):
    """Response payload for ``GET /playbooks``."""

    playbooks: List[Playbook] = Field(default_factory=list)
    total: int = Field(ge=0, description="Total playbooks on disk")
    fingerprints: Dict[str, str] = Field(
        default_factory=dict,
        description="playbook_id -> fingerprint hash for change detection",
    )


class PlaybookValidateResponse(BaseModel):
    """Response payload for ``POST /playbooks/validate``."""

    valid: bool = Field(description="True when the body parses as a Playbook")
    playbook: Optional[Playbook] = Field(default=None)
    errors: List[str] = Field(default_factory=list)


class PlaybookReloadResponse(BaseModel):
    """Response payload for ``POST /playbooks/reload``."""

    reloaded_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    playbooks_path: str = Field(description="Configured playbooks directory")
    previous_count: int = Field(ge=0)
    new_count: int = Field(ge=0)
    diff_added: List[str] = Field(default_factory=list)
    diff_removed: List[str] = Field(default_factory=list)
    diff_changed: List[str] = Field(default_factory=list)
    diff_unchanged: int = Field(default=0, ge=0)


class PlaybookEvaluateRequest(BaseModel):
    """Request payload for ``POST /playbooks/evaluate``.

    Runs an event through the loaded library and returns the full trace.
    Never persists to the trace buffer (this is the safe playground).
    """

    model_config = ConfigDict(extra="forbid")

    event: Dict[str, Any] = Field(
        description="Raw PlaybookEvent payload (validated server-side)"
    )
    dry_run: bool = Field(default=True)
    phase: ActionPhase = Field(default="all")


class PlaybookEvaluateResponse(BaseModel):
    """Response payload for ``POST /playbooks/evaluate``."""

    trace: ExecutionTrace


class PlaybookEventRequest(BaseModel):
    """Request payload for ``POST /playbooks/events``.

    Used by the Correlation Engine (or any external producer) to push a
    finding into the playbook engine. Dispatches via the runtime, so it
    persists into the trace buffer and honors the global kill switch.
    """

    model_config = ConfigDict(extra="forbid")

    event: Dict[str, Any] = Field(description="Raw PlaybookEvent payload")


class PlaybookEventResponse(BaseModel):
    """Response payload for ``POST /playbooks/events``."""

    accepted: bool = Field(description="True when the engine accepted the event")
    enabled: bool = Field(description="Engine kill-switch state at dispatch time")
    inline_trace: ExecutionTrace = Field(
        description="Synchronous (inline-phase) trace returned to the caller"
    )


class PlaybookTraceListResponse(BaseModel):
    """Response payload for ``GET /playbooks/traces``."""

    total: int = Field(ge=0, description="Total traces matching the filter")
    returned: int = Field(ge=0, description="Number of traces returned in this page")
    capacity: int = Field(ge=0, description="Trace ring buffer capacity")
    traces: List[ExecutionTrace] = Field(default_factory=list)
