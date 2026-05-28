# Valo(TM) Conference Architecture

## Component Roles

- Engine: deterministic prompt-risk evaluation using fixed rule logic and scoring formulas.
- API: operational interface for `/analyze`, `/scan/report`, `/portfolio`, and `/ingest`.
- Ingestion: accepts external scanner outputs and canonicalizes them into `ScanResult` records.
- Portfolio Layer: aggregates scans into executive metrics (average risk, highest risk, severity distribution, category breakdown, trend).
- Dashboard: consumes portfolio summaries for near real-time risk visibility.
- PDF: generates executive artifacts for governance review and conference demonstrations.

## Why This Matters for Conference Audiences

- Transparent architecture: each control point is explicit and inspectable.
- Deterministic behavior: same input, same output, enabling reproducible demos.
- Governance-ready outputs: summary metrics and downloadable evidence artifacts.
