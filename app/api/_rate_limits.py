"""Shared per-endpoint rate-limit registry for Community Edition routes."""

from app.core.config import settings
from app.schemas import EndpointRateLimit

ENDPOINT_RATE_LIMIT_ORDER: list[tuple[str, str]] = [
    ("GET", "/meta/edition"),
    ("GET", "/health"),
    ("GET", "/health/ready"),
    ("POST", "/analyze"),
    ("GET", "/rules"),
    ("POST", "/rules/evaluate"),
    ("POST", "/rules/reload"),
    ("GET", "/policies"),
    ("POST", "/policies"),
    ("GET", "/policies/{policy_id}"),
    ("PUT", "/policies/{policy_id}"),
    ("DELETE", "/policies/{policy_id}"),
    ("POST", "/policies/validate"),
    ("POST", "/policies/evaluate"),
    ("POST", "/policies/reload"),
    ("POST", "/scan/report"),
    ("POST", "/report/pdf"),
    ("GET", "/report/pdf/scan/{scan_id}"),
    ("GET", "/dashboard/data"),
    ("GET", "/settings"),
    ("PATCH", "/settings"),
    ("POST", "/v1/proxy/chat/completions"),
    ("GET", "/enforcement/events"),
    ("GET", "/enforcement/stats"),
    ("GET", "/enforcement/config"),
    ("PATCH", "/enforcement/config"),
    ("POST", "/enforcement/simulate"),
]

ENDPOINT_RATE_LIMIT_MAP: dict[tuple[str, str], str] = {
    ("GET", "/meta/edition"): "60/minute",
    ("GET", "/health"): "60/minute",
    ("GET", "/health/ready"): "60/minute",
    ("POST", "/analyze"): "60/minute",
    ("GET", "/rules"): "100/minute",
    ("POST", "/rules/evaluate"): "60/minute",
    ("POST", "/rules/reload"): "10/minute",
    ("GET", "/policies"): "100/minute",
    ("POST", "/policies"): "30/minute",
    ("GET", "/policies/{policy_id}"): "100/minute",
    ("PUT", "/policies/{policy_id}"): "30/minute",
    ("DELETE", "/policies/{policy_id}"): "30/minute",
    ("POST", "/policies/validate"): "60/minute",
    ("POST", "/policies/evaluate"): "60/minute",
    ("POST", "/policies/reload"): "10/minute",
    ("POST", "/scan/report"): "60/minute",
    ("POST", "/report/pdf"): "20/minute",
    ("GET", "/report/pdf/scan/{scan_id}"): "20/minute",
    ("GET", "/dashboard/data"): "60/minute",
    ("GET", "/settings"): "30/minute",
    ("PATCH", "/settings"): "10/minute",
    ("POST", "/v1/proxy/chat/completions"): "20/minute",
    ("GET", "/enforcement/events"): "120/minute",
    ("GET", "/enforcement/stats"): "120/minute",
    ("GET", "/enforcement/config"): "60/minute",
    ("PATCH", "/enforcement/config"): "20/minute",
    ("POST", "/enforcement/simulate"): "60/minute",
}


def rate_limit_for(method: str, path: str):
    """Return a slowapi resolver that defers lookup until call time."""
    key = (method.upper(), path)

    def _resolver(*_args, **_kwargs):
        return ENDPOINT_RATE_LIMIT_MAP.get(key, settings.rate_limit)

    return _resolver


def endpoint_rate_limits_payload() -> list[EndpointRateLimit]:
    """Render the rate limit table in stable order for /settings responses."""
    return [
        EndpointRateLimit(
            method=method,
            path=path,
            limit=ENDPOINT_RATE_LIMIT_MAP[(method, path)],
        )
        for method, path in ENDPOINT_RATE_LIMIT_ORDER
    ]
