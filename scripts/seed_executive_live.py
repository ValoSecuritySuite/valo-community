"""Seed the live executive_metrics SQLite store with realistic synthetic data.

By default this leaves the last 24 hours EMPTY (so the 24h view stays at 0)
and populates only the older history:

* 1-hour buckets between 24 h ago and 7 d ago    -> drives the 7d view
* 1-day buckets between 24 h ago and 90 d ago    -> drives the 30d / 90d views

That way you can demo "no traffic in the last 24 h" while still having a
rich week / month / quarter trend behind it.

Reads ``settings.executive_metrics_db_path`` so it writes into the exact
file the running uvicorn queries.

Run with: ./venv/bin/python scripts/seed_executive_live.py
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import settings  # noqa: E402
from app.services.executive_aggregator import (  # noqa: E402
    SOURCE_ENFORCEMENT,
    SOURCE_PIPELINE,
    SOURCE_PLAYBOOKS,
    _coalesce_rows,
)
from app.services.executive_store import (  # noqa: E402
    BUCKET_SIZE_1D,
    BUCKET_SIZE_1H,
    BUCKET_SIZE_5M,
    BucketRow,
    align_bucket,
    init_schema,
    upsert_buckets,
)


POLICIES = [
    ("block_secret_exposure", 0.55),
    ("block_high_risk", 0.30),
    ("warn_pii", 0.15),
]
DECISIONS = [("allow", 0.55), ("warn", 0.20), ("deny", 0.25)]
ROUTES = ["/v1/proxy/chat/completions", "/analyze", "/scan/report"]
ACTIONS = ["alert", "block", "ticket", "revoke", "quarantine", "rate_limit"]


def _emit_traffic_for_bucket(
    *,
    bucket_start: int,
    bucket_size_seconds: int,
    load: int,
    rng: random.Random,
) -> list[BucketRow]:
    """Return a batch of synthetic enforcement / playbooks / pipeline rows.

    *load* controls roughly how many requests landed in the bucket. Each
    request emits the same family of metric rows the live aggregator
    would produce; ``_coalesce_rows`` then merges duplicates per primary
    key so SUMs are correct.
    """
    rows: list[BucketRow] = []

    for _ in range(load):
        decision = rng.choices(
            [d for d, _ in DECISIONS], weights=[w for _, w in DECISIONS]
        )[0]
        route = rng.choice(ROUTES)
        blocked = decision == "deny"

        rows.append(
            BucketRow(
                bucket_start=bucket_start,
                bucket_size_seconds=bucket_size_seconds,
                source=SOURCE_ENFORCEMENT,
                dimension_key="global",
                dimension_value="global",
                metric="requests",
                value=1.0,
                count=1,
            )
        )
        rows.append(
            BucketRow(
                bucket_start=bucket_start,
                bucket_size_seconds=bucket_size_seconds,
                source=SOURCE_ENFORCEMENT,
                dimension_key="global",
                dimension_value="global",
                metric="duration_ms_sum",
                value=rng.uniform(2.0, 25.0),
                count=1,
            )
        )
        rows.append(
            BucketRow(
                bucket_start=bucket_start,
                bucket_size_seconds=bucket_size_seconds,
                source=SOURCE_ENFORCEMENT,
                dimension_key="decision",
                dimension_value=decision,
                metric="count",
                value=1.0,
                count=1,
            )
        )
        rows.append(
            BucketRow(
                bucket_start=bucket_start,
                bucket_size_seconds=bucket_size_seconds,
                source=SOURCE_ENFORCEMENT,
                dimension_key="direction",
                dimension_value="ingress",
                metric="count",
                value=1.0,
                count=1,
            )
        )
        rows.append(
            BucketRow(
                bucket_start=bucket_start,
                bucket_size_seconds=bucket_size_seconds,
                source=SOURCE_ENFORCEMENT,
                dimension_key="route",
                dimension_value=route,
                metric="requests",
                value=1.0,
                count=1,
            )
        )
        if blocked:
            rows.append(
                BucketRow(
                    bucket_start=bucket_start,
                    bucket_size_seconds=bucket_size_seconds,
                    source=SOURCE_ENFORCEMENT,
                    dimension_key="global",
                    dimension_value="global",
                    metric="blocked",
                    value=1.0,
                    count=1,
                )
            )
            rows.append(
                BucketRow(
                    bucket_start=bucket_start,
                    bucket_size_seconds=bucket_size_seconds,
                    source=SOURCE_ENFORCEMENT,
                    dimension_key="global",
                    dimension_value="global",
                    metric="would_block",
                    value=1.0,
                    count=1,
                )
            )
            policy_id = rng.choices(
                [p for p, _ in POLICIES], weights=[w for _, w in POLICIES]
            )[0]
            rows.append(
                BucketRow(
                    bucket_start=bucket_start,
                    bucket_size_seconds=bucket_size_seconds,
                    source=SOURCE_ENFORCEMENT,
                    dimension_key="policy_id",
                    dimension_value=policy_id,
                    metric="matches",
                    value=1.0,
                    count=1,
                )
            )
            rows.append(
                BucketRow(
                    bucket_start=bucket_start,
                    bucket_size_seconds=bucket_size_seconds,
                    source=SOURCE_ENFORCEMENT,
                    dimension_key="policy_id",
                    dimension_value=policy_id,
                    metric="blocked",
                    value=1.0,
                    count=1,
                )
            )

    # Playbooks: ~one event every couple of buckets.
    if rng.random() < 0.4:
        action = rng.choice(ACTIONS)
        rows.append(
            BucketRow(
                bucket_start=bucket_start,
                bucket_size_seconds=bucket_size_seconds,
                source=SOURCE_PLAYBOOKS,
                dimension_key="global",
                dimension_value="global",
                metric="events_total",
                value=1.0,
                count=1,
            )
        )
        rows.append(
            BucketRow(
                bucket_start=bucket_start,
                bucket_size_seconds=bucket_size_seconds,
                source=SOURCE_PLAYBOOKS,
                dimension_key="global",
                dimension_value="global",
                metric="playbooks_fired",
                value=1.0,
                count=1,
            )
        )
        rows.append(
            BucketRow(
                bucket_start=bucket_start,
                bucket_size_seconds=bucket_size_seconds,
                source=SOURCE_PLAYBOOKS,
                dimension_key="action",
                dimension_value=action,
                metric="executed",
                value=1.0,
                count=1,
            )
        )
        rows.append(
            BucketRow(
                bucket_start=bucket_start,
                bucket_size_seconds=bucket_size_seconds,
                source=SOURCE_PLAYBOOKS,
                dimension_key="playbook_id",
                dimension_value="pb_alert_secret",
                metric="actions_executed",
                value=1.0,
                count=1,
            )
        )
        rows.append(
            BucketRow(
                bucket_start=bucket_start,
                bucket_size_seconds=bucket_size_seconds,
                source=SOURCE_PLAYBOOKS,
                dimension_key="mtta",
                dimension_value="mtta",
                metric="duration_ms_sum",
                value=rng.uniform(40.0, 160.0),
                count=1,
            )
        )

    # Pipeline scans: rare.
    if rng.random() < 0.12:
        score = rng.choices(
            [12.0, 38.5, 67.0, 82.0, 91.5], weights=[3, 4, 3, 1.5, 1]
        )[0]
        severity = (
            "critical" if score >= 80
            else "high" if score >= 60
            else "medium" if score >= 40
            else "low" if score >= 20
            else "minimal"
        )
        rows.append(
            BucketRow(
                bucket_start=bucket_start,
                bucket_size_seconds=bucket_size_seconds,
                source=SOURCE_PIPELINE,
                dimension_key="global",
                dimension_value="global",
                metric="risk_score_sum",
                value=score,
                count=1,
            )
        )
        rows.append(
            BucketRow(
                bucket_start=bucket_start,
                bucket_size_seconds=bucket_size_seconds,
                source=SOURCE_PIPELINE,
                dimension_key="global",
                dimension_value="global",
                metric="scans",
                value=1.0,
                count=1,
            )
        )
        rows.append(
            BucketRow(
                bucket_start=bucket_start,
                bucket_size_seconds=bucket_size_seconds,
                source=SOURCE_PIPELINE,
                dimension_key="severity",
                dimension_value=severity,
                metric="count",
                value=1.0,
                count=1,
            )
        )
        if score >= 80:
            rows.append(
                BucketRow(
                    bucket_start=bucket_start,
                    bucket_size_seconds=bucket_size_seconds,
                    source=SOURCE_PIPELINE,
                    dimension_key="global",
                    dimension_value="global",
                    metric="critical_findings",
                    value=1.0,
                    count=1,
                )
            )

    return rows


def _seed_window(
    *,
    bucket_size_seconds: int,
    earliest_offset_seconds: int,
    latest_offset_seconds: int,
    avg_load_per_bucket: int,
    now: float,
    rng: random.Random,
) -> list[BucketRow]:
    """Generate synthetic rows in ``[now - earliest, now - latest)``.

    ``earliest_offset_seconds`` is older than ``latest_offset_seconds``
    (so they are interpreted as "how far back from now").
    """
    rows: list[BucketRow] = []
    cursor = align_bucket(now - earliest_offset_seconds, bucket_size_seconds)
    stop = align_bucket(now - latest_offset_seconds, bucket_size_seconds)
    while cursor < stop:
        load = max(0, int(rng.gauss(avg_load_per_bucket, max(1, avg_load_per_bucket / 3))))
        if load > 0:
            rows.extend(
                _emit_traffic_for_bucket(
                    bucket_start=cursor,
                    bucket_size_seconds=bucket_size_seconds,
                    load=load,
                    rng=rng,
                )
            )
        cursor += bucket_size_seconds
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include-24h",
        action="store_true",
        help="Also populate the last 24 hours (5m buckets).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=1234,
        help="Deterministic RNG seed (default: 1234).",
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)
    now = time.time()
    db_path = Path(settings.executive_metrics_db_path)

    print(f"[seed] db: {db_path}")
    init_schema(db_path)

    rows: list[BucketRow] = []

    if args.include_24h:
        # Last 24h, 5m buckets, ~6 requests / bucket.
        rows.extend(
            _seed_window(
                bucket_size_seconds=BUCKET_SIZE_5M,
                earliest_offset_seconds=24 * 3600,
                latest_offset_seconds=0,
                avg_load_per_bucket=6,
                now=now,
                rng=rng,
            )
        )

    # 24h .. 7d ago, 1h buckets, ~80 requests / hour (denser real-world traffic).
    rows.extend(
        _seed_window(
            bucket_size_seconds=BUCKET_SIZE_1H,
            earliest_offset_seconds=7 * 86400,
            latest_offset_seconds=24 * 3600,
            avg_load_per_bucket=80,
            now=now,
            rng=rng,
        )
    )

    # 24h .. 90d ago, 1d buckets, ~1200 requests / day.
    rows.extend(
        _seed_window(
            bucket_size_seconds=BUCKET_SIZE_1D,
            earliest_offset_seconds=90 * 86400,
            latest_offset_seconds=24 * 3600,
            avg_load_per_bucket=1200,
            now=now,
            rng=rng,
        )
    )

    coalesced = _coalesce_rows(rows)
    inserted = upsert_buckets(coalesced, path=db_path)

    print(f"[seed] include 24h: {args.include_24h}")
    print(f"[seed] raw rows:       {len(rows):>8}")
    print(f"[seed] coalesced rows: {len(coalesced):>8}")
    print(f"[seed] inserted (new): {inserted:>8}")
    print()
    print("[seed] Window expectations:")
    print(
        "  /executive/summary?window=24h ->",
        "POPULATED" if args.include_24h else "ZERO (intentional)",
    )
    print("  /executive/summary?window=7d  -> populated from 1h buckets")
    print("  /executive/summary?window=30d -> populated from 1d buckets")
    print("  /executive/summary?window=90d -> populated from 1d buckets")
    print()
    print("[seed] OK - hit /executive/summary or refresh the dashboard")


if __name__ == "__main__":
    main()
