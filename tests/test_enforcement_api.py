"""Tests for the GET/PATCH /enforcement/* admin and observability endpoints.

These tests exercise the public contract used by the new AI Firewall UI:

- GET /enforcement/events    (filtering, pagination, ring-buffer eviction)
- GET /enforcement/stats     (aggregation, decision counts, top policies)
- GET /enforcement/config    (settings snapshot)
- PATCH /enforcement/config  (mode + proxy URL updates with validation)
- POST /enforcement/simulate (firewall playground dry-run)
"""

from pathlib import Path
from textwrap import dedent

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import enforcement_events
from app.services import policy_store as store


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
      message: blanket-deny used by enforcement-api tests
    tags: [test:enforce]
    version: 1
    """
).strip()


_WARN_PII = dedent(
    """
    id: warn_pii
    name: Warn on PII
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
def _reset_enforcement_state(monkeypatch: pytest.MonkeyPatch):
    """Snapshot and restore mutable enforcement settings + the events buffer."""
    original_mode = settings.enforcement_mode
    original_url = settings.proxy_upstream_url
    original_timeout = settings.proxy_request_timeout_seconds
    original_max = settings.enforcement_max_body_bytes
    original_routes = list(settings.enforcement_protected_routes)
    enforcement_events.clear_events()
    monkeypatch.setattr(settings, "enforcement_mode", "monitor")
    yield
    settings.enforcement_mode = original_mode
    settings.proxy_upstream_url = original_url
    settings.proxy_request_timeout_seconds = original_timeout
    settings.enforcement_max_body_bytes = original_max
    settings.enforcement_protected_routes = original_routes
    enforcement_events.clear_events()


def _seed_policy(target: Path, body: str, name: str = "block_high_risk.yml") -> None:
    (target / name).write_text(body)
    store.clear_policies_cache()


def _trigger_event(client: TestClient, prompt: str = "trigger event") -> str:
    """Drive one /analyze through the middleware and return its trace_id."""
    response = client.post("/analyze", json={"prompt": prompt, "target": "events-test"})
    assert response.status_code in (200, 403)
    return response.headers.get("X-Valo-Trace-Id", "")


# ── /enforcement/events ─────────────────────────────────────────────────────


