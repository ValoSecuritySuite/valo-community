# Phase 4 - Learning Loop

## Status

Phase 4 ships the closed-loop layer on top of the Phase 3 Response engine
(:doc:`PLAYBOOKS.md`):

- Durable outcome store: every playbook execution that today reaches the
  in-memory trace ring buffer is also persisted to SQLite, so analyst
  labels and aggregate stats survive process restarts.
- Cross-product outcome ingest: LLMShadow, SaaSShadow, and any external
  SOC console can post analyst labels into the same store via a single
  HMAC-signed envelope. One canonical timeline per tenant, regardless of
  which scanner produced the finding.
- Refiner: a heuristic engine that reads the outcome store and writes
  reviewable rule proposals to ``app/policies/proposals/*.yml`` and
  ``app/playbooks/proposals/*.yml``.
- Review surface: a small REST API plus YAML diffs so operators accept,
  reject, and audit every proposed change before it touches a live rule.

Default-off, default-secure: no proposals are generated until
``APP_LEARNING_LOOP_ENABLED=true`` and no proposals modify a live rule
until an operator calls ``POST /learning/proposals/{id}/accept``.

## Why

Phase 1 detects (rule + policy engines).
Phase 2 correlates (`correlation_emitter` ships envelopes to the
Correlation Engine).
Phase 3 acts (playbook executor: alert, block, revoke, ...).
Phase 4 closes the loop: capture analyst feedback on Phase 3 outcomes,
turn it into per-rule statistics, and refine rules so the next pass
fires more accurately.

The aggregate of labeled outcomes is the proprietary signal: noisy
rules get tuned down, valuable rules get reinforced, and the entire
playbook library improves continuously without anyone hand-editing
YAML against gut feel.

## Architecture

```
+--------------------+       +---------------------+
| Playbook executor  |       | Cross-product       |
| (Phase 3)          |       | scanner (LLMShadow, |
| record_trace()     |       | SaaSShadow, ...)    |
+----------+---------+       +----------+----------+
           |                            |
           v                            v
        +-----------------------------------+
        |      outcome_store (SQLite)       |
        | outcomes table, labeled per-event |
        +----------------+------------------+
                         |
        +----------------+------------------+
        |                |                  |
        v                v                  v
  /outcomes        Refiner job        /outcomes/stats
  /outcomes/ingest (background       (per-rule FP rate,
  /outcomes/{id}/   thread or         labeled count, ...)
   label            POST /learning/
                    refresh)
                         |
                         v
              +----------------------+
              |  Proposals on disk   |
              | app/policies/        |
              |   proposals/*.yml    |
              | app/playbooks/       |
              |   proposals/*.yml    |
              +----------+-----------+
                         |
                         v
              +----------------------+
              |  Review surface      |
              | GET /learning/       |
              |   proposals          |
              | POST /learning/      |
              |   proposals/{id}/    |
              |   accept | reject    |
              +----------+-----------+
                         |
                         v  (writes through policy_store /
                            playbooks store atomically)
                  Live YAML rules
```

## Outcome envelope (canonical wire format)

This is the contract LLMShadow, SaaSShadow, and any other external
producer should follow when posting analyst labels into Valo. The same
envelope is used by ``POST /outcomes/ingest`` and by the cross-product
correlation flow.

```jsonc
{
  "outcome_id": "uuid (optional, server generates if omitted)",
  "event_id": "scanner-local id of the event that produced this outcome",
  "source": "valo | correlation_engine | llmshadow | saasshadow | external",
  "trace_id": "scanner-side trace id (optional)",
  "correlation_id": "join key between producers (optional)",
  "tenant_id": "string (optional)",
  "severity": "info | low | medium | high | critical",
  "decision": "allow | warn | deny",
  "matched_policy_ids": ["..."],
  "matched_playbook_ids": ["..."],
  "action_results": [
    { "action": "alert", "status": "executed", "detail": { ... } }
  ],
  "started_at": "ISO-8601 (defaults to now)",
  "duration_ms": 0.0,
  "dry_run": false,
  "enabled": true,
  "label": "true_positive | false_positive | benign_block | malicious_allow | suppressed | dismissed",
  "label_reason": "free text (optional)",
  "labeled_by": "user id or service (optional)",
  "raw": { "scanner-specific extra fields": "..." }
}
```

Field rules:

- ``event_id`` and ``source`` are required; the rest are optional.
- ``label`` must be one of the allowed values. Anything else returns
  HTTP 422.
- ``outcome_id`` is the idempotency key. Re-posting the same id replaces
  the row; this is how producers retry safely.
- ``raw`` is opaque and round-trips unchanged so downstream tooling can
  attach scanner-specific context without changing the schema.

### HMAC signing

When ``APP_OUTCOME_INGEST_SECRET`` is set, the request must include:

| Header              | Value                                            |
|---------------------|--------------------------------------------------|
| ``X-Valo-Source``   | producer slug (``llmshadow``, ``saasshadow``)    |
| ``X-Valo-Timestamp``| unix seconds, must be within 5 minutes of server |
| ``X-Valo-Signature``| ``hex(hmac_sha256(secret, f"{ts}." + body))``    |

This is the same scheme the existing
:mod:`app.services.correlation_emitter` uses, so producers that already
ship to the Correlation Engine can reuse their key material.

If the server has no secret configured, requests are still accepted but
a warning is logged. Production deployments must set the secret.

## Refiner heuristics

All heuristics share these guard rails:

- ``learning_loop_min_samples`` (default 50): never propose against a
  rule with fewer than N labeled outcomes.
- ``learning_loop_fp_threshold`` (default 0.30): the FP rate above which
  a rule is considered noisy.
- ``learning_loop_healthy_fp_ceiling`` (default 0.05): rules at or below
  this rate get no proposal.
- The "FP rate" mixes ``false_positive`` and ``benign_block`` labels: a
  block on legitimate traffic carries the same downward pressure as a
  detection FP.

| Heuristic                            | Trigger                                                                | Proposed change                                  |
|--------------------------------------|------------------------------------------------------------------------|--------------------------------------------------|
| ``disable_noisy_playbook``           | playbook with FP rate > threshold and currently enabled                | ``enabled: false``                               |
| ``lower_priority_noisy_playbook``    | playbook with healthy_ceiling < FP rate <= threshold                   | ``priority -= 10``                               |
| ``raise_combined_score_threshold``   | policy gating on ``combined_score`` (gte / gt) with FP rate > threshold | bump threshold by 5 (capped at 100)              |

Healthy rules get no proposal. Under-sampled rules get no proposal. A
rule that has already been disabled gets no proposal.

Proposals are addressed by a deterministic ``proposal_id``:
``<kind>_<rule_id>_<heuristic>_<8-char-hash>``. Re-running the refiner
overwrites the existing proposal in place instead of accumulating
duplicates.

## Review workflow

1. Refiner runs (background scheduler every
   ``learning_loop_schedule_seconds`` seconds, or on demand via
   ``POST /learning/refresh``).
2. Each emitted proposal is a YAML file under
   ``app/policies/proposals/`` or ``app/playbooks/proposals/`` with the
   full ``current_yaml`` and ``proposed_yaml`` plus a
   human-readable ``diff_summary`` and the supporting stats slice.
3. Operator inspects the proposals via ``GET /learning/proposals``
   (filterable by kind, status, rule_id) and ``GET /learning/proposals/{id}``.
4. Operator accepts via ``POST /learning/proposals/{id}/accept`` (with
   optional ``reviewer`` and ``reason`` in the body). The handler
   schema-validates ``proposed_yaml``, writes it through the live policy
   or playbook store (which already covers atomic writes and cache
   invalidation), and stamps the proposal ``status: applied``.
5. Operator can also reject via ``POST /learning/proposals/{id}/reject``;
   the file stays on disk for audit history.

There is no "auto-apply in production" path. ``learning_loop_auto_apply``
exists for completeness but defaults ``False`` and stays off; every
change goes through ``/accept``.

## Endpoints

| Method | Path                                      | Purpose                                            |
|--------|-------------------------------------------|----------------------------------------------------|
| GET    | ``/outcomes``                             | Paginated list of persisted outcomes               |
| GET    | ``/outcomes/stats``                       | Per-rule aggregate stats (FP rate, hit count)      |
| POST   | ``/outcomes/{trace_id}/label``            | Apply analyst label to one outcome                 |
| POST   | ``/outcomes/ingest``                      | Cross-product outcome ingest (HMAC-signed)         |
| GET    | ``/learning/proposals``                   | List refiner proposals                             |
| GET    | ``/learning/proposals/{id}``              | Fetch one proposal with diff and stats             |
| POST   | ``/learning/proposals/{id}/accept``       | Apply through live store, mark ``applied``        |
| POST   | ``/learning/proposals/{id}/reject``       | Mark ``rejected`` with reviewer reason             |
| POST   | ``/learning/refresh``                     | Run the refiner immediately (503 if disabled)      |

## Settings

| Setting                                | Default                            | Notes                                                                  |
|----------------------------------------|------------------------------------|------------------------------------------------------------------------|
| ``APP_OUTCOME_STORE_PATH``             | ``data/learning_outcomes.sqlite``  | SQLite file backing the outcomes table                                 |
| ``APP_OUTCOME_INGEST_SECRET``          | ``""``                             | When set, HMAC headers are required on ``/outcomes/ingest``            |
| ``APP_LEARNING_LOOP_ENABLED``          | ``false``                          | Master kill switch for the refiner background task                     |
| ``APP_LEARNING_LOOP_AUTO_APPLY``       | ``false``                          | Reserved; do not flip on in production                                 |
| ``APP_LEARNING_LOOP_MIN_SAMPLES``      | ``50``                             | Per-rule minimum labeled samples                                       |
| ``APP_LEARNING_LOOP_FP_THRESHOLD``     | ``0.30``                           | FP rate above which a rule is "noisy"                                  |
| ``APP_LEARNING_LOOP_HEALTHY_FP_CEILING`` | ``0.05``                         | FP rate at or below this gets no proposal                              |
| ``APP_LEARNING_LOOP_SCHEDULE_SECONDS`` | ``3600``                           | Cadence for the background refiner task                                |

## Out of scope (Phase 4)

- ML-based proposers. Heuristics first; ML can plug into the same
  proposal interface later.
- Distributed refiner execution. One process per deployment is enough
  while the rule library is YAML on disk.
- LLMShadow / SaaSShadow analyst-label UIs. Those scanners only need to
  start posting labels via the documented envelope when their UI ships
  the feature.
- Auto-apply in production. The accept / reject contract is the only
  path that mutates live YAML.
