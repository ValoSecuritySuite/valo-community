"""Inline policy enforcement middleware (AI Firewall ingress layer).

Runs the existing scan pipeline + policy engine *before* the route handler is
invoked for a configurable allowlist of POST endpoints. When the global mode
is ``enforce`` and at least one matched ``deny`` policy carries
``enforce=True``, the request is short-circuited with HTTP 403 and the
handler is never called. In ``monitor`` mode the same evaluation runs but the
request always passes through with advisory headers + an audit-log entry.

The computed :class:`EnforcementOutcome` is cached on ``request.state`` so
handlers that need the same result (``/analyze``, ``/scan/report``,
``/report/pdf``) can reuse it via ``get_or_run_pipeline`` instead of running
the pipeline a second time.
"""

from __future__ import annotations

import json
from typing import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas import EnforcementOutcome, PipelineRequest
from app.services.policy_enforcement import (
    evaluate_request_for_enforcement,
    log_enforcement_outcome,
)

logger = get_logger(__name__)

REQUEST_STATE_ATTR = "policy_enforcement_outcome"

_DENY_HEADER = "X-Valo-Policy-Decision"
_TRACE_HEADER = "X-Valo-Trace-Id"
_MATCHED_HEADER = "X-Valo-Matched-Policies"
_MODE_HEADER = "X-Valo-Enforcement-Mode"


class PolicyEnforcementMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces governance policies at the HTTP edge."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not self._should_inspect(request):
            return await call_next(request)

        body = await self._buffer_body(request)
        if body is None:
            return await call_next(request)

        payload = self._parse_payload(body)
        if payload is None:
            return await call_next(request)

        try:
            outcome = evaluate_request_for_enforcement(payload)
        except Exception:
            logger.exception("policy_enforcement_pipeline_error path=%s", request.url.path)
            return await call_next(request)

        setattr(request.state, REQUEST_STATE_ATTR, outcome)
        log_enforcement_outcome(outcome, route=request.url.path, direction="ingress")

        if outcome.blocked:
            return _block_response(outcome)

        response = await call_next(request)
        _attach_decision_headers(response, outcome)
        return response

    def _should_inspect(self, request: Request) -> bool:
        if settings.enforcement_mode == "off":
            return False
        if request.method.upper() != "POST":
            return False
        path = request.url.path
        return any(path == route or path.startswith(route + "/") for route in settings.enforcement_protected_routes)

    async def _buffer_body(self, request: Request) -> bytes | None:
        """Read the body once and rewind it for the downstream handler.

        Starlette caches ``await request.body()`` on the request object, so a
        subsequent ``await request.body()`` (or ``request.json()``) inside the
        handler will return the same bytes without re-reading the receive
        stream.
        """
        body = await request.body()
        max_bytes = settings.enforcement_max_body_bytes
        if len(body) > max_bytes:
            logger.warning(
                "policy_enforcement_body_too_large path=%s bytes=%d cap=%d",
                request.url.path,
                len(body),
                max_bytes,
            )
            return None
        return body

    def _parse_payload(self, body: bytes) -> PipelineRequest | None:
        if not body:
            return None
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        prompt_value = data.get("prompt") or data.get("text")
        if not isinstance(prompt_value, str) or not prompt_value:
            return None
        try:
            return PipelineRequest.model_validate(
                {
                    "prompt": prompt_value,
                    "target": data.get("target", "prompt") or "prompt",
                }
            )
        except ValidationError:
            return None


def _outcome_detail(outcome: EnforcementOutcome) -> dict:
    return {
        "trace_id": outcome.trace_id,
        "final_decision": outcome.final_decision,
        "matched_policy_ids": outcome.matched_policy_ids,
        "decisions": [decision.model_dump() for decision in outcome.decisions if decision.matched],
    }


def _attach_decision_headers(response: Response, outcome: EnforcementOutcome) -> None:
    response.headers[_DENY_HEADER] = outcome.final_decision
    response.headers[_TRACE_HEADER] = outcome.trace_id
    response.headers[_MODE_HEADER] = outcome.mode
    if outcome.matched_policy_ids:
        response.headers[_MATCHED_HEADER] = ",".join(outcome.matched_policy_ids)


def _block_response(outcome: EnforcementOutcome) -> JSONResponse:
    """Build the 403 PolicyDenied envelope and surface decision headers.

    ``BaseHTTPMiddleware`` does not propagate raised exceptions through the
    FastAPI exception-handler chain, so the middleware returns the structured
    ``AppException`` envelope directly to keep the contract identical to the
    rest of the API.
    """
    body = {
        "error": {
            "code": "PolicyDenied",
            "message": "Request blocked by Valo governance policy.",
            "detail": _outcome_detail(outcome),
        }
    }
    response = JSONResponse(status_code=403, content=body)
    _attach_decision_headers(response, outcome)
    return response


__all__ = ["PolicyEnforcementMiddleware", "REQUEST_STATE_ATTR"]
