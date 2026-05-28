"""Sample Plugin: PII & Sensitive-Data Watchlist
================================================

This plugin demonstrates a practical use of the plugin system.  It maintains a
categorised watchlist of sensitive keyword / regex patterns (PII, credentials,
internal identifiers) and exposes hook callables that any part of the
application can invoke without knowing the plugin's internals.

Hook summary
------------
``scan_text(text: str) -> list[dict]``
    Scan arbitrary text and return a list of hit dicts, each with:
    ``category``, ``keyword``, ``severity``, ``match``, ``start``, ``end``.

``get_watchlist_info() -> list[dict]``
    Return the full watchlist catalogue (category, label, severity) without
    regex objects so it can be serialised safely.

``summarise(text: str) -> dict``
    Convenience wrapper – returns ``{"hits": [...], "hit_count": n,
    "max_severity": n, "categories": [...unique categories...]}``.

Usage example (from application code)
--------------------------------------
    from app.plugins.plugin_loader import get_loaded_plugins

    plugins = get_loaded_plugins()
    if "PII Watchlist" in plugins:
        scan_fn = plugins["PII Watchlist"]["hooks"]["scan_text"]
        hits = scan_fn("My SSN is 123-45-6789 and email is user@example.com")
        # hits -> [
        #   {"category": "pii", "keyword": "ssn", "severity": 5, ...},
        #   {"category": "pii", "keyword": "email", "severity": 3, ...},
        # ]
"""

import re
from typing import Any

# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------

PLUGIN_NAME = "PII Watchlist"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = (
    "Scans text for personally-identifiable information (PII) and sensitive "
    "credential patterns using a categorised keyword/regex watchlist. "
    "Exposes scan_text, get_watchlist_info, and summarise hooks."
)
PLUGIN_AUTHOR = "Core Platform Team"
PLUGIN_TAGS = ["security", "pii", "compliance", "watchlist", "credentials"]

# ---------------------------------------------------------------------------
# Watchlist definition
# Each entry: (category, label, regex_pattern, severity 1-5)
# ---------------------------------------------------------------------------

_WATCHLIST_RAW: list[tuple[str, str, str, int]] = [
    # ── PII ──────────────────────────────────────────────────────────────────
    ("pii", "ssn",
     r"\b\d{3}-\d{2}-\d{4}\b",
     5),
    ("pii", "email",
     r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
     3),
    ("pii", "phone_us",
     r"\b(?:\+1\s?)?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}\b",
     3),
    ("pii", "credit_card",
     r"\b(?:4\d{3}|5[1-5]\d{2}|6011|3[47]\d{2})[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b",
     5),
    ("pii", "date_of_birth",
     r"\b(?:dob|date of birth|born on)\s*[:\-]?\s*\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b",
     4),
    ("pii", "ip_address",
     r"\b(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)"
     r"\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b",
     2),

    # ── Credentials ──────────────────────────────────────────────────────────
    ("credential", "aws_access_key",
     r"\bAKIA[0-9A-Z]{16}\b",
     5),
    ("credential", "aws_secret_key",
     r"(?i)aws[_\-]?secret[_\-]?(?:access[_\-]?)?key\s*[:=]\s*\S+",
     5),
    ("credential", "api_key_generic",
     r"(?i)\b(?:api[_\-]?key|apikey)\s*[:=]\s*\S+",
     4),
    ("credential", "bearer_token",
     r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*",
     4),
    ("credential", "password_literal",
     r"(?i)\bpassword\s*[:=]\s*\S+",
     4),
    ("credential", "private_key_header",
     r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
     5),
    ("credential", "github_token",
     r"\bghp_[A-Za-z0-9]{36}\b",
     5),

    # ── Sensitive labels ──────────────────────────────────────────────────────
    ("sensitive", "confidential_label",
     r"(?i)\b(confidential|top secret|internal use only|do not distribute|proprietary)\b",
     3),
    ("sensitive", "pii_label",
     r"(?i)\b(personally identifiable information|PII|GDPR|HIPAA|PHI)\b",
     3),
]

# Compile once at import time
_COMPILED: list[tuple[str, str, re.Pattern[str], int]] = [
    (cat, label, re.compile(pattern), severity)
    for cat, label, pattern, severity in _WATCHLIST_RAW
]


# ---------------------------------------------------------------------------
# Hook implementations
# ---------------------------------------------------------------------------

def _scan_text(text: str) -> list[dict[str, Any]]:
    """Scan *text* against the watchlist and return a list of hit dicts.

    Each hit dict contains::

        {
            "category": str,   # watchlist category (pii / credential / sensitive)
            "keyword":  str,   # watchlist entry label
            "severity": int,   # 1 (low) – 5 (critical)
            "match":    str,   # the matched substring
            "start":    int,   # character offset of match start
            "end":      int,   # character offset of match end
        }
    """
    hits: list[dict[str, Any]] = []
    for category, label, pattern, severity in _COMPILED:
        for m in pattern.finditer(text):
            hits.append(
                {
                    "category": category,
                    "keyword": label,
                    "severity": severity,
                    "match": m.group(),
                    "start": m.start(),
                    "end": m.end(),
                }
            )
    return hits


def _get_watchlist_info() -> list[dict[str, Any]]:
    """Return a serialisable catalogue of every watchlist entry.

    Returns a list of dicts with keys ``category``, ``label``, ``severity``.
    No regex / callable objects are included so the output is JSON-safe.
    """
    return [
        {"category": cat, "label": label, "severity": severity}
        for cat, label, _, severity in _WATCHLIST_RAW
    ]


def _summarise(text: str) -> dict[str, Any]:
    """Convenience wrapper around :func:`_scan_text`.

    Returns::

        {
            "hits":          list[dict],   # full hit list from scan_text
            "hit_count":     int,
            "max_severity":  int,          # 0 when no hits
            "categories":    list[str],    # unique categories that fired
        }
    """
    hits = _scan_text(text)
    return {
        "hits": hits,
        "hit_count": len(hits),
        "max_severity": max((h["severity"] for h in hits), default=0),
        "categories": sorted({h["category"] for h in hits}),
    }


# ---------------------------------------------------------------------------
# Plugin interface – required entry point
# ---------------------------------------------------------------------------

def register() -> dict[str, Any]:
    """Return plugin metadata and hook callables.

    This is the **only** public contract required by the plugin loader.
    All hook callables are pure functions with no shared mutable state so they
    are safe to call concurrently.
    """
    return {
        "name": PLUGIN_NAME,
        "version": PLUGIN_VERSION,
        "description": PLUGIN_DESCRIPTION,
        "author": PLUGIN_AUTHOR,
        "tags": PLUGIN_TAGS,
        "enabled": True,
        "hooks": {
            # Primary hook – scan raw text, returns list of hit dicts
            "scan_text": _scan_text,
            # Catalogue hook – inspect what the watchlist contains (JSON-safe)
            "get_watchlist_info": _get_watchlist_info,
            # Convenience hook – summary dict for quick dashboards
            "summarise": _summarise,
        },
    }
