"""Governance Policy API.

Exposes full CRUD on YAML-backed policies plus dry-run validation, ad-hoc
evaluation against an arbitrary context, and a hot-reload endpoint that mirrors
``POST /rules/reload``.
"""

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import ValidationError

from app.api._rate_limits import rate_limit_for
from app.core.config import settings
from app.core.limiter import limiter
from app.schemas import (
    Policy,
    PolicyEvaluateRequest,
    PolicyEvaluateResponse,
    PolicyListResponse,
    PolicyReloadResponse,
    PolicyValidateResponse,
    RuleReloadDiff,
)
from app.services.policy_engine import aggregate_decision, evaluate_policies
from app.services.policy_store import (
    clear_policies_cache,
    delete_policy,
    get_policy,
    get_policy_fingerprints,
    list_policies,
    load_policies,
    save_policy,
)

router = APIRouter(prefix="/policies", tags=["policies"])


def _format_validation_errors(exc: ValidationError) -> list[str]:
    return [
        f"{'.'.join(str(loc) for loc in err.get('loc', ()))}: {err.get('msg', 'invalid')}"
        for err in exc.errors()
    ]


@router.get("", response_model=PolicyListResponse)
@limiter.limit(rate_limit_for("GET", "/policies"))
def list_policies_endpoint(request: Request) -> PolicyListResponse:
    """Return every governance policy currently on disk.

    Uses the cached policy set when valid; mutations through this API
    automatically invalidate the cache, so callers always see their latest
    write. Out-of-band edits require ``POST /policies/reload`` to take effect.
    """
    policy_set = load_policies(use_cache=True)
    fingerprints = get_policy_fingerprints(policy_set)
    return PolicyListResponse(
        policies=list(policy_set.policies),
        total=len(policy_set.policies),
        fingerprints=fingerprints,
    )


@router.get("/{policy_id}", response_model=Policy)
@limiter.limit(rate_limit_for("GET", "/policies/{policy_id}"))
def get_policy_endpoint(request: Request, policy_id: str) -> Policy:
    """Fetch a single policy by id."""
    policy = get_policy(policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail=f"policy '{policy_id}' not found")
    return policy


@router.post("", response_model=Policy, status_code=201)
@limiter.limit(rate_limit_for("POST", "/policies"))
def create_policy_endpoint(request: Request, payload: Policy) -> Policy:
    """Persist a new policy. 409 if a policy with the same id already exists."""
    if get_policy(payload.id) is not None:
        raise HTTPException(
            status_code=409,
            detail=f"policy '{payload.id}' already exists; use PUT to update",
        )
    return save_policy(payload)


@router.put("/{policy_id}", response_model=Policy)
@limiter.limit(rate_limit_for("PUT", "/policies/{policy_id}"))
def update_policy_endpoint(request: Request, policy_id: str, payload: Policy) -> Policy:
    """Replace an existing policy. 404 if not present, 422 if id mismatches."""
    if payload.id != policy_id:
        raise HTTPException(
            status_code=422,
            detail=f"policy id in path '{policy_id}' does not match body id '{payload.id}'",
        )
    if get_policy(policy_id) is None:
        raise HTTPException(status_code=404, detail=f"policy '{policy_id}' not found")
    return save_policy(payload)


@router.delete("/{policy_id}", status_code=204)
@limiter.limit(rate_limit_for("DELETE", "/policies/{policy_id}"))
def delete_policy_endpoint(request: Request, policy_id: str) -> None:
    """Remove a policy. 404 if it does not exist on disk."""
    removed = delete_policy(policy_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"policy '{policy_id}' not found")
    return None


@router.post("/validate", response_model=PolicyValidateResponse)
@limiter.limit(rate_limit_for("POST", "/policies/validate"))
def validate_policy_endpoint(
    request: Request,
    payload: dict = Body(..., description="Raw policy body to dry-run validate"),
) -> PolicyValidateResponse:
    """Dry-run schema validation. Never writes to disk."""
    try:
        policy = Policy.model_validate(payload)
    except ValidationError as exc:
        return PolicyValidateResponse(valid=False, errors=_format_validation_errors(exc))
    return PolicyValidateResponse(valid=True, policy=policy)


@router.post("/evaluate", response_model=PolicyEvaluateResponse)
@limiter.limit(rate_limit_for("POST", "/policies/evaluate"))
def evaluate_policies_endpoint(
    request: Request,
    payload: PolicyEvaluateRequest,
) -> PolicyEvaluateResponse:
    """Evaluate the loaded policy set against an arbitrary JSON context."""
    policy_set = load_policies(use_cache=False)
    decisions = evaluate_policies(payload.context, policy_set)
    return PolicyEvaluateResponse(
        decisions=decisions,
        final_decision=aggregate_decision(decisions),
    )


@router.post("/reload", response_model=PolicyReloadResponse)
@limiter.limit(rate_limit_for("POST", "/policies/reload"))
def reload_policies_endpoint(request: Request) -> PolicyReloadResponse:
    """Drop the cached policy set, reload from disk, and return a precise diff.

    Uses the cached policy set as the "before" snapshot so out-of-band edits
    (manual file changes, GitOps writes) are correctly classified as added /
    removed / changed.
    """
    old_set = load_policies(use_cache=True)
    old_fp = get_policy_fingerprints(old_set)
    old_ids = set(old_fp)

    clear_policies_cache()
    new_set = load_policies(use_cache=False)
    new_fp = get_policy_fingerprints(new_set)
    new_ids = set(new_fp)

    added = sorted(new_ids - old_ids)
    removed = sorted(old_ids - new_ids)
    changed = sorted(pid for pid in old_ids & new_ids if old_fp[pid] != new_fp[pid])
    unchanged = max(len(new_ids) - len(added) - len(changed), 0)

    return PolicyReloadResponse(
        policies_path=str(settings.policies_path),
        previous_policy_count=len(old_ids),
        new_policy_count=len(new_ids),
        diff=RuleReloadDiff(
            added=added,
            removed=removed,
            changed=changed,
            unchanged=unchanged,
        ),
    )


__all__ = ["router"]
