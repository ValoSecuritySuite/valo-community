"""YAML loader for the playbook library (compat shim).

The real implementation now lives in :mod:`app.playbooks.store`. This
module is kept so existing call sites (including the original test suite)
that imported :func:`load_library` keep working.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.playbooks.schemas import PlaybookSet
from app.playbooks.store import _load_playbooks_from_disk

DEFAULT_LIBRARY_DIR = Path(__file__).parent / "library"


def load_library(library_dir: Optional[Path] = None) -> PlaybookSet:
    """Load every ``*.yml`` / ``*.yaml`` file in *library_dir* into a PlaybookSet.

    When *library_dir* is provided it temporarily overrides
    ``settings.playbooks_path`` so the existing on-disk loader (which
    already handles invalid files) is the single code path.
    """
    if library_dir is None:
        return _load_playbooks_from_disk()
    original = settings.playbooks_path
    try:
        settings.playbooks_path = Path(library_dir)
        return _load_playbooks_from_disk()
    finally:
        settings.playbooks_path = original


__all__ = ["DEFAULT_LIBRARY_DIR", "load_library"]
