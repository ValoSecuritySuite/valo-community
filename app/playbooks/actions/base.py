"""Action protocol and execution context.

Every action (built-in or custom) accepts the same two arguments and
returns the same shape: an :class:`ActionResult`. Actions MUST honor
``ctx.dry_run`` and refuse to perform real side effects when it is True.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from pydantic import BaseModel, ConfigDict, Field

from app.playbooks.events import PlaybookEvent
from app.playbooks.schemas import ActionResult


class ActionContext(BaseModel):
    """Per-invocation context passed to every action."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    event: PlaybookEvent = Field(description="The event that triggered this action")
    playbook_id: str = Field(description="Playbook id that owns the action")
    dry_run: bool = Field(
        default=True,
        description="When True, actions must not produce real side effects",
    )
    correlation_id: str = Field(
        default="",
        description="Stable id for joining audit records across actions",
    )
    extras: Dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form extras (e.g. injected adapters in tests)",
    )


ActionCallable = Callable[[ActionContext, Dict[str, Any]], ActionResult]
"""All actions are plain callables: ``(ctx, params) -> ActionResult``."""


__all__ = ["ActionCallable", "ActionContext", "ActionResult"]
