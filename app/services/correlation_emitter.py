"""Background emitter that ships prompt-class signals to the Correlation Engine.

The Correlation Engine accepts a single wire format
(``IngestSignalEnvelope``). Every Valo enforcement outcome is converted
into one of those envelopes here, in Valo, before it leaves the process.
The engine has no Valo-specific code; replacing Valo with any other
prompt-class scanner only requires that other scanner to produce the same
envelope.

The emitter is intentionally fire-and-forget: it never raises into the
request path and any failure is logged so the AI Firewall stays available
even when the engine is down.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas import EnforcementDirection, EnforcementOutcome

logger = get_logger(__name__)


_HMAC_SOURCE_HEADER = "X-Valo-Source"
_HMAC_TIMESTAMP_HEADER = "X-Valo-Timestamp"
_HMAC_SIGNATURE_HEADER = "X-Valo-Signature"

_SOURCE_SLUG = "valo"
_CATEGORY = "prompt"
_TIMEOUT_SECONDS = 5.0


def _is_enabled() -> bool:
    return bool(
        settings.correlation_engine_enabled
        and settings.correlation_engine_url
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _build_entities(
    outcome: EnforcementOutcome,
    *,
    prompt_fingerprint: Optional[str],
    tenant_id: Optional[str],
) -> List[Dict[str, Any]]:
    entities: List[Dict[str, Any]] = []

    if prompt_fingerprint:
        entities.append(
            {
                "entity_type": "prompt_fingerprint",
                "canonical_key": f"prompt:{prompt_fingerprint}",
                "display_name": f"prompt:{prompt_fingerprint[:12]}",
                "attributes": {
                    "final_decision": outcome.final_decision,
                    "blocked": outcome.blocked,
                    "would_block": outcome.would_block,
                    "matched_policy_count": len(outcome.matched_policy_ids or []),
                },
                "confidence": 1.0,
                "role": "observed",
                "tenant_id": tenant_id,
            }
        )

    if tenant_id:
        entities.append(
            {
                "entity_type": "tenant",
                "canonical_key": f"tenant:{tenant_id}",
                "display_name": tenant_id,
                "attributes": {},
                "confidence": 1.0,
                "role": "acted_as",
                "tenant_id": tenant_id,
            }
        )

    # Heuristic: if the policy engine matched a known-secret policy, surface
    # the secret as a referenced entity so the engine can correlate it with
    # any code-class scanner that already saw the same key. Valo only exposes
    # the policy IDs (not the raw secrets), so we hash the policy ID as a
    # proxy. Code-class scanners use the same hash scheme, which is what
    # makes the join possible.
    for policy_id in outcome.matched_policy_ids or []:
        if "secret" in policy_id.lower():
            entities.append(
                {
                    "entity_type": "secret",
                    "canonical_key": f"secret:policy:{_sha256(policy_id)[:32]}",
                    "display_name": f"matched-policy:{policy_id}",
                    "attributes": {"matched_policy_id": policy_id, "observed_in": "prompt"},
                    "confidence": 0.6,
                    "role": "matched",
                    "tenant_id": tenant_id,
                }
            )

    return entities


def _severity_from_outcome(outcome: EnforcementOutcome) -> str:
    if outcome.blocked:
        return "high"
    if outcome.would_block:
        return "medium"
    if outcome.matched_policy_ids:
        return "low"
    return "info"


def _build_envelope(
    outcome: EnforcementOutcome,
    *,
    route: str,
    direction: EnforcementDirection,
    prompt_fingerprint: Optional[str],
    tenant_id: Optional[str],
) -> Dict[str, Any]:
    return {
        "source": _SOURCE_SLUG,
        "category": _CATEGORY,
        "source_scan_id": outcome.trace_id,
        "source_job_id": outcome.trace_id,
        "tenant_id": tenant_id,
        "severity": _severity_from_outcome(outcome),
        "risk_score": float(outcome.combined_score) if outcome.combined_score is not None else None,
        "summary": (
            f"Valo {direction} on {route}: {outcome.final_decision} "
            f"({len(outcome.matched_policy_ids or [])} policies matched)"
        )[:2048],
        "entities": _build_entities(
            outcome,
            prompt_fingerprint=prompt_fingerprint,
            tenant_id=tenant_id,
        ),
        "raw_payload": {
            "trace_id": outcome.trace_id,
            "final_decision": outcome.final_decision,
            "blocked": outcome.blocked,
            "would_block": outcome.would_block,
            "matched_policy_ids": outcome.matched_policy_ids,
            "combined_score": outcome.combined_score,
            "max_severity_found": outcome.max_severity_found,
            "route": route,
            "direction": direction,
        },
    }


def _sign_headers(body: bytes) -> Dict[str, str]:
    if not settings.correlation_engine_secret:
        return {"Content-Type": "application/json"}
    timestamp = str(int(time.time()))
    base = f"{timestamp}.".encode("utf-8") + body
    signature = hmac.new(
        settings.correlation_engine_secret.encode("utf-8"), base, hashlib.sha256
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        _HMAC_SOURCE_HEADER: _SOURCE_SLUG,
        _HMAC_TIMESTAMP_HEADER: timestamp,
        _HMAC_SIGNATURE_HEADER: signature,
    }


def _emit_sync(envelope: Dict[str, Any]) -> None:
    if not _is_enabled():
        return
    body = json.dumps(envelope, separators=(",", ":"), default=str).encode("utf-8")
    headers = _sign_headers(body)
    url = settings.correlation_engine_url.rstrip("/") + "/ingest"
    try:
        with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
            response = client.post(url, content=body, headers=headers)
        if response.status_code >= 400:
            logger.warning(
                "correlation_emit_failed status=%d url=%s body=%s",
                response.status_code,
                url,
                response.text[:512],
            )
    except Exception as exc:
        logger.warning("correlation_emit_error url=%s err=%s", url, exc)


def emit_outcome(
    outcome: EnforcementOutcome,
    *,
    route: str,
    direction: EnforcementDirection,
    prompt_fingerprint: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> None:
    """Schedule a one-shot POST of a prompt-class envelope to the engine.

    The work happens on a background thread so the request path is never
    blocked by the engine's response time.
    """
    if not _is_enabled():
        return
    envelope = _build_envelope(
        outcome,
        route=route,
        direction=direction,
        prompt_fingerprint=prompt_fingerprint,
        tenant_id=tenant_id,
    )

    def _runner() -> None:
        try:
            _emit_sync(envelope)
        except Exception:
            logger.exception(
                "correlation_emit_thread_failed trace_id=%s", outcome.trace_id
            )

    threading.Thread(target=_runner, name="correlation-emit", daemon=True).start()


__all__ = ["emit_outcome"]
