"""Action registry for the playbook engine.

Decorate a callable with :func:`register_action` to make it dispatchable
from a YAML playbook's ``then[].action`` field. Decorators run at import
time, so :mod:`app.playbooks.actions` must be imported once at startup
(executed by ``app.playbooks.__init__``) for built-in actions to be
available.

This module is intentionally tiny so unit tests can swap or shadow the
registry without touching disk.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from app.playbooks.actions.base import ActionCallable

_REGISTRY: Dict[str, ActionCallable] = {}


def register_action(name: str) -> Callable[[ActionCallable], ActionCallable]:
    """Decorator that registers *fn* under *name* in the global registry.

    Re-registration is allowed (last writer wins) so tests can override
    built-in adapters with stub implementations.
    """

    def _decorator(fn: ActionCallable) -> ActionCallable:
        _REGISTRY[name] = fn
        return fn

    return _decorator


def get_action(name: str) -> Optional[ActionCallable]:
    return _REGISTRY.get(name)


def all_actions() -> Dict[str, ActionCallable]:
    """Return a copy of the registry (read-only view for diagnostics)."""
    return dict(_REGISTRY)


def clear_registry() -> None:
    """Wipe the registry (used by tests; do not call from production code)."""
    _REGISTRY.clear()


__all__ = [
    "all_actions",
    "clear_registry",
    "get_action",
    "register_action",
]
