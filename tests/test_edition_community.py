"""Tests for Community Edition capability boundaries."""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def community_env(monkeypatch):
    monkeypatch.setenv("APP_EDITION", "community")
    monkeypatch.setenv("APP_ENFORCEMENT_MODE", "monitor")
    monkeypatch.setenv("APP_CORRELATION_ENGINE_ENABLED", "false")
    monkeypatch.setenv("APP_EXECUTIVE_METRICS_ENABLED", "false")
    monkeypatch.setenv("APP_REPORTS_ENABLED", "false")
    monkeypatch.setenv("APP_PLAYBOOKS_ENABLED", "false")
    monkeypatch.setenv("APP_LEARNING_LOOP_ENABLED", "false")


@pytest.fixture
def community_client(community_env):
    """Fresh app instance with community settings."""
    from importlib import reload

    import app.core.config as config_mod
    import app.main as main_mod

    reload(config_mod)
    reload(main_mod)
    with TestClient(main_mod.app) as client:
        yield client


def test_community_edition_meta(community_client):
    resp = community_client.get("/meta/edition")
    assert resp.status_code == 200
    body = resp.json()
    assert body["edition"] == "community"
    assert body["features"]["portfolio"] is False
    assert body["enforcement_mode"] == "monitor"


def test_community_has_no_portfolio_rollup(community_client):
    resp = community_client.post(
        "/portfolio/rollup",
        json={"scans": [{"target": "t", "prompt": "hello"}]},
    )
    assert resp.status_code == 404


def test_community_has_no_executive_routes(community_client):
    resp = community_client.get("/executive/summary")
    assert resp.status_code == 404


def test_community_enforce_mode_rejected_at_startup(monkeypatch):
    monkeypatch.setenv("APP_EDITION", "community")
    monkeypatch.setenv("APP_ENFORCEMENT_MODE", "enforce")

    from importlib import reload

    import app.core.config as config_mod

    with pytest.raises(ValueError, match="enforce is not allowed"):
        reload(config_mod)


def test_community_dashboard_data(community_client):
    community_client.post(
        "/analyze",
        json={"target": "dash-test", "prompt": "summarize this safely"},
    )
    resp = community_client.get("/dashboard/data")
    assert resp.status_code == 200
    body = resp.json()
    assert "executive_summary" in body
    assert body["executive_summary"]["total_scans"] >= 1
    assert "scans" in body


def test_community_analyze_works(community_client):
    resp = community_client.post(
        "/analyze",
        json={
            "target": "community-test",
            "prompt": "Summarize the release notes in three bullet points.",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "risk_score" in body or "report" in body
