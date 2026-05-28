"""Phase 4 Learning Loop: capture outcomes and refine rules.

Three pieces:

- :mod:`app.services.outcome_store` (sibling module): durable SQLite
  table of every playbook execution + analyst label.
- :mod:`app.services.learning_loop.proposals`: filesystem-backed store
  of pending refiner proposals (one YAML file per proposal).
- :mod:`app.services.learning_loop.refiner`: heuristic engine that
  reads the outcome store, computes per-rule statistics, and writes
  proposals.

Default-off behaviour mirrors the playbook engine: the refiner does
not generate any proposals while ``settings.learning_loop_enabled`` is
``False``, and accepted proposals only mutate live rules when an
operator calls ``POST /learning/proposals/{id}/accept`` (or, opt-in,
when ``settings.learning_loop_auto_apply`` is ``True``).
"""

from app.services.learning_loop.proposals import (
    PROPOSAL_KIND_PLAYBOOK,
    PROPOSAL_KIND_POLICY,
    Proposal,
    accept_proposal,
    delete_proposal,
    list_proposals,
    load_proposal,
    proposals_dir,
    reject_proposal,
    save_proposal,
)
from app.services.learning_loop.refiner import (
    refine_once,
    summarize_rule,
)

__all__ = [
    "PROPOSAL_KIND_PLAYBOOK",
    "PROPOSAL_KIND_POLICY",
    "Proposal",
    "accept_proposal",
    "delete_proposal",
    "list_proposals",
    "load_proposal",
    "proposals_dir",
    "refine_once",
    "reject_proposal",
    "save_proposal",
    "summarize_rule",
]
