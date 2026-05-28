"""End-to-end smoke for the Executive Dashboard.

Spins up the FastAPI app in-process with the kill switch on, populates the
enforcement / playbook / scan history buffers with synthetic data,
forces a rollup, then exercises every /executive/* endpoint and prints
the highlights. Intended to be a quick "does this thing work?" check
that does not depend on a long-running uvicorn or the dev frontend.
"""

from __future__ import annotations

import json
import os
import random
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Force the kill switch ON before any settings caching, and route the SQLite
# rollup file into a tmpdir so the smoke run does not pollute the repo.
TMP_ROOT = Path(tempfile.mkdtemp(prefix="valo-exec-smoke-"))
os.environ["APP_EXECUTIVE_METRICS_ENABLED"] = "true"
os.environ["APP_EXECUTIVE_METRICS_DB_PATH"] = str(TMP_ROOT / "exec.sqlite")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.playbooks import trace_buffer  # noqa: E402
from app.playbooks.schemas import (  # noqa: E402
    ActionResult,
    ExecutionTrace,
    PlaybookMatch,
)
from app.schemas import EnforcementEvent, ScanResult  # noqa: E402
from app.services import (  # noqa: E402
    enforcement_events,
    executive_aggregator,
    executive_store,
    portfolio,
)


SCENARIOS = [
    ("allow", False, [], "/v1/proxy/chat/completions", "ingress"),
    ("allow", False, [], "/v1/proxy/chat/completions", "ingress"),
    ("allow", False, [], "/v1/proxy/chat/completions", "ingress"),
    ("allow", False, [], "/analyze", "ingress"),
    ("warn", False, ["warn_pii"], "/v1/proxy/chat/completions", "ingress"),
    ("warn", False, ["warn_pii"], "/v1/proxy/chat/completions", "ingress"),
    ("deny", True, ["block_secret_exposure"], "/v1/proxy/chat/completions", "ingress"),
    ("deny", True, ["block_secret_exposure"], "/v1/proxy/chat/completions", "ingress"),
    ("deny", True, ["block_high_risk"], "/v1/proxy/chat/completions", "ingress"),
    ("deny", True, ["block_high_risk", "warn_pii"], "/v1/proxy/chat/completions", "ingress"),
]


def reset() -> None:
    enforcement_events.clear_events()
    trace_buffer.clear_traces()
    portfolio.clear_scan_history()
    executive_store.reset_database(Path(os.environ["APP_EXECUTIVE_METRICS_DB_PATH"]))
    executive_store.init_schema(Path(os.environ["APP_EXECUTIVE_METRICS_DB_PATH"]))


def seed_enforcement_events() -> int:
    """Push synthetic enforcement events spread across the past hour."""
    now = datetime.now(timezone.utc)
    rng = random.Random(42)
    pushed = 0
    for offset_minutes in range(0, 60, 6):
        for decision, blocked, policies, route, direction in SCENARIOS:
            ts = now - timedelta(minutes=offset_minutes, seconds=rng.randint(0, 30))
            event = EnforcementEvent(
                trace_id=f"trace-{pushed}",
                timestamp=ts,
                route=route,
                direction=direction,
                mode="enforce",
                final_decision=decision,
                blocked=blocked,
                would_block=blocked or decision == "deny",
                matched_policy_ids=policies,
                matched_decisions=[],
                duration_ms=rng.uniform(2.0, 25.0),
            )
            enforcement_events._buffer.append(event)  # type: ignore[attr-defined]
            pushed += 1
    return pushed


def seed_playbook_traces() -> int:
    """Push merged 'all'-phase traces so the aggregator can roll them up."""
    now = datetime.now(timezone.utc)
    rng = random.Random(7)
    pushed = 0
    actions = ("alert", "block", "revoke", "ticket")
    for offset_minutes in range(0, 60, 12):
        ts = now - timedelta(minutes=offset_minutes, seconds=rng.randint(0, 30))
        match = PlaybookMatch(
            playbook_id="pb_alert_secret",
            name="Alert on secret exposure",
            priority=80,
            matched=True,
            reasons=["matched_policy_ids contains block_secret_exposure"],
            results=[
                ActionResult(
                    action=rng.choice(actions),
                    status="executed",
                    message="dry-run ok",
                    duration_ms=rng.uniform(5.0, 50.0),
                ),
            ],
        )
        trace = ExecutionTrace(
            event_id=f"evt-{pushed}",
            started_at=ts,
            duration_ms=rng.uniform(40.0, 180.0),
            matched_playbook_ids=["pb_alert_secret"],
            matches=[match],
            dry_run=True,
            enabled=True,
            phase="all",
            correlation_id=f"corr-{pushed}",
            trace_id=f"trace-pb-{pushed}",
        )
        trace_buffer.record_trace(trace)
        pushed += 1
    return pushed


def seed_scans() -> int:
    """Push a handful of pipeline scans across the last hour."""
    now = datetime.now(timezone.utc)
    pushed = 0
    for offset_minutes, score in [(2, 12.0), (15, 38.5), (32, 67.0), (48, 82.0), (55, 91.5)]:
        scan = ScanResult(
            scan_id=f"scan-{pushed}",
            target=f"https://example.com/api/{pushed}",
            risk_score=score,
            max_severity_found=4 if score >= 60 else 2,
            timestamp=now - timedelta(minutes=offset_minutes),
            finding_count=int(score / 10),
            severity_counts={},
            category_counts={},
            findings=[],
        )
        portfolio.record_scan_result(scan)
        pushed += 1
    return pushed


