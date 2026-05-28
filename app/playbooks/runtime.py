"""Live runtime for the Automated Response Playbook engine.

Bridges three concerns the executor itself does not know about:

1. **Configuration**: read ``settings.playbooks_enabled`` and
   ``settings.playbooks_dry_run`` once per dispatch.
2. **Hybrid execution**: run the synchronous inline phase on the request
   thread (so a 'block' action can affect the response) and the
   background phase on a daemon thread (so slow integrations cannot
   stall the request path).
3. **Persistence**: append the merged trace to the in-memory trace ring
   buffer so the audit and SOC views can query it.
"""

from __future__ import annotations

import threading
import uuid
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.playbooks.events import PlaybookEvent
from app.playbooks.executor import merge_traces, process_event
from app.playbooks.schemas import ExecutionTrace, PlaybookSet
from app.playbooks.store import load_playbooks
from app.playbooks.trace_buffer import record_trace

logger = get_logger(__name__)


def _empty_trace(event: PlaybookEvent, *, correlation: str) -> ExecutionTrace:
    """Return a no-op trace shaped exactly like a real one (kill-switch path)."""
    return ExecutionTrace(
        event_id=event.event_id,
        enabled=False,
        dry_run=settings.playbooks_dry_run,
        phase="inline",
        correlation_id=correlation,
        trace_id=event.trace_id,
    )


def dispatch(
    event: PlaybookEvent,
    *,
    library: Optional[PlaybookSet] = None,
    enabled: Optional[bool] = None,
    dry_run: Optional[bool] = None,
) -> ExecutionTrace:
    """Run *event* through the live engine and return the inline-phase trace.

    The background phase runs in a daemon thread and persists the
    merged trace to the ring buffer when it completes. Callers that
    need the merged trace (e.g. tests) should poll
    :mod:`app.playbooks.trace_buffer` afterwards.

    All exceptions are absorbed: this function never raises into the
    request hot path.
    """
    is_enabled = settings.playbooks_enabled if enabled is None else bool(enabled)
    is_dry_run = settings.playbooks_dry_run if dry_run is None else bool(dry_run)
    correlation = str(uuid.uuid4())

    if not is_enabled:
        trace = _empty_trace(event, correlation=correlation)
        try:
            record_trace(trace)
        except Exception:
            logger.exception("playbook_trace_record_failed event=%s", event.event_id)
        return trace

    try:
        playbooks = library or load_playbooks(use_cache=True)
    except Exception:
        logger.exception("playbook_library_load_failed; treating as empty")
        playbooks = PlaybookSet(playbooks=[])

    try:
        inline_trace = process_event(
            event,
            playbooks,
            enabled=is_enabled,
            dry_run=is_dry_run,
            correlation_id=correlation,
            phase="inline",
        )
    except Exception:
        logger.exception("playbook_inline_phase_failed event=%s", event.event_id)
        inline_trace = _empty_trace(event, correlation=correlation)

    def _background() -> None:
        try:
            background_trace = process_event(
                event,
                playbooks,
                enabled=is_enabled,
                dry_run=is_dry_run,
                correlation_id=correlation,
                phase="background",
            )
            merged = merge_traces(inline_trace, background_trace)
            record_trace(merged)
        except Exception:
            logger.exception(
                "playbook_background_phase_failed event=%s", event.event_id
            )
            try:
                record_trace(inline_trace)
            except Exception:
                logger.exception(
                    "playbook_trace_record_failed event=%s", event.event_id
                )

    threading.Thread(
        target=_background,
        name=f"playbook-bg-{event.event_id[:8]}",
        daemon=True,
    ).start()

    return inline_trace


def dispatch_sync(
    event: PlaybookEvent,
    *,
    library: Optional[PlaybookSet] = None,
    enabled: Optional[bool] = None,
    dry_run: Optional[bool] = None,
) -> ExecutionTrace:
    """Synchronous variant: run inline + background phases in-line and persist.

    Used by the manual ``POST /playbooks/events`` endpoint and by tests
    that need a fully-merged trace returned immediately. Production code
    on the request hot path should call :func:`dispatch` instead.
    """
    is_enabled = settings.playbooks_enabled if enabled is None else bool(enabled)
    is_dry_run = settings.playbooks_dry_run if dry_run is None else bool(dry_run)
    correlation = str(uuid.uuid4())

    if not is_enabled:
        trace = ExecutionTrace(
            event_id=event.event_id,
            enabled=False,
            dry_run=is_dry_run,
            phase="all",
            correlation_id=correlation,
            trace_id=event.trace_id,
        )
        try:
            record_trace(trace)
        except Exception:
            logger.exception("playbook_trace_record_failed event=%s", event.event_id)
        return trace

    playbooks = library or load_playbooks(use_cache=True)

    inline_trace = process_event(
        event,
        playbooks,
        enabled=is_enabled,
        dry_run=is_dry_run,
        correlation_id=correlation,
        phase="inline",
    )
    background_trace = process_event(
        event,
        playbooks,
        enabled=is_enabled,
        dry_run=is_dry_run,
        correlation_id=correlation,
        phase="background",
    )
    merged = merge_traces(inline_trace, background_trace)
    record_trace(merged)
    return merged


__all__ = ["dispatch", "dispatch_sync"]
