"""Filesystem-backed governance policy store.

Each policy is persisted as ``<policies_path>/<policy_id>.yml``. The store
caches the loaded ``PolicySet`` for ``settings.policies_cache_ttl_seconds``
seconds and exposes the same fingerprint pattern used by ``rules_loader`` so
the reload endpoint can produce a precise diff.
"""

import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.core.config import settings
from app.core.exceptions import ServiceError
from app.core.logging import get_logger
from app.schemas import Policy, PolicySet

logger = get_logger(__name__)

_VALID_FILENAME_SUFFIXES = (".yml", ".yaml")

_policies_cache: tuple[PolicySet | None, float] = (None, 0.0)


def _policies_dir() -> Path:
    return settings.policies_path


def _policy_path(policy_id: str) -> Path:
    safe = str(policy_id).strip()
    if not safe:
        raise ServiceError(message="Policy id must not be empty")
    return _policies_dir() / f"{safe}.yml"


def _ensure_dir() -> Path:
    directory = _policies_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _load_one_from_disk(path: Path) -> Policy:
    """Load a single policy file and validate it against the schema."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        logger.error("Invalid YAML in policy file: %s", path, exc_info=True)
        raise ServiceError(
            message="Invalid policy file format",
            detail={"path": str(path), "yaml_error": str(exc)},
        ) from exc

    try:
        return Policy.model_validate(data)
    except ValidationError as exc:
        raise ServiceError(
            message="Policy file failed schema validation",
            detail={"path": str(path), "errors": exc.errors()},
        ) from exc


def _load_policies_from_disk() -> PolicySet:
    """Walk the policies directory and load every YAML policy file."""
    directory = _policies_dir()
    if not directory.exists():
        logger.info("Policies directory not found: %s", directory)
        return PolicySet(policies=[])

    policies: list[Policy] = []
    seen_ids: set[str] = set()
    for entry in sorted(directory.iterdir()):
        if not entry.is_file() or entry.suffix.lower() not in _VALID_FILENAME_SUFFIXES:
            continue
        policy = _load_one_from_disk(entry)
        if policy.id in seen_ids:
            logger.warning("Duplicate policy id %s in %s, skipping", policy.id, entry)
            continue
        seen_ids.add(policy.id)
        policies.append(policy)

    return PolicySet(policies=policies)


def _is_cache_valid() -> bool:
    if settings.policies_cache_ttl_seconds <= 0:
        return False
    cached, ts = _policies_cache
    if cached is None:
        return False
    return (time.time() - ts) < settings.policies_cache_ttl_seconds


def load_policies(use_cache: bool = True) -> PolicySet:
    """Return the current ``PolicySet`` from disk, optionally cached."""
    global _policies_cache
    if use_cache and _is_cache_valid():
        cached = _policies_cache[0]
        assert cached is not None
        return cached
    policy_set = _load_policies_from_disk()
    if use_cache and settings.policies_cache_ttl_seconds > 0:
        _policies_cache = (policy_set, time.time())
    return policy_set


def clear_policies_cache() -> None:
    """Drop the cached policy set (called by reload and by tests)."""
    global _policies_cache
    _policies_cache = (None, 0.0)
    logger.debug("Policies cache cleared")


def get_policy(policy_id: str) -> Policy | None:
    """Return one policy by id, or ``None`` if not present on disk."""
    path = _policy_path(policy_id)
    if not path.exists():
        return None
    return _load_one_from_disk(path)


def list_policies() -> list[Policy]:
    """Return every policy currently on disk in id-sorted order."""
    return list(load_policies(use_cache=False).policies)


def _atomic_write(path: Path, payload: str) -> None:
    """Write *payload* to *path* via a same-directory temp file then rename."""
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=str(directory))
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


def _serialize(policy: Policy) -> str:
    """Render a policy as deterministic YAML for on-disk persistence."""
    payload = policy.model_dump(mode="json", exclude_none=False)
    return yaml.safe_dump(payload, sort_keys=True, allow_unicode=True)


def save_policy(policy: Policy) -> Policy:
    """Persist a policy to disk, stamping ``updated_at``. Invalidates the cache."""
    _ensure_dir()
    stamped = policy.model_copy(update={"updated_at": datetime.now(timezone.utc)})
    target = _policy_path(stamped.id)
    _atomic_write(target, _serialize(stamped))
    clear_policies_cache()
    logger.info("Policy %s saved to %s", stamped.id, target)
    return stamped


def delete_policy(policy_id: str) -> bool:
    """Remove a policy file. Returns ``True`` when the file existed."""
    path = _policy_path(policy_id)
    if not path.exists():
        return False
    path.unlink()
    clear_policies_cache()
    logger.info("Policy %s deleted from %s", policy_id, path)
    return True


def get_policy_fingerprints(policy_set: PolicySet) -> dict[str, str]:
    """Return ``{policy_id: md5_hash}`` covering the fields that drive evaluation."""
    fingerprints: dict[str, str] = {}
    for policy in policy_set.policies:
        payload = json.dumps(
            {
                "enabled": policy.enabled,
                "when": [c.model_dump(mode="json") for c in policy.when],
                "then": policy.then.model_dump(mode="json"),
                "tags": list(policy.tags),
                "version": policy.version,
            },
            sort_keys=True,
        )
        fingerprints[policy.id] = hashlib.md5(payload.encode()).hexdigest()  # noqa: S324
    return fingerprints
