"""SQLite-backed outcome store for the Phase 4 Learning Loop.

Every playbook execution that today reaches
:func:`app.playbooks.trace_buffer.record_trace` is also persisted here so
the refiner can compute per-rule statistics across process restarts.
Analysts can later attach a label (true_positive, false_positive, ...) to
any persisted outcome via ``POST /outcomes/{trace_id}/label``.

Mirrors the design of :mod:`app.services.executive_store`:

- One narrow table (``outcomes``) keyed by ``outcome_id``.
- WAL mode so the refiner reads while the runtime writes.
- Lazy schema creation on every :func:`connect` so a wiped or missing
  file does not crash the API.

Cross-product outcomes (LLMShadow, SaaSShadow, external SOC consoles)
land in the same table by posting to ``POST /outcomes/ingest``; the
``source`` column distinguishes them.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

OutcomeLabel = str
"""Free-form for forward compat; validation lives in the API layer.

The recommended vocabulary is:

- ``true_positive``: the rule fired correctly.
- ``false_positive``: the rule fired but the underlying behaviour was benign.
- ``benign_block``: the action blocked legitimate traffic.
- ``malicious_allow``: the rule failed to catch malicious traffic.
- ``suppressed``: analyst marked the outcome as known noise.
- ``dismissed``: analyst chose not to label (informational close-out).
"""

ALLOWED_LABELS: frozenset[str] = frozenset(
    {
        "true_positive",
        "false_positive",
        "benign_block",
        "malicious_allow",
        "suppressed",
        "dismissed",
    }
)

KNOWN_SOURCES: frozenset[str] = frozenset(
    {
        "valo",
        "correlation_engine",
        "llmshadow",
        "saasshadow",
        "external",
    }
)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS outcomes (
    outcome_id          TEXT    NOT NULL PRIMARY KEY,
    event_id            TEXT    NOT NULL,
    trace_id            TEXT,
    correlation_id      TEXT,
    tenant_id           TEXT,
    source              TEXT    NOT NULL,
    severity            TEXT,
    decision            TEXT,
    matched_policy_ids  TEXT    NOT NULL DEFAULT '[]',
    matched_playbook_ids TEXT   NOT NULL DEFAULT '[]',
    action_results      TEXT    NOT NULL DEFAULT '[]',
    started_at          TEXT    NOT NULL,
    duration_ms         REAL    NOT NULL DEFAULT 0,
    dry_run             INTEGER NOT NULL DEFAULT 1,
    enabled             INTEGER NOT NULL DEFAULT 1,
    label               TEXT,
    label_reason        TEXT,
    labeled_by          TEXT,
    labeled_at          TEXT,
    raw                 TEXT    NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_outcomes_trace_id ON outcomes (trace_id);
CREATE INDEX IF NOT EXISTS idx_outcomes_event_id ON outcomes (event_id);
CREATE INDEX IF NOT EXISTS idx_outcomes_source_started ON outcomes (source, started_at);
CREATE INDEX IF NOT EXISTS idx_outcomes_label ON outcomes (label);
"""

_lock = threading.RLock()


@dataclass
class OutcomeRecord:
    """Single row in the ``outcomes`` table.

    JSON columns (``matched_policy_ids``, ``matched_playbook_ids``,
    ``action_results``, ``raw``) are exposed as native Python objects on
    the dataclass: serialization happens at the persistence boundary.
    """

    event_id: str
    source: str
    started_at: datetime
    outcome_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: Optional[str] = None
    correlation_id: Optional[str] = None
    tenant_id: Optional[str] = None
    severity: Optional[str] = None
    decision: Optional[str] = None
    matched_policy_ids: list[str] = field(default_factory=list)
    matched_playbook_ids: list[str] = field(default_factory=list)
    action_results: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: float = 0.0
    dry_run: bool = True
    enabled: bool = True
    label: Optional[str] = None
    label_reason: Optional[str] = None
    labeled_by: Optional[str] = None
    labeled_at: Optional[datetime] = None
    raw: dict[str, Any] = field(default_factory=dict)


def _db_path() -> Path:
    return Path(settings.outcome_store_path)


def _ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    """Open a SQLite connection with WAL + lazy schema creation."""
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
    conn.executescript(_SCHEMA_SQL)
    return conn


def init_schema(path: Optional[Path] = None) -> None:
    """Create the outcomes table and indexes if they do not exist."""
    with _lock:
        conn = connect(path)
        try:
            conn.executescript(_SCHEMA_SQL)
        finally:
            conn.close()


def reset_database(path: Optional[Path] = None) -> None:
    """Drop and re-create the outcomes table (used by tests)."""
    with _lock:
        conn = connect(path)
        try:
            conn.execute("DROP TABLE IF EXISTS outcomes")
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


