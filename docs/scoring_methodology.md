# Valo™ Scoring Methodology (Day 1 Locked)

## Purpose
This document defines the locked deterministic risk scoring model for Valo.

## Design Constraints
- Deterministic scoring only
- No randomness, no sampling, no probabilistic modifiers
- Same input must always produce the same score
- Final score range is 0–100 with a hard cap at 100

## Base Severity Weights
| Severity | Level | Weight |
|---|---|---:|
| 5 | Critical | 80 |
| 4 | High | 60 |
| 3 | Medium | 40 |
| 2 | Low | 20 |
| 1 | Info | 10 |

## Score Components
For each scan result:
1. Determine base severity from highest-severity confirmed match.
2. Add breadth bonus based on number of distinct rule families matched.
3. Add repetition bonus based on total matched trigger count.
4. Enforce hard cap at 100.

### Component A: Base Severity Score
- Critical => 80
- High => 60
- Medium => 40
- Low => 20
- Info => 10
- No confirmed match => 0

### Component B: Breadth Bonus (Max +15)
Breadth reflects attack surface variety (distinct detection rule families hit).

Deterministic mapping:
- 1 family => +0
- 2 families => +5
- 3 families => +10
- 4+ families => +15

Detection families counted for breadth:
1. `instruction_override`
2. `role_confusion`
3. `system_prompt_extraction`
4. `tool_misuse`
5. `encoded_payload`
6. `data_exfiltration`

Rules without an explicit family do not contribute to the breadth bonus.

### Component C: Repetition Bonus (Max +10)
Repetition reflects persistence/intensity across matched triggers.

Deterministic tiered mapping:
- 1 total trigger => +0
- 2–3 triggers => +3
- 4–6 triggers => +6
- 7–9 triggers => +8
- 10+ triggers => +10

## Final Score Formula
Final score is:

`risk_score = min(100, base_severity_score + breadth_bonus + repetition_bonus)`

## No-Finding Fallback
When no text-scan rules fire but context rules produce a score:

`risk_score = min(100, context_score × 0.5)`

## Determinism Requirements (Mandatory)
- No random number generation in scoring path
- No time-based variation
- No user/session-based hidden modifiers
- All thresholds and mappings are static and versioned

## Tie/Conflict Rules
- If multiple severities are present, choose the maximum severity for base score.
- Bonuses are additive and capped independently.
- If no valid rule match is confirmed, score is 0.

## Reference Pseudocode
```text
if no_matches:
    return min(100, context_score * 0.5)

base = severity_weight(max_severity)
breadth = breadth_bonus(distinct_families_count)   # capped at 15
repetition = repetition_bonus(total_trigger_count)  # capped at 10

return min(100, base + breadth + repetition)
```
