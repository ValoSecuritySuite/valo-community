"""Filesystem-backed proposal store for the Phase 4 Learning Loop.

A *proposal* is a refiner-generated suggestion to change one live rule
(a governance policy or a response playbook). Proposals are persisted
as YAML files under ``app/policies/proposals/`` and
``app/playbooks/proposals/`` so they sit next to the rules they would
update and so operators can review them with the same git diff workflow
that already covers the live rule.

Each proposal carries:

- the target rule id and kind (``policy`` or ``playbook``).
- the heuristic that produced it and the supporting stats slice.
- a ``status`` field driven by the review workflow (``pending`` /
  ``accepted`` / ``rejected``).
- an ``updated_yaml`` blob: the proposed rule body, ready to be written
  through the existing :mod:`app.services.policy_store` /
  :mod:`app.playbooks.store` interfaces.

The store never auto-applies a proposal. Acceptance happens through
:func:`accept_proposal`, which validates ``updated_yaml`` against the
live rule schema and only then writes it through the live store.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, List, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.config import settings  # noqa: I001
from app.core.exceptions import ServiceError
from app.core.logging import get_logger
from app.playbooks.schemas import Playbook
from app.playbooks.store import save_playbook
from app.schemas import Policy
from app.services.policy_store import save_policy

logger = get_logger(__name__)

PROPOSAL_KIND_POLICY: Literal["policy"] = "policy"
PROPOSAL_KIND_PLAYBOOK: Literal["playbook"] = "playbook"

PROPOSAL_STATUSES: tuple[str, ...] = ("pending", "accepted", "rejected", "applied")

_VALID_FILENAME_SUFFIXES = (".yml", ".yaml")
_SAFE_PROPOSAL_ID_RE = re.compile(r"^[A-Za-z0-9_\-.]+$")


class Proposal(BaseModel):
    """One refiner-generated rule change suggestion."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=1, max_length=120)
    rule_kind: Literal["policy", "playbook"]
    rule_id: str = Field(min_length=1, max_length=120)
    heuristic: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=500)
    status: Literal["pending", "accepted", "rejected", "applied"] = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reviewer: Optional[str] = None
    reviewer_reason: Optional[str] = Field(default=None, max_length=2048)
    sample_size: int = Field(default=0, ge=0)
    fp_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    stats: dict[str, Any] = Field(default_factory=dict)
    diff_summary: List[str] = Field(default_factory=list)
    current_yaml: dict[str, Any] = Field(default_factory=dict)
    proposed_yaml: dict[str, Any] = Field(default_factory=dict)

    @field_validator("proposal_id")
    @classmethod
    def _validate_proposal_id(cls, value: str) -> str:
        slug = value.strip()
        if not slug or not _SAFE_PROPOSAL_ID_RE.match(slug):
            raise ValueError(
                "proposal_id must contain only letters, digits, underscores, dots, or hyphens"
            )
        return slug


# ---- on-disk layout --------------------------------------------------------


def proposals_dir(kind: str) -> Path:
    """Return the proposal directory for a rule kind, creating it lazily."""
    if kind == PROPOSAL_KIND_POLICY:
        base = Path(settings.policies_path).parent / "proposals"
    elif kind == PROPOSAL_KIND_PLAYBOOK:
        base = Path(settings.playbooks_path).parent / "proposals"
    else:
        raise ServiceError(
            message="Unknown proposal kind", detail={"kind": kind}
        )
    base.mkdir(parents=True, exist_ok=True)
    return base


def _proposal_path(kind: str, proposal_id: str) -> Path:
    safe = proposal_id.strip()
    if not safe or not _SAFE_PROPOSAL_ID_RE.match(safe):
        raise ServiceError(
            message="Invalid proposal id", detail={"proposal_id": proposal_id}
        )
    return proposals_dir(kind) / f"{safe}.yml"


def _atomic_write(path: Path, payload: str) -> None:
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.stem + ".", suffix=".tmp", dir=str(directory)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _serialize(proposal: Proposal) -> str:
    payload = proposal.model_dump(mode="json", exclude_none=False)
    return yaml.safe_dump(payload, sort_keys=True, allow_unicode=True)


