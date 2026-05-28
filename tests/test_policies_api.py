"""End-to-end tests for the /policies/* governance API."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import policy_store as store


@pytest.fixture(autouse=True)
def _isolated_policies_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "policies"
    monkeypatch.setattr(settings, "policies_path", target)
    store.clear_policies_cache()
    yield target
    store.clear_policies_cache()


def _policy_payload(
    policy_id: str = "p1",
    decision: str = "deny",
    field: str = "combined_score",
    op: str = "gte",
    value: int = 80,
    enabled: bool = True,
) -> dict:
    return {
        "id": policy_id,
        "name": f"Policy {policy_id}",
        "description": "test",
        "enabled": enabled,
        "when": [{"field": field, "op": op, "value": value}],
        "then": {"decision": decision, "severity": 7, "message": "match"},
        "tags": ["test"],
        "version": 1,
    }


# ── CRUD ─────────────────────────────────────────────────────────────────────


class TestPoliciesCrud:
    def test_list_empty(self, client: TestClient) -> None:
        response = client.get("/policies")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 0
        assert body["policies"] == []
        assert body["fingerprints"] == {}

    def test_create_returns_201_and_persists(self, client: TestClient) -> None:
        response = client.post("/policies", json=_policy_payload("created"))
        assert response.status_code == 201
        assert response.json()["id"] == "created"

        listing = client.get("/policies").json()
        assert listing["total"] == 1
        assert listing["policies"][0]["id"] == "created"
        assert "created" in listing["fingerprints"]

    def test_create_duplicate_returns_409(self, client: TestClient) -> None:
        assert client.post("/policies", json=_policy_payload("dup")).status_code == 201
        response = client.post("/policies", json=_policy_payload("dup"))
        assert response.status_code == 409

    def test_get_one_returns_policy(self, client: TestClient) -> None:
        client.post("/policies", json=_policy_payload("one"))
        response = client.get("/policies/one")
        assert response.status_code == 200
        assert response.json()["id"] == "one"

    def test_get_one_404(self, client: TestClient) -> None:
        assert client.get("/policies/missing").status_code == 404

    def test_put_updates_existing(self, client: TestClient) -> None:
        client.post("/policies", json=_policy_payload("upd", decision="warn"))
        updated = _policy_payload("upd", decision="deny")
        response = client.put("/policies/upd", json=updated)
        assert response.status_code == 200
        assert response.json()["then"]["decision"] == "deny"

    def test_put_404_when_missing(self, client: TestClient) -> None:
        response = client.put("/policies/ghost", json=_policy_payload("ghost"))
        assert response.status_code == 404

    def test_put_id_mismatch_422(self, client: TestClient) -> None:
        client.post("/policies", json=_policy_payload("real"))
        response = client.put("/policies/real", json=_policy_payload("other"))
        assert response.status_code == 422

    def test_delete_204_then_404(self, client: TestClient) -> None:
        client.post("/policies", json=_policy_payload("kill"))
        assert client.delete("/policies/kill").status_code == 204
        assert client.get("/policies/kill").status_code == 404
        assert client.delete("/policies/kill").status_code == 404


# ── /policies/validate ──────────────────────────────────────────────────────


class TestPoliciesValidate:
    def test_validate_accepts_well_formed(self, client: TestClient) -> None:
        response = client.post("/policies/validate", json=_policy_payload("ok"))
        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is True
        assert body["policy"]["id"] == "ok"
        assert body["errors"] == []

    def test_validate_rejects_bad_id(self, client: TestClient) -> None:
        bad = _policy_payload("ok")
        bad["id"] = "with spaces!"
        response = client.post("/policies/validate", json=bad)
        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is False
        assert body["errors"]
        assert body["policy"] is None

    def test_validate_does_not_persist(self, client: TestClient) -> None:
        client.post("/policies/validate", json=_policy_payload("phantom"))
        assert client.get("/policies/phantom").status_code == 404


# ── /policies/evaluate ──────────────────────────────────────────────────────


class TestPoliciesEvaluate:
    def test_evaluate_returns_decisions_and_final(self, client: TestClient) -> None:
        client.post("/policies", json=_policy_payload("hi", decision="deny", value=80))
        client.post(
            "/policies",
            json=_policy_payload("warn", decision="warn", field="contains_email", op="eq", value=True),
        )

        response = client.post(
            "/policies/evaluate",
            json={"context": {"combined_score": 90, "contains_email": True}},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["final_decision"] == "deny"
        assert {d["policy_id"] for d in body["decisions"]} == {"hi", "warn"}
        assert all(d["matched"] for d in body["decisions"])

    def test_evaluate_allows_when_nothing_matches(self, client: TestClient) -> None:
        client.post("/policies", json=_policy_payload("hi", decision="deny", value=80))
        response = client.post(
            "/policies/evaluate",
            json={"context": {"combined_score": 5}},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["final_decision"] == "allow"
        assert body["decisions"][0]["matched"] is False


# ── /policies/reload ────────────────────────────────────────────────────────


class TestPoliciesReload:
    def test_reload_reports_added_changed_removed(
        self, client: TestClient, _isolated_policies_dir: Path
    ) -> None:
        import yaml

        # Initial state on disk and primed in cache via the API
        client.post("/policies", json=_policy_payload("stable", decision="warn"))
        client.post("/policies", json=_policy_payload("doomed", decision="warn"))
        # Prime the cache so reload has a meaningful "before" snapshot.
        store.load_policies(use_cache=True)

        # Out-of-band disk edits (no cache invalidation): change `stable`,
        # delete `doomed`, add `fresh`.
        stable_payload = _policy_payload("stable", decision="deny")
        (_isolated_policies_dir / "stable.yml").write_text(
            yaml.safe_dump(stable_payload, sort_keys=True), encoding="utf-8"
        )
        (_isolated_policies_dir / "doomed.yml").unlink()
        fresh_payload = _policy_payload("fresh", decision="warn")
        (_isolated_policies_dir / "fresh.yml").write_text(
            yaml.safe_dump(fresh_payload, sort_keys=True), encoding="utf-8"
        )

        response = client.post("/policies/reload")
        assert response.status_code == 200
        body = response.json()
        diff = body["diff"]
        assert "fresh" in diff["added"]
        assert "doomed" in diff["removed"]
        assert "stable" in diff["changed"]
        assert body["policies_path"].endswith("policies")
