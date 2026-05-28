"""Periodic rollup task feeding the executive metrics store.

Snapshots the in-memory enforcement event ring buffer, the playbook trace
ring buffer, and the in-process scan history; emits 5-minute, 1-hour, and
1-day aggregated rows into ``metrics_buckets`` (idempotently, via
``INSERT OR IGNORE`` semantics in the store).

The aggregator is a single coroutine kicked off from ``app.main``'s
lifespan when ``settings.executive_metrics_enabled`` is True. Tests drive
``run_once`` directly.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Iterable, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.playbooks.schemas import ExecutionTrace
from app.playbooks.trace_buffer import all_traces as all_playbook_traces
from app.schemas import EnforcementEvent
from app.services import executive_store
from app.services.enforcement_events import all_events as all_enforcement_events
from app.services.executive_store import (
    BUCKET_SIZE_1D,
    BUCKET_SIZE_1H,
    BUCKET_SIZE_5M,
    BucketRow,
    align_bucket,
)
from app.services.portfolio import list_scan_results

logger = get_logger(__name__)

SOURCE_ENFORCEMENT = "enforcement"
SOURCE_PLAYBOOKS = "playbooks"
SOURCE_PIPELINE = "pipeline"

DIM_GLOBAL = "global"
DIM_POLICY = "policy_id"
DIM_ROUTE = "route"
DIM_DIRECTION = "direction"
DIM_DECISION = "decision"
DIM_SUBJECT = "subject"
DIM_PLAYBOOK = "playbook_id"
DIM_ACTION = "action"
DIM_SEVERITY = "severity"
DIM_MTTA = "mtta"


def _bucket_for(ts: float) -> int:
    return align_bucket(ts, BUCKET_SIZE_5M)


def _safe_severity(score: float) -> str:
    if score >= 80:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 40:
        return "medium"
    if score >= 20:
        return "low"
    return "minimal"


def _enforcement_rows(
    events: Iterable[EnforcementEvent],
) -> list[BucketRow]:
    """Turn enforcement events into 5-minute bucket rows."""
    rows: list[BucketRow] = []
    for event in events:
        bucket_start = _bucket_for(event.timestamp.timestamp())
        rows.append(
            BucketRow(
                bucket_start=bucket_start,
                bucket_size_seconds=BUCKET_SIZE_5M,
                source=SOURCE_ENFORCEMENT,
                dimension_key=DIM_GLOBAL,
                dimension_value=DIM_GLOBAL,
                metric="requests",
                value=1.0,
                count=1,
            )
        )
        rows.append(
            BucketRow(
                bucket_start=bucket_start,
                bucket_size_seconds=BUCKET_SIZE_5M,
                source=SOURCE_ENFORCEMENT,
                dimension_key=DIM_GLOBAL,
                dimension_value=DIM_GLOBAL,
                metric="duration_ms_sum",
                value=float(event.duration_ms),
                count=1,
            )
        )
        if event.blocked:
            rows.append(
                BucketRow(
                    bucket_start=bucket_start,
                    bucket_size_seconds=BUCKET_SIZE_5M,
                    source=SOURCE_ENFORCEMENT,
                    dimension_key=DIM_GLOBAL,
                    dimension_value=DIM_GLOBAL,
                    metric="blocked",
                    value=1.0,
                    count=1,
                )
            )
        if event.would_block:
            rows.append(
                BucketRow(
                    bucket_start=bucket_start,
                    bucket_size_seconds=BUCKET_SIZE_5M,
                    source=SOURCE_ENFORCEMENT,
                    dimension_key=DIM_GLOBAL,
                    dimension_value=DIM_GLOBAL,
                    metric="would_block",
                    value=1.0,
                    count=1,
                )
            )
        rows.append(
            BucketRow(
                bucket_start=bucket_start,
                bucket_size_seconds=BUCKET_SIZE_5M,
                source=SOURCE_ENFORCEMENT,
                dimension_key=DIM_DECISION,
                dimension_value=str(event.final_decision),
                metric="count",
                value=1.0,
                count=1,
            )
        )
        rows.append(
            BucketRow(
                bucket_start=bucket_start,
                bucket_size_seconds=BUCKET_SIZE_5M,
                source=SOURCE_ENFORCEMENT,
                dimension_key=DIM_DIRECTION,
                dimension_value=str(event.direction),
                metric="count",
                value=1.0,
                count=1,
            )
        )
        rows.append(
            BucketRow(
                bucket_start=bucket_start,
                bucket_size_seconds=BUCKET_SIZE_5M,
                source=SOURCE_ENFORCEMENT,
                dimension_key=DIM_ROUTE,
                dimension_value=str(event.route or "unknown"),
                metric="requests",
                value=1.0,
                count=1,
            )
        )
        if event.blocked:
            rows.append(
                BucketRow(
                    bucket_start=bucket_start,
                    bucket_size_seconds=BUCKET_SIZE_5M,
                    source=SOURCE_ENFORCEMENT,
                    dimension_key=DIM_ROUTE,
                    dimension_value=str(event.route or "unknown"),
                    metric="blocked",
                    value=1.0,
                    count=1,
                )
            )
        for policy_id in event.matched_policy_ids:
            rows.append(
                BucketRow(
                    bucket_start=bucket_start,
                    bucket_size_seconds=BUCKET_SIZE_5M,
                    source=SOURCE_ENFORCEMENT,
                    dimension_key=DIM_POLICY,
                    dimension_value=str(policy_id),
                    metric="matches",
                    value=1.0,
                    count=1,
                )
            )
            if event.blocked:
                rows.append(
                    BucketRow(
                        bucket_start=bucket_start,
                        bucket_size_seconds=BUCKET_SIZE_5M,
                        source=SOURCE_ENFORCEMENT,
                        dimension_key=DIM_POLICY,
                        dimension_value=str(policy_id),
                        metric="blocked",
                        value=1.0,
                        count=1,
                    )
                )
    return rows


def _subject_for_trace(trace: ExecutionTrace) -> Optional[tuple[str, str]]:
    """Pull a ``(subject_type, subject_id)`` pair off a trace if present.

    The trace itself doesn't carry the subject, but the originating event
    payload does. We rely on the playbook matches' first reasons to
    optionally surface a deny-sourced offender; otherwise return None.
    """
    return None


def _playbook_rows(traces: Iterable[ExecutionTrace]) -> list[BucketRow]:
    """Emit playbook-side rollups from trace history."""
    rows: list[BucketRow] = []
    for trace in traces:
        if trace.phase != "all":
            # Only the merged "all" trace counts as a single execution
            # event; phase-scoped traces are intermediate.
            continue
        bucket_start = _bucket_for(trace.started_at.timestamp())

        rows.append(
            BucketRow(
                bucket_start=bucket_start,
                bucket_size_seconds=BUCKET_SIZE_5M,
                source=SOURCE_PLAYBOOKS,
                dimension_key=DIM_GLOBAL,
                dimension_value=DIM_GLOBAL,
                metric="events_total",
                value=1.0,
                count=1,
            )
        )

        if trace.matched_playbook_ids:
            rows.append(
                BucketRow(
                    bucket_start=bucket_start,
                    bucket_size_seconds=BUCKET_SIZE_5M,
                    source=SOURCE_PLAYBOOKS,
                    dimension_key=DIM_GLOBAL,
                    dimension_value=DIM_GLOBAL,
                    metric="playbooks_fired",
                    value=float(len(trace.matched_playbook_ids)),
                    count=1,
                )
            )
            rows.append(
                BucketRow(
                    bucket_start=bucket_start,
                    bucket_size_seconds=BUCKET_SIZE_5M,
                    source=SOURCE_PLAYBOOKS,
                    dimension_key=DIM_MTTA,
                    dimension_value=DIM_MTTA,
                    metric="duration_ms_sum",
                    value=float(trace.duration_ms),
                    count=1,
                )
            )

        for match in trace.matches:
            if not match.matched:
                continue
            rows.append(
                BucketRow(
                    bucket_start=bucket_start,
                    bucket_size_seconds=BUCKET_SIZE_5M,
                    source=SOURCE_PLAYBOOKS,
                    dimension_key=DIM_PLAYBOOK,
                    dimension_value=str(match.playbook_id),
                    metric="matches",
                    value=1.0,
                    count=1,
                )
            )
            for result in match.results:
                rows.append(
                    BucketRow(
                        bucket_start=bucket_start,
                        bucket_size_seconds=BUCKET_SIZE_5M,
                        source=SOURCE_PLAYBOOKS,
                        dimension_key=DIM_PLAYBOOK,
                        dimension_value=str(match.playbook_id),
                        metric="actions_executed",
                        value=1.0,
                        count=1,
                    )
                )
                rows.append(
                    BucketRow(
                        bucket_start=bucket_start,
                        bucket_size_seconds=BUCKET_SIZE_5M,
                        source=SOURCE_PLAYBOOKS,
                        dimension_key=DIM_ACTION,
                        dimension_value=str(result.action),
                        metric=str(result.status),
                        value=1.0,
                        count=1,
                    )
                )

    return rows


def _pipeline_rows() -> list[BucketRow]:
    """Emit pipeline (scan) rollups from the in-process scan history."""
    rows: list[BucketRow] = []
    for scan in list_scan_results():
        bucket_start = _bucket_for(scan.timestamp.timestamp())
        rows.append(
            BucketRow(
                bucket_start=bucket_start,
                bucket_size_seconds=BUCKET_SIZE_5M,
                source=SOURCE_PIPELINE,
                dimension_key=DIM_GLOBAL,
                dimension_value=DIM_GLOBAL,
                metric="risk_score_sum",
                value=float(scan.risk_score),
                count=1,
            )
        )
        rows.append(
            BucketRow(
                bucket_start=bucket_start,
                bucket_size_seconds=BUCKET_SIZE_5M,
                source=SOURCE_PIPELINE,
                dimension_key=DIM_GLOBAL,
                dimension_value=DIM_GLOBAL,
                metric="scans",
                value=1.0,
                count=1,
            )
        )
        rows.append(
            BucketRow(
                bucket_start=bucket_start,
                bucket_size_seconds=BUCKET_SIZE_5M,
                source=SOURCE_PIPELINE,
                dimension_key=DIM_SEVERITY,
                dimension_value=_safe_severity(float(scan.risk_score)),
                metric="count",
                value=1.0,
                count=1,
            )
        )
        if float(scan.risk_score) >= 80:
            rows.append(
                BucketRow(
                    bucket_start=bucket_start,
                    bucket_size_seconds=BUCKET_SIZE_5M,
                    source=SOURCE_PIPELINE,
                    dimension_key=DIM_GLOBAL,
                    dimension_value=DIM_GLOBAL,
                    metric="critical_findings",
                    value=1.0,
                    count=1,
                )
            )
    return rows


def _rollup_to(
    *,
    target_size: int,
    source_size: int,
    bucket_start_lt: int,
    db_path=None,
) -> int:
    """Sum every ``source_size`` row into the corresponding ``target_size`` bucket.

    ``bucket_start_lt`` defines the upper exclusive bound: only fully
    closed source buckets get rolled up so the same window is never
    aggregated twice.
    """
    conn = executive_store.connect(db_path)
    try:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO metrics_buckets (
                bucket_start, bucket_size_seconds, source,
                dimension_key, dimension_value, metric, value, count
            )
            SELECT
                (bucket_start - (bucket_start % ?)) AS rolled_start,
                ?,
                source,
                dimension_key,
                dimension_value,
                metric,
                SUM(value),
                SUM(count)
            FROM metrics_buckets
            WHERE bucket_size_seconds = ?
              AND bucket_start < ?
            GROUP BY rolled_start, source, dimension_key, dimension_value, metric
            """,
            (target_size, target_size, source_size, bucket_start_lt),
        )
        return cur.rowcount or 0
    finally:
        conn.close()