def _row_to_record(row: sqlite3.Row) -> OutcomeRecord:
    started = _from_iso(row["started_at"]) or datetime.now(timezone.utc)
    return OutcomeRecord(
        outcome_id=row["outcome_id"],
        event_id=row["event_id"],
        trace_id=row["trace_id"],
        correlation_id=row["correlation_id"],
        tenant_id=row["tenant_id"],
        source=row["source"],
        severity=row["severity"],
        decision=row["decision"],
        matched_policy_ids=json.loads(row["matched_policy_ids"] or "[]"),
        matched_playbook_ids=json.loads(row["matched_playbook_ids"] or "[]"),
        action_results=json.loads(row["action_results"] or "[]"),
        started_at=started,
        duration_ms=float(row["duration_ms"] or 0.0),
        dry_run=bool(row["dry_run"]),
        enabled=bool(row["enabled"]),
        label=row["label"],
        label_reason=row["label_reason"],
        labeled_by=row["labeled_by"],
        labeled_at=_from_iso(row["labeled_at"]),
        raw=json.loads(row["raw"] or "{}"),
    )


def upsert_outcome(
    record: OutcomeRecord,
    *,
    path: Optional[Path] = None,
) -> OutcomeRecord:
    """Insert or replace an outcome by ``outcome_id``.

    Replace semantics keep the loop idempotent: re-emitting the same
    trace overwrites the previous row instead of creating duplicates.
    """
    payload = (
        record.outcome_id,
        record.event_id,
        record.trace_id,
        record.correlation_id,
        record.tenant_id,
        record.source,
        record.severity,
        record.decision,
        json.dumps(record.matched_policy_ids, sort_keys=True),
        json.dumps(record.matched_playbook_ids, sort_keys=True),
        json.dumps(record.action_results, default=str),
        _to_iso(record.started_at),
        float(record.duration_ms),
        int(record.dry_run),
        int(record.enabled),
        record.label,
        record.label_reason,
        record.labeled_by,
        _to_iso(record.labeled_at),
        json.dumps(record.raw, default=str),
    )
    sql = """
        INSERT INTO outcomes (
            outcome_id, event_id, trace_id, correlation_id, tenant_id,
            source, severity, decision, matched_policy_ids,
            matched_playbook_ids, action_results, started_at, duration_ms,
            dry_run, enabled, label, label_reason, labeled_by, labeled_at, raw
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(outcome_id) DO UPDATE SET
            event_id = excluded.event_id,
            trace_id = excluded.trace_id,
            correlation_id = excluded.correlation_id,
            tenant_id = excluded.tenant_id,
            source = excluded.source,
            severity = excluded.severity,
            decision = excluded.decision,
            matched_policy_ids = excluded.matched_policy_ids,
            matched_playbook_ids = excluded.matched_playbook_ids,
            action_results = excluded.action_results,
            started_at = excluded.started_at,
            duration_ms = excluded.duration_ms,
            dry_run = excluded.dry_run,
            enabled = excluded.enabled,
            label = COALESCE(excluded.label, outcomes.label),
            label_reason = COALESCE(excluded.label_reason, outcomes.label_reason),
            labeled_by = COALESCE(excluded.labeled_by, outcomes.labeled_by),
            labeled_at = COALESCE(excluded.labeled_at, outcomes.labeled_at),
            raw = excluded.raw
    """
    with _lock:
        conn = connect(path)
        try:
            conn.execute(sql, payload)
        finally:
            conn.close()
    return record


def insert_outcomes(
    records: Sequence[OutcomeRecord],
    *,
    path: Optional[Path] = None,
) -> int:
    """Bulk upsert. Returns the number of rows the database touched."""
    if not records:
        return 0
    written = 0
    for record in records:
        upsert_outcome(record, path=path)
        written += 1
    return written


def label_outcome(
    *,
    trace_id: Optional[str] = None,
    outcome_id: Optional[str] = None,
    label: str,
    reason: Optional[str] = None,
    labeled_by: Optional[str] = None,
    labeled_at: Optional[datetime] = None,
    path: Optional[Path] = None,
) -> int:
    """Attach a label to one or more outcomes.

    Either ``trace_id`` or ``outcome_id`` must be provided. Returns the
    number of rows updated. The caller (the API layer) validates that
    ``label`` is in :data:`ALLOWED_LABELS`.
    """
    if not trace_id and not outcome_id:
        raise ValueError("label_outcome requires trace_id or outcome_id")
    stamped = _to_iso(labeled_at or datetime.now(timezone.utc))
    if outcome_id is not None:
        sql = (
            "UPDATE outcomes SET label = ?, label_reason = ?, "
            "labeled_by = ?, labeled_at = ? WHERE outcome_id = ?"
        )
        params: tuple[Any, ...] = (label, reason, labeled_by, stamped, outcome_id)
    else:
        sql = (
            "UPDATE outcomes SET label = ?, label_reason = ?, "
            "labeled_by = ?, labeled_at = ? WHERE trace_id = ?"
        )
        params = (label, reason, labeled_by, stamped, trace_id)
    with _lock:
        conn = connect(path)
        try:
            cur = conn.execute(sql, params)
            return cur.rowcount or 0
        finally:
            conn.close()


