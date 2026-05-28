# Reporting Automation (Phase 4)

## Status

Phase 4 reporting pipeline landed:

- New `data/reports/` filesystem store + `data/reports.sqlite` index
  for generated reports (PDF / CSV / JSON failure stubs).
- Dispatch table over the existing engines: every report kind is a
  thin adapter, no engine logic is duplicated.
- Default-off weekly scheduler that walks the configured kinds once
  per weekly window (Mon 06:00 UTC by default) and writes results to
  disk. Bookkeeping survives restarts via SQLite.
- REST surface under `/reports/*` with paginated list, single-record
  fetch, binary download, ad-hoc generate, manual scheduler trigger,
  catalogue, and delete.
- Web console "Reports" view under Executive: scheduler banner,
  generate-now form, persisted reports table with download / delete.

## Why

- Phase 4 row in the Valo plan: "Weekly reports + API export, depends
  on Dashboard, drives recurring insights and revenue support."
- The PDF and CSV engines already existed. What was missing was a
  cadence (weekly), durability (browse generated reports), and a UI
  surface to consume the artifacts.

## What is reused

This pipeline is intentionally a thin layer; it never re-implements
report rendering. The existing engines drive every kind:

- `app.services.executive_metrics.export(window, fmt)` for the
  executive PDF + CSV (already returns `(bytes, filename)`).
- `app.services.pdf_report_generator.generate_executive_pdf(report,
  dashboard_payload=..., include_scan_sections=False)` for portfolio
  rollup PDFs (mirrors `GET /report/pdf/rollup`).
- `app.services.dashboard.build_dashboard_payload()` for the rollup
  data, plus `dashboard.get_scan_report(scan_id)` for per-scan PDFs.

## Data layout

| What            | Where                                                 |
|-----------------|-------------------------------------------------------|
| Index           | `data/reports.sqlite` (`APP_REPORT_INDEX_PATH`)       |
| Blobs           | `data/reports/{report_id}.{format}` (`APP_REPORT_STORE_PATH`) |
| Scheduler state | `report_kv` table inside the index                    |

The index has two tables:

```
reports(report_id PK, kind, window, format, status, filename,
        size_bytes, sha256, generated_at, error, metadata)
report_kv(key PK, value)
```

Files are written first, then indexed: a partial write never lands a
phantom row in the catalogue.

## Report kinds

Defined in `app/services/report_generator_jobs.py::REGISTRY`. Surfaced
via `GET /reports/kinds`.

| Kind                  | Format | Window | Engine                                        |
|-----------------------|--------|--------|-----------------------------------------------|
| `executive_pdf_7d`    | pdf    | 7d     | `executive_metrics.export`                    |
| `executive_csv_7d`    | csv    | 7d     | `executive_metrics.export`                    |
| `executive_pdf_30d`   | pdf    | 30d    | `executive_metrics.export`                    |
| `executive_csv_30d`   | csv    | 30d    | `executive_metrics.export`                    |
| `portfolio_rollup_pdf`| pdf    | -      | `generate_executive_pdf` + `build_dashboard_payload` |
| `scan_pdf`            | pdf    | -      | `generate_executive_pdf` (requires `scan_id`) |

Adding a new kind is a single dictionary entry plus a runner:

```
REGISTRY["my_new_kind"] = ReportKind(...)
_RUNNERS["my_new_kind"] = my_runner_function
```

## Configuration

All settings are environment-prefixed with `APP_` (see
`app/core/config.py`). Sane defaults ship in `.env.example`.

| Setting                                | Default | Notes                                     |
|----------------------------------------|---------|-------------------------------------------|
| `APP_REPORTS_ENABLED`                  | `true`  | Master switch for `/reports/*`.           |
| `APP_REPORT_STORE_PATH`                | `data/reports` | Directory for blobs.               |
| `APP_REPORT_INDEX_PATH`                | `data/reports.sqlite` | Index location.             |
| `APP_REPORT_SCHEDULER_ENABLED`         | `false` | Opt-in for the weekly cadence task.       |
| `APP_REPORT_SCHEDULE_WEEKLY_WEEKDAY`   | `0`     | 0 = Mon, 6 = Sun (UTC).                   |
| `APP_REPORT_SCHEDULE_WEEKLY_HOUR`      | `6`     | Hour of day (UTC, 0-23).                  |
| `APP_REPORT_SCHEDULER_TICK_SECONDS`    | `60`    | Polling cadence.                          |
| `APP_REPORT_RETENTION_DAYS`            | `90`    | Pruned after each successful tick.        |
| `APP_REPORT_DEFAULT_KINDS`             | `executive_pdf_7d,executive_csv_7d,portfolio_rollup_pdf` | Kinds the scheduler runs each tick. |

