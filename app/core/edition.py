"""Edition capability helpers."""

from __future__ import annotations

from functools import wraps
from typing import Callable, TypeVar

from fastapi import HTTPException

from app.core.config import settings

F = TypeVar("F", bound=Callable)


def is_community() -> bool:
    return settings.edition == "community"


def is_enterprise() -> bool:
    return settings.edition == "enterprise"


def require_enterprise() -> None:
    """Raise 404 when the route requires Valo Enterprise."""
    if is_community():
        raise HTTPException(
            status_code=404,
            detail={
                "code": "feature_unavailable",
                "message": "This endpoint is available in Valo Enterprise only.",
            },
        )


def enterprise_only(func: F) -> F:
    """Decorator for route handlers that require the enterprise edition."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        require_enterprise()
        return func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]
