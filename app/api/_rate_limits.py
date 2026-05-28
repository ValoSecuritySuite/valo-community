"""Shared per-endpoint rate-limit registry.

Lifted out of ``app.api.routes`` so additional routers (e.g. the governance
``/policies/*`` router) can reuse the same lookup and runtime-update plumbing
without circular imports.
"""

from app.core.config import settings
from app.schemas import EndpointRateLimit

ENDPOINT_RATE_LIMIT_ORDER: list[tuple[str, str]] = [
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
    ("GET", "/report/pdf/rollup"),
    ("GET", "/report/pdf/scan/{scan_id}"),
    ("POST", "/portfolio/rollup"),
    ("GET", "/portfolio"),
    ("POST", "/portfolio"),
    ("POST", "/ingest"),
    ("POST", "/ingest/normalize"),
    ("GET", "/dashboard/data"),
    ("GET", "/settings"),
    ("PATCH", "/settings"),
    ("POST", "/v1/proxy/chat/completions"),
    ("GET", "/enforcement/events"),
    ("GET", "/enforcement/stats"),
    ("GET", "/enforcement/config"),
    ("PATCH", "/enforcement/config"),
    ("POST", "/enforcement/simulate"),
    ("GET", "/playbooks"),
    ("POST", "/playbooks"),
    ("GET", "/playbooks/{playbook_id}"),
    ("PUT", "/playbooks/{playbook_id}"),
    ("DELETE", "/playbooks/{playbook_id}"),
    ("POST", "/playbooks/validate"),
    ("POST", "/playbooks/evaluate"),
    ("POST", "/playbooks/events"),
    ("POST", "/playbooks/reload"),
    ("GET", "/playbooks/traces"),
    ("GET", "/outcomes"),
    ("GET", "/outcomes/stats"),
    ("POST", "/outcomes/{trace_id}/label"),
    ("POST", "/outcomes/ingest"),
    ("GET", "/learning/proposals"),
    ("GET", "/learning/proposals/{proposal_id}"),
    ("POST", "/learning/proposals/{proposal_id}/accept"),
    ("POST", "/learning/proposals/{proposal_id}/reject"),
    ("POST", "/learning/refresh"),
    ("GET", "/executive/summary"),
    ("GET", "/executive/trends"),
    ("GET", "/executive/export"),
    ("GET", "/reports"),
    ("GET", "/reports/kinds"),
    ("GET", "/reports/scheduler"),
    ("GET", "/reports/{report_id}"),
    ("GET", "/reports/{report_id}/download"),
    ("POST", "/reports/generate"),
    ("POST", "/reports/scheduler/run"),
    ("DELETE", "/reports/{report_id}"),
]

ENDPOINT_RATE_LIMIT_MAP: dict[tuple[str, str], str] = {
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
    ("GET", "/report/pdf/rollup"): "20/minute",
    ("GET", "/report/pdf/scan/{scan_id}"): "20/minute",
    ("POST", "/portfolio/rollup"): "20/minute",
    ("GET", "/portfolio"): "60/minute",
    ("POST", "/portfolio"): "30/minute",
    ("POST", "/ingest"): "30/minute",
    ("POST", "/ingest/normalize"): "30/minute",
    ("GET", "/dashboard/data"): "60/minute",
    ("GET", "/settings"): "30/minute",
    ("PATCH", "/settings"): "10/minute",
    ("POST", "/v1/proxy/chat/completions"): "20/minute",
    ("GET", "/enforcement/events"): "120/minute",
    ("GET", "/enforcement/stats"): "120/minute",
    ("GET", "/enforcement/config"): "60/minute",
    ("PATCH", "/enforcement/config"): "20/minute",
    ("POST", "/enforcement/simulate"): "60/minute",
    ("GET", "/playbooks"): "100/minute",
    ("POST", "/playbooks"): "30/minute",
    ("GET", "/playbooks/{playbook_id}"): "100/minute",
    ("PUT", "/playbooks/{playbook_id}"): "30/minute",
    ("DELETE", "/playbooks/{playbook_id}"): "30/minute",
    ("POST", "/playbooks/validate"): "60/minute",
    ("POST", "/playbooks/evaluate"): "60/minute",
    ("POST", "/playbooks/events"): "120/minute",
    ("POST", "/playbooks/reload"): "10/minute",
    ("GET", "/playbooks/traces"): "120/minute",
    ("GET", "/outcomes"): "120/minute",
    ("GET", "/outcomes/stats"): "60/minute",
    ("POST", "/outcomes/{trace_id}/label"): "60/minute",
    ("POST", "/outcomes/ingest"): "120/minute",
    ("GET", "/learning/proposals"): "60/minute",
    ("GET", "/learning/proposals/{proposal_id}"): "60/minute",
    ("POST", "/learning/proposals/{proposal_id}/accept"): "20/minute",
    ("POST", "/learning/proposals/{proposal_id}/reject"): "20/minute",
    ("POST", "/learning/refresh"): "10/minute",
    ("GET", "/executive/summary"): "60/minute",
    ("GET", "/executive/trends"): "60/minute",
    ("GET", "/executive/export"): "10/minute",
    ("GET", "/reports"): "60/minute",
    ("GET", "/reports/kinds"): "60/minute",
    ("GET", "/reports/scheduler"): "60/minute",
    ("GET", "/reports/{report_id}"): "60/minute",
    ("GET", "/reports/{report_id}/download"): "30/minute",
    ("POST", "/reports/generate"): "10/minute",
    ("POST", "/reports/scheduler/run"): "10/minute",
    ("DELETE", "/reports/{report_id}"): "20/minute",
}


def rate_limit_for(method: str, path: str):
    """Return a slowapi resolver that defers lookup until call time.

    This indirection lets PATCH /settings update the rate-limit map at runtime
    while still applying the new value on the next request.
    """
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