Note: `executive_*` kinds depend on `APP_EXECUTIVE_METRICS_ENABLED`
being on (so the SQLite rollup file exists). The reports API itself
does not require it; only those kinds will fail until executive
metrics is enabled.

## Scheduling model

The scheduler defines a weekly window opening at `(weekday, hour)`
UTC and lasting 7 days. Each kind in `APP_REPORT_DEFAULT_KINDS` is
"due" once per window:

- A kind is generated when `is_due(kind, now) == True`, i.e. its
  last successful run is before the current window start.
- After a successful run the per-kind `last_run` is recorded in
  `report_kv` and the kind becomes `skipped` until the next window.
- Failures are persisted as `status=failed` reports (with the error
  in `metadata`) but do **not** advance `last_run`, so the next tick
  retries.
- After every tick the store prunes records older than
  `APP_REPORT_RETENTION_DAYS`.

Manual control:

- `POST /reports/scheduler/run`           - run kinds that are due.
- `POST /reports/scheduler/run` `{"force": true}` - re-run regardless.
- `POST /reports/scheduler/run` `{"kinds": ["executive_pdf_7d"]}` - subset.

## REST surface

```
GET    /reports                          ?kind&window&format&status&after&before&limit&offset
GET    /reports/kinds                    catalogue of supported kinds
GET    /reports/scheduler                config + per-kind last-run info
GET    /reports/{report_id}              metadata
GET    /reports/{report_id}/download     stream binary (Content-Disposition attachment)
POST   /reports/generate                 {kind, scan_id?}
POST   /reports/scheduler/run            {kinds?, force?}
DELETE /reports/{report_id}              remove file + row
```

When `APP_REPORTS_ENABLED=false` every endpoint returns 503.

### Curl examples

```
# Generate an on-demand 7-day executive PDF
curl -X POST http://localhost:8000/reports/generate \
  -H 'Content-Type: application/json' \
  -d '{"kind": "executive_pdf_7d"}'

# Browse what is persisted
curl 'http://localhost:8000/reports?kind=executive_pdf_7d&format=pdf'

# Download the actual bytes
curl -OJ http://localhost:8000/reports/<report_id>/download

# Force-run every default weekly kind right now (handy for demos)
curl -X POST http://localhost:8000/reports/scheduler/run \
  -H 'Content-Type: application/json' \
  -d '{"force": true}'
```

## Web console

The "Executive -> Reports" sidebar entry hosts `ReportsView.jsx`:

- Scheduler banner: enabled flag, weekly cadence, retention, default
  kinds, current/next window, per-kind last-run table.
- Generate-now form: pulls `/reports/kinds`, shows the description,
  prompts for `scan_id` when the selected kind requires it.
- Persisted reports table: filter by kind / format / status, paginate,
  download with the server-provided filename, or delete.
- "Run scheduler now" runs only the due kinds; "Force run all" runs
  every default kind regardless of last-run timestamp.

The new view rides the same proxy plumbing (`/reports` is added to
`PROXY_PREFIXES` in `web/vite.config.js`) so the dev server forwards
the requests to FastAPI.

## Executive KPI report layout

The `executive_pdf_7d` and `executive_pdf_30d` kinds are rendered by
`app/services/executive_kpi_pdf.py::generate_kpi_pdf`. The output is a
boardroom-style ReportLab PDF that mirrors the navy branding used by
the per-scan PDF and is structured around widely-cited CISO reporting
guidance (posture headline, headline KPIs, trends, exposure, risk,
automation, coverage, recommended actions).

### Pages

1. **Cover.** Full-bleed navy page with the `Valo` brand mark, the
   report title, the trailing-window subtitle, and three headline
   metrics (blocked count + rate, critical findings, average risk
   score). Optional "Prepared for ..." line shown when branding is
   provided. Switches to the body template on `PageBreak`.
