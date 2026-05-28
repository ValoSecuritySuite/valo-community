"""End-to-end tests for the OpenAI-compatible LLM proxy endpoint."""

from contextlib import contextmanager
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import proxy as proxy_module
from app.core.config import settings
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
      message: blanket-deny used by proxy tests
    tags: [test:enforce]
    version: 1
    """
).strip()


_NO_OP_POLICY = dedent(
    """
    id: noop
    name: No-op policy (always allow)
    enabled: true
    enforce: true
    when:
      - field: combined_score
        op: gte
        value: 1000000
    then:
      decision: deny
      severity: 1
      message: never matches
    tags: []
    version: 1
    """
).strip()


_RESPONSE_BLOCK_POLICY = dedent(
    """
    id: block_secret_in_response
    name: Block secret completions
    enabled: true
    enforce: true
    when:
      - field: contains_secret_keyword
        op: eq
        value: true
    then:
      decision: deny
      severity: 9
      message: response carries secret keyword
    tags: [test:response]
    version: 1
    """
).strip()


_UPSTREAM_OK = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "created": 1700000000,
    "model": "gpt-4o-mini",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hello, world!"},
            "finish_reason": "stop",
        }
    ],
}


_UPSTREAM_WITH_SECRET = {
    **_UPSTREAM_OK,
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "Sure, your api_key is sk-leaked-1234.",
            },
            "finish_reason": "stop",
        }
    ],
}


@pytest.fixture(autouse=True)
def _isolated_policies_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "policies"
    target.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "policies_path", target)
    store.clear_policies_cache()
    yield target
    store.clear_policies_cache()


@pytest.fixture(autouse=True)
def _enforce_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "enforcement_mode", "enforce")
    monkeypatch.setattr(settings, "proxy_upstream_url", "https://api.openai.example/v1/chat/completions")


def _seed(target: Path, body: str, name: str) -> None:
    (target / f"{name}.yml").write_text(body)
    store.clear_policies_cache()


def _request_payload(content: str = "Hi there") -> dict:
    return {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": content}],
    }


@contextmanager
def _mock_upstream(handler):
    """Patch httpx.AsyncClient inside the proxy module to use MockTransport."""
    transport = httpx.MockTransport(handler)
    real_async_client = proxy_module.httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    with patch.object(proxy_module.httpx, "AsyncClient", side_effect=factory):
        yield


# ── Inbound (request-side) enforcement ──────────────────────────────────────


class TestInboundEnforcement:
    def test_deny_blocks_before_upstream_call(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
    ) -> None:
        _seed(_isolated_policies_dir, _BLOCK_HIGH_RISK, "block_high_risk")
        upstream_calls = {"count": 0}

        def handler(request):
            upstream_calls["count"] += 1
            return httpx.Response(200, json=_UPSTREAM_OK)

        with _mock_upstream(handler):
            response = client.post("/v1/proxy/chat/completions", json=_request_payload("anything"))

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PolicyDenied"
        assert response.json()["error"]["detail"]["side"] == "request"
        assert upstream_calls["count"] == 0

    def test_allow_forwards_and_returns_completion(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
    ) -> None:
        _seed(_isolated_policies_dir, _NO_OP_POLICY, "noop")
        upstream_calls = {"count": 0, "body": None}

        def handler(request):
            upstream_calls["count"] += 1
            upstream_calls["body"] = request.content
            return httpx.Response(200, json=_UPSTREAM_OK)

        with _mock_upstream(handler):
            response = client.post("/v1/proxy/chat/completions", json=_request_payload("Hello"))

        assert response.status_code == 200
        assert response.json()["choices"][0]["message"]["content"] == "Hello, world!"
        assert upstream_calls["count"] == 1
        assert response.headers["X-Valo-Policy-Decision"] == "allow"
        assert response.headers["X-Valo-Trace-Id"]
        assert response.headers["X-Valo-Inbound-Trace-Id"]


# ── Outbound (response-side) enforcement ────────────────────────────────────


class TestResponseSideEnforcement:
    def test_secret_in_completion_is_blocked(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
    ) -> None:
        _seed(_isolated_policies_dir, _RESPONSE_BLOCK_POLICY, "block_secret_in_response")

        def handler(request):
            return httpx.Response(200, json=_UPSTREAM_WITH_SECRET)

        with _mock_upstream(handler):
            response = client.post("/v1/proxy/chat/completions", json=_request_payload("benign question"))

        assert response.status_code == 403
        body = response.json()
        assert body["error"]["code"] == "PolicyDenied"
        assert body["error"]["detail"]["side"] == "response"


# ── Streaming (Phase 1: buffer-then-flush) ──────────────────────────────────


class TestStreaming:
    def test_stream_request_is_buffered_and_filtered(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
    ) -> None:
        _seed(_isolated_policies_dir, _NO_OP_POLICY, "noop")
        seen_bodies: list[bytes] = []

        def handler(request):
            seen_bodies.append(request.content)
            return httpx.Response(200, json=_UPSTREAM_OK)

        payload = _request_payload("hello")
        payload["stream"] = True

        with _mock_upstream(handler):
            response = client.post("/v1/proxy/chat/completions", json=payload)

        assert response.status_code == 200
        # Phase 1 disables upstream streaming so the proxy can scan the full body.
        assert b'"stream": false' in seen_bodies[0]
        assert response.json()["choices"][0]["message"]["content"] == "Hello, world!"


# ── Upstream errors are forwarded with Valo headers ─────────────────────────


class TestUpstreamErrors:
    def test_upstream_4xx_passes_through(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
    ) -> None:
        _seed(_isolated_policies_dir, _NO_OP_POLICY, "noop")

        def handler(request):
            return httpx.Response(400, json={"error": "bad model"})

        with _mock_upstream(handler):
            response = client.post("/v1/proxy/chat/completions", json=_request_payload())

        assert response.status_code == 400
        assert response.json() == {"error": "bad model"}
        assert response.headers["X-Valo-Upstream-Status"] == "400"

    def test_upstream_network_error_returns_503ish_envelope(
        self,
        client: TestClient,
        _isolated_policies_dir: Path,
    ) -> None:
        _seed(_isolated_policies_dir, _NO_OP_POLICY, "noop")

        def handler(request):
            raise httpx.ConnectError("connection refused")

        with _mock_upstream(handler):
            response = client.post("/v1/proxy/chat/completions", json=_request_payload())

        assert response.status_code == 500
        body = response.json()
        assert body["error"]["code"] == "ServiceError"
        assert "trace_id" in body["error"]["detail"]
