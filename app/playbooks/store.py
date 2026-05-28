"""Filesystem-backed playbook store.

Each playbook is persisted as ``<playbooks_path>/<playbook_id>.yml``.
Mirrors :mod:`app.services.policy_store`: TTL cache, atomic writes,
fingerprint-based diffs for ``POST /playbooks/reload``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Optional

import yaml
from pydantic import ValidationError

from app.core.config import settings
from app.core.exceptions import ServiceError
from app.core.logging import get_logger
from app.playbooks.schemas import Playbook, PlaybookSet

logger = get_logger(__name__)

_VALID_FILENAME_SUFFIXES = (".yml", ".yaml")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_\-.]+$")

_playbooks_cache: tuple[Optional[PlaybookSet], float] = (None, 0.0)


def _playbooks_dir() -> Path:
    return Path(settings.playbooks_path)


def _validate_id(playbook_id: str) -> str:
    safe = str(playbook_id).strip()
    if not safe or not _SAFE_ID_RE.match(safe):
        raise ServiceError(
            message="Invalid playbook id",
            detail={"playbook_id": playbook_id},
        )
    return safe


def _playbook_path(playbook_id: str) -> Path:
    return _playbooks_dir() / f"{_validate_id(playbook_id)}.yml"


def _ensure_dir() -> Path:
    directory = _playbooks_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _load_one_from_disk(path: Path) -> Playbook:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        logger.error("Invalid YAML in playbook file: %s", path, exc_info=True)
        raise ServiceError(
            message="Invalid playbook file format",
            detail={"path": str(path), "yaml_error": str(exc)},
        ) from exc
    try:
        return Playbook.model_validate(data)
    except ValidationError as exc:
        raise ServiceError(
            message="Playbook file failed schema validation",
            detail={"path": str(path), "errors": exc.errors()},
        ) from exc


def _load_playbooks_from_disk() -> PlaybookSet:
    directory = _playbooks_dir()
    if not directory.exists():
        logger.info("Playbooks directory not found: %s", directory)
        return PlaybookSet(playbooks=[])

    playbooks: list[Playbook] = []
    seen_ids: set[str] = set()
    for entry in sorted(directory.iterdir()):
        if not entry.is_file() or entry.suffix.lower() not in _VALID_FILENAME_SUFFIXES:
            continue
        try:
            playbook = _load_one_from_disk(entry)
        except ServiceError as exc:
            logger.warning(
                "playbook_load_skipped path=%s reason=%s", entry, exc.message
            )
            continue
        if playbook.id in seen_ids:
            logger.warning(
                "Duplicate playbook id %s in %s, skipping", playbook.id, entry
            )
            continue
        seen_ids.add(playbook.id)
        playbooks.append(playbook)

    return PlaybookSet(playbooks=playbooks)


def _is_cache_valid() -> bool:
    if settings.playbooks_cache_ttl_seconds <= 0:
        return False
    cached, ts = _playbooks_cache
    if cached is None:
        return False
    return (time.time() - ts) < settings.playbooks_cache_ttl_seconds


def load_playbooks(use_cache: bool = True) -> PlaybookSet:
    """Return the current :class:`PlaybookSet` from disk, optionally cached."""
    global _playbooks_cache
    if use_cache and _is_cache_valid():
        cached = _playbooks_cache[0]
        assert cached is not None
        return cached
    playbook_set = _load_playbooks_from_disk()
    if use_cache and settings.playbooks_cache_ttl_seconds > 0:
        _playbooks_cache = (playbook_set, time.time())
    return playbook_set


def clear_playbooks_cache() -> None:
    """Drop the cached playbook set (called by reload and by tests)."""
    global _playbooks_cache
    _playbooks_cache = (None, 0.0)
    logger.debug("Playbooks cache cleared")


def get_playbook(playbook_id: str) -> Optional[Playbook]:
    path = _playbook_path(playbook_id)
    if not path.exists():
        return None
    return _load_one_from_disk(path)


def list_playbooks() -> list[Playbook]:
    """Return every playbook currently on disk in id-sorted order."""
    return list(load_playbooks(use_cache=False).playbooks)


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


def _serialize(playbook: Playbook) -> str:
    payload = playbook.model_dump(mode="json", exclude_none=False)
    return yaml.safe_dump(payload, sort_keys=True, allow_unicode=True)


def save_playbook(playbook: Playbook) -> Playbook:
    """Persist a playbook to disk. Invalidates the cache."""
    _ensure_dir()
    target = _playbook_path(playbook.id)
    _atomic_write(target, _serialize(playbook))
    clear_playbooks_cache()
    logger.info("Playbook %s saved to %s", playbook.id, target)
    return playbook


def delete_playbook(playbook_id: str) -> bool:
    """Remove a playbook file. Returns ``True`` when the file existed."""
    path = _playbook_path(playbook_id)
    if not path.exists():
        return False
    path.unlink()
    clear_playbooks_cache()
    logger.info("Playbook %s deleted from %s", playbook_id, path)
    return True


def get_playbook_fingerprints(playbook_set: PlaybookSet) -> dict[str, str]:
    """Return ``{playbook_id: md5_hash}`` over the fields that drive execution."""
    fingerprints: dict[str, str] = {}
    for pb in playbook_set.playbooks:
        payload = json.dumps(
            {
                "enabled": pb.enabled,
                "priority": pb.priority,
                "when": [c.model_dump(mode="json") for c in pb.when],
                "then": [a.model_dump(mode="json") for a in pb.then],
                "tags": list(pb.tags),
                "version": pb.version,
            },
            sort_keys=True,
        )
        fingerprints[pb.id] = hashlib.md5(payload.encode()).hexdigest()  # noqa: S324
    return fingerprints


__all__ = [
    "clear_playbooks_cache",
    "delete_playbook",
    "get_playbook",
    "get_playbook_fingerprints",
    "list_playbooks",
    "load_playbooks",
    "save_playbook",
]