class TestEventsEndpoint:
    def test_events_recorded_after_analyze(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
    ) -> None:
        _seed_policy(_isolated_policies_dir, _BLOCK_HIGH_RISK)
        trace_id = _trigger_event(client)
        assert trace_id

        response = client.get("/enforcement/events")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1
        assert body["returned"] >= 1
        assert body["capacity"] >= 1
        first = body["events"][0]
        assert first["trace_id"] == trace_id
        assert first["route"] == "/analyze"
        assert first["direction"] == "ingress"
        assert first["final_decision"] == "deny"
        assert "block_high_risk" in first["matched_policy_ids"]

    def test_events_filter_by_decision(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
    ) -> None:
        _seed_policy(_isolated_policies_dir, _BLOCK_HIGH_RISK)
        _trigger_event(client, prompt="aaa")
        _trigger_event(client, prompt="bbb")

        denies = client.get("/enforcement/events", params={"decision": "deny"}).json()
        allows = client.get("/enforcement/events", params={"decision": "allow"}).json()
        assert denies["total"] >= 2
        assert all(e["final_decision"] == "deny" for e in denies["events"])
        assert allows["total"] == 0

    def test_events_filter_by_trace_id(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
    ) -> None:
        _seed_policy(_isolated_policies_dir, _BLOCK_HIGH_RISK)
        trace_id = _trigger_event(client)
        _trigger_event(client, prompt="another")

        scoped = client.get("/enforcement/events", params={"trace_id": trace_id}).json()
        assert scoped["total"] == 1
        assert scoped["events"][0]["trace_id"] == trace_id

    def test_events_pagination(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
    ) -> None:
        _seed_policy(_isolated_policies_dir, _BLOCK_HIGH_RISK)
        for i in range(5):
            _trigger_event(client, prompt=f"trigger {i}")

        page = client.get("/enforcement/events", params={"limit": 2, "offset": 1}).json()
        assert page["returned"] == 2
        assert page["total"] >= 5

    def test_events_ring_buffer_eviction(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed_policy(_isolated_policies_dir, _BLOCK_HIGH_RISK)
        monkeypatch.setattr(settings, "enforcement_event_buffer_capacity", 10)
        enforcement_events.clear_events()

        for i in range(15):
            _trigger_event(client, prompt=f"trigger {i}")

        body = client.get("/enforcement/events", params={"limit": 100}).json()
        assert body["total"] == 10
        assert body["capacity"] == 10


# ── /enforcement/stats ──────────────────────────────────────────────────────


class TestStatsEndpoint:
    def test_stats_counts_decisions_and_top_policies(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
    ) -> None:
        _seed_policy(_isolated_policies_dir, _BLOCK_HIGH_RISK)
        for _ in range(3):
            _trigger_event(client)

        response = client.get("/enforcement/stats")
        assert response.status_code == 200
        body = response.json()
        assert body["total_events"] >= 3
        assert body["by_decision"]["deny"] >= 3
        assert body["would_block"] >= 3
        assert body["top_policies"]
        assert body["top_policies"][0]["policy_id"] == "block_high_risk"
        assert body["top_routes"]
        assert any(r["route"] == "/analyze" for r in body["top_routes"])
        assert 0.0 <= body["block_rate"] <= 1.0

    def test_stats_window_filter(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
    ) -> None:
        _seed_policy(_isolated_policies_dir, _BLOCK_HIGH_RISK)
        _trigger_event(client)

        all_window = client.get("/enforcement/stats", params={"window_seconds": 0}).json()
        narrow = client.get("/enforcement/stats", params={"window_seconds": 60}).json()
        assert all_window["total_events"] >= 1
        assert narrow["window_seconds"] == 60


# ── /enforcement/config ─────────────────────────────────────────────────────


class TestConfigEndpoint:
    def test_get_config_returns_current_settings(self, client: TestClient) -> None:
        response = client.get("/enforcement/config")
        assert response.status_code == 200
        body = response.json()
        assert body["enforcement_mode"] in ("off", "monitor", "enforce")
        assert body["proxy_upstream_url"]
        assert body["enforcement_max_body_bytes"] > 0
        assert body["event_buffer_capacity"] >= 1

    def test_patch_config_rejects_enforce_mode_in_community(self, client: TestClient) -> None:
        response = client.patch(
            "/enforcement/config",
            json={"enforcement_mode": "enforce"},
        )
        assert response.status_code == 403
        detail = response.json()["detail"]
        assert detail["code"] == "feature_unavailable"

    def test_patch_config_updates_mode_to_off(self, client: TestClient) -> None:
        response = client.patch(
            "/enforcement/config",
            json={"enforcement_mode": "off"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["enforcement_mode"] == "off"
        assert settings.enforcement_mode == "off"

    def test_patch_config_updates_proxy_url_and_timeout(self, client: TestClient) -> None:
        response = client.patch(
            "/enforcement/config",
            json={
                "proxy_upstream_url": "https://example.invalid/v1/chat/completions",
                "proxy_request_timeout_seconds": 12.5,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["proxy_upstream_url"] == "https://example.invalid/v1/chat/completions"
        assert body["proxy_request_timeout_seconds"] == pytest.approx(12.5)

    def test_patch_config_rejects_unknown_fields(self, client: TestClient) -> None:
        response = client.patch("/enforcement/config", json={"bogus": "value"})
        assert response.status_code == 422

    def test_patch_config_rejects_invalid_mode(self, client: TestClient) -> None:
        response = client.patch(
            "/enforcement/config",
            json={"enforcement_mode": "panic"},
        )
        assert response.status_code == 422

    def test_patch_config_rejects_route_without_slash(self, client: TestClient) -> None:
        response = client.patch(
            "/enforcement/config",
            json={"enforcement_protected_routes": ["analyze"]},
        )
        assert response.status_code == 422


# ── /enforcement/simulate ───────────────────────────────────────────────────


class TestSimulateEndpoint:
    def test_simulate_returns_decisions_and_headers(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
    ) -> None:
        _seed_policy(_isolated_policies_dir, _BLOCK_HIGH_RISK)

        response = client.post(
            "/enforcement/simulate",
            json={"prompt": "anything goes", "mode": "enforce"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["outcome"]["final_decision"] == "deny"
        assert body["outcome"]["blocked"] is True
        assert body["outcome"]["mode"] == "enforce"
        assert body["headers"]["X-Valo-Policy-Decision"] == "deny"
        assert body["headers"]["X-Valo-Enforcement-Mode"] == "enforce"
        assert body["headers"]["X-Valo-Trace-Id"]
        assert "block_high_risk" in body["headers"]["X-Valo-Matched-Policies"]
        assert body["block_envelope"]["error"]["code"] == "PolicyDenied"
        assert body["block_envelope"]["error"]["detail"]["simulated"] is True

    def test_simulate_does_not_persist_event(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
    ) -> None:
        _seed_policy(_isolated_policies_dir, _BLOCK_HIGH_RISK)
        enforcement_events.clear_events()

        response = client.post(
            "/enforcement/simulate",
            json={"prompt": "anything goes"},
        )
        assert response.status_code == 200
        assert enforcement_events.buffer_used() == 0

    def test_simulate_rejects_empty_prompt(self, client: TestClient) -> None:
        response = client.post("/enforcement/simulate", json={"prompt": "   "})
        assert response.status_code == 422

    def test_simulate_warn_does_not_block(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
    ) -> None:
        _seed_policy(_isolated_policies_dir, _WARN_PII, name="warn_pii.yml")

        response = client.post(
            "/enforcement/simulate",
            json={
                "prompt": "contact me at user@example.com please",
                "mode": "enforce",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["outcome"]["final_decision"] == "warn"
        assert body["outcome"]["blocked"] is False
        assert body["block_envelope"] is None
