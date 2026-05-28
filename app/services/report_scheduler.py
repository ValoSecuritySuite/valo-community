"""Weekly cadence scheduler for the Phase 4 reporting pipeline.

Walks the configured default report kinds on every tick and runs the
ones that have not yet been generated for the current weekly window.
The "weekly window" begins at the configured weekday + hour (UTC) and
runs until the same time next week. Once a kind has produced an ``ok``
report inside the current window, it is skipped until the next window
opens.

State (per-kind last successful run) is persisted via
:func:`app.services.report_store.kv_set` so a process restart picks up
where the previous one left off and the API can surface "next run" /
"last run" hints in the UI.

The scheduler also calls :func:`report_store.prune_older_than` after
each successful tick so the disk catalogue stays bounded by
``settings.report_retention_days``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.services import report_generator_jobs, report_store

logger = get_logger(__name__)

_LAST_RUN_KEY_PREFIX = "scheduler:last_weekly_run:"


@dataclass
class TickResult:
    """Summary of a single scheduler tick."""

    ran: list[str]
    skipped: list[str]
    failed: list[tuple[str, str]]
    pruned: int = 0
    now: Optional[datetime] = None


def _last_run_key(kind: str) -> str:
    return f"{_LAST_RUN_KEY_PREFIX}{kind}"


def _weekday_hour(now: datetime) -> tuple[int, int]:
    """Return weekday + hour (UTC) for the configured weekly cadence."""
    weekday = int(settings.report_schedule_weekly_weekday) % 7
    hour = max(0, min(23, int(settings.report_schedule_weekly_hour)))
    _ = now  # placeholder so callers can pass the clock for tests
    return weekday, hour


def current_window_start(now: datetime) -> datetime:
    """Return the start (inclusive) of the weekly window containing *now*.

    The window opens at weekday/hour UTC and runs for 7 days. If *now*
    is before the first window opening of its current week, we return
    the previous week's opening.
    """
    weekday, hour = _weekday_hour(now)
    aligned = now.astimezone(timezone.utc).replace(
        minute=0, second=0, microsecond=0
    )
    delta_days = (aligned.weekday() - weekday) % 7
    candidate = aligned.replace(hour=hour) - timedelta(days=delta_days)
    if candidate > aligned:
        candidate -= timedelta(days=7)
    return candidate


def next_window_start(now: datetime) -> datetime:
    """Return the next weekly window opening after *now*."""
    return current_window_start(now) + timedelta(days=7)


def get_last_run(kind: str) -> Optional[datetime]:
    raw = report_store.kv_get(_last_run_key(kind))
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def set_last_run(kind: str, when: datetime) -> None:
    when = when.astimezone(timezone.utc)
    report_store.kv_set(_last_run_key(kind), when.isoformat())


def is_due(kind: str, now: datetime) -> bool:
    """Return True when *kind* has not yet been generated in the current window."""
    window_start = current_window_start(now)
    last_run = get_last_run(kind)
    if last_run is None:
        return True
    return last_run < window_start


def _resolved_default_kinds() -> list[str]:
    kinds = list(settings.report_default_kinds or [])
    return [k for k in kinds if k in report_generator_jobs.REGISTRY]


def run_due_kinds(
    *,
    now: Optional[datetime] = None,
    kinds: Optional[Iterable[str]] = None,
    force: bool = False,
) -> TickResult:
    """Generate every kind in *kinds* that is currently due.

    When *force* is True every requested kind is generated regardless of
    its last-run timestamp; useful for the manual ``POST /reports/scheduler/run``
    endpoint and for tests.
    """
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    candidate_kinds = list(kinds) if kinds is not None else _resolved_default_kinds()

    ran: list[str] = []
    skipped: list[str] = []
    failed: list[tuple[str, str]] = []

    for kind in candidate_kinds:
        if kind not in report_generator_jobs.REGISTRY:
            failed.append((kind, "unknown report kind"))
            continue
        if not force and not is_due(kind, stamp):
            skipped.append(kind)
            continue
        try:
            result = report_generator_jobs.run_kind(kind, now=stamp)
        except report_generator_jobs.ReportJobError as exc:
            logger.warning(
                "report_scheduler_kind_failed kind=%s message=%s",
                kind,
                exc.message,
            )
            failed.append((kind, exc.message))
            try:
                report_store.save_report(
                    kind=kind,
                    fmt="json",
                    payload=b"{}",
                    filename=f"valo-{kind}-failure-{stamp.strftime('%Y%m%dT%H%M%SZ')}.json",
                    status="failed",
                    error=exc.message,
                    metadata={"detail": exc.detail or {}},
                    generated_at=stamp,
                )
            except Exception:  # pragma: no cover - defensive
                logger.exception(
                    "report_scheduler_failure_record_failed kind=%s", kind
                )
            continue
        try:
            report_store.save_report(
                kind=kind,
                fmt=result.format,
                payload=result.payload,
                filename=result.filename,
                window=result.window,
                status="ok",
                metadata=dict(result.metadata or {}),
                generated_at=stamp,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("report_scheduler_persist_failed kind=%s", kind)
            failed.append((kind, str(exc)))
            continue
        set_last_run(kind, stamp)
        ran.append(kind)
        logger.info(
            "report_scheduler_kind_generated kind=%s bytes=%d format=%s",
            kind,
            len(result.payload),
            result.format,
        )

    pruned = 0
    if ran:
        try:
            pruned = report_store.prune_older_than(
                int(settings.report_retention_days)
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception("report_scheduler_prune_failed")
    return TickResult(ran=ran, skipped=skipped, failed=failed, pruned=pruned, now=stamp)


async def run_forever() -> None:
    """Run the scheduler on a fixed cadence until cancelled."""
    interval = max(10, int(settings.report_scheduler_tick_seconds))
    logger.info(
        "report_scheduler_started interval_seconds=%d weekday=%d hour=%d",
        interval,
        int(settings.report_schedule_weekly_weekday),
        int(settings.report_schedule_weekly_hour),
    )
    try:
        while True:
            try:
                tick = await asyncio.to_thread(run_due_kinds)
                if tick.ran or tick.failed:
                    logger.info(
                        "report_scheduler_tick ran=%s failed=%s skipped=%s pruned=%d",
                        tick.ran,
                        [k for k, _ in tick.failed],
                        tick.skipped,
                        tick.pruned,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - defensive
                logger.exception("report_scheduler_tick_failed")
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("report_scheduler_stopped")
        raise


__all__ = [
    "TickResult",
    "current_window_start",
    "get_last_run",
    "is_due",
    "next_window_start",
    "run_due_kinds",
    "run_forever",
    "set_last_run",
]