def get_outcome(
    outcome_id: str,
    *,
    path: Optional[Path] = None,
) -> Optional[OutcomeRecord]:
    """Fetch one outcome by its primary key."""
    with _lock:
        conn = connect(path)
        try:
            row = conn.execute(
                "SELECT * FROM outcomes WHERE outcome_id = ?",
                (outcome_id,),
            ).fetchone()
            return _row_to_record(row) if row else None
        finally:
            conn.close()


def query_outcomes(
    *,
    limit: int = 50,
    offset: int = 0,
    event_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    source: Optional[str] = None,
    label: Optional[str] = None,
    has_label: Optional[bool] = None,
    matched_only: Optional[bool] = None,
    since: Optional[datetime] = None,
    path: Optional[Path] = None,
) -> tuple[list[OutcomeRecord], int]:
    """Return ``(rows, total_matching)``. Newest first.

    ``total_matching`` ignores pagination so the UI can render counts.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if event_id is not None:
        clauses.append("event_id = ?")
        params.append(event_id)
    if trace_id is not None:
        clauses.append("trace_id = ?")
        params.append(trace_id)
    if correlation_id is not None:
        clauses.append("correlation_id = ?")
        params.append(correlation_id)
    if source is not None:
        clauses.append("source = ?")
        params.append(source)
    if label is not None:
        clauses.append("label = ?")
        params.append(label)
    if has_label is True:
        clauses.append("label IS NOT NULL")
    elif has_label is False:
        clauses.append("label IS NULL")
    if matched_only is True:
        clauses.append("matched_playbook_ids != '[]'")
    elif matched_only is False:
        clauses.append("matched_playbook_ids = '[]'")
    if since is not None:
        clauses.append("started_at >= ?")
        params.append(_to_iso(since))

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    count_sql = f"SELECT COUNT(*) AS total FROM outcomes{where}"
    page_sql = (
        f"SELECT * FROM outcomes{where} ORDER BY started_at DESC, outcome_id DESC "
        "LIMIT ? OFFSET ?"
    )
    page_params = list(params) + [int(max(1, limit)), int(max(0, offset))]
    with _lock:
        conn = connect(path)
        try:
            total_row = conn.execute(count_sql, params).fetchone()
            total = int(total_row["total"]) if total_row else 0
            rows = conn.execute(page_sql, page_params).fetchall()
            records = [_row_to_record(r) for r in rows]
            return records, total
        finally:
            conn.close()


@dataclass
class RuleStats:
    """Aggregate stats for a single rule (policy or playbook)."""

    rule_id: str
    rule_kind: str
    total: int = 0
    labeled: int = 0
    true_positives: int = 0
    false_positives: int = 0
    benign_blocks: int = 0
    malicious_allows: int = 0
    suppressed: int = 0
    dismissed: int = 0
    last_started_at: Optional[datetime] = None
    last_label_at: Optional[datetime] = None

    @property
    def fp_rate(self) -> float:
        """Fraction of labeled outcomes counted as a false positive.

        ``benign_block`` is included as a false-positive style label so
        actions that hit innocent traffic get the same downward pressure
        as detection FPs.
        """
        bad = self.false_positives + self.benign_blocks
        if self.labeled <= 0:
            return 0.0
        return bad / float(self.labeled)


_LABEL_BUCKETS: dict[str, str] = {
    "true_positive": "true_positives",
    "false_positive": "false_positives",
    "benign_block": "benign_blocks",
    "malicious_allow": "malicious_allows",
    "suppressed": "suppressed",
    "dismissed": "dismissed",
}


def aggregate_rule_stats(
    *,
    kind: str = "policy",
    since: Optional[datetime] = None,
    path: Optional[Path] = None,
    rule_ids: Optional[Iterable[str]] = None,
) -> dict[str, RuleStats]:
    """Aggregate per-rule label counts.

    ``kind`` selects the JSON column scanned: ``"policy"`` reads
    ``matched_policy_ids``; ``"playbook"`` reads ``matched_playbook_ids``.
    The aggregation is done in Python because each row's matched ids
    list is a JSON array; SQLite has json_each but we stay portable.
    """
    column = "matched_policy_ids" if kind == "policy" else "matched_playbook_ids"
    clauses: list[str] = [f"{column} != '[]'"]
    params: list[Any] = []
    if since is not None:
        clauses.append("started_at >= ?")
        params.append(_to_iso(since))
    where = " WHERE " + " AND ".join(clauses)

    sql = (
        f"SELECT outcome_id, {column} AS ids_json, label, started_at, labeled_at "
        f"FROM outcomes{where}"
    )

    accepted: Optional[set[str]] = (
        {str(rid) for rid in rule_ids} if rule_ids is not None else None
    )

    aggregates: dict[str, RuleStats] = {}
    with _lock:
        conn = connect(path)
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    for row in rows:
        try:
            ids = json.loads(row["ids_json"] or "[]")
        except json.JSONDecodeError:
            continue
        for rid in ids:
            rid_str = str(rid)
            if accepted is not None and rid_str not in accepted:
                continue
            stat = aggregates.get(rid_str)
            if stat is None:
                stat = RuleStats(rule_id=rid_str, rule_kind=kind)
                aggregates[rid_str] = stat
            stat.total += 1
            label = row["label"]
            if label:
                stat.labeled += 1
                bucket = _LABEL_BUCKETS.get(label)
                if bucket is not None:
                    setattr(stat, bucket, getattr(stat, bucket) + 1)
            started = _from_iso(row["started_at"])
            if started is not None and (
                stat.last_started_at is None or started > stat.last_started_at
            ):
                stat.last_started_at = started
            labeled_at = _from_iso(row["labeled_at"])
            if labeled_at is not None and (
                stat.last_label_at is None or labeled_at > stat.last_label_at
            ):
                stat.last_label_at = labeled_at
    return aggregates


def total_outcomes(path: Optional[Path] = None) -> int:
    with _lock:
        conn = connect(path)
        try:
            row = conn.execute("SELECT COUNT(*) AS total FROM outcomes").fetchone()
            return int(row["total"]) if row else 0
        finally:
            conn.close()


def record_from_trace(
    trace: Any,
    *,
    source: str = "valo",
    tenant_id: Optional[str] = None,
    raw: Optional[dict[str, Any]] = None,
) -> OutcomeRecord:
    """Build an :class:`OutcomeRecord` from a playbook ``ExecutionTrace``.

    Accepts a duck-typed object so unit tests can pass plain dataclasses
    if they want; the production caller is the playbook trace buffer.
    """
    matched_policy_ids: list[str] = []
    action_results: list[dict[str, Any]] = []
    matches = list(getattr(trace, "matches", []) or [])
    for match in matches:
        for result in getattr(match, "results", []) or []:
            try:
                action_results.append(result.model_dump(mode="json"))
            except AttributeError:
                action_results.append(dict(result))  # type: ignore[arg-type]

    raw_payload = dict(raw or {})
    raw_payload.setdefault("trace", _trace_to_payload(trace))

    return OutcomeRecord(
        outcome_id=str(uuid.uuid4()),
        event_id=str(getattr(trace, "event_id", "") or ""),
        trace_id=getattr(trace, "trace_id", None),
        correlation_id=getattr(trace, "correlation_id", None) or None,
        tenant_id=tenant_id,
        source=source,
        severity=raw_payload.get("severity"),
        decision=raw_payload.get("decision"),
        matched_policy_ids=matched_policy_ids,
        matched_playbook_ids=list(getattr(trace, "matched_playbook_ids", []) or []),
        action_results=action_results,
        started_at=getattr(trace, "started_at", None) or datetime.now(timezone.utc),
        duration_ms=float(getattr(trace, "duration_ms", 0.0) or 0.0),
        dry_run=bool(getattr(trace, "dry_run", True)),
        enabled=bool(getattr(trace, "enabled", True)),
        raw=raw_payload,
    )


def _trace_to_payload(trace: Any) -> dict[str, Any]:
    try:
        return trace.model_dump(mode="json")  # type: ignore[no-any-return]
    except AttributeError:
        return {}
    except Exception:  # pragma: no cover, defensive
        logger.exception("outcome_trace_dump_failed")
        return {}


__all__ = [
    "ALLOWED_LABELS",
    "KNOWN_SOURCES",
    "OutcomeRecord",
    "RuleStats",
    "aggregate_rule_stats",
    "connect",
    "get_outcome",
    "init_schema",
    "insert_outcomes",
    "label_outcome",
    "query_outcomes",
    "record_from_trace",
    "reset_database",
    "total_outcomes",
    "upsert_outcome",
]