def _coalesce_rows(rows: Iterable[BucketRow]) -> list[BucketRow]:
    """Sum ``(value, count)`` for rows that share the rollup primary key.

    The store uses ``INSERT OR IGNORE`` on the same key, so every event-
    derived row must be combined locally before upsert; otherwise the
    first event in a bucket wins and the rest silently drop.
    """
    merged: dict[
        tuple[int, int, str, str, str, str],
        tuple[float, int],
    ] = {}
    for row in rows:
        key = (
            row.bucket_start,
            row.bucket_size_seconds,
            row.source,
            row.dimension_key,
            row.dimension_value,
            row.metric,
        )
        prev_value, prev_count = merged.get(key, (0.0, 0))
        merged[key] = (prev_value + float(row.value), prev_count + int(row.count))
    return [
        BucketRow(
            bucket_start=key[0],
            bucket_size_seconds=key[1],
            source=key[2],
            dimension_key=key[3],
            dimension_value=key[4],
            metric=key[5],
            value=value,
            count=count,
        )
        for key, (value, count) in merged.items()
    ]


def run_once(now: Optional[float] = None, *, db_path=None) -> dict[str, int]:
    """Snapshot live buffers, emit 5m rows, then roll up + prune.

    Returns a small stats dict so callers/tests can assert what happened
    without poking the database.
    """
    current = now if now is not None else time.time()

    raw_rows: list[BucketRow] = []
    raw_rows.extend(_enforcement_rows(all_enforcement_events()))
    raw_rows.extend(_playbook_rows(all_playbook_traces()))
    raw_rows.extend(_pipeline_rows())

    rows = _coalesce_rows(raw_rows)

    # Use REPLACE semantics so a 5m bucket that accumulates events
    # between aggregator ticks always reflects the latest totals.
    # INSERT OR IGNORE froze the first-seen value and silently dropped
    # later updates, which produced impossible ratios such as
    # blocked > total_requests.
    inserted_5m = executive_store.upsert_buckets(
        rows,
        path=db_path,
        replace=True,
    )

    boundary_1h = align_bucket(current, BUCKET_SIZE_1H)
    boundary_1d = align_bucket(current, BUCKET_SIZE_1D)
    inserted_1h = _rollup_to(
        target_size=BUCKET_SIZE_1H,
        source_size=BUCKET_SIZE_5M,
        bucket_start_lt=boundary_1h,
        db_path=db_path,
    )
    inserted_1d = _rollup_to(
        target_size=BUCKET_SIZE_1D,
        source_size=BUCKET_SIZE_1H,
        bucket_start_lt=boundary_1d,
        db_path=db_path,
    )

    pruned = executive_store.prune(current, path=db_path)

    stats = {
        "snapshotted_rows": len(raw_rows),
        "coalesced_rows": len(rows),
        "inserted_5m": int(inserted_5m),
        "inserted_1h": int(inserted_1h),
        "inserted_1d": int(inserted_1d),
        "pruned": int(pruned),
        "ran_at": int(current),
    }
    logger.info(
        "executive_aggregator_run rows=%d inserted_5m=%d inserted_1h=%d "
        "inserted_1d=%d pruned=%d",
        stats["snapshotted_rows"],
        stats["inserted_5m"],
        stats["inserted_1h"],
        stats["inserted_1d"],
        stats["pruned"],
    )
    return stats


