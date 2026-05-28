"""Governance Policy Engine.

Evaluates :class:`Policy` definitions against a flattened context dictionary
(typically derived from the rule-engine pipeline output) and aggregates the
resulting :class:`PolicyDecision` list into a single ``allow / warn / deny``
verdict using strict precedence: ``deny > warn > allow``.

The engine is intentionally side-effect free and deterministic so it can be
used both inside the pipeline and from the standalone ``/policies/evaluate``
endpoint.
"""

import re
from typing import Any, Iterable

from app.schemas import (
    DetectionFlags,
    PipelineResult,
    Policy,
    PolicyCondition,
    PolicyDecision,
    PolicyDecisionLiteral,
    PolicySet,
)

_DECISION_RANK: dict[str, int] = {"allow": 0, "warn": 1, "deny": 2}


def _get_nested(context: dict[str, Any], field_path: str) -> Any:
    """Walk a dot-separated path through nested dicts, returning ``None`` on miss."""
    parts = field_path.split(".")
    value: Any = context
    for part in parts:
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return None
    return value


def _evaluate_condition(context: dict[str, Any], condition: PolicyCondition) -> bool:
    """Return ``True`` when *condition* holds against *context*."""
    actual = _get_nested(context, condition.field)
    expected = condition.value
    op = condition.op

    if op == "exists":
        return actual is not None
    if op == "not_exists":
        return actual is None

    if actual is None:
        return False

    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op == "in":
        return expected is not None and actual in expected
    if op == "not_in":
        return expected is None or actual not in expected
    if op == "contains":
        # Membership against list/tuple/set, otherwise substring.
        if isinstance(actual, (list, tuple, set)):
            return expected in actual
        if expected is None:
            return False
        return str(expected) in str(actual)
    if op == "matches":
        if expected is None:
            return False
        try:
            return bool(re.search(str(expected), str(actual)))
        except re.error:
            return False

    try:
        actual_num = float(actual)
        expected_num = float(expected) if expected is not None else 0.0
    except (TypeError, ValueError):
        return False

    if op == "gt":
        return actual_num > expected_num
    if op == "gte":
        return actual_num >= expected_num
    if op == "lt":
        return actual_num < expected_num
    if op == "lte":
        return actual_num <= expected_num

    return False


def _condition_reason(context: dict[str, Any], condition: PolicyCondition, matched: bool) -> str:
    """Human-readable trace string describing one condition outcome."""
    actual = _get_nested(context, condition.field)
    status = "matched" if matched else "did not match"
    if condition.op in {"exists", "not_exists"}:
        return f"{condition.field} {condition.op} ({status})"
    return (
        f"{condition.field} {condition.op} {condition.value!r} "
        f"(actual={actual!r}, {status})"
    )


def evaluate_policy(context: dict[str, Any], policy: Policy) -> PolicyDecision:
    """Evaluate one policy against *context* and return its :class:`PolicyDecision`.

    Disabled policies always return an ``allow`` decision with ``matched=False``.
    Policies with an empty ``when`` list match every context (useful for
    blanket-deny configurations).
    """
    if not policy.enabled:
        return PolicyDecision(
            policy_id=policy.id,
            name=policy.name,
            matched=False,
            decision="allow",
            severity=0,
            message=f"Policy '{policy.id}' is disabled",
            reasons=[],
            tags=list(policy.tags),
        )

    if not policy.when:
        all_matched = True
        reasons = ["no conditions defined: matches every context"]
    else:
        results = [(cond, _evaluate_condition(context, cond)) for cond in policy.when]
        all_matched = all(matched for _, matched in results)
        reasons = [_condition_reason(context, cond, matched) for cond, matched in results]

    decision: PolicyDecisionLiteral = policy.then.decision if all_matched else "allow"
    severity = policy.then.severity if all_matched else 0
    message = policy.then.message if all_matched else f"Policy '{policy.id}' did not match"

    return PolicyDecision(
        policy_id=policy.id,
        name=policy.name,
        matched=all_matched,
        decision=decision,
        severity=severity,
        message=message,
        reasons=reasons,
        tags=list(policy.tags),
    )


def evaluate_policies(context: dict[str, Any], policy_set: PolicySet) -> list[PolicyDecision]:
    """Evaluate every policy in *policy_set* and return the per-policy decisions."""
    return [evaluate_policy(context, policy) for policy in policy_set.policies]


def aggregate_decision(decisions: Iterable[PolicyDecision]) -> PolicyDecisionLiteral:
    """Reduce a list of decisions to a single verdict using ``deny > warn > allow``."""
    final: PolicyDecisionLiteral = "allow"
    final_rank = _DECISION_RANK["allow"]
    for decision in decisions:
        if not decision.matched:
            continue
        rank = _DECISION_RANK.get(decision.decision, 0)
        if rank > final_rank:
            final = decision.decision
            final_rank = rank
    return final


def policies_by_id(policy_set: PolicySet) -> dict[str, Policy]:
    """Return a ``{policy_id: Policy}`` map for fast lookup during enforcement.

    The enforcement layer needs the original ``Policy`` (for the per-policy
    ``enforce`` flag) when interpreting a ``PolicyDecision``. Building this
    once per request avoids O(N) scans inside the middleware hot path.
    """
    return {policy.id: policy for policy in policy_set.policies}


def context_from_pipeline(result: PipelineResult, detection: DetectionFlags) -> dict[str, Any]:
    """Build the flat context dict policies evaluate against.

    Surfaces commonly-referenced fields at the top level (``combined_score``,
    ``matched_rule_ids``, ``contains_email``, ...) and also keeps grouped
    sub-objects (``detection``, ``normalized``) for advanced rules that prefer
    explicit dot paths.
    """
    matched_rule_ids = sorted({m.rule_name for m in result.matched_rules if m.matched})
    text_finding_rule_ids = sorted({f.rule_id for f in result.text_findings})
    matched_text_rule_ids = sorted({d.rule_id for d in result.matched_rule_details})

    context: dict[str, Any] = {
        # Aggregate scores
        "context_score": result.context_score,
        "text_scan_score": result.text_scan_score,
        "combined_score": result.combined_score,
        # Counts
        "matched_count": result.passed_count,
        "passed_count": result.passed_count,
        "failed_count": result.failed_count,
        "text_matched_count": result.text_matched_count,
        # Convenience lists for `contains` membership checks
        "matched_rule_ids": matched_rule_ids,
        "matched_text_rule_ids": matched_text_rule_ids,
        "text_finding_rule_ids": text_finding_rule_ids,
        # Severity surfacing
        "max_text_severity": max((f.severity for f in result.text_findings), default=0),
        # Detection flags lifted to the top level for ergonomic policies
        "content_type": detection.content_type,
        "detected_language": detection.detected_language,
        "token_count": detection.token_count,
        "line_count": detection.line_count,
        "detection_flags": list(detection.flags),
        # Normalized input shape
        "target": result.normalized.target,
        "input_kind": result.normalized.input_kind,
        "content_length": result.normalized.content_length,
        # Grouped sub-objects for explicit dot paths
        "detection": detection.model_dump(),
        "normalized": result.normalized.model_dump(),
        # Each detection flag also exposed as a boolean for ergonomic equality
        # checks, e.g. field: contains_email, op: eq, value: true
        **{flag: True for flag in detection.flags},
    }
    return context
