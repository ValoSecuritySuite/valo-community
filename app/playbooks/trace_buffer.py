"""In-memory ring buffer of playbook execution traces.

Symmetric with :mod:`app.services.enforcement_events`: bounded FIFO queue,
process-local, fed by :func:`app.playbooks.runtime.dispatch`.

Phase 4 (Learning Loop) wraps this buffer: every call to
:func:`record_trace` also writes a durable :class:`OutcomeRecord` to
:mod:`app.services.outcome_store` so analyst labels and the refiner job
keep working across process restarts. The ring buffer stays in place as
a hot cache for the existing ``GET /playbooks/traces`` dashboard read
path.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.playbooks.schemas import ExecutionTrace
from app.services import outcome_store

logger = get_logger(__name__)

_lock = threading.RLock()
_buffer: deque[ExecutionTrace] = deque(
    maxlen=settings.playbook_trace_buffer_capacity
)


def _ensure_capacity() -> None:
    """Resync the internal deque with the current settings capacity."""
    global _buffer
    target = max(int(settings.playbook_trace_buffer_capacity), 1)
    if _buffer.maxlen == target:
        return
    new_buffer: deque[ExecutionTrace] = deque(_buffer, maxlen=target)
    _buffer = new_buffer


def record_trace(trace: ExecutionTrace) -> ExecutionTrace:
    """Append *trace* to the ring buffer and persist a durable outcome.

    The durable write is best-effort: a SQLite failure must never break
    the request hot path, so any exception from the outcome store is
    logged and swallowed. The ring buffer is the single source of truth
    for the existing dashboard query surface.
    """
    with _lock:
        _ensure_capacity()
        _buffer.append(trace)
    try:
        record = outcome_store.record_from_trace(trace, source="valo")
        outcome_store.upsert_outcome(record)
    except Exception:
        logger.exception(
            "outcome_persist_failed event_id=%s trace_id=%s",
            getattr(trace, "event_id", None),
            getattr(trace, "trace_id", None),
        )
    return trace


def clear_traces() -> None:
    """Drop every retained trace (used by tests and operator action)."""
    with _lock:
        _buffer.clear()


def buffer_capacity() -> int:
    return max(int(settings.playbook_trace_buffer_capacity), 1)


def buffer_used() -> int:
    with _lock:
        return len(_buffer)


def query_traces(
    *,
    limit: int = 50,
    offset: int = 0,
    event_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    matched_only: Optional[bool] = None,
    since: Optional[datetime] = None,
) -> tuple[list[ExecutionTrace], int]:
    """Return ``(traces, total_matching)`` for the given filters (newest first).

    ``total_matching`` ignores pagination so the UI can render counts.
    """
    with _lock:
        snapshot = list(_buffer)

    filtered: list[ExecutionTrace] = []
    for trace in reversed(snapshot):
        if event_id is not None and trace.event_id != event_id:
            continue
        if trace_id is not None and trace.trace_id != trace_id:
            continue
        if correlation_id is not None and trace.correlation_id != correlation_id:
            continue
        if matched_only is True and not trace.matched_playbook_ids:
            continue
        if matched_only is False and trace.matched_playbook_ids:
            continue
        if since is not None and trace.started_at < since:
            continue
        filtered.append(trace)

    total = len(filtered)
    sliced = filtered[offset : offset + max(0, int(limit))]
    return sliced, total


def all_traces() -> list[ExecutionTrace]:
    """Snapshot of every retained trace, oldest first. Used by tests."""
    with _lock:
        return list(_buffer)


__all__ = [
    "all_traces",
    "buffer_capacity",
    "buffer_used",
    "clear_traces",
    "query_traces",
    "record_trace",
]
