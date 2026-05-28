"""OpenAI-compatible LLM proxy endpoint with inline policy filtering.

Customers point their existing OpenAI client at Valo (``OPENAI_BASE_URL``)
and every prompt + completion is policed by the governance policy engine
*before* it leaves the network. This is the egress half of the AI Firewall.

Response-side scanning is buffered for Phase 1: streaming requests are
served by collecting the full upstream response, evaluating it against the
policy engine, and returning either a single non-streamed response or a
``403 PolicyDenied`` envelope. True token-level filtering is tracked for
Phase 2.
"""

from typing import Any

import httpx
from fastapi import APIRouter, Request

from app.api._rate_limits import rate_limit_for
from app.core.config import settings
from app.core.exceptions import PolicyDeniedException, ServiceError
from app.core.limiter import limiter
from app.core.logging import get_logger
from app.schemas import (
    ChatCompletionRequest,
    EnforcementOutcome,
)
from app.services.policy_enforcement import (
    evaluate_text_for_enforcement,
    log_enforcement_outcome,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/proxy", tags=["proxy"])

PROXY_ROUTE_PATH = "/v1/proxy/chat/completions"

_HOP_BY_HOP_REQUEST_HEADERS = {
    "host",
    "content-length",
    "connection",
    "keep-alive",
    "proxy-authorization",
    "proxy-authenticate",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

_HOP_BY_HOP_RESPONSE_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-encoding",
    "content-length",
}


def _concatenate_messages(payload: ChatCompletionRequest) -> str:
    """Flatten ``messages[].content`` into a single string for policy scanning."""
    parts: list[str] = []
    for message in payload.messages:
        if message.content:
            parts.append(f"{message.role}: {message.content}")
    return "\n".join(parts)


def _extract_completion_text(upstream_payload: dict[str, Any]) -> str:
    """Pull every ``choices[].message.content`` for response-side scanning."""
    choices = upstream_payload.get("choices") or []
    parts: list[str] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content:
            parts.append(content)
    return "\n".join(parts)


def _forward_headers(request: Request) -> dict[str, str]:
    forwarded: dict[str, str] = {}
    for key, value in request.headers.items():
        if key.lower() in _HOP_BY_HOP_REQUEST_HEADERS:
            continue
        forwarded[key] = value
    forwarded.setdefault("Accept", "application/json")
    forwarded["Content-Type"] = "application/json"
    return forwarded


def _decision_response_headers(outcome: EnforcementOutcome) -> dict[str, str]:
    headers = {
        "X-Valo-Policy-Decision": outcome.final_decision,
        "X-Valo-Trace-Id": outcome.trace_id,
        "X-Valo-Enforcement-Mode": outcome.mode,
    }
    if outcome.matched_policy_ids:
        headers["X-Valo-Matched-Policies"] = ",".join(outcome.matched_policy_ids)
    return headers


def _block_detail(outcome: EnforcementOutcome, side: str) -> dict[str, Any]:
    return {
        "trace_id": outcome.trace_id,
        "side": side,
        "final_decision": outcome.final_decision,
        "matched_policy_ids": outcome.matched_policy_ids,
        "decisions": [decision.model_dump() for decision in outcome.decisions if decision.matched],
    }


@router.post("/chat/completions")
@limiter.limit(rate_limit_for("POST", PROXY_ROUTE_PATH))
async def proxy_chat_completions(request: Request, payload: ChatCompletionRequest) -> Any:
    """OpenAI-compatible chat.completions proxy with two-sided policy filtering."""

    inbound_text = _concatenate_messages(payload)
    inbound_outcome = evaluate_text_for_enforcement(
        inbound_text,
        target="proxy:chat-completions:request",
    )
    log_enforcement_outcome(
        inbound_outcome,
        route=PROXY_ROUTE_PATH,
        direction="ingress",
    )

    if inbound_outcome.blocked:
        raise PolicyDeniedException(
            message="Inbound prompt blocked by Valo governance policy.",
            detail=_block_detail(inbound_outcome, side="request"),
        )

    forward_body = payload.model_dump(mode="json", exclude_none=True)
    forward_body["stream"] = False
    forward_headers = _forward_headers(request)

    try:
        async with httpx.AsyncClient(timeout=settings.proxy_request_timeout_seconds) as client:
            upstream_response = await client.post(
                settings.proxy_upstream_url,
                json=forward_body,
                headers=forward_headers,
            )
    except httpx.HTTPError as exc:
        logger.error(
            "proxy_upstream_error trace_id=%s url=%s",
            inbound_outcome.trace_id,
            settings.proxy_upstream_url,
            exc_info=True,
        )
        raise ServiceError(
            message="Upstream LLM provider unavailable",
            detail={
                "trace_id": inbound_outcome.trace_id,
                "upstream_url": settings.proxy_upstream_url,
                "error": str(exc),
            },
        ) from exc

    if upstream_response.status_code >= 400:
        return _passthrough_error(upstream_response, inbound_outcome)

    try:
        upstream_payload: dict[str, Any] = upstream_response.json()
    except ValueError as exc:
        raise ServiceError(
            message="Upstream returned a non-JSON success response",
            detail={"trace_id": inbound_outcome.trace_id, "error": str(exc)},
        ) from exc

    completion_text = _extract_completion_text(upstream_payload)
    response_outcome = evaluate_text_for_enforcement(
        completion_text or " ",
        target="proxy:chat-completions:response",
    )
    log_enforcement_outcome(
        response_outcome,
        route=PROXY_ROUTE_PATH,
        direction="egress",
    )

    if response_outcome.blocked:
        raise PolicyDeniedException(
            message="Upstream completion blocked by Valo governance policy.",
            detail=_block_detail(response_outcome, side="response"),
        )

    headers = _decision_response_headers(response_outcome)
    headers["X-Valo-Inbound-Trace-Id"] = inbound_outcome.trace_id
    return _build_json_response(upstream_payload, headers, status_code=upstream_response.status_code)


def _passthrough_error(
    upstream_response: "httpx.Response",
    inbound_outcome: EnforcementOutcome,
) -> Any:
    """Forward upstream 4xx/5xx bodies verbatim with Valo headers attached."""
    from fastapi.responses import Response as FastAPIResponse

    headers = _decision_response_headers(inbound_outcome)
    headers["X-Valo-Inbound-Trace-Id"] = inbound_outcome.trace_id
    headers["X-Valo-Upstream-Status"] = str(upstream_response.status_code)
    return FastAPIResponse(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=headers,
        media_type=upstream_response.headers.get("content-type", "application/json"),
    )


def _build_json_response(
    body: dict[str, Any],
    headers: dict[str, str],
    status_code: int = 200,
) -> Any:
    from fastapi.responses import JSONResponse

    return JSONResponse(content=body, status_code=status_code, headers=headers)


__all__ = ["router", "PROXY_ROUTE_PATH"]
