"""SQLite-backed metrics rollup store for the Executive Dashboard.

One wide table (`metrics_buckets`) holds rollups at three granularities
(5-minute, 1-hour, 1-day) keyed by ``(bucket_start, bucket_size_seconds,
source, dimension_key, dimension_value, metric)``. The schema is
intentionally narrow so per-policy, per-playbook, per-tag, and
per-offender rollups all share one table without a per-feature schema
explosion.

WAL mode is enabled so the API can read summary/trend queries while the
aggregator background task writes new buckets.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

BUCKET_SIZE_5M = 300
BUCKET_SIZE_1H = 3600
BUCKET_SIZE_1D = 86400

ALL_BUCKET_SIZES: tuple[int, ...] = (BUCKET_SIZE_5M, BUCKET_SIZE_1H, BUCKET_SIZE_1D)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS metrics_buckets (
    bucket_start         INTEGER NOT NULL,
    bucket_size_seconds  INTEGER NOT NULL,
    source               TEXT    NOT NULL,
    dimension_key        TEXT    NOT NULL,
    dimension_value      TEXT    NOT NULL,
    metric               TEXT    NOT NULL,
    value                REAL    NOT NULL,
    count                INTEGER NOT NULL,
    PRIMARY KEY (
        bucket_start,
        bucket_size_seconds,
        source,
        dimension_key,
        dimension_value,
        metric
    )
);
CREATE INDEX IF NOT EXISTS idx_buckets_window
    ON metrics_buckets (bucket_size_seconds, bucket_start);
CREATE INDEX IF NOT EXISTS idx_buckets_dimension
    ON metrics_buckets (dimension_key, dimension_value, bucket_size_seconds, bucket_start);
"""

_lock = threading.RLock()


@dataclass(frozen=True)
class BucketRow:
    """One row destined for the ``metrics_buckets`` table."""

    bucket_start: int
    bucket_size_seconds: int
    source: str
    dimension_key: str
    dimension_value: str
    metric: str
    value: float = 0.0
    count: int = 1


def _db_path() -> Path:
    return Path(settings.executive_metrics_db_path)


def _ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    """Open a SQLite connection with WAL + sane defaults.

    The metrics table is created lazily on every connect so a wiped or
    missing file produces clean empty queries instead of a 500.
    """
    target = path or _db_path()
    _ensure_parent_dir(target)
    conn = sqlite3.connect(
        str(target),
        timeout=10.0,
        isolation_level=None,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA_SQL)
    return conn


def init_schema(path: Optional[Path] = None) -> None:
    """Create the rollup table and indexes if they do not exist."""
    with _lock:
        conn = connect(path)
        try:
            conn.executescript(_SCHEMA_SQL)
        finally:
            conn.close()


