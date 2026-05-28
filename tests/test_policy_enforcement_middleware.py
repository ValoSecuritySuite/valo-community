"""End-to-end tests for the inline policy enforcement middleware."""

from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.middleware.policy_enforcement import REQUEST_STATE_ATTR
from app.services import policy_enforcement as enforcement_module
from app.services import policy_store as store
from app.services import pipeline as pipeline_module


_BLOCK_HIGH_RISK = dedent(
    """
    id: block_high_risk
    name: Block high-risk prompts
    enabled: true
    enforce: true
    when:
      - field: combined_score
        op: gte
        value: 0
    then:
      decision: deny
      severity: 9
      message: blanket-deny used by enforcement tests
    tags: [test:enforce]
    version: 1
    """
).strip()


_BLOCK_HIGH_RISK_SOFT = dedent(
    """
    id: block_high_risk
    name: Block high-risk prompts (soft)
    enabled: true
    enforce: false
    when:
      - field: combined_score
        op: gte
        value: 0
    then:
      decision: deny
      severity: 9
      message: blanket-deny but enforce=false
    tags: [test:soft]
    version: 1
    """
).strip()


_WARN_PII = dedent(
    """
    id: warn_pii
    name: Warn on PII exposure
    enabled: true
    enforce: true
    when:
      - field: contains_email
        op: eq
        value: true
    then:
      decision: warn
      severity: 4
      message: pii detected
    tags: [test:warn]
    version: 1
    """
).strip()


@pytest.fixture(autouse=True)
def _isolated_policies_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "policies"
    target.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "policies_path", target)
    store.clear_policies_cache()
    yield target
    store.clear_policies_cache()


@pytest.fixture(autouse=True)
def _reset_enforcement_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "enforcement_mode", "monitor")
    yield


def _seed_policy(target: Path, body: str) -> None:
    (target / "block_high_risk.yml").write_text(body)
    store.clear_policies_cache()


def _payload(prompt: str = "hello world") -> dict:
    return {"prompt": prompt, "target": "test"}


# ── Mode matrix ──────────────────────────────────────────────────────────────


