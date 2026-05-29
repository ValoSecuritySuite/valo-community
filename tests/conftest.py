"""Shared pytest configuration."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client

_ENTERPRISE_ONLY_KEYWORDS = (
    "portfolio",
    "ingest",
    "rollup_pdf",
    "dashboard_data",
    "executive",
    "reports",
    "playbooks",
    "learning",
    "outcomes",
)


def pytest_collection_modifyitems(config, items):
    if settings.edition != "community":
        return
    skip = pytest.mark.skip(reason="not available in Community Edition")
    for item in items:
        nodeid = item.nodeid.lower()
        if any(keyword in nodeid for keyword in _ENTERPRISE_ONLY_KEYWORDS):
            item.add_marker(skip)
