import time
from pathlib import Path
from typing import Callable

import yaml

from app.core.config import settings
from app.core.exceptions import ServiceError
from app.core.logging import get_logger
from app.schemas import RuleSet

logger = get_logger(__name__)

# In-memory cache: (rules, timestamp)
_rules_cache: tuple[RuleSet | None, float] = (None, 0)


def _load_rules_from_disk(path: Path) -> RuleSet:
    """Load rules from file without caching."""
    if not path.exists():
        logger.warning("Rules file not found: %s", path)
        return RuleSet(rules=[])

    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return RuleSet.model_validate(data)
    except yaml.YAMLError as e:
        logger.error("Invalid YAML in rules file: %s", path, exc_info=True)
        raise ServiceError(
            message="Invalid rules file format",
            detail={"path": str(path), "yaml_error": str(e)},
        ) from e
    except Exception as e:
        logger.error("Failed to load rules from %s", path, exc_info=True)
        raise ServiceError(
            message="Failed to load rules",
            detail={"path": str(path), "error": str(e)},
        ) from e


def _is_cache_valid() -> bool:
    """Check if cached rules are still valid."""
    if settings.rules_cache_ttl_seconds <= 0:
        return False
    cached_rules, cached_at = _rules_cache
    if cached_rules is None:
        return False
    return (time.time() - cached_at) < settings.rules_cache_ttl_seconds


def load_rules(use_cache: bool = True) -> RuleSet:
    """Load rules from configured path, with optional caching."""
    global _rules_cache
    path = settings.rules_path
    if use_cache and _is_cache_valid():
        cached = _rules_cache[0]
        assert cached is not None
        return cached
    rules = _load_rules_from_disk(path)
    if use_cache and settings.rules_cache_ttl_seconds > 0:
        _rules_cache = (rules, time.time())
    return rules


def clear_rules_cache() -> None:
    """Clear the rules cache (useful for tests or manual reload)."""
    global _rules_cache
    _rules_cache = (None, 0.0)
    logger.debug("Rules cache cleared")


def get_rule_fingerprints(rule_set: RuleSet) -> dict[str, str]:
    """Return ``{rule_id: md5_hash}`` for every rule in *rule_set*.

    Hash covers the fields that determine scanning behaviour:
    - context rules   : weight, enabled, patterns
    - text-scan rules : weight, enabled, pattern, category

    Used by the hot-reload endpoint to produce an accurate diff.
    """
    import hashlib
    import json

    fingerprints: dict[str, str] = {}

    for r in rule_set.rules:
        payload = json.dumps(
            {"weight": r.weight, "enabled": r.enabled, "patterns": [p.model_dump() for p in r.patterns]},
            sort_keys=True,
        )
        fingerprints[r.name] = hashlib.md5(payload.encode()).hexdigest()  # noqa: S324

    for r in rule_set.text_scan_rules:
        payload = json.dumps(
            {"weight": r.weight, "enabled": r.enabled, "pattern": r.pattern, "category": r.category},
            sort_keys=True,
        )
        fingerprints[r.id] = hashlib.md5(payload.encode()).hexdigest()  # noqa: S324

    return fingerprints
