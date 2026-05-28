"""Built-in action package.

Importing this module triggers ``@register_action`` side effects for every
built-in adapter, so :func:`app.playbooks.registry.get_action` can resolve
``block``, ``revoke``, ``alert``, ``quarantine``, ``ticket``, and
``rate_limit`` immediately after import.

Custom actions placed in this package are also auto-loaded by the
discovery in :func:`app.playbooks.load_builtin_actions`.
"""

from app.playbooks.actions import (  # noqa: F401  side-effect imports
    alert,
    block,
    quarantine,
    ratelimit,
    revoke,
    ticket,
)