def _load_one(path: Path) -> Proposal:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    try:
        return Proposal.model_validate(data)
    except ValidationError as exc:
        raise ServiceError(
            message="Proposal failed schema validation",
            detail={"path": str(path), "errors": exc.errors()},
        ) from exc


# ---- public API ------------------------------------------------------------


def save_proposal(proposal: Proposal) -> Proposal:
    """Persist a proposal to disk under its rule kind."""
    stamped = proposal.model_copy(update={"updated_at": datetime.now(timezone.utc)})
    path = _proposal_path(stamped.rule_kind, stamped.proposal_id)
    _atomic_write(path, _serialize(stamped))
    logger.info(
        "learning_proposal_saved kind=%s id=%s status=%s",
        stamped.rule_kind,
        stamped.proposal_id,
        stamped.status,
    )
    return stamped


def load_proposal(proposal_id: str) -> Optional[Proposal]:
    """Find a proposal by id across both kinds. Returns the first match."""
    for kind in (PROPOSAL_KIND_POLICY, PROPOSAL_KIND_PLAYBOOK):
        path = _proposal_path(kind, proposal_id)
        if path.exists():
            return _load_one(path)
    return None


def list_proposals(
    *,
    kind: Optional[str] = None,
    status: Optional[str] = None,
    rule_id: Optional[str] = None,
) -> list[Proposal]:
    """Return all on-disk proposals matching the filters, newest first."""
    kinds: Iterable[str] = (
        (kind,) if kind in (PROPOSAL_KIND_POLICY, PROPOSAL_KIND_PLAYBOOK)
        else (PROPOSAL_KIND_POLICY, PROPOSAL_KIND_PLAYBOOK)
    )
    seen_files: set[Path] = set()
    seen_ids: set[str] = set()
    out: list[Proposal] = []
    for k in kinds:
        directory = proposals_dir(k)
        if not directory.exists():
            continue
        for entry in sorted(directory.iterdir()):
            if (
                not entry.is_file()
                or entry.suffix.lower() not in _VALID_FILENAME_SUFFIXES
            ):
                continue
            resolved = entry.resolve()
            if resolved in seen_files:
                continue
            seen_files.add(resolved)
            try:
                proposal = _load_one(entry)
            except ServiceError as exc:
                logger.warning(
                    "learning_proposal_skipped path=%s reason=%s",
                    entry,
                    exc.message,
                )
                continue
            if proposal.proposal_id in seen_ids:
                continue
            seen_ids.add(proposal.proposal_id)
            if kind is not None and proposal.rule_kind != kind:
                continue
            if status is not None and proposal.status != status:
                continue
            if rule_id is not None and proposal.rule_id != rule_id:
                continue
            out.append(proposal)
    out.sort(key=lambda p: p.created_at, reverse=True)
    return out


def delete_proposal(proposal_id: str) -> bool:
    """Remove a proposal file. Returns ``True`` when the file existed."""
    for kind in (PROPOSAL_KIND_POLICY, PROPOSAL_KIND_PLAYBOOK):
        path = _proposal_path(kind, proposal_id)
        if path.exists():
            path.unlink()
            logger.info(
                "learning_proposal_deleted kind=%s id=%s",
                kind,
                proposal_id,
            )
            return True
    return False


# ---- review actions --------------------------------------------------------


def reject_proposal(
    proposal_id: str,
    *,
    reviewer: Optional[str] = None,
    reason: Optional[str] = None,
) -> Proposal:
    """Mark a proposal as rejected. The file is kept for audit history."""
    proposal = load_proposal(proposal_id)
    if proposal is None:
        raise ServiceError(
            message="Proposal not found", detail={"proposal_id": proposal_id}
        )
    updated = proposal.model_copy(
        update={
            "status": "rejected",
            "reviewer": reviewer,
            "reviewer_reason": reason,
            "updated_at": datetime.now(timezone.utc),
        }
    )
    return save_proposal(updated)


