"""Automated Response Playbooks (Phase 3).

Importing this package triggers built-in action registration via
``app.playbooks.actions``.

See :doc:`docs/PLAYBOOKS.md` for the full design.
"""

from app.playbooks import actions as _actions  # noqa: F401  side-effect imports
from app.playbooks.events import PlaybookEvent, from_enforcement_outcome
from app.playbooks.executor import INLINE_ACTIONS, merge_traces, process_event
from app.playbooks.loader import load_library
from app.playbooks.registry import (
    all_actions,
    clear_registry,
    get_action,
    register_action,
)
from app.playbooks.runtime import dispatch, dispatch_sync
from app.playbooks.schemas import (
    ActionPhase,
    ActionResult,
    ActionSpec,
    ExecutionTrace,
    Playbook,
    PlaybookCondition,
    PlaybookMatch,
    PlaybookSet,
)
from app.playbooks.store import (
    clear_playbooks_cache,
    delete_playbook,
    get_playbook,
    get_playbook_fingerprints,
    list_playbooks,
    load_playbooks,
    save_playbook,
)
from app.playbooks.trace_buffer import (
    all_traces,
    buffer_capacity,
    buffer_used,
    clear_traces,
    query_traces,
    record_trace,
)

__all__ = [
    "ActionPhase",
    "ActionResult",
    "ActionSpec",
    "ExecutionTrace",
    "INLINE_ACTIONS",
    "Playbook",
    "PlaybookCondition",
    "PlaybookEvent",
    "PlaybookMatch",
    "PlaybookSet",
    "all_actions",
    "all_traces",
    "buffer_capacity",
    "buffer_used",
    "clear_playbooks_cache",
    "clear_registry",
    "clear_traces",
    "delete_playbook",
    "dispatch",
    "dispatch_sync",
    "from_enforcement_outcome",
    "get_action",
    "get_playbook",
    "get_playbook_fingerprints",
    "list_playbooks",
    "load_library",
    "load_playbooks",
    "merge_traces",
    "process_event",
    "query_traces",
    "record_trace",
    "register_action",
    "save_playbook",
]
