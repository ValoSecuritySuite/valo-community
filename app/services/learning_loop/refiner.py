"""Refiner: turn labeled outcomes into reviewable rule proposals.

The refiner is a pure-Python heuristic engine. It reads aggregate stats
from :mod:`app.services.outcome_store`, walks the live policy and
playbook libraries, and writes one :class:`Proposal` per (rule,
heuristic) pair that crosses a threshold.

Heuristics shipped in this PR:

- ``disable_noisy_playbook``: when a playbook's labeled FP rate exceeds
  ``settings.learning_loop_fp_threshold`` and the labeled sample size
  meets ``settings.learning_loop_min_samples``, propose ``enabled: false``.
- ``lower_priority_noisy_playbook``: same trigger as above, but only
  fires when the playbook's FP rate is in the warning band (between the
  healthy ceiling and the FP threshold). Proposes a priority decrease
  so the playbook still fires but loses precedence ties.
- ``raise_combined_score_threshold``: when a policy has a numeric
  ``combined_score`` condition and its labeled FP rate exceeds the
  threshold, propose tightening the threshold by 5 points (capped at
  100). This keeps tuning conservative and gives the operator a clear
  delta to reason about.

Healthy rules (FP rate at or below
``settings.learning_loop_healthy_fp_ceiling``) get no proposal. Rules
without enough labeled samples to clear ``learning_loop_min_samples``
also get no proposal: it's safer to let an under-sampled rule keep
running than to overreact to a few labels.

The refiner never auto-applies. It only writes pending proposals.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.playbooks.schemas import Playbook
from app.playbooks.store import list_playbooks
from app.schemas import Policy
from app.services import outcome_store
from app.services.learning_loop.proposals import (
    PROPOSAL_KIND_PLAYBOOK,
    PROPOSAL_KIND_POLICY,
    Proposal,
    diff_yaml,
    save_proposal,
    stable_proposal_id,
)
from app.services.outcome_store import RuleStats
from app.services.policy_store import list_policies

logger = get_logger(__name__)

HEURISTIC_DISABLE_PLAYBOOK = "disable_noisy_playbook"
HEURISTIC_LOWER_PRIORITY = "lower_priority_noisy_playbook"
HEURISTIC_RAISE_THRESHOLD = "raise_combined_score_threshold"

_PRIORITY_DECREASE = 10
_THRESHOLD_BUMP = 5.0
_THRESHOLD_CEILING = 100.0


def _fp_threshold() -> float:
    return float(settings.learning_loop_fp_threshold)


def _healthy_ceiling() -> float:
    return float(settings.learning_loop_healthy_fp_ceiling)


def _min_samples() -> int:
    return int(settings.learning_loop_min_samples)


def summarize_rule(stat: RuleStats) -> dict[str, Any]:
    """Render the stats payload that ships inside each proposal."""
    return {
        "total": stat.total,
        "labeled": stat.labeled,
        "true_positives": stat.true_positives,
        "false_positives": stat.false_positives,
        "benign_blocks": stat.benign_blocks,
        "malicious_allows": stat.malicious_allows,
        "suppressed": stat.suppressed,
        "dismissed": stat.dismissed,
        "fp_rate": round(stat.fp_rate, 4),
        "last_started_at": stat.last_started_at.isoformat()
        if stat.last_started_at
        else None,
        "last_label_at": stat.last_label_at.isoformat()
        if stat.last_label_at
        else None,
    }


# ---- playbook heuristics ---------------------------------------------------


def _build_disable_playbook_proposal(
    playbook: Playbook,
    stat: RuleStats,
) -> Proposal:
    current = playbook.model_dump(mode="json", exclude_none=False)
    proposed = dict(current)
    proposed["enabled"] = False
    return Proposal(
        proposal_id=stable_proposal_id(
            PROPOSAL_KIND_PLAYBOOK, playbook.id, HEURISTIC_DISABLE_PLAYBOOK
        ),
        rule_kind=PROPOSAL_KIND_PLAYBOOK,
        rule_id=playbook.id,
        heuristic=HEURISTIC_DISABLE_PLAYBOOK,
        summary=(
            f"Disable playbook '{playbook.id}': "
            f"FP rate {stat.fp_rate:.0%} over {stat.labeled} labeled samples "
            f"exceeds threshold {_fp_threshold():.0%}."
        ),
        sample_size=stat.labeled,
        fp_rate=round(stat.fp_rate, 4),
        stats=summarize_rule(stat),
        diff_summary=diff_yaml(current, proposed),
        current_yaml=current,
        proposed_yaml=proposed,
    )


def _build_lower_priority_proposal(
    playbook: Playbook,
    stat: RuleStats,
) -> Proposal:
    current = playbook.model_dump(mode="json", exclude_none=False)
    proposed = dict(current)
    new_priority = max(0, int(playbook.priority) - _PRIORITY_DECREASE)
    proposed["priority"] = new_priority
    return Proposal(
        proposal_id=stable_proposal_id(
            PROPOSAL_KIND_PLAYBOOK, playbook.id, HEURISTIC_LOWER_PRIORITY
        ),
        rule_kind=PROPOSAL_KIND_PLAYBOOK,
        rule_id=playbook.id,
        heuristic=HEURISTIC_LOWER_PRIORITY,
        summary=(
            f"Lower priority of playbook '{playbook.id}' "
            f"({playbook.priority} -> {new_priority}): "
            f"FP rate {stat.fp_rate:.0%} is in the warning band over "
            f"{stat.labeled} labeled samples."
        ),
        sample_size=stat.labeled,
        fp_rate=round(stat.fp_rate, 4),
        stats=summarize_rule(stat),
        diff_summary=diff_yaml(current, proposed),
        current_yaml=current,
        proposed_yaml=proposed,
    )


def _refine_playbooks(
    *,
    since: Optional[datetime],
) -> list[Proposal]:
    playbooks = list_playbooks()
    if not playbooks:
        return []
    accepted_ids = {pb.id for pb in playbooks}
    stats = outcome_store.aggregate_rule_stats(
        kind="playbook", since=since, rule_ids=accepted_ids
    )
    out: list[Proposal] = []
    fp_threshold = _fp_threshold()
    healthy_ceiling = _healthy_ceiling()
    min_samples = _min_samples()

    for playbook in playbooks:
        stat = stats.get(playbook.id)
        if stat is None:
            continue
        if stat.labeled < min_samples:
            continue
        rate = stat.fp_rate
        if rate > fp_threshold and playbook.enabled:
            out.append(_build_disable_playbook_proposal(playbook, stat))
            continue
        if (
            healthy_ceiling < rate <= fp_threshold
            and playbook.enabled
            and playbook.priority > 0
        ):
            out.append(_build_lower_priority_proposal(playbook, stat))
    return out


# ---- policy heuristics -----------------------------------------------------


def _find_combined_score_condition(
    policy: Policy,
) -> tuple[Optional[int], Optional[float]]:
    """Return ``(index, threshold_value)`` for a numeric combined_score gate.

    The refiner only proposes threshold bumps for policies that already
    gate on ``combined_score`` with one of the numeric operators
    (``gte`` / ``gt`` / ``lt`` / ``lte``). Other shapes (eq, contains,
    regex) are out of scope for this heuristic.
    """
    for index, condition in enumerate(policy.when):
        if condition.field != "combined_score":
            continue
        if condition.op not in {"gte", "gt"}:
            continue
        try:
            return index, float(condition.value)
        except (TypeError, ValueError):
            continue
    return None, None


def _build_threshold_proposal(
    policy: Policy,
    stat: RuleStats,
    *,
    condition_index: int,
    current_threshold: float,
    new_threshold: float,
) -> Proposal:
    current = policy.model_dump(mode="json", exclude_none=False)
    proposed = policy.model_dump(mode="json", exclude_none=False)
    proposed_when: List[dict[str, Any]] = list(proposed.get("when") or [])
    if 0 <= condition_index < len(proposed_when):
        cond_copy = dict(proposed_when[condition_index])
        cond_copy["value"] = new_threshold
        proposed_when[condition_index] = cond_copy
    proposed["when"] = proposed_when
    return Proposal(
        proposal_id=stable_proposal_id(
            PROPOSAL_KIND_POLICY, policy.id, HEURISTIC_RAISE_THRESHOLD
        ),
        rule_kind=PROPOSAL_KIND_POLICY,
        rule_id=policy.id,
        heuristic=HEURISTIC_RAISE_THRESHOLD,
        summary=(
            f"Raise combined_score threshold on policy '{policy.id}' "
            f"({current_threshold:g} -> {new_threshold:g}): "
            f"FP rate {stat.fp_rate:.0%} over {stat.labeled} labeled samples "
            f"exceeds threshold {_fp_threshold():.0%}."
        ),
        sample_size=stat.labeled,
        fp_rate=round(stat.fp_rate, 4),
        stats=summarize_rule(stat),
        diff_summary=diff_yaml(current, proposed),
        current_yaml=current,
        proposed_yaml=proposed,
    )


def _refine_policies(
    *,
    since: Optional[datetime],
) -> list[Proposal]:
    policies = list_policies()
    if not policies:
        return []
    accepted_ids = {p.id for p in policies}
    stats = outcome_store.aggregate_rule_stats(
        kind="policy", since=since, rule_ids=accepted_ids
    )
    out: list[Proposal] = []
    fp_threshold = _fp_threshold()
    min_samples = _min_samples()

    for policy in policies:
        stat = stats.get(policy.id)
        if stat is None:
            continue
        if stat.labeled < min_samples:
            continue
        rate = stat.fp_rate
        if rate <= fp_threshold:
            continue
        condition_index, current_threshold = _find_combined_score_condition(policy)
        if condition_index is None or current_threshold is None:
            continue
        new_threshold = min(_THRESHOLD_CEILING, current_threshold + _THRESHOLD_BUMP)
        if new_threshold <= current_threshold:
            continue
        out.append(
            _build_threshold_proposal(
                policy,
                stat,
                condition_index=condition_index,
                current_threshold=current_threshold,
                new_threshold=new_threshold,
            )
        )
    return out


# ---- public entry point ----------------------------------------------------


def refine_once(
    *,
    since: Optional[datetime] = None,
    persist: bool = True,
) -> list[Proposal]:
    """Run all heuristics once and return the proposals.

    When ``persist`` is True (default) every proposal is written to disk
    via :func:`save_proposal` before returning, with a deterministic id
    so re-runs overwrite stale proposals instead of stacking duplicates.
    Pass ``persist=False`` from tests that want to inspect the result
    without touching the filesystem.
    """
    since_window = since or (
        datetime.now(timezone.utc) - timedelta(days=30)
    )
    proposals: list[Proposal] = []
    proposals.extend(_refine_playbooks(since=since_window))
    proposals.extend(_refine_policies(since=since_window))

    if persist:
        for proposal in proposals:
            try:
                save_proposal(proposal)
            except Exception:
                logger.exception(
                    "learning_proposal_save_failed kind=%s id=%s",
                    proposal.rule_kind,
                    proposal.proposal_id,
                )
    logger.info(
        "learning_loop_refined proposals=%d window_start=%s",
        len(proposals),
        since_window.isoformat(),
    )
    return proposals
