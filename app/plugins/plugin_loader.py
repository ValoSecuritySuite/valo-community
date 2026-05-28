"""Dynamic plugin discovery and loading.

Plugin Interface Contract
-------------------------
Every plugin module **must** export a ``register()`` function that returns a
dict conforming to the following shape (defined as :class:`PluginInfo`)::

    {
        "name":        str,           # Human-readable plugin name        (required)
        "version":     str,           # Semantic version, e.g. "1.0.0"   (required)
        "description": str,           # Short description                 (required)
        "author":      str,           # Author name / team                (required)
        "hooks":       {              # Named callable hooks              (required)
            "<hook_name>": <callable>,
        },
        # ---- optional ----
        "tags":    list[str],         # Categorisation labels
        "enabled": bool,              # Defaults to True if absent
    }

Lifecycle
---------
``load_plugins()`` is called once during application startup (lifespan).
It iterates every sub-module in ``app/plugins/``, imports those that expose
``register()``, validates the returned dict, and stores them in the global
registry keyed by **plugin name**.

``get_loaded_plugins()`` returns the same registry at any later point so
that routes, services, or other plugins can look up loaded plugins and call
their hooks without re-importing anything.
"""

import importlib
import pkgutil
from typing import Any, TypedDict

import app.plugins
from app.core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Contract type
# ---------------------------------------------------------------------------

class PluginInfo(TypedDict, total=False):
    """Typed contract for the dict returned by every plugin's ``register()``."""

    name: str                   # required
    version: str                # required
    description: str            # required
    author: str                 # required
    hooks: dict[str, Any]       # required – map of hook_name → callable
    tags: list[str]             # optional
    enabled: bool               # optional – defaults to True


_REQUIRED_KEYS = ("name", "version", "description", "author", "hooks")

# ---------------------------------------------------------------------------
# Global registry
# ---------------------------------------------------------------------------

_PLUGIN_REGISTRY: dict[str, PluginInfo] = {}


def load_plugins() -> dict[str, PluginInfo]:
    """Discover and load all plugins from the ``app/plugins`` package.

    Iterates every sub-module, imports those that expose ``register()``,
    validates the returned :class:`PluginInfo` dict, and stores the result in
    the global registry keyed by **plugin name**.

    Returns the populated registry so callers can inspect results immediately.
    """
    global _PLUGIN_REGISTRY
    _PLUGIN_REGISTRY = {}

    for _, module_name, _ in pkgutil.iter_modules(app.plugins.__path__):
        # Skip the loader itself
        if module_name == "plugin_loader":
            continue

        try:
            module = importlib.import_module(f"app.plugins.{module_name}")

            if not hasattr(module, "register"):
                logger.debug("Skipping %s – no register() function", module_name)
                continue

            info: PluginInfo = module.register()

            # Minimal contract validation
            missing = [k for k in _REQUIRED_KEYS if k not in info]
            if missing:
                logger.warning(
                    "Plugin %s is missing required keys %s – skipped",
                    module_name,
                    missing,
                )
                continue

            key = info["name"]  # type: ignore[literal-required]
            _PLUGIN_REGISTRY[key] = info
            logger.info("Loaded plugin: %s v%s", info["name"], info["version"])  # type: ignore[literal-required]

        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load plugin %s: %s", module_name, exc)

    logger.info("Plugin loader: %d plugin(s) active", len(_PLUGIN_REGISTRY))
    return _PLUGIN_REGISTRY


def get_loaded_plugins() -> dict[str, PluginInfo]:
    """Return the current plugin registry (populated at startup by :func:`load_plugins`)."""
    return _PLUGIN_REGISTRY
