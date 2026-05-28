# Valo Policy Engine

Centralized governance for prompt-injection scanning. The policy engine sits on
top of the existing rule engine and emits ``allow``, ``warn``, or ``deny``
decisions against a normalised pipeline context. It is the enforcement seam
between Valo's deterministic detection logic and your enterprise compliance
posture (SOC2, GDPR, internal allowlists, etc.).

## How the layers fit together

1. **Rule engine** ([app/services/rule_engine.py](../app/services/rule_engine.py)): YAML-driven, runs context rules (``rules:``) and text-scan rules (``text_scan_rules:``) against `NormalizedInput` and detection flags. Produces `context_score`, `text_scan_score`, `combined_score`, and a list of matched rule ids.
2. **Policy engine** ([app/services/policy_engine.py](../app/services/policy_engine.py)): consumes the rule-engine output (plus detection flags and prompt metadata) and evaluates governance policies. Each policy is a single decision (``allow`` / ``warn`` / ``deny``) gated by AND-conjoined conditions.
3. **Pipeline** ([app/services/pipeline.py](../app/services/pipeline.py)): orchestrates Normalize, Detect, Rule engine, Policy engine, then builds the final `ScanReport`.

```text
Normalize -> Detect -> Rule Engine (context + text-scan) -> Policy Engine -> Report
```

## Storage

Each policy is persisted as a single YAML file under `app/policies/governance/<policy_id>.yml`. The directory is configured by `settings.policies_path` (env var `APP_POLICIES_PATH`). One file per policy keeps git diffs small and enables GitOps-style review workflows.

## Policy schema

```yaml
id: block_high_risk         # slug, [a-zA-Z0-9_-]+, unique, also the filename
name: Block high-risk prompts
description: |
  Optional free-form explanation surfaced to operators.
enabled: true               # disabled policies are skipped
when:                       # list of AND-conjoined conditions (empty = always match)
  - field: combined_score
    op: gte
    value: 80
then:
  decision: deny            # allow | warn | deny
  severity: 9               # 0-10
  message: Combined risk score crosses the deny threshold (>= 80).
tags:                       # arbitrary labels (e.g. compliance:soc2, pii)
  - governance:enterprise
  - severity:critical
version: 1                  # operator-managed counter
```

### Supported condition operators

- `eq`, `ne`: equality / inequality
- `gt`, `gte`, `lt`, `lte`: numeric comparisons (string values coerced to float)
- `in`, `not_in`: membership against a list
- `contains`: substring (string actuals) or list membership (list / tuple / set actuals)
- `matches`: Python regex search (`re.search`)
- `exists`, `not_exists`: presence check (`value` ignored)

`field` supports dot-paths (e.g. `detection.contains_email`, `normalized.target`).

## Policy context

The context built by the pipeline (see `context_from_pipeline` in [policy_engine.py](../app/services/policy_engine.py)) surfaces commonly referenced fields at the top level:

| Field                        | Type        | Description                                  |
| ---------------------------- | ----------- | -------------------------------------------- |
| `combined_score`             | float       | Final 0-100 risk score                       |
| `context_score`              | float       | Score from YAML context rules                |
| `text_scan_score`            | float       | Score from regex / keyword / entropy engines |
| `matched_rule_ids`           | list[str]   | Names of context rules that fired            |
| `matched_text_rule_ids`      | list[str]   | Text-scan rule ids that fired                |
| `text_finding_rule_ids`      | list[str]   | Text-scan rule ids appearing in findings     |
| `max_text_severity`          | int         | Max severity across text findings            |
| `content_type`               | str         | code / json / html / xml / text              |
| `detected_language`          | str \| None | Probable language for code blocks            |
| `token_count`                | int         | Whitespace-split token count                 |
| `line_count`                 | int         | Line count                                   |
| `detection_flags`            | list[str]   | All detection flags (see below)              |
| `target`, `input_kind`, ...  | various     | Lifted from `NormalizedInput`                |
| `<flag>` (e.g. `contains_email`) | bool   | Each detection flag also exposed as a top-level boolean for ergonomic equality conditions |
| `detection`                  | object      | Full `DetectionFlags` for explicit dot-paths |
| `normalized`                 | object      | Full `NormalizedInput` for explicit dot-paths |

## Decision aggregation

Each policy contributes one `PolicyDecision`. The aggregate `final_decision` uses strict precedence:

```
deny > warn > allow
```

Disabled policies and unmatched policies always emit `allow` and do not affect the aggregate.

## Worked examples