def upsert_buckets(
    rows: Sequence[BucketRow],
    *,
    path: Optional[Path] = None,
    replace: bool = False,
) -> int:
    """Persist *rows* into the rollup table.

    By default this uses ``INSERT OR IGNORE``: existing rows with the same
    primary key are left untouched, which keeps backfills and rollups
    idempotent. Set ``replace=True`` for live snapshotting (the executive
    aggregator's 5-minute pass): the row is overwritten with the latest
    ``(value, count)``, so a bucket that accumulates events between ticks
    cannot get stuck on the totals it had during the first observation.

    Returns the number of rows the database reports as written. With
    SQLite that is the modified row count (insert + update), which is
    fine for monitoring.
    """
    if not rows:
        return 0
    payload = [
        (
            r.bucket_start,
            r.bucket_size_seconds,
            r.source,
            r.dimension_key,
            r.dimension_value,
            r.metric,
            float(r.value),
            int(r.count),
        )
        for r in rows
    ]
    if replace:
        sql = """
            INSERT INTO metrics_buckets (
                bucket_start, bucket_size_seconds, source,
                dimension_key, dimension_value, metric, value, count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(
                bucket_start, bucket_size_seconds, source,
                dimension_key, dimension_value, metric
            ) DO UPDATE SET
                value = excluded.value,
                count = excluded.count
        """
    else:
        sql = """
            INSERT OR IGNORE INTO metrics_buckets (
                bucket_start, bucket_size_seconds, source,
                dimension_key, dimension_value, metric, value, count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
    with _lock:
        conn = connect(path)
        try:
            cur = conn.executemany(sql, payload)
            return cur.rowcount or 0
        finally:
            conn.close()


def query_buckets(
    *,
    bucket_size_seconds: int,
    bucket_start_gte: Optional[int] = None,
    bucket_start_lt: Optional[int] = None,
    source: Optional[str] = None,
    dimension_key: Optional[str] = None,
    dimension_value: Optional[str] = None,
    metric: Optional[str | Iterable[str]] = None,
    path: Optional[Path] = None,
) -> list[sqlite3.Row]:
    """Return raw rows matching the filters.

    All filters are optional except ``bucket_size_seconds``; supplying
    only the size returns every retained bucket at that granularity.
    """
    clauses = ["bucket_size_seconds = ?"]
    params: list[object] = [int(bucket_size_seconds)]
    if bucket_start_gte is not None:
        clauses.append("bucket_start >= ?")
        params.append(int(bucket_start_gte))
    if bucket_start_lt is not None:
        clauses.append("bucket_start < ?")
        params.append(int(bucket_start_lt))
    if source is not None:
        clauses.append("source = ?")
        params.append(source)
    if dimension_key is not None:
        clauses.append("dimension_key = ?")
        params.append(dimension_key)
    if dimension_value is not None:
        clauses.append("dimension_value = ?")
        params.append(dimension_value)
    if metric is not None:
        if isinstance(metric, str):
            clauses.append("metric = ?")
            params.append(metric)
        else:
            metric_list = list(metric)
            if metric_list:
                placeholders = ",".join("?" for _ in metric_list)
                clauses.append(f"metric IN ({placeholders})")
                params.extend(metric_list)

    sql = (
        "SELECT bucket_start, bucket_size_seconds, source, dimension_key, "
        "dimension_value, metric, value, count "
        "FROM metrics_buckets WHERE " + " AND ".join(clauses) + " "
        "ORDER BY bucket_start ASC"
    )
    with _lock:
        conn = connect(path)
        try:
            return list(conn.execute(sql, params).fetchall())
        finally:
            conn.close()


def aggregate_to_window(
    *,
    bucket_size_seconds: int,
    bucket_start_gte: Optional[int] = None,
    bucket_start_lt: Optional[int] = None,
    source: Optional[str] = None,
    dimension_key: Optional[str] = None,
    dimension_value: Optional[str] = None,
    metric: Optional[str | Iterable[str]] = None,
    path: Optional[Path] = None,
) -> dict[tuple[str, str, str, str], tuple[float, int]]:
    """Sum ``(value, count)`` over a window, grouped by dimension + metric.

    Result key: ``(source, dimension_key, dimension_value, metric)``.
    Used by the service layer to compute KPIs without re-implementing
    aggregation in Python.
    """
    rows = query_buckets(
        bucket_size_seconds=bucket_size_seconds,
        bucket_start_gte=bucket_start_gte,
        bucket_start_lt=bucket_start_lt,
        source=source,
        dimension_key=dimension_key,
        dimension_value=dimension_value,
        metric=metric,
        path=path,
    )
    out: dict[tuple[str, str, str, str], tuple[float, int]] = {}
    for row in rows:
        key = (
            row["source"],
            row["dimension_key"],
            row["dimension_value"],
            row["metric"],
        )
        prev_value, prev_count = out.get(key, (0.0, 0))
        out[key] = (prev_value + float(row["value"]), prev_count + int(row["count"]))
    return out


def prune(now: Optional[float] = None, *, path: Optional[Path] = None) -> int:
    """Delete rollups older than the per-granularity retention horizon.

    Returns the total number of rows removed across all granularities.
    """
    current = now if now is not None else time.time()
    cutoffs: dict[int, int] = {
        BUCKET_SIZE_5M: int(current - settings.executive_retention_5m_hours * 3600),
        BUCKET_SIZE_1H: int(
            current - settings.executive_retention_1h_days * 86400
        ),
        BUCKET_SIZE_1D: int(
            current - settings.executive_retention_1d_days * 86400
        ),
    }
    deleted = 0
    with _lock:
        conn = connect(path)
        try:
            for size, cutoff in cutoffs.items():
                cur = conn.execute(
                    "DELETE FROM metrics_buckets "
                    "WHERE bucket_size_seconds = ? AND bucket_start < ?",
                    (size, cutoff),
                )
                deleted += cur.rowcount or 0
        finally:
            conn.close()
    return deleted


def reset_database(path: Optional[Path] = None) -> None:
    """Drop and re-create the metrics table (used by tests)."""
    with _lock:
        conn = connect(path)
        try:
            conn.execute("DROP TABLE IF EXISTS metrics_buckets")
            conn.executescript(_SCHEMA_SQL)
        finally:
            conn.close()


def align_bucket(timestamp: float, bucket_size_seconds: int) -> int:
    """Return the unix-second start of the bucket *timestamp* falls into."""
    ts = int(timestamp)
    return ts - (ts % int(bucket_size_seconds))


__all__ = [
    "ALL_BUCKET_SIZES",
    "BUCKET_SIZE_1D",
    "BUCKET_SIZE_1H",
    "BUCKET_SIZE_5M",
    "BucketRow",
    "aggregate_to_window",
    "align_bucket",
    "connect",
    "init_schema",
    "prune",
    "query_buckets",
    "reset_database",
    "upsert_buckets",
]
