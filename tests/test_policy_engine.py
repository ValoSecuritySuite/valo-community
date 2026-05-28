"""Unit tests for the governance policy engine."""

import pytest

from app.schemas import (
    DetectionFlags,
    NormalizedInput,
    PipelineResult,
    Policy,
    PolicyAction,
    PolicyCondition,
    PolicyDecision,
    PolicySet,
    RuleMatch,
    TextFinding,
)
from app.services.policy_engine import (
    aggregate_decision,
    context_from_pipeline,
    evaluate_policies,
    evaluate_policy,
)


def _policy(
    policy_id: str,
    when: list[PolicyCondition],
    decision: str = "deny",
    severity: int = 5,
    enabled: bool = True,
    tags: list[str] | None = None,
) -> Policy:
    return Policy(
        id=policy_id,
        name=f"Test {policy_id}",
        enabled=enabled,
        when=when,
        then=PolicyAction(decision=decision, severity=severity, message=f"{policy_id} matched"),
        tags=tags or [],
    )


# ── Condition operators ──────────────────────────────────────────────────────


class TestConditionOps:
    def test_eq_matches(self) -> None:
        policy = _policy("eq", [PolicyCondition(field="a", op="eq", value=1)])
        assert evaluate_policy({"a": 1}, policy).matched is True
        assert evaluate_policy({"a": 2}, policy).matched is False

    def test_ne_matches(self) -> None:
        policy = _policy("ne", [PolicyCondition(field="a", op="ne", value=1)])
        assert evaluate_policy({"a": 2}, policy).matched is True
        assert evaluate_policy({"a": 1}, policy).matched is False

    def test_gte_lt_numeric(self) -> None:
        gte = _policy("gte", [PolicyCondition(field="score", op="gte", value=80)])
        assert evaluate_policy({"score": 80}, gte).matched is True
        assert evaluate_policy({"score": 79.9}, gte).matched is False

        lt = _policy("lt", [PolicyCondition(field="score", op="lt", value=10)])
        assert evaluate_policy({"score": 5}, lt).matched is True
        assert evaluate_policy({"score": 10}, lt).matched is False

    def test_in_membership(self) -> None:
        policy = _policy(
            "in",
            [PolicyCondition(field="role", op="in", value=["admin", "root"])],
        )
        assert evaluate_policy({"role": "admin"}, policy).matched is True
        assert evaluate_policy({"role": "viewer"}, policy).matched is False

    def test_not_in(self) -> None:
        policy = _policy(
            "not_in",
            [PolicyCondition(field="env", op="not_in", value=["prod"])],
        )
        assert evaluate_policy({"env": "dev"}, policy).matched is True
        assert evaluate_policy({"env": "prod"}, policy).matched is False

    def test_contains_substring(self) -> None:
        policy = _policy(
            "substring",
            [PolicyCondition(field="msg", op="contains", value="leak")],
        )
        assert evaluate_policy({"msg": "secret leak detected"}, policy).matched is True
        assert evaluate_policy({"msg": "all good"}, policy).matched is False

    def test_contains_list_membership(self) -> None:
        policy = _policy(
            "list",
            [PolicyCondition(field="ids", op="contains", value="x")],
        )
        assert evaluate_policy({"ids": ["a", "x", "y"]}, policy).matched is True
        assert evaluate_policy({"ids": ["a", "b"]}, policy).matched is False

    def test_matches_regex(self) -> None:
        policy = _policy(
            "regex",
            [PolicyCondition(field="ua", op="matches", value=r"curl/\d+")],
        )
        assert evaluate_policy({"ua": "curl/8.0"}, policy).matched is True
        assert evaluate_policy({"ua": "Mozilla"}, policy).matched is False

    def test_exists_and_not_exists(self) -> None:
        exists = _policy("exists", [PolicyCondition(field="t", op="exists")])
        assert evaluate_policy({"t": 0}, exists).matched is True
        assert evaluate_policy({}, exists).matched is False

        absent = _policy("absent", [PolicyCondition(field="t", op="not_exists")])
        assert evaluate_policy({}, absent).matched is True
        assert evaluate_policy({"t": 0}, absent).matched is False

    def test_dot_path(self) -> None:
        policy = _policy(
            "dot",
            [PolicyCondition(field="user.role", op="eq", value="admin")],
        )
        assert evaluate_policy({"user": {"role": "admin"}}, policy).matched is True
        assert evaluate_policy({"user": {"role": "viewer"}}, policy).matched is False


# ── AND semantics, disabled policies, empty-when ─────────────────────────────


class TestPolicySemantics:
    def test_and_semantics_all_must_match(self) -> None:
        policy = _policy(
            "and",
            [
                PolicyCondition(field="a", op="eq", value=1),
                PolicyCondition(field="b", op="eq", value=2),
            ],
        )
        assert evaluate_policy({"a": 1, "b": 2}, policy).matched is True
        assert evaluate_policy({"a": 1, "b": 3}, policy).matched is False

    def test_disabled_policy_skipped(self) -> None:
        policy = _policy(
            "off",
            [PolicyCondition(field="x", op="eq", value=1)],
            enabled=False,
        )
        decision = evaluate_policy({"x": 1}, policy)
        assert decision.matched is False
        assert decision.decision == "allow"
        assert "disabled" in decision.message.lower()

    def test_empty_when_matches_every_context(self) -> None:
        policy = _policy("blanket", when=[], decision="warn", severity=2)
        decision = evaluate_policy({}, policy)
        assert decision.matched is True
        assert decision.decision == "warn"

    def test_unmatched_policy_returns_allow(self) -> None:
        policy = _policy("nope", [PolicyCondition(field="a", op="eq", value=1)])
        decision = evaluate_policy({"a": 0}, policy)
        assert decision.matched is False
        assert decision.decision == "allow"
        assert decision.severity == 0

    def test_decision_carries_tags(self) -> None:
        policy = _policy(
            "tagged",
            [PolicyCondition(field="x", op="eq", value=1)],
            tags=["compliance:soc2", "pii"],
        )
        decision = evaluate_policy({"x": 1}, policy)
        assert decision.tags == ["compliance:soc2", "pii"]

    def test_reasons_record_outcomes(self) -> None:
        policy = _policy(
            "with-reasons",
            [
                PolicyCondition(field="a", op="eq", value=1),
                PolicyCondition(field="b", op="gt", value=10),
            ],
        )
        decision = evaluate_policy({"a": 1, "b": 12}, policy)
        assert len(decision.reasons) == 2
        assert any("a" in reason for reason in decision.reasons)
        assert any("b" in reason for reason in decision.reasons)