### 1. Block high-risk prompts ([app/policies/governance/block_high_risk.yml](../app/policies/governance/block_high_risk.yml))

```yaml
id: block_high_risk
name: Block high-risk prompts
when:
  - field: combined_score
    op: gte
    value: 80
then:
  decision: deny
  severity: 9
  message: Combined risk score is at or above the enterprise deny threshold (>= 80).
tags: [governance:enterprise, severity:critical]
```

### 2. Warn on PII exposure ([app/policies/governance/warn_pii.yml](../app/policies/governance/warn_pii.yml))

```yaml
id: warn_pii
name: Warn on PII exposure
when:
  - field: contains_email
    op: eq
    value: true
then:
  decision: warn
  severity: 4
  message: Personally identifiable information detected (email pattern).
tags: [compliance:gdpr, pii]
```

### 3. Block secret exposure ([app/policies/governance/block_secret_exposure.yml](../app/policies/governance/block_secret_exposure.yml))

```yaml
id: block_secret_exposure
name: Block secret exposure
when:
  - field: matched_rule_ids
    op: contains
    value: secret_signal
then:
  decision: deny
  severity: 8
  message: Prompt contains secret-like material (password / api_key / bearer token).
tags: [compliance:soc2, secret-leak]
```

## REST API

Full reference lives in [ENDPOINTS_AND_LOGIC.md](ENDPOINTS_AND_LOGIC.md). The shape of the surface:

- `GET /policies`: list + fingerprints
- `GET /policies/{id}`: fetch one
- `POST /policies`: create (409 on duplicate id, 201 on success)
- `PUT /policies/{id}`: replace (404 / 422)
- `DELETE /policies/{id}`: remove (204)
- `POST /policies/validate`: dry-run schema validation
- `POST /policies/evaluate`: ad-hoc evaluation against a JSON context
- `POST /policies/reload`: cache invalidation + diff after out-of-band edits

### Example: dry-run evaluation in CI

```bash
curl -s -X POST http://localhost:8000/policies/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"context": {"combined_score": 92, "contains_email": true}}'
```

```json
{
  "decisions": [
    {
      "policy_id": "block_high_risk",
      "matched": true,
      "decision": "deny",
      "severity": 9,
      "message": "Combined risk score is at or above the enterprise deny threshold (>= 80).",
      "reasons": ["combined_score gte 80 (actual=92, matched)"],
      "tags": ["governance:enterprise", "severity:critical"]
    }
  ],
  "final_decision": "deny"
}
```

### Example: GitOps workflow

1. Edit YAML files under `app/policies/governance/` in source control.
2. Run `POST /policies/validate` against each file in CI to catch schema regressions.
3. Sync the directory to the running container (rsync / volume mount / image rebuild).
4. Call `POST /policies/reload` to refresh the cache and inspect the diff.

## Operational notes

- Caching: policies are cached for `settings.policies_cache_ttl_seconds` seconds (default 60). Mutations through the API invalidate the cache automatically; out-of-band file edits require `POST /policies/reload`.
- Atomic writes: `save_policy` writes to a same-directory temp file then `os.replace`s into place to avoid partial reads on concurrent listing.
- Determinism: the engine has no randomness, no I/O during evaluation, and no implicit context lookups. Same input + same policy file always produces the same decision.

## Enforcement (AI Firewall)

Phase 1 promotes `allow / warn / deny` from advisory to in-line enforcement. The policy engine itself is unchanged: a small Starlette middleware (`app/middleware/policy_enforcement.py`) and the OpenAI-compatible egress proxy (`app/api/proxy.py`) consume the same `PolicyDecision` list and decide whether to pass, warn, or block at the HTTP edge.

### Surfaces

1. **Ingress middleware**: every `POST` to a route in `settings.enforcement_protected_routes` (`/analyze`, `/scan/report`, `/report/pdf`, `/ingest/normalize` by default) is buffered, scanned via `run_pipeline`, and either short-circuited with `403 PolicyDenied` or allowed through with advisory headers.
2. **Egress LLM proxy**: `POST /v1/proxy/chat/completions` is OpenAI-compatible. Inbound `messages[].content` is scanned before any upstream call, then the upstream completion is scanned again before being returned. A deny on either side returns `403 PolicyDenied` and the upstream provider is never billed (request-side) or never reaches the client (response-side).

### Modes

Two layers of control, both must be set so an operator can roll out enforcement safely:

| Layer        | Setting                              | Values                          | Default     |
| ------------ | ------------------------------------ | ------------------------------- | ----------- |
| Global       | env `APP_ENFORCEMENT_MODE` / `settings.enforcement_mode` | `off` / `monitor` / `enforce` | `monitor` |
| Per-policy   | `enforce: true \| false` field on `Policy` (YAML) | `true` / `false`               | `true`      |

A request is **blocked** only when **all** of the following hold:

```
settings.enforcement_mode == "enforce"
AND a matched policy has decision == "deny"
AND that policy has enforce == true
```

Any deny in `monitor` mode (or with `enforce: false` even in `enforce` mode) is logged as `would_block` but the request still passes through.

### HTTP contract

| Outcome         | Status | Headers                                                                                          | Body                       |
| --------------- | ------ | ------------------------------------------------------------------------------------------------ | -------------------------- |
| Allow           | 200    | `X-Valo-Policy-Decision: allow`, `X-Valo-Trace-Id`, `X-Valo-Enforcement-Mode`                    | original handler response  |
| Warn            | 200    | as above with `decision=warn` and `X-Valo-Matched-Policies: id1,id2`                             | original handler response  |
| Deny (enforce)  | 403    | `X-Valo-Policy-Decision: deny`, `X-Valo-Trace-Id`, `X-Valo-Matched-Policies`                     | `PolicyDenied` envelope (below) |
| Deny (monitor)  | 200    | `X-Valo-Policy-Decision: deny`, `X-Valo-Enforcement-Mode: monitor` (would_block recorded in log) | original handler response  |

Block envelope (`AppException` shape):

```json
{
  "error": {
    "code": "PolicyDenied",
    "message": "Request blocked by Valo governance policy.",
    "detail": {
      "trace_id": "5b1c...",
      "final_decision": "deny",
      "matched_policy_ids": ["block_high_risk"],
      "decisions": [
        {
          "policy_id": "block_high_risk",
          "name": "Block high-risk prompts",
          "matched": true,
          "decision": "deny",
          "severity": 9,
          "message": "Combined risk score is at or above ...",
          "reasons": ["combined_score gte 80 (actual=92, matched)"],
          "tags": ["governance:enterprise", "severity:critical"]
        }
      ]
    }
  }
}
```

The proxy adds a `"side": "request"` or `"side": "response"` field to `detail` so callers can tell which leg of the LLM call was blocked.

### No-double-work guarantee

The middleware caches its `EnforcementOutcome` (with the full `PipelineResult`) on `request.state.policy_enforcement_outcome`. Handlers like `/analyze`, `/scan/report`, and `/report/pdf` use `get_or_run_pipeline(request, payload, rules)` from `app/services/pipeline.py` which transparently reuses that cached result instead of running the pipeline a second time. If the middleware did not run (mode `off`, oversized body, unprotected route) the helper falls through to `run_pipeline`.

### Audit log

Every middleware and proxy decision emits one structured line via the standard logger:

```
event=policy_enforcement trace_id=... route=/analyze direction=ingress
  mode=enforce final_decision=deny blocked=true would_block=true
  matched_policy_ids=["block_high_risk"] duration_ms=12.7
```

`direction` is `ingress` for the request-side scan and `egress` for the proxy's response-side scan, so SIEMs can split the two cleanly.

### Configuration reference

| Setting (`APP_*` env)           | Default                                                  | Notes                                                           |
| ------------------------------- | -------------------------------------------------------- | --------------------------------------------------------------- |
| `ENFORCEMENT_MODE`              | `monitor`                                                | `off` skips the middleware entirely.                            |
| `ENFORCEMENT_PROTECTED_ROUTES`  | `/analyze,/scan/report,/report/pdf,/ingest/normalize`    | Comma-separated list. Path prefix match.                        |
| `ENFORCEMENT_MAX_BODY_BYTES`    | `1048576`                                                | Bodies above this bypass enforcement and are logged.            |
| `PROXY_UPSTREAM_URL`            | `https://api.openai.com/v1/chat/completions`             | OpenAI-compatible upstream for `/v1/proxy/chat/completions`.    |
| `PROXY_REQUEST_TIMEOUT_SECONDS` | `60.0`                                                   | Upstream timeout for the proxy.                                 |

### Out of scope (Phase 2+)

- RBAC on `/v1/proxy/*` and per-tenant policy sets.
- Anthropic / Gemini / Bedrock proxy parity (only OpenAI-compatible chat.completions in Phase 1).
- True token-level streaming response-side scanning (Phase 1 buffers the full upstream response).
- Persistent decision store / decision replay UI.
