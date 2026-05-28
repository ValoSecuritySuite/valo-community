# Automated Response Playbooks (Phase 3)

## Status

Phase 3 execution engine landed:

- Schema, matcher, action registry, and six dry-run action stubs (skeleton).
- Filesystem-backed playbook store with TTL cache and atomic writes.
- Two-phase executor: ``inline`` (block on the request thread) and
  ``background`` (everything else on a daemon thread).
- Live runtime hooked into ``log_enforcement_outcome`` so every proxy
  and middleware decision dispatches into the engine.
- Trace ring buffer + REST surface (``/playbooks/*``) for CRUD,
  validate, reload, evaluate, external event ingest, and traces.
- Default-off, default-secure: ``APP_PLAYBOOKS_ENABLED=false`` and
  ``APP_PLAYBOOKS_DRY_RUN=true``. No real side effects until real
  adapters land in Phase 3.x.

## Why

Phase 1 detects (rule and policy engines).
Phase 2 correlates (`correlation_emitter` ships envelopes to the Correlation Engine).
Phase 3 acts: when a finding crosses a threshold or matches a pattern,
Valo runs an automated response.

Playbooks are the customer-facing primitive that ties detections (Valo
policies, correlated findings) to a list of named actions, declared in
YAML, audited, dry-runnable, and version-controlled in Git.

## Out of scope (Phase 3 skeleton)

- Real action side effects (delivered in Phase 3.x adapter PRs).
- Distributed execution / job queue (delivered in Phase 4).
- Retries, circuit breakers, deduplication windows (Phase 3.1).

## Architecture

```
+--------------------+     +-----------------+     +--------------------+
|  Enforcement       |     |  Correlation    |     |  External event    |
|  outcome (in-proc) |     |  finding (HTTP) |     |  source (future)   |
+---------+----------+     +--------+--------+     +----------+---------+
          \                         |                         /
           \                        v                        /
            +--------- PlaybookEvent (typed) ---------------+
                                  |
                                  v
                       +----------------------+
                       |  PlaybookExecutor    |
                       |   1. load library    |
                       |   2. match triggers  |
                       |   3. run actions     |
                       |   4. emit trace      |
                       +----------+-----------+
                                  |
                                  v
                       +----------------------+
                       |  ActionRegistry      |
                       |  block, revoke,      |
                       |  alert, quarantine,  |
                       |  ticket, rate_limit, |
                       |  custom.<name>       |
                       +----------------------+
```

All work is in-process and side-effect free in v1: every action only logs
a structured `ActionResult{status: "planned"}` line. Phase 3.x replaces
each stub with a real adapter behind the same contract.

## Trigger model: hybrid

Two trigger sources, both consumed by the same engine:

1. **YAML rules** (preferred for governance / GitOps).
   Same condition dialect as the existing policy engine
   (`eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `contains`,
   `matches`, `exists`, `not_exists`). Conditions evaluate against the
   flattened `PlaybookEvent` dict.

2. **Python plugins** (preferred for custom logic / integration glue).
   A typed `Action` callable registered with `@register_action("name")`.
   YAML rules can dispatch to `custom.<name>` to invoke a registered
   plugin.

## Files

```
app/playbooks/
  __init__.py
  schemas.py         Pydantic models
  events.py          PlaybookEvent + factories
  matcher.py         Condition evaluator (mirrors policy_engine dialect)
  registry.py        ActionRegistry (decorator + lookup)
  loader.py          YAML library loader
  executor.py        Match -> dispatch -> trace
  actions/
    __init__.py      Side-effect imports (decorators register here)
    base.py          Action protocol + ActionContext
    block.py         deny inline (Valo proxy 403)
    revoke.py        invalidate session / OAuth grant / token
    alert.py         SOC notification (webhook / Slack / email)
    quarantine.py    mark scan / connector / repo unsafe
    ticket.py        open Jira / Linear / GitHub issue
    ratelimit.py     throttle the offending source
  library/
    block_high_risk_proxy.yml
    revoke_and_alert_secret_exposure.yml
```

Tests live in `tests/test_playbooks.py`.

## Schema reference

### `Playbook`

```yaml
id: revoke_and_alert_secret_exposure
name: Revoke leaked secret and alert SOC
description: |
  When a prompt contains an API key or password, immediately block the
  call, revoke any session attached to the request, and alert the SOC.
enabled: true
priority: 80                       # higher fires first; ties: stable order
when:
  - field: source
    op: eq
    value: valo
  - field: matched_policy_ids
    op: contains
    value: block_secret_exposure
then:
  - action: block
    params:
      reason: secret_exposure
  - action: revoke
    params:
      target: session
      reason: leaked_credential
  - action: alert
    params:
      channel: soc_high_severity
      severity: high
tags:
  - compliance:soc2
  - secret-leak
version: 1
```

### Built-in actions

| Action     | Stub semantics in v1                          | Phase 3.x adapter target |
|------------|-----------------------------------------------|--------------------------|
| block      | Returns `planned` with the inline `403` body. | Already wired in Valo proxy: this re-affirms it. |
| revoke     | Logs `would-revoke`. No-op.                   | Session store / OAuth provider call. |
| alert      | Logs structured event.                        | Webhook / Slack / email / pagerduty. |
| quarantine | Logs `would-quarantine`.                      | Scan store flag, connector disable. |
| ticket     | Logs ticket payload.                          | Jira / Linear / GitHub issue API. |
| rate_limit | Logs `would-throttle`.                        | Token bucket on offender id. |

### Custom actions

```python
# app/playbooks/actions/notify_oncall.py
from app.playbooks.registry import register_action
from app.playbooks.actions.base import ActionContext, ActionResult

@register_action("custom.notify_oncall")
def notify_oncall(ctx: ActionContext, params: dict) -> ActionResult:
    return ActionResult(action="custom.notify_oncall", status="planned",
                        detail={"oncall_team": params.get("team", "default")})
```

A YAML playbook can then declare:

```yaml
then:
  - action: custom.notify_oncall
    params:
      team: ai-firewall
```

## Event shape (`PlaybookEvent`)

```jsonc
{
  "event_id": "uuid",
  "timestamp": "ISO-8601",
  "source": "valo|correlation_engine|external",
  "event_type": "enforcement.outcome | correlation.finding | <custom>",
  "tenant_id": "string|null",
  "severity": "info|low|medium|high|critical",
  "decision": "allow|warn|deny|null",
  "blocked": true,
  "matched_policy_ids": ["block_secret_exposure"],
  "combined_score": 87.5,
  "trace_id": "valo-trace-id",
  "subject": {                     // who/what triggered
    "type": "session|ip|user|api_key|repo|connector",
    "id": "string"
  },
  "raw": { ... }                   // original payload, opaque
}
```

`PlaybookEvent.from_enforcement_outcome(outcome, route, direction)` is
provided so the existing `policy_enforcement` pipeline can adopt this in
one call.

## Execution semantics

1. `executor.process_event(event)`:
   - Returns immediately with an empty trace if `settings.playbooks_enabled` is `False`.
   - Loads the in-memory `PlaybookSet` (loaded once at startup, hot-reloadable).
   - Filters playbooks where `enabled=true` and every `when` condition matches.
   - Sorts matched playbooks by descending `priority`, then by id for stability.
   - For each matched playbook, runs its `then` actions in order.
   - Each action is dispatched through `ActionRegistry.get(name)`. Unknown actions log a structured warning and produce an `ActionResult{status: "skipped", detail: "unknown_action"}`.
   - All exceptions raised inside an action are captured and returned as `ActionResult{status: "error", detail: {message}}`. **The engine never raises.**
2. Returns an `ExecutionTrace` listing matched playbooks and per-action results, suitable for serialization into the audit ring buffer.

## Safety controls

- `settings.playbooks_enabled` (default `False`): hard kill switch.
- `settings.playbooks_dry_run` (default `True`): every adapter MUST honor this and return `planned` without calling external APIs. Default-secure: even when the engine is on, no real side effects until a human sets `dry_run=False` for that environment.
- Per-playbook `enabled: true|false`.
- All execution is logged; ring-buffer integration is a follow-up PR.

## Wiring (delivered)

- ``log_enforcement_outcome`` in :mod:`app.services.policy_enforcement`
  builds a :class:`PlaybookEvent` from every enforcement outcome and
  calls :func:`app.playbooks.runtime.dispatch`. Inline phase runs
  synchronously so a ``block`` action can affect the response; the rest
  fires-and-forgets on a daemon thread mirroring ``correlation_emitter``.
- ``/playbooks/*`` REST surface ships full CRUD plus ``validate``,
  ``reload``, ``evaluate`` (no persistence), ``events`` (external
  ingest, fully-merged trace returned), and ``traces`` (query the ring
  buffer).
- The trace ring buffer (``app.playbooks.trace_buffer``) keeps merged
  ``ExecutionTrace`` records for the dashboard.

## Wiring (next PRs, still pending)

- Replace dry-run stubs with real adapters one at a time
  (alert -> Slack/webhook is the easiest first win, then revoke ->
  session store, then ticket -> Jira/Linear/GitHub).
- Web console panel: ``Playbooks`` view alongside ``Policies`` for CRUD
  plus a live trace viewer reading from ``GET /playbooks/traces``.
- Phase 4 (delivered): durable outcome store + cross-product analyst
  labeling + heuristic refiner that proposes rule changes for human
  review. See :doc:`LEARNING_LOOP.md`. Every call to
  :func:`app.playbooks.trace_buffer.record_trace` now also persists an
  :class:`OutcomeRecord` so labels and stats survive restarts.
- Phase 4 Reporting Automation (delivered): persistent weekly executive
  + portfolio rollup reports, an ad-hoc generation API, and a download
  catalogue. Reuses the existing executive metrics export and the
  portfolio rollup PDF engine. See :doc:`REPORTING.md`.
- Phase 4.x: distributed action execution (queue + retry / circuit
  breakers / dedup window) for the slowest adapters.
