# Valo(TM) Scoring Whitepaper (Short)

## Executive Summary

Valo uses a deterministic scoring model for AI prompt-risk assessment. The objective is governance-grade reproducibility: identical inputs under identical rules always produce identical risk outputs.

## 1) Deterministic Model

The scoring path contains no randomization, no sampling, and no hidden user/session multipliers.

- Rule matching is exact and static.
- Severity mapping is fixed.
- Bonus mappings are fixed and capped.
- Final score is mathematically bounded.

This guarantees conference demonstrations and production runs are consistent.

## 2) Weighted Categories

Risk scoring combines three weighted components:

1. Base severity weight: derived from highest confirmed severity.
2. Breadth bonus: number of distinct matched risk families.
3. Repetition bonus: repeated trigger intensity.

The families are aligned to governance-relevant prompt abuse classes, including instruction override, system prompt extraction, tool misuse, and data exfiltration.

## 3) Hard Cap at 100

Final risk is constrained by:

`risk_score = min(100, base + breadth + repetition)`

The hard cap keeps outputs stable for executive interpretation and prevents inflation from noisy repeated matches.

## 4) Reproducibility and Auditability

Valo is designed for repeatable security evidence:

- Same prompt + same rules -> same matched findings and score.
- Output can be revalidated with archived request bodies.
- Portfolio summaries are deterministic aggregations of scan records.

This supports governance workflows, audit conversations, and OWASP-positioned control narratives.
