"""SQLite-backed metadata index for the Phase 4 reporting pipeline.

The store keeps a small SQLite catalogue of generated reports
(executive PDFs, executive CSVs, portfolio rollup PDFs, per-scan PDFs)
together with the binary payload on disk under
``settings.report_store_path``. The split lets the API stream report
bytes directly off the filesystem without round-tripping them through
the database, while the catalogue powers the ``/reports`` listing
endpoints and the weekly scheduler's "last run" bookkeeping.

Design notes:

- One narrow table (``reports``) keyed by ``report_id``.
- A complementary key/value table (``report_kv``) for scheduler bookkeeping
  ("last_weekly_run_<kind>", etc.) so the scheduler can be inspected and
  reset without poking at file mtimes.
- WAL mode + lazy schema creation on every :func:`connect` so a wiped
  database file does not crash the API.
- The blob lives at ``<report_store_path>/<report_id>.<format>``; the
  catalogue keeps the SHA-256 + size for cheap integrity checks.
"""

import hashlib
import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

REPORT_FORMATS: frozenset[str] = frozenset({"pdf", "csv", "json"})
"""Formats the API will accept for downloads. JSON is included for forward-compat."""

REPORT_STATUSES: frozenset[str] = frozenset({"ok", "failed"})

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reports (
    report_id     TEXT NOT NULL PRIMARY KEY,
    kind          TEXT NOT NULL,
    window        TEXT,
    format        TEXT NOT NULL,
    status        TEXT NOT NULL,
    filename      TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL DEFAULT 0,
    sha256        TEXT,
    generated_at  TEXT NOT NULL,
    error         TEXT,
    metadata      TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_reports_kind ON reports (kind);
CREATE INDEX IF NOT EXISTS idx_reports_generated_at ON reports (generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_reports_kind_generated ON reports (kind, generated_at DESC);

CREATE TABLE IF NOT EXISTS report_kv (
    key   TEXT NOT NULL PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_lock = threading.RLock()


@dataclass
class ReportRecord:
    """Single row in the ``reports`` table.

    The persisted file lives under :func:`report_file_path` and is keyed
    by ``(report_id, format)`` so two formats of the same logical report
    can coexist without colliding.
    """

    kind: str
    format: str
    filename: str
    generated_at: datetime
    report_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    window: Optional[str] = None
    status: str = "ok"
    size_bytes: int = 0
    sha256: Optional[str] = None
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _index_path() -> Path:
    return Path(settings.report_index_path)


def _store_dir() -> Path:
    return Path(settings.report_store_path)


def _ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _ensure_store_dir(path: Optional[Path] = None) -> Path:
    target = path or _store_dir()
    target.mkdir(parents=True, exist_ok=True)
    return target


def report_file_path(
    report_id: str,
    fmt: str,
    *,
    store_path: Optional[Path] = None,
) -> Path:
    """Return the on-disk location for a report blob."""
    target_dir = _ensure_store_dir(store_path)
    safe_fmt = fmt.lower().strip().lstrip(".") or "bin"
    return target_dir / f"{report_id}.{safe_fmt}"


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    """Open a SQLite connection with WAL + lazy schema creation."""
    target = path or _index_path()
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
    conn.executescript(_SCHEMA_SQL)
    return conn


def init_schema(path: Optional[Path] = None) -> None:
    """Create the reports tables and indexes if they do not exist."""
    with _lock:
        conn = connect(path)
        try:
            conn.executescript(_SCHEMA_SQL)
        finally:
            conn.close()
    _ensure_store_dir()


def reset_database(path: Optional[Path] = None) -> None:
    """Drop and re-create the reports + report_kv tables (used by tests)."""
    with _lock:
        conn = connect(path)
        try:
            conn.execute("DROP TABLE IF EXISTS reports")
            conn.execute("DROP TABLE IF EXISTS report_kv")
            conn.executescript(_SCHEMA_SQL)
        finally:
            conn.close()


def _to_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _from_iso(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _row_to_record(row: sqlite3.Row) -> ReportRecord:
    generated = _from_iso(row["generated_at"]) or datetime.now(timezone.utc)
    return ReportRecord(
        report_id=row["report_id"],
        kind=row["kind"],
        window=row["window"],
        format=row["format"],
        status=row["status"],
        filename=row["filename"],
        size_bytes=int(row["size_bytes"] or 0),
        sha256=row["sha256"],
        generated_at=generated,
        error=row["error"],
        metadata=json.loads(row["metadata"] or "{}"),
    )


def save_report(
    *,
    kind: str,
    fmt: str,
    payload: bytes,
    filename: Optional[str] = None,
    window: Optional[str] = None,
    status: str = "ok",
    error: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    generated_at: Optional[datetime] = None,
    index_path: Optional[Path] = None,
    store_path: Optional[Path] = None,
) -> ReportRecord:
    """Persist a report payload + index row.

    Writes the file first (so a partial write never lands a phantom row
    in the index) and then commits the catalogue entry.
    """
    if status not in REPORT_STATUSES:
        raise ValueError(f"invalid report status: {status!r}")
    if fmt.lower().strip().lstrip(".") not in REPORT_FORMATS:
        raise ValueError(f"unsupported report format: {fmt!r}")
    record = ReportRecord(
        kind=kind,
        window=window,
        format=fmt.lower().strip().lstrip("."),
        status=status,
        filename=filename or _default_filename(kind, fmt, window, generated_at),
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        generated_at=generated_at or datetime.now(timezone.utc),
        error=error,
        metadata=dict(metadata or {}),
    )

    store_dir = _ensure_store_dir(store_path)
    file_path = store_dir / f"{record.report_id}.{record.format}"
    file_path.write_bytes(payload)

    sql = """
        INSERT INTO reports (
            report_id, kind, window, format, status, filename,
            size_bytes, sha256, generated_at, error, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = (
        record.report_id,
        record.kind,
        record.window,
        record.format,
        record.status,
        record.filename,
        record.size_bytes,
        record.sha256,
        _to_iso(record.generated_at),
        record.error,
        json.dumps(record.metadata, default=str, sort_keys=True),
    )
    with _lock:
        conn = connect(index_path)
        try:
            conn.execute(sql, params)
        finally:
            conn.close()
    return record


def _default_filename(
    kind: str,
    fmt: str,
    window: Optional[str],
    generated_at: Optional[datetime],
) -> str:
    stamp = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    parts = ["valo", kind]
    if window:
        parts.append(window)
    parts.append(stamp.strftime("%Y%m%d-%H%M%S"))
    safe = "-".join(parts).replace(" ", "-")
    return f"{safe}.{fmt.lower().lstrip('.')}"


def get_report(
    report_id: str,
    *,
    index_path: Optional[Path] = None,
) -> Optional[ReportRecord]:
    """Fetch a single report by its primary key."""
    with _lock:
        conn = connect(index_path)
        try:
            row = conn.execute(
                "SELECT * FROM reports WHERE report_id = ?",
                (report_id,),
            ).fetchone()
            return _row_to_record(row) if row else None
        finally:
            conn.close()


def list_reports(
    *,
    limit: int = 50,
    offset: int = 0,
    kind: Optional[str] = None,
    window: Optional[str] = None,
    fmt: Optional[str] = None,
    status: Optional[str] = None,
    after: Optional[datetime] = None,
    before: Optional[datetime] = None,
    index_path: Optional[Path] = None,
) -> tuple[list[ReportRecord], int]:
    """Return ``(rows, total_matching)``. Newest first."""
    clauses: list[str] = []
    params: list[Any] = []
    if kind is not None:
        clauses.append("kind = ?")
        params.append(kind)
    if window is not None:
        clauses.append("window = ?")
        params.append(window)
    if fmt is not None:
        clauses.append("format = ?")
        params.append(fmt.lower().strip().lstrip("."))
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if after is not None:
        clauses.append("generated_at >= ?")
        params.append(_to_iso(after))
    if before is not None:
        clauses.append("generated_at < ?")
        params.append(_to_iso(before))

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    count_sql = f"SELECT COUNT(*) AS total FROM reports{where}"
    page_sql = (
        f"SELECT * FROM reports{where} "
        "ORDER BY generated_at DESC, report_id DESC "
        "LIMIT ? OFFSET ?"
    )
    page_params = list(params) + [int(max(1, limit)), int(max(0, offset))]
    with _lock:
        conn = connect(index_path)
        try:
            total_row = conn.execute(count_sql, params).fetchone()
            total = int(total_row["total"]) if total_row else 0
            rows = conn.execute(page_sql, page_params).fetchall()
            records = [_row_to_record(r) for r in rows]
            return records, total
        finally:
            conn.close()


def delete_report(
    report_id: str,
    *,
    index_path: Optional[Path] = None,
    store_path: Optional[Path] = None,
) -> bool:
    """Remove a report's index row and on-disk blob.

    Returns ``True`` when the index row existed (regardless of whether
    the blob was present on disk).
    """
    record = get_report(report_id, index_path=index_path)
    if record is None:
        return False
    file_path = report_file_path(report_id, record.format, store_path=store_path)
    try:
        file_path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        logger.exception("report_blob_unlink_failed report_id=%s", report_id)
    with _lock:
        conn = connect(index_path)
        try:
            conn.execute("DELETE FROM reports WHERE report_id = ?", (report_id,))
        finally:
            conn.close()
    return True


def latest_for_kind(
    kind: str,
    *,
    status: Optional[str] = "ok",
    index_path: Optional[Path] = None,
) -> Optional[ReportRecord]:
    """Return the most recent successful report of *kind* (or any status)."""
    clauses = ["kind = ?"]
    params: list[Any] = [kind]
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    sql = (
        "SELECT * FROM reports WHERE "
        + " AND ".join(clauses)
        + " ORDER BY generated_at DESC, report_id DESC LIMIT 1"
    )
    with _lock:
        conn = connect(index_path)
        try:
            row = conn.execute(sql, params).fetchone()
            return _row_to_record(row) if row else None
        finally:
            conn.close()


def prune_older_than(
    days: int,
    *,
    index_path: Optional[Path] = None,
    store_path: Optional[Path] = None,
) -> int:
    """Drop index rows + on-disk blobs older than *days*.

    Returns the number of rows deleted. Files for orphaned blobs (rows
    where the disk file is already missing) are still pruned from the
    index.
    """
    if days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
    clauses = "WHERE generated_at < ?"
    select_sql = f"SELECT report_id, format FROM reports {clauses}"
    delete_sql = f"DELETE FROM reports {clauses}"
    deleted = 0
    with _lock:
        conn = connect(index_path)
        try:
            rows = conn.execute(select_sql, (_to_iso(cutoff),)).fetchall()
            for row in rows:
                rid = row["report_id"]
                fmt = row["format"]
                file_path = report_file_path(rid, fmt, store_path=store_path)
                try:
                    file_path.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    logger.exception(
                        "report_blob_prune_failed report_id=%s", rid
                    )
            cur = conn.execute(delete_sql, (_to_iso(cutoff),))
            deleted = cur.rowcount or 0
        finally:
            conn.close()
    return deleted


def total_reports(index_path: Optional[Path] = None) -> int:
    with _lock:
        conn = connect(index_path)
        try:
            row = conn.execute("SELECT COUNT(*) AS total FROM reports").fetchone()
            return int(row["total"]) if row else 0
        finally:
            conn.close()


def kv_set(
    key: str,
    value: str,
    *,
    index_path: Optional[Path] = None,
) -> None:
    """Persist a single scheduler bookkeeping value.

    Used by :mod:`app.services.report_scheduler` to record the last
    successful weekly run per kind so a process restart picks up where
    the previous one left off.
    """
    sql = (
        "INSERT INTO report_kv (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
    )
    with _lock:
        conn = connect(index_path)
        try:
            conn.execute(sql, (key, value))
        finally:
            conn.close()


def kv_get(
    key: str,
    *,
    index_path: Optional[Path] = None,
) -> Optional[str]:
    with _lock:
        conn = connect(index_path)
        try:
            row = conn.execute(
                "SELECT value FROM report_kv WHERE key = ?", (key,)
            ).fetchone()
            return str(row["value"]) if row else None
        finally:
            conn.close()


def kv_delete(
    key: str,
    *,
    index_path: Optional[Path] = None,
) -> None:
    with _lock:
        conn = connect(index_path)
        try:
            conn.execute("DELETE FROM report_kv WHERE key = ?", (key,))
        finally:
            conn.close()


def kv_items(
    prefix: str = "",
    *,
    index_path: Optional[Path] = None,
) -> list[tuple[str, str]]:
    with _lock:
        conn = connect(index_path)
        try:
            if prefix:
                rows = conn.execute(
                    "SELECT key, value FROM report_kv WHERE key LIKE ? ORDER BY key",
                    (f"{prefix}%",),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT key, value FROM report_kv ORDER BY key"
                ).fetchall()
            return [(str(r["key"]), str(r["value"])) for r in rows]
        finally:
            conn.close()


def iter_reports(
    *,
    index_path: Optional[Path] = None,
) -> Iterable[ReportRecord]:
    with _lock:
        conn = connect(index_path)
        try:
            rows = conn.execute(
                "SELECT * FROM reports ORDER BY generated_at DESC, report_id DESC"
            ).fetchall()
        finally:
            conn.close()
    for row in rows:
        yield _row_to_record(row)


__all__ = [
    "REPORT_FORMATS",
    "REPORT_STATUSES",
    "ReportRecord",
    "connect",
    "delete_report",
    "get_report",
    "init_schema",
    "iter_reports",
    "kv_delete",
    "kv_get",
    "kv_items",
    "kv_set",
    "latest_for_kind",
    "list_reports",
    "prune_older_than",
    "report_file_path",
    "reset_database",
    "save_report",
    "total_reports",
]
