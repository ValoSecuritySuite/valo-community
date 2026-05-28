

import json
import re
from typing import Any

from app.core.logging import get_logger
from app.schemas import InputKind, NormalizedInput

logger = get_logger(__name__)

# Default encoding used when no BOM or declaration is found
_DEFAULT_ENCODING = "utf-8"

# Regex for common BOM / encoding declarations
_XML_ENCODING_RE = re.compile(rb'<\?xml[^>]*encoding=["\']([^"\']+)["\']', re.IGNORECASE)


def _detect_encoding(raw: bytes) -> str:
    """Best-effort encoding detection from BOM or XML declaration."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if raw.startswith(b"\xfe\xff"):
        return "utf-16-be"
    m = _XML_ENCODING_RE.search(raw[:200])
    if m:
        return m.group(1).decode("ascii", errors="replace")
    return _DEFAULT_ENCODING


def _clean_text(text: str) -> str:
    """Normalise whitespace while preserving newlines (useful for code/logs)."""
    # Replace carriage returns; collapse runs of spaces/tabs to single space per line
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines)


# ── Public normalizers ────────────────────────────────────────────────────────


def normalize_text(
    text: str,
    target: str = "text-input",
    metadata: dict[str, Any] | None = None,
) -> NormalizedInput:
    """Normalise a raw text string."""
    clean = _clean_text(text)
    return NormalizedInput(
        target=target,
        content=clean,
        metadata=metadata or {},
        input_kind="text",
        content_length=len(clean),
        encoding="utf-8",
    )


def normalize_json(
    data: dict[str, Any],
    target: str = "json-input",
    metadata: dict[str, Any] | None = None,
) -> NormalizedInput:
    """Normalise a JSON/dict object.

    The dict is serialised to a pretty-printed JSON string that the text-scan
    and context engines can both operate on. Key-value pairs are also merged
    into ``metadata`` so the context rule engine can match on them directly.
    """
    serialised = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    merged_meta = {**(metadata or {}), **{k: v for k, v in data.items() if isinstance(k, str)}}
    return NormalizedInput(
        target=target,
        content=serialised,
        metadata=merged_meta,
        input_kind="json",
        content_length=len(serialised),
        encoding="utf-8",
    )


def normalize_bytes(
    raw: bytes,
    target: str = "bytes-input",
    filename: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> NormalizedInput:
    """Normalise raw bytes (e.g. a file upload).

    Tries to decode using detected encoding; falls back to latin-1 (lossless).
    """
    enc = _detect_encoding(raw)
    try:
        text = raw.decode(enc)
    except (UnicodeDecodeError, LookupError):
        logger.warning("Could not decode bytes as %s – falling back to latin-1", enc)
        text = raw.decode("latin-1")
        enc = "latin-1"

    clean = _clean_text(text)
    meta = metadata or {}
    if filename:
        meta = {**meta, "filename": filename}
    return NormalizedInput(
        target=target or filename or "bytes-input",
        content=clean,
        metadata=meta,
        input_kind="bytes",
        content_length=len(clean),
        encoding=enc,
    )


def normalize(
    raw: str | bytes | dict[str, Any],
    target: str = "input",
    metadata: dict[str, Any] | None = None,
    filename: str | None = None,
) -> NormalizedInput:
    """Dispatch to the correct normalizer based on *raw*'s type.

    This is the single entry point used by the pipeline.
    """
    if isinstance(raw, bytes):
        return normalize_bytes(raw, target=target, filename=filename, metadata=metadata)
    if isinstance(raw, dict):
        return normalize_json(raw, target=target, metadata=metadata)
    return normalize_text(str(raw), target=target, metadata=metadata)