def hr(title: str) -> None:
    bar = "=" * 72
    print(f"\n{bar}\n {title}\n{bar}")


def main() -> None:
    print("[smoke] tmp dir:", TMP_ROOT)
    print("[smoke] settings.executive_metrics_enabled =", settings.executive_metrics_enabled)
    print("[smoke] settings.executive_metrics_db_path =", settings.executive_metrics_db_path)

    reset()

    hr("Seeding live buffers")
    n_events = seed_enforcement_events()
    n_traces = seed_playbook_traces()
    n_scans = seed_scans()
    print(f"  enforcement events: {n_events}")
    print(f"  playbook traces:    {n_traces}")
    print(f"  scan history:       {n_scans}")

    hr("Running aggregator.run_once")
    stats = executive_aggregator.run_once(
        db_path=Path(os.environ["APP_EXECUTIVE_METRICS_DB_PATH"]),
    )
    for key, value in stats.items():
        print(f"  {key:<18} {value}")

    with TestClient(app) as client:
        hr("GET /executive/summary?window=24h")
        resp = client.get("/executive/summary?window=24h")
        print(f"  status: {resp.status_code}")
        if resp.status_code != 200:
            print("  body:", resp.text)
            return
        body = resp.json()
        print(f"  window:           {body['window']}")
        print(f"  total_requests:   {body['exposure']['total_requests']}")
        print(f"  blocked:          {body['exposure']['blocked']}")
        print(f"  would_block:      {body['exposure']['would_block']}")
        print(f"  block_rate:       {body['exposure']['block_rate']}")
        print(f"  by_decision:      {body['exposure']['by_decision']}")
        print(f"  by_direction:     {body['exposure']['by_direction']}")
        print(
            f"  top_policy:       {body['exposure']['top_blocking_policy_id']} "
            f"({body['exposure']['top_blocking_policy_count']})"
        )
        print(f"  avg_risk_score:   {body['risk']['average_risk_score']}")
        print(f"  p95_risk_score:   {body['risk']['p95_risk_score']}")
        print(f"  critical:         {body['risk']['critical_findings']}")
        print(f"  severity_dist:    {body['risk']['severity_distribution']}")
        print(f"  events_total:     {body['automation']['events_total']}")
        print(f"  playbooks_fired:  {body['automation']['playbooks_fired']}")
        print(f"  actions_executed: {body['automation']['actions_executed']}")
        print(f"  actions_by_type:  {body['automation']['actions_by_type']}")
        print(f"  mtta_ms:          {body['automation']['mean_time_to_action_ms']}")
        print(f"  coverage:         {body['coverage']}")
        print(f"  compliance rows:  {len(body['compliance'])}")
        print(f"  top_offenders:    {len(body['top_offenders'])}")

        hr("GET /executive/trends?window=24h&bucket=5m&metrics=requests,blocked,playbooks_fired,risk_score_sum")
        resp = client.get(
            "/executive/trends",
            params={
                "window": "24h",
                "bucket": "5m",
                "metrics": "requests,blocked,playbooks_fired,risk_score_sum",
            },
        )
        print(f"  status: {resp.status_code}")
        body = resp.json()
        for series in body["series"]:
            totals = sum(p["value"] for p in series["points"])
            peak = max((p["value"] for p in series["points"]), default=0)
            print(
                f"  series={series['metric']:<18} "
                f"points={len(series['points']):>3}  total={totals:.2f}  peak={peak:.2f}"
            )

        hr("GET /executive/export?format=csv&window=24h")
        resp = client.get("/executive/export", params={"format": "csv", "window": "24h"})
        print(f"  status: {resp.status_code}")
        print(f"  content-type: {resp.headers.get('content-type')}")
        print(f"  filename: {resp.headers.get('content-disposition')}")
        head_lines = resp.content.decode("utf-8").splitlines()[:6]
        for line in head_lines:
            print(f"  csv> {line}")
        print(f"  csv bytes: {len(resp.content)}")

        hr("GET /executive/export?format=pdf&window=24h")
        resp = client.get("/executive/export", params={"format": "pdf", "window": "24h"})
        print(f"  status: {resp.status_code}")
        print(f"  content-type: {resp.headers.get('content-type')}")
        print(f"  filename: {resp.headers.get('content-disposition')}")
        print(f"  pdf magic: {resp.content[:8]!r}")
        print(f"  pdf bytes: {len(resp.content)}")

        hr("503 path: flip kill switch off, retry summary")
        from app.core.config import settings as live_settings

        live_settings.executive_metrics_enabled = False
        try:
            resp = client.get("/executive/summary?window=24h")
            print(f"  status: {resp.status_code}")
            print(f"  detail: {resp.json().get('detail')}")
        finally:
            live_settings.executive_metrics_enabled = True

    print("\n[smoke] OK")


if __name__ == "__main__":
    try:
        main()
    finally:
        # Tidy up tmp file on success; leave it on failure for inspection.
        if "OK" in (sys.stdout.getvalue() if hasattr(sys.stdout, "getvalue") else ""):
            for child in TMP_ROOT.glob("**/*"):
                if child.is_file():
                    child.unlink()
            TMP_ROOT.rmdir()