# ── Aggregation precedence ──────────────────────────────────────────────────


class TestAggregateDecision:
    def test_deny_beats_warn_and_allow(self) -> None:
        decisions = [
            PolicyDecision(
                policy_id="a",
                name="a",
                matched=True,
                decision="warn",
                severity=2,
                message="warn",
            ),
            PolicyDecision(
                policy_id="b",
                name="b",
                matched=True,
                decision="deny",
                severity=8,
                message="deny",
            ),
            PolicyDecision(
                policy_id="c",
                name="c",
                matched=True,
                decision="allow",
                severity=0,
                message="allow",
            ),
        ]
        assert aggregate_decision(decisions) == "deny"

    def test_warn_beats_allow(self) -> None:
        decisions = [
            PolicyDecision(
                policy_id="a",
                name="a",
                matched=True,
                decision="warn",
                severity=2,
                message="warn",
            ),
            PolicyDecision(
                policy_id="b",
                name="b",
                matched=True,
                decision="allow",
                severity=0,
                message="allow",
            ),
        ]
        assert aggregate_decision(decisions) == "warn"

    def test_unmatched_decisions_ignored(self) -> None:
        decisions = [
            PolicyDecision(
                policy_id="a",
                name="a",
                matched=False,
                decision="deny",
                severity=0,
                message="not matched",
            ),
        ]
        assert aggregate_decision(decisions) == "allow"

    def test_empty_decision_list(self) -> None:
        assert aggregate_decision([]) == "allow"


# ── PolicySet evaluate + context builder ────────────────────────────────────


def test_evaluate_policies_runs_each_in_order() -> None:
    policies = PolicySet(
        policies=[
            _policy("p1", [PolicyCondition(field="a", op="eq", value=1)], decision="warn", severity=2),
            _policy("p2", [PolicyCondition(field="b", op="gte", value=10)], decision="deny", severity=8),
        ]
    )
    decisions = evaluate_policies({"a": 1, "b": 11}, policies)
    assert [d.policy_id for d in decisions] == ["p1", "p2"]
    assert all(d.matched for d in decisions)
    assert aggregate_decision(decisions) == "deny"


def test_enforce_field_defaults_true_and_round_trips() -> None:
    """The new per-policy `enforce` flag defaults to True and accepts overrides."""
    default_policy = _policy("default-enforce", [PolicyCondition(field="x", op="eq", value=1)])
    assert default_policy.enforce is True

    soft_policy = Policy.model_validate(
        {
            "id": "soft",
            "name": "Soft",
            "when": [{"field": "x", "op": "eq", "value": 1}],
            "then": {"decision": "deny", "severity": 5, "message": "soft"},
            "enforce": False,
        }
    )
    assert soft_policy.enforce is False
    assert soft_policy.enabled is True


def test_policies_by_id_returns_lookup_map() -> None:
    """`policies_by_id` builds a fast {id: Policy} index used by enforcement."""
    from app.services.policy_engine import policies_by_id

    policy_a = _policy("a", [PolicyCondition(field="x", op="eq", value=1)])
    policy_b = _policy("b", [PolicyCondition(field="y", op="eq", value=2)])
    lookup = policies_by_id(PolicySet(policies=[policy_a, policy_b]))
    assert set(lookup) == {"a", "b"}
    assert lookup["a"] is policy_a


def test_context_from_pipeline_exposes_signals() -> None:
    norm = NormalizedInput(
        target="t",
        content="contact admin@example.com",
        input_kind="text",
        content_length=24,
    )
    detection = DetectionFlags(
        content_type="text",
        token_count=4,
        line_count=1,
        flags=["contains_email"],
    )
    result = PipelineResult(
        normalized=norm,
        detection=detection,
        matched_rules=[
            RuleMatch(rule_name="pii_signal", severity=3, weight=5.0, matched=True),
        ],
        context_score=10.0,
        passed_count=1,
        failed_count=0,
        text_findings=[
            TextFinding(
                rule_id="email_pattern",
                category="regex",
                severity=2,
                weight=4.0,
                evidence="admin@example.com",
            )
        ],
        text_scan_score=20.0,
        text_matched_count=1,
        combined_score=25.0,
    )

    context = context_from_pipeline(result, detection)
    assert context["combined_score"] == 25.0
    assert context["contains_email"] is True
    assert "pii_signal" in context["matched_rule_ids"]
    assert "email_pattern" in context["text_finding_rule_ids"]
    assert context["max_text_severity"] == 2
    assert context["detection"]["content_type"] == "text"
    assert context["normalized"]["target"] == "t"
