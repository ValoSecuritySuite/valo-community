"""Tests for POST /rules/evaluate (ad-hoc context rule evaluation)."""

from fastapi.testclient import TestClient


def test_rules_evaluate_returns_200_and_score(client: TestClient) -> None:
    response = client.post(
        "/rules/evaluate",
        json={"context": {"contains_email": True, "content_length": 50}},
    )
    assert response.status_code == 200
    body = response.json()
    assert "matched_rules" in body
    assert "total_score" in body
    assert "passed_count" in body
    assert "failed_count" in body
    assert 0.0 <= body["total_score"] <= 100.0


def test_rules_evaluate_pii_signal_matches(client: TestClient) -> None:
    """The seeded pii_signal context rule fires when contains_email is true."""
    response = client.post(
        "/rules/evaluate",
        json={"context": {"contains_email": True}},
    )
    body = response.json()
    matched = [m["rule_name"] for m in body["matched_rules"] if m["matched"]]
    assert "pii_signal" in matched


def test_rules_evaluate_secret_signal_matches(client: TestClient) -> None:
    response = client.post(
        "/rules/evaluate",
        json={"context": {"contains_secret_keyword": True}},
    )
    body = response.json()
    matched = [m["rule_name"] for m in body["matched_rules"] if m["matched"]]
    assert "secret_signal" in matched


def test_rules_evaluate_oversize_prompt_matches(client: TestClient) -> None:
    response = client.post(
        "/rules/evaluate",
        json={"context": {"content_length": 25000}},
    )
    body = response.json()
    matched = [m["rule_name"] for m in body["matched_rules"] if m["matched"]]
    assert "oversize_prompt" in matched


def test_rules_evaluate_empty_context_matches_nothing(client: TestClient) -> None:
    response = client.post("/rules/evaluate", json={"context": {}})
    body = response.json()
    assert body["passed_count"] == 0
    assert body["total_score"] == 0.0


def test_rules_evaluate_rejects_non_dict_context(client: TestClient) -> None:
    response = client.post("/rules/evaluate", json={"context": "not-a-dict"})
    assert response.status_code == 422


def test_rules_evaluate_deterministic_repeat(client: TestClient) -> None:
    payload = {"context": {"contains_email": True, "content_length": 50}}
    first = client.post("/rules/evaluate", json=payload).json()
    second = client.post("/rules/evaluate", json=payload).json()
    assert first == second
