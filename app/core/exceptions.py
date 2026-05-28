"""Custom exceptions and error handling."""

from typing import Any


class AppException(Exception):
    """Base exception for application errors."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}
        super().__init__(message)


class NotFoundError(AppException):
    """Resource not found (404)."""

    def __init__(self, message: str = "Resource not found", **kwargs: Any) -> None:
        super().__init__(message, status_code=404, **kwargs)


class ValidationError(AppException):
    """Validation error (422)."""

    def __init__(self, message: str = "Validation error", **kwargs: Any) -> None:
        super().__init__(message, status_code=422, **kwargs)


class ServiceError(AppException):
    """Service/internal error (500)."""

    def __init__(self, message: str = "Internal service error", **kwargs: Any) -> None:
        super().__init__(message, status_code=500, **kwargs)


class PolicyDeniedException(AppException):
    """Request blocked by the enforcement middleware (HTTP 403).

    Carries the structured ``EnforcementOutcome`` (decisions, matched policy
    ids, trace id) in ``detail`` so clients receive a deterministic error
    envelope they can act on.
    """

    code: str = "PolicyDenied"

    def __init__(
        self,
        message: str = "Request blocked by Valo governance policy.",
        **kwargs: Any,
    ) -> None:
        super().__init__(message, status_code=403, **kwargs)
