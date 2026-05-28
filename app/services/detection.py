

import re

from app.core.logging import get_logger
from app.schemas import DetectionFlags, NormalizedInput

logger = get_logger(__name__)

# ── Quick-hit regex patterns ──────────────────────────────────────────────────

_RE_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_RE_IP = re.compile(
    r"\b(?:25[0-5]|2[0-4]\d|[01]?\d\d?)(?:\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)){3}\b"
)
_RE_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_RE_SECRET_KW = re.compile(
    r"\b(?:password|passwd|secret|private_key|api_key|access_token|auth_token|bearer)\b",
    re.IGNORECASE,
)
# Base64 blobs ≥ 20 chars with typical base64 alphabet
_RE_BASE64 = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")
_RE_CREDIT_CARD = re.compile(r"\b(?:\d[ -]?){13,16}\b")
_RE_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# ── Content-type heuristics ───────────────────────────────────────────────────

_JSON_START = re.compile(r"^\s*[\[{]")
_XML_START = re.compile(r"^\s*<(?:\?xml|!DOCTYPE|\w)", re.IGNORECASE)
_HTML_START = re.compile(r"^\s*<!DOCTYPE\s+html|<html", re.IGNORECASE)

# Code indicators: import / def / class / function / SELECT / CREATE TABLE …
_CODE_HINTS = re.compile(
    r"\b(?:import|from\s+\w+\s+import|def\s+\w+|class\s+\w+|function\s+\w+|"
    r"SELECT\s+|INSERT\s+INTO|CREATE\s+TABLE|DROP\s+TABLE|ALTER\s+TABLE)\b",
    re.IGNORECASE,
)

# Language fingerprints
_LANG_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("python", re.compile(r"\bdef\s+\w+\s*\(|import\s+\w+|from\s+\w+\s+import\b")),
    ("javascript", re.compile(r"\bfunction\s+\w+\s*\(|const\s+\w+\s*=|let\s+\w+\s*=|=>\s*{")),
    ("sql", re.compile(r"\b(?:SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER)\s+", re.IGNORECASE)),
    ("shell", re.compile(r"^#!.*(?:bash|sh|zsh)|^\s*(?:echo|export|source|chmod)\s+", re.MULTILINE)),
    ("java", re.compile(r"\bpublic\s+(?:class|static|void)\b|System\.out\.print")),
    ("csharp", re.compile(r"\busing\s+System|namespace\s+\w+|Console\.Write")),
    ("ruby", re.compile(r"\bdef\s+\w+\s*\n|require\s+'|puts\s+")),
    ("go", re.compile(r'\bpackage\s+\w+\s*\n|import\s+\(|func\s+\w+\s*\(')),
]


def _infer_content_type(content: str, input_kind: str) -> str:
    """Heuristically determine content type."""
    if input_kind == "json":
        return "json"
    snip = content[:2048]
    if _HTML_START.search(snip):
        return "html"
    if _XML_START.search(snip):
        return "xml"
    if _JSON_START.search(snip) and input_kind != "text":
        return "json"
    if _CODE_HINTS.search(snip):
        return "code"
    return "text"


def _infer_language(content: str, content_type: str) -> str | None:
    """Return a probable programming language or None."""
    if content_type not in ("code", "text"):
        return None
    snip = content[:4096]
    for lang, pattern in _LANG_PATTERNS:
        if pattern.search(snip):
            return lang
    return None


def _collect_flags(content: str) -> list[str]:
    """Return a list of quick-hit signal flags."""
    flags: list[str] = []
    if _RE_EMAIL.search(content):
        flags.append("contains_email")
    if _RE_IP.search(content):
        flags.append("contains_ip")
    if _RE_URL.search(content):
        flags.append("contains_url")
    if _RE_SECRET_KW.search(content):
        flags.append("contains_secret_keyword")
    if _RE_BASE64.search(content):
        flags.append("contains_base64_blob")
    if _RE_CREDIT_CARD.search(content):
        flags.append("contains_credit_card_candidate")
    if _RE_SSN.search(content):
        flags.append("contains_ssn_pattern")
    if _CODE_HINTS.search(content[:2048]):
        flags.append("possibly_code")
    return flags


# ── Public API ────────────────────────────────────────────────────────────────


def detect(normalized: NormalizedInput) -> DetectionFlags:
    """Run detection utilities on a normalised input and return signal flags.

    This is a pure, side-effect-free function – safe to call in tests.
    """
    content = normalized.content
    content_type = _infer_content_type(content, normalized.input_kind)
    detected_language = _infer_language(content, content_type)
    flags = _collect_flags(content)
    token_count = len(content.split())
    line_count = content.count("\n") + 1

    logger.debug(
        "Detection: target=%s type=%s lang=%s flags=%s tokens=%d",
        normalized.target,
        content_type,
        detected_language,
        flags,
        token_count,
    )

    return DetectionFlags(
        content_type=content_type,
        detected_language=detected_language,
        token_count=token_count,
        line_count=line_count,
        flags=flags,
    )