def accept_proposal(
    proposal_id: str,
    *,
    reviewer: Optional[str] = None,
    reason: Optional[str] = None,
) -> tuple[Proposal, dict[str, Any]]:
    """Apply ``proposed_yaml`` through the live rule store, then mark applied.

    Returns ``(proposal, applied_payload)`` where ``applied_payload`` is
    the rule body actually written (after schema validation). Raises
    :class:`ServiceError` on schema or store failures so the API layer
    can surface a 422/500 cleanly.
    """
    proposal = load_proposal(proposal_id)
    if proposal is None:
        raise ServiceError(
            message="Proposal not found", detail={"proposal_id": proposal_id}
        )
    if proposal.status in ("applied",):
        raise ServiceError(
            message="Proposal has already been applied",
            detail={"proposal_id": proposal_id, "status": proposal.status},
        )

    applied: dict[str, Any]
    if proposal.rule_kind == PROPOSAL_KIND_POLICY:
        try:
            policy = Policy.model_validate(proposal.proposed_yaml)
        except ValidationError as exc:
            raise ServiceError(
                message="Proposed policy failed schema validation",
                detail={"errors": exc.errors()},
            ) from exc
        if policy.id != proposal.rule_id:
            raise ServiceError(
                message="Proposed policy id does not match proposal rule_id",
                detail={"policy_id": policy.id, "rule_id": proposal.rule_id},
            )
        saved = save_policy(policy)
        applied = saved.model_dump(mode="json")
    elif proposal.rule_kind == PROPOSAL_KIND_PLAYBOOK:
        try:
            playbook = Playbook.model_validate(proposal.proposed_yaml)
        except ValidationError as exc:
            raise ServiceError(
                message="Proposed playbook failed schema validation",
                detail={"errors": exc.errors()},
            ) from exc
        if playbook.id != proposal.rule_id:
            raise ServiceError(
                message="Proposed playbook id does not match proposal rule_id",
                detail={"playbook_id": playbook.id, "rule_id": proposal.rule_id},
            )
        saved_playbook = save_playbook(playbook)
        applied = saved_playbook.model_dump(mode="json")
    else:
        raise ServiceError(
            message="Unknown proposal kind", detail={"kind": proposal.rule_kind}
        )

    updated = proposal.model_copy(
        update={
            "status": "applied",
            "reviewer": reviewer,
            "reviewer_reason": reason,
            "updated_at": datetime.now(timezone.utc),
        }
    )
    saved_proposal = save_proposal(updated)
    return saved_proposal, applied


# ---- helpers for the refiner ----------------------------------------------


def diff_yaml(
    current: dict[str, Any],
    proposed: dict[str, Any],
) -> List[str]:
    """Return a small set of human-readable diff lines for the review UI."""
    lines: list[str] = []
    keys = sorted(set(current.keys()) | set(proposed.keys()))
    for key in keys:
        before = current.get(key)
        after = proposed.get(key)
        if before == after:
            continue
        lines.append(f"{key}: {_render(before)} -> {_render(after)}")
    return lines


def _render(value: Any) -> str:
    if value is None:
        return "<unset>"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value)


def stable_proposal_id(rule_kind: str, rule_id: str, heuristic: str) -> str:
    """Return a deterministic id so re-runs overwrite stale proposals.

    Idempotency: re-running the refiner on the same rule + heuristic
    updates the existing proposal in place instead of producing
    duplicates the operator has to clean up.
    """
    raw = f"{rule_kind}:{rule_id}:{heuristic}"
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]  # noqa: S324
    return f"{rule_kind}_{rule_id}_{heuristic}_{digest}"


__all__ = [
    "PROPOSAL_KIND_PLAYBOOK",
    "PROPOSAL_KIND_POLICY",
    "PROPOSAL_STATUSES",
    "Proposal",
    "accept_proposal",
    "delete_proposal",
    "diff_yaml",
    "list_proposals",
    "load_proposal",
    "proposals_dir",
    "reject_proposal",
    "save_proposal",
    "stable_proposal_id",
]