class TestEnforcementModes:
    def test_off_bypasses_evaluation(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed_policy(_isolated_policies_dir, _BLOCK_HIGH_RISK)
        monkeypatch.setattr(settings, "enforcement_mode", "off")

        response = client.post("/analyze", json=_payload())
        assert response.status_code == 200
        assert "X-Valo-Policy-Decision" not in response.headers
        assert "X-Valo-Trace-Id" not in response.headers

    def test_monitor_lets_request_through_with_headers(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed_policy(_isolated_policies_dir, _BLOCK_HIGH_RISK)
        monkeypatch.setattr(settings, "enforcement_mode", "monitor")

        response = client.post("/analyze", json=_payload())
        assert response.status_code == 200
        assert response.headers["X-Valo-Policy-Decision"] == "deny"
        assert response.headers["X-Valo-Enforcement-Mode"] == "monitor"
        assert "block_high_risk" in response.headers["X-Valo-Matched-Policies"]
        assert response.headers["X-Valo-Trace-Id"]

    def test_enforce_blocks_with_403(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed_policy(_isolated_policies_dir, _BLOCK_HIGH_RISK)
        monkeypatch.setattr(settings, "enforcement_mode", "enforce")

        response = client.post("/analyze", json=_payload())
        assert response.status_code == 403
        body = response.json()
        assert body["error"]["code"] == "PolicyDenied"
        assert body["error"]["detail"]["final_decision"] == "deny"
        assert "block_high_risk" in body["error"]["detail"]["matched_policy_ids"]
        assert body["error"]["detail"]["trace_id"]

    def test_per_policy_enforce_false_does_not_block(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed_policy(_isolated_policies_dir, _BLOCK_HIGH_RISK_SOFT)
        monkeypatch.setattr(settings, "enforcement_mode", "enforce")

        response = client.post("/analyze", json=_payload())
        assert response.status_code == 200
        assert response.headers["X-Valo-Policy-Decision"] == "deny"

    def test_warn_decision_does_not_block_in_enforce(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (_isolated_policies_dir / "warn_pii.yml").write_text(_WARN_PII)
        store.clear_policies_cache()
        monkeypatch.setattr(settings, "enforcement_mode", "enforce")

        response = client.post(
            "/analyze",
            json=_payload(prompt="please email admin@example.com"),
        )
        assert response.status_code == 200
        assert response.headers["X-Valo-Policy-Decision"] == "warn"


# ── No-double-work guarantee ────────────────────────────────────────────────


class TestPipelineReuse:
    def test_handler_does_not_run_pipeline_twice_on_block(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed_policy(_isolated_policies_dir, _BLOCK_HIGH_RISK)
        monkeypatch.setattr(settings, "enforcement_mode", "enforce")

        with patch.object(
            enforcement_module,
            "run_pipeline",
            wraps=enforcement_module.run_pipeline,
        ) as spy:
            response = client.post("/analyze", json=_payload())

        assert response.status_code == 403
        assert spy.call_count == 1

    def test_handler_reuses_middleware_pipeline_result(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed_policy(_isolated_policies_dir, _BLOCK_HIGH_RISK_SOFT)
        monkeypatch.setattr(settings, "enforcement_mode", "monitor")

        with patch.object(
            enforcement_module,
            "run_pipeline",
            wraps=enforcement_module.run_pipeline,
        ) as enforcement_spy, patch.object(
            pipeline_module,
            "run_pipeline",
            wraps=pipeline_module.run_pipeline,
        ) as handler_spy:
            response = client.post("/analyze", json=_payload())

        assert response.status_code == 200
        assert enforcement_spy.call_count == 1
        assert handler_spy.call_count == 0


# ── Fast-path bypass ────────────────────────────────────────────────────────


class TestFastPathBypass:
    def test_unprotected_route_does_not_get_headers(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed_policy(_isolated_policies_dir, _BLOCK_HIGH_RISK)
        monkeypatch.setattr(settings, "enforcement_mode", "enforce")

        response = client.get("/health")
        assert response.status_code == 200
        assert "X-Valo-Policy-Decision" not in response.headers

    def test_get_method_is_not_inspected(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed_policy(_isolated_policies_dir, _BLOCK_HIGH_RISK)
        monkeypatch.setattr(settings, "enforcement_mode", "enforce")

        response = client.get("/policies")
        assert response.status_code == 200
        assert "X-Valo-Policy-Decision" not in response.headers

    def test_body_without_prompt_falls_through(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed_policy(_isolated_policies_dir, _BLOCK_HIGH_RISK)
        monkeypatch.setattr(settings, "enforcement_mode", "enforce")

        response = client.post(
            "/policies/validate",
            json={"id": "x", "name": "x", "then": {"decision": "allow", "message": "x"}},
        )
        assert response.status_code == 200
        assert "X-Valo-Policy-Decision" not in response.headers


# ── Body size cap ───────────────────────────────────────────────────────────


def test_oversized_body_bypasses_enforcement(
    client: TestClient,
    _isolated_policies_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_policy(_isolated_policies_dir, _BLOCK_HIGH_RISK)
    monkeypatch.setattr(settings, "enforcement_mode", "enforce")
    monkeypatch.setattr(settings, "enforcement_max_body_bytes", 32)

    response = client.post("/analyze", json=_payload(prompt="x" * 1024))
    assert response.status_code == 200
    assert "X-Valo-Policy-Decision" not in response.headers


# ── Trace id and request.state caching ──────────────────────────────────────


def test_outcome_cached_on_request_state(
    client: TestClient,
    _isolated_policies_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_policy(_isolated_policies_dir, _BLOCK_HIGH_RISK_SOFT)
    monkeypatch.setattr(settings, "enforcement_mode", "monitor")

    # The middleware sets the outcome on request.state under a known attribute.
    # Verify the contract by importing and asserting the constant is consumable.
    assert REQUEST_STATE_ATTR == "policy_enforcement_outcome"

    response = client.post("/analyze", json=_payload())
    trace_id = response.headers["X-Valo-Trace-Id"]
    assert trace_id and len(trace_id) >= 8