async def run_forever(stop_event: Optional[asyncio.Event] = None) -> None:
    """Run :func:`run_once` on the configured cadence until cancelled.

    Wrapped in a ``try`` so a single bad iteration cannot kill the task;
    failures log and back off via the same interval.
    """
    interval = max(int(settings.executive_aggregator_interval_seconds), 30)
    logger.info("executive_aggregator_started interval_seconds=%d", interval)

    while True:
        if stop_event is not None and stop_event.is_set():
            logger.info("executive_aggregator_stopping reason=stop_event")
            return
        try:
            await asyncio.to_thread(run_once)
        except asyncio.CancelledError:
            logger.info("executive_aggregator_cancelled")
            raise
        except Exception:
            logger.exception("executive_aggregator_iteration_failed")

        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("executive_aggregator_cancelled")
            raise


def aggregator_status(now: Optional[float] = None) -> dict[str, object]:
    """Lightweight introspection: enabled state + last bucket boundaries."""
    current = now if now is not None else time.time()
    return {
        "enabled": bool(settings.executive_metrics_enabled),
        "interval_seconds": int(settings.executive_aggregator_interval_seconds),
        "next_5m_boundary": align_bucket(current, BUCKET_SIZE_5M) + BUCKET_SIZE_5M,
        "next_1h_boundary": align_bucket(current, BUCKET_SIZE_1H) + BUCKET_SIZE_1H,
        "next_1d_boundary": align_bucket(current, BUCKET_SIZE_1D) + BUCKET_SIZE_1D,
        "now": datetime.fromtimestamp(current, tz=timezone.utc).isoformat(),
    }


__all__ = [
    "DIM_ACTION",
    "DIM_DECISION",
    "DIM_DIRECTION",
    "DIM_GLOBAL",
    "DIM_MTTA",
    "DIM_PLAYBOOK",
    "DIM_POLICY",
    "DIM_ROUTE",
    "DIM_SEVERITY",
    "DIM_SUBJECT",
    "SOURCE_ENFORCEMENT",
    "SOURCE_PIPELINE",
    "SOURCE_PLAYBOOKS",
    "aggregator_status",
    "run_forever",
    "run_once",
]
