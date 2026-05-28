"""In-memory ring buffer of enforcement events.

The ingress middleware and egress proxy each call :func:`record_event` after
they finish evaluating a request. The buffer feeds the ``/enforcement/events``
and ``/enforcement/stats`` endpoints so the UI can render a live traffic log
and dashboards without parsing log files or standing up a database.

Phase 1 is intentionally bounded and process-local: capacity is configurable
via ``settings.enforcement_event_buffer_capacity`` and oldest events are
evicted FIFO when the buffer is full. Phase 2+ should swap this for a durable
store (DuckDB / SQLite / external SIEM exporter) with the same query surface.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Iterable

from app.core.config import settings
from app.schemas import (
    EnforcementDecisionCounts,
    EnforcementDirection,
    EnforcementEvent,
    EnforcementOutcome,
    EnforcementStats,
    EnforcementTopPolicy,
    EnforcementTopRoute,
    PolicyDecisionLiteral,
)

_lock = threading.RLock()
_buffer: deque[EnforcementEvent] = deque(maxlen=settings.enforcement_event_buffer_capacity)


def _ensure_capacity() -> None:
    """Resync the internal deque with the current settings capacity."""
    global _buffer
    target = max(int(settings.enforcement_event_buffer_capacity), 1)
    if _buffer.maxlen == target:
        return
    new_buffer: deque[EnforcementEvent] = deque(_buffer, maxlen=target)
    _buffer = new_buffer


def _outcome_to_event(
    outcome: EnforcementOutcome,
    *,
    route: str,
    direction: EnforcementDirection,
) -> EnforcementEvent:
    matched_decisions = [d for d in outcome.decisions if d.matched]
    return EnforcementEvent(
        trace_id=outcome.trace_id,
        timestamp=datetime.now(timezone.utc),
        route=route,
        direction=direction,
        mode=outcome.mode,
        final_decision=outcome.final_decision,
        blocked=outcome.blocked,
        would_block=outcome.would_block,
        matched_policy_ids=list(outcome.matched_policy_ids),
        matched_decisions=matched_decisions,
        duration_ms=outcome.duration_ms,
    )


def record_event(
    outcome: EnforcementOutcome,
    *,
    route: str,
    direction: EnforcementDirection = "ingress",
) -> EnforcementEvent:
    """Append an event derived from *outcome* to the ring buffer."""
    event = _outcome_to_event(outcome, route=route, direction=direction)
    with _lock:
        _ensure_capacity()
        _buffer.append(event)
    return event


def clear_events() -> None:
    """Drop every retained event (used by tests and by manual operator action)."""
    with _lock:
        _buffer.clear()


def buffer_capacity() -> int:
    return max(int(settings.enforcement_event_buffer_capacity), 1)


def buffer_used() -> int:
    with _lock:
        return len(_buffer)


def query_events(
    *,
    limit: int = 50,
    offset: int = 0,
    decision: PolicyDecisionLiteral | None = None,
    route: str | None = None,
    direction: EnforcementDirection | None = None,
    blocked: bool | None = None,
    trace_id: str | None = None,
    since: datetime | None = None,
) -> tuple[list[EnforcementEvent], int]:
    """Return ``(events, total_matching)`` for the given filters.

    Events come back newest-first. ``total_matching`` ignores ``limit`` and
    ``offset`` so the UI can render pagination state correctly.
    """
    with _lock:
        snapshot = list(_buffer)

    filtered: list[EnforcementEvent] = []
    for event in reversed(snapshot):
        if decision is not None and event.final_decision != decision:
            continue
        if route is not None and event.route != route:
            continue
        if direction is not None and event.direction != direction:
            continue
        if blocked is not None and event.blocked != blocked:
            continue
        if trace_id is not None and event.trace_id != trace_id:
            continue
        if since is not None and event.timestamp < since:
            continue
        filtered.append(event)

    total = len(filtered)
    sliced = filtered[offset : offset + max(0, int(limit))]
    return sliced, total


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    if percentile <= 0:
        return values[0]
    if percentile >= 100:
        return values[-1]
    sorted_values = sorted(values)
    rank = (percentile / 100.0) * (len(sorted_values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = rank - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def aggregate_stats(
    *,
    window_seconds: int = 0,
    top_n: int = 5,
    now: datetime | None = None,
) -> EnforcementStats:
    """Aggregate retained events into a single :class:`EnforcementStats`.

    ``window_seconds == 0`` means "all retained events"; otherwise events
    older than ``now - window_seconds`` are excluded.
    """
    current = now or datetime.now(timezone.utc)
    with _lock:
        snapshot = list(_buffer)

    if window_seconds > 0:
        cutoff = current.timestamp() - window_seconds
        windowed = [e for e in snapshot if e.timestamp.timestamp() >= cutoff]
    else:
        windowed = list(snapshot)

    decision_counts = EnforcementDecisionCounts()
    direction_counts: dict[str, int] = {}
    policy_counts: dict[str, int] = {}
    route_counts: dict[str, int] = {}
    durations: list[float] = []
    blocked_total = 0
    would_block_total = 0

    for event in windowed:
        if event.final_decision == "deny":
            decision_counts.deny += 1
        elif event.final_decision == "warn":
            decision_counts.warn += 1
        else:
            decision_counts.allow += 1

        direction_counts[event.direction] = direction_counts.get(event.direction, 0) + 1
        route_counts[event.route] = route_counts.get(event.route, 0) + 1
        for policy_id in event.matched_policy_ids:
            policy_counts[policy_id] = policy_counts.get(policy_id, 0) + 1
        durations.append(float(event.duration_ms))
        if event.blocked:
            blocked_total += 1
        if event.would_block:
            would_block_total += 1

    top_policies = [
        EnforcementTopPolicy(policy_id=pid, matches=count)
        for pid, count in sorted(policy_counts.items(), key=lambda x: x[1], reverse=True)[:top_n]
    ]
    top_routes = [
        EnforcementTopRoute(route=route, requests=count)
        for route, count in sorted(route_counts.items(), key=lambda x: x[1], reverse=True)[:top_n]
    ]

    total = len(windowed)
    block_rate = (blocked_total / total) if total > 0 else 0.0

    return EnforcementStats(
        window_seconds=window_seconds,
        total_events=total,
        blocked=blocked_total,
        would_block=would_block_total,
        by_decision=decision_counts,
        by_direction=direction_counts,
        top_policies=top_policies,
        top_routes=top_routes,
        p50_duration_ms=round(_percentile(durations, 50), 3),
        p95_duration_ms=round(_percentile(durations, 95), 3),
        block_rate=round(block_rate, 4),
    )


def all_events() -> list[EnforcementEvent]:
    """Snapshot of every retained event, oldest first. Used by tests."""
    with _lock:
        return list(_buffer)


def iter_events() -> Iterable[EnforcementEvent]:
    """Iterate over a snapshot of the events without holding the lock."""
    with _lock:
        snapshot = list(_buffer)
    return iter(snapshot)


__all__ = [
    "record_event",
    "clear_events",
    "buffer_capacity",
    "buffer_used",
    "query_events",
    "aggregate_stats",
    "all_events",
    "iter_events",
]
