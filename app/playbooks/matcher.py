"""Condition evaluator for playbook triggers.

Mirrors :mod:`app.services.policy_engine` semantics so YAML written for one
engine is portable to the other. Implemented locally (not imported) to
avoid coupling the playbook layer to the policy layer's runtime.
"""

from __future__ import annotations

import re
from typing import Any, List, Tuple

from app.playbooks.schemas import Playbook, PlaybookCondition


def _get_nested(context: dict, field_path: str) -> Any:
    """Walk a dot-separated path through nested dicts; return ``None`` on miss."""
    parts = field_path.split(".")
    value: Any = context
    for part in parts:
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return None
    return value


def evaluate_condition(context: dict, condition: PlaybookCondition) -> bool:
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


def _condition_reason(context: dict, condition: PlaybookCondition, matched: bool) -> str:
    actual = _get_nested(context, condition.field)
    status = "matched" if matched else "did not match"
    if condition.op in {"exists", "not_exists"}:
        return f"{condition.field} {condition.op} ({status})"
    return (
        f"{condition.field} {condition.op} {condition.value!r} "
        f"(actual={actual!r}, {status})"
    )


def matches_playbook(context: dict, playbook: Playbook) -> Tuple[bool, List[str]]:
    """Return ``(all_matched, reasons)`` for one playbook against *context*.

    An empty ``when`` list matches every event (catch-all playbooks).
    Disabled playbooks return ``(False, [...])`` with an explicit reason so
    the trace shows why nothing fired.
    """
    if not playbook.enabled:
        return False, [f"playbook '{playbook.id}' disabled"]
    reasons: List[str] = []
    if not playbook.when:
        return True, ["no conditions: catch-all match"]
    all_matched = True
    for condition in playbook.when:
        ok = evaluate_condition(context, condition)
        reasons.append(_condition_reason(context, condition, ok))
        if not ok:
            all_matched = False
    return all_matched, reasons


__all__ = ["evaluate_condition", "matches_playbook"]