2. **Executive Summary.** One-paragraph posture headline
   (`improving` / `stable` / `degrading`) auto-derived from the
   period-over-period delta on critical findings and block-rate
   percentage points. Followed by a 2x2 KPI tile grid (block rate,
   average risk score, critical findings, mean time-to-action) with
   `up` / `down` / `=` glyphs in green or red depending on whether the
   metric direction is good for the business. The same page lists 1 to
   5 "Recommended Actions" auto-derived from coverage and exposure
   (inactive playbooks, over-broad top blocking policy, critical
   findings to triage, observe-only policies to promote, missing
   compliance tags).
3. **Trends.** A `reportlab.graphics.charts.lineplots.LinePlot` with
   three series (`requests`, `blocked`, `actions_executed`) plus a
   period-over-period numeric table comparing each headline metric to
   the prior equally-sized window. Empty data degrades to a styled
   "no trend data" paragraph.
4. **Exposure.** Two `HorizontalBarChart` charts: decisions
   (`allow` / `block` / `monitor` / ...) and direction
   (`ingress` / `egress`). Closes with the top blocking policy
   callout and its share of total blocks.
5. **Risk.** A severity `Pie` chart (`info` / `low` / `medium` /
   `high` / `critical`, with any unknown buckets aggregated into
   "other") and a Top Offenders table (subject_type, subject_id,
   deny_count, last_seen).
6. **Automation.** Mean time-to-action with delta vs prior period plus
   counters for events, playbooks fired, and actions executed. Bar
   chart of `actions_by_type`.
7. **Coverage and Compliance.** Authored-controls table
   (policies / playbooks total / enabled / live) and a per-tag
   compliance posture rollup (top 10 tags by matched events).
8. **Appendix.** Methodology paragraph, window-definitions table
   (24h / 7d / 30d / 90d with default bucket sizes), and the exact
   window timestamps and `generated_at` for the report.

### Period-over-period model

`export(window, fmt="pdf")` calls `summary(window=...)` twice:

- once for the current window,
- once with `now = current.window_start.timestamp() - 1.0` to compute
  the equally-sized prior window immediately before it.

It also calls `trends(window=...)` for the line chart. The three
payloads are passed to `generate_kpi_pdf(current, prior, trend, ...)`.
The KPI tile glyph and color map deterministically:

- `up + good` (e.g. block rate up) -> `up` glyph, green
- `up + bad` (e.g. critical findings up) -> `up` glyph, red
- `down + good` (e.g. MTTA down) -> `down` glyph, green
- `down + bad` (e.g. block rate down) -> `down` glyph, red
- `|delta| < 0.5%` -> `=` glyph, gray

Posture label rules:

- `degrading` if critical findings rose, or block rate fell by at
  least 2 percentage points.
- `improving` if block rate rose by at least 2 percentage points and
  critical findings did not rise.
- `stable` otherwise.

### Optional branding

`_resolve_branding()` in `executive_metrics.py` reads three optional
settings (all admin-controlled, none required):

- `APP_REPORT_BRANDING_COMPANY_NAME` (max 200 chars). When set, the
  cover renders a "Prepared for ..." line.
- `APP_REPORT_BRANDING_LOGO_PATH`. When set, the file is read and
  drawn above the company name.
- `APP_REPORT_BRANDING_LOGO_MAX_BYTES` (default 4 MiB, 1 KiB - 64 MiB
  range). The loader reads at most `max_bytes + 1` and discards the
  bytes if the cap is exceeded, so a misconfigured huge file cannot
  exhaust memory. Non-image bytes are also discarded after a failed
  `ImageReader.getSize()` call.

If the logo path is unreadable, oversized, or not a valid image, the
cover gracefully omits the brand block. The CSV variant
(`executive_csv_*`) is unchanged: only the PDF body was upgraded.

## Out of scope (deferred)

- Email / Slack / webhook delivery. The selected milestone option was
  "persist + list" only. Adding delivery later is an additive
  callback after `save_report` and does not change the API.
- Cron-string parsing or multiple custom schedules per kind. The
  weekly cadence is enough for "weekly reports" today; a future
  enhancement can swap the simple weekday/hour parser for a
  dependency like `croniter` without touching the schema.
- Per-tenant / per-customer report partitioning. The current store is
  single-tenant, matching the rest of Valo today.
