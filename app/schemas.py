import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_MAX_LOGO_BYTES = 1024 * 1024
_ALLOWED_LOGO_MIME_PREFIXES = ("data:image/png;base64,", "data:image/jpeg;base64,")


class ErrorDetail(BaseModel):
    """Error detail for API responses."""

    code: str = Field(description="Error code")
    message: str = Field(description="Human-readable message")
    detail: dict[str, Any] | None = Field(default=None, description="Additional context")


class ErrorResponse(BaseModel):
    """Standard error response schema."""

    error: ErrorDetail = Field(description="Error information")


class HealthResponse(BaseModel):
    status: str


_ALLOWED_RATE_LIMIT_UNITS = {"second", "minute", "hour", "day"}
_ALLOWED_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def _normalize_rate_limit(value: str) -> str:
    raw = str(value or "").strip()
    if "/" not in raw:
        raise ValueError("Rate limit must be in the format '<count>/<unit>', e.g., 60/minute")

    count_part, unit_part = raw.split("/", 1)
    try:
        count = int(count_part.strip())
    except ValueError as exc:
        raise ValueError("Rate limit count must be an integer") from exc

    if count <= 0:
        raise ValueError("Rate limit count must be greater than 0")

    unit = unit_part.strip().lower()
    if unit.endswith("s"):
        unit = unit[:-1]

    if unit not in _ALLOWED_RATE_LIMIT_UNITS:
        raise ValueError("Rate limit unit must be one of: second, minute, hour, day")

    return f"{count}/{unit}"


class EndpointRateLimit(BaseModel):
    """Rate limit configuration for a specific API endpoint."""

    model_config = ConfigDict(extra="forbid")

    method: str = Field(description="HTTP method")
    path: str = Field(description="Endpoint path")
    limit: str = Field(description="Applied request rate limit")

    @field_validator("method")
    @classmethod
    def _validate_method(cls, value: str) -> str:
        method = str(value or "").strip().upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}:
            raise ValueError("Unsupported HTTP method")
        return method

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        path = str(value or "").strip()
        if not path.startswith("/"):
            raise ValueError("Endpoint path must start with '/'")
        return path

    @field_validator("limit")
    @classmethod
    def _validate_limit(cls, value: str) -> str:
        return _normalize_rate_limit(value)


class BackendSettingsResponse(BaseModel):
    """UI-safe view of key backend operational settings."""

    rules_path: str = Field(description="Configured rules file path")
    rules_file_exists: bool = Field(description="Whether the configured rules file exists")
    log_level: str = Field(description="Configured application log level")
    default_rate_limit: str = Field(description="Global default API rate limit")
    rules_cache_ttl_seconds: int = Field(description="Rules cache TTL in seconds")
    rules_cache_enabled: bool = Field(description="Whether rules caching is enabled")
    endpoint_rate_limits: List[EndpointRateLimit] = Field(
        default_factory=list,
        description="Per-endpoint rate limit settings",
    )


class BackendSettingsUpdateRequest(BaseModel):
    """Patch payload for runtime backend settings updates from UI."""

    model_config = ConfigDict(extra="forbid")

    log_level: str | None = Field(default=None, description="Logging level")
    default_rate_limit: str | None = Field(default=None, description="Default API rate limit")
    rules_cache_ttl_seconds: int | None = Field(
        default=None,
        ge=0,
        description="Rules cache TTL in seconds",
    )
    rules_cache_enabled: bool | None = Field(
        default=None,
        description="Optional cache toggle; false forces TTL to 0",
    )
    endpoint_rate_limits: List[EndpointRateLimit] | None = Field(
        default=None,
        description="Updated per-endpoint rate limits",
    )

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str | None) -> str | None:
        if value is None:
            return None
        level = str(value).strip().upper()
        if level not in _ALLOWED_LOG_LEVELS:
            raise ValueError("Unsupported log level")
        return level

    @field_validator("default_rate_limit")
    @classmethod
    def _validate_default_rate_limit(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_rate_limit(value)


PatternOp = Literal[
    "eq",
    "neq",
    "in",
    "not_in",
    "contains",
    "not_contains",
    "gte",
    "lte",
    "gt",
    "lt",
    "matches",
    "exists",
    "not_exists",
]


class Pattern(BaseModel):
    """Single pattern condition for rule matching."""

    model_config = ConfigDict(extra="ignore")

    field: str = Field(min_length=1, description="Context field path (e.g., 'severity', 'user.role')")
    op: PatternOp = Field(description="Comparison operator")
    value: Any | None = Field(default=None, description="Value to compare (omit for exists/not_exists)")


class Rule(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)
    severity: int = Field(ge=1, le=5)
    weight: float = Field(gt=0, description="Weight to score risk")
    enabled: bool = True
    patterns: List[Pattern] = Field(default_factory=list, description="Patterns (all must match)")


TextScanRuleCategory = Literal["regex", "keyword", "entropy"]


class TextScanRule(BaseModel):
    """A rule for scanning raw text content by regex, keyword, or entropy analysis."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, description="Unique rule identifier")
    family: Optional[str] = Field(default=None, description="Detection rule family for breadth scoring")
    category: TextScanRuleCategory = Field(description="Rule category: regex, keyword, or entropy")
    pattern: str = Field(default="", description="Pattern string (regex or keyword; may be empty for entropy)")
    severity: int = Field(ge=1, le=5, description="Severity level 1-5")
    weight: float = Field(gt=0, description="Weight for risk scoring")
    enabled: bool = True
    description: Optional[str] = Field(default=None, description="Human-readable description")

    @model_validator(mode="after")
    def _validate_pattern_for_category(self) -> "TextScanRule":
        if self.category in ("regex", "keyword") and not self.pattern:
            raise ValueError(
                f"Rule '{self.id}': 'pattern' must not be empty for category '{self.category}'"
            )
        return self


class TextFinding(BaseModel):
    """A single finding from text scanning."""

    rule_id: str = Field(description="ID of the rule that matched")
    family: Optional[str] = Field(default=None, description="Detection rule family")
    category: str = Field(description="Rule category that produced this finding")
    severity: int = Field(ge=1, le=5)
    weight: float
    evidence: str = Field(description="Matched text snippet with surrounding context")
    match_start: Optional[int] = Field(default=None, description="Start character offset of the match")
    match_end: Optional[int] = Field(default=None, description="End character offset of the match")


class MatchedFragment(BaseModel):
    """A single fragment of the input prompt that matched a rule."""

    evidence: str = Field(description="Matched text snippet (with surrounding context)")
    match_start: int = Field(description="Start character offset in the prompt")
    match_end: int = Field(description="End character offset in the prompt")


class MatchedRuleDetail(BaseModel):
    """One rule that matched the prompt, with all fragments of the prompt that matched it."""

    rule_id: str = Field(description="ID of the rule that matched")
    description: Optional[str] = Field(default=None, description="Human-readable rule description")
    family: Optional[str] = Field(default=None, description="Detection rule family")
    severity: int = Field(ge=1, le=5, description="Rule severity (1-5)")
    matched_fragments: List[MatchedFragment] = Field(
        default_factory=list,
        description="Parts of the input prompt that matched this rule",
    )


class TextScanResult(BaseModel):
    """Aggregated result of scanning raw text against text-scan rules."""

    findings: List[TextFinding] = Field(default_factory=list)
    total_score: float = Field(default=0.0, ge=0, description="Normalised 0-100 risk score")
    matched_count: int = Field(default=0, ge=0, description="Total number of individual matches found")


class RuleSet(BaseModel):
    rules: List[Rule] = Field(default_factory=list)
    text_scan_rules: List[TextScanRule] = Field(
        default_factory=list,
        description="Text-scan rules (regex / keyword / entropy)",
    )


class RuleSetResponse(BaseModel):
    rules: List[Rule]
    text_scan_rules: List[TextScanRule] = Field(default_factory=list)
    rules_info: "RulesInfo" = Field(description="Summary metadata for the loaded rules file")


class RuleMatch(BaseModel):
    """Result of a single rule match."""

    rule_name: str
    severity: int
    weight: float
    matched: bool


class RuleEngineResult(BaseModel):
    """Deterministic result of rule engine evaluation."""

    matched_rules: List[RuleMatch] = Field(default_factory=list)
    total_score: float = Field(default=0.0, ge=0)
    passed_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)


class PdfRequest(BaseModel):
    title: str = Field(min_length=1)
    lines: List[str] = Field(default_factory=list, max_length=50)


class ScanInput(BaseModel):
    target: str = Field(min_length=1, description="Input identifier or source")
    content: str = Field(min_length=1, description="Raw content to evaluate")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Optional context")


# ── JSON Report schema ───────────────────────────────────────────────────────


class ContextRuleSummary(BaseModel):
    """Lightweight summary of a single context rule as stored in the report."""

    name: str
    severity: int
    weight: float
    enabled: bool
    pattern_count: int = Field(description="Number of patterns in this rule")


class TextScanRuleSummary(BaseModel):
    """Lightweight summary of a single text-scan rule as stored in the report."""

    id: str
    family: Optional[str] = None
    category: str
    severity: int
    weight: float
    enabled: bool
    description: Optional[str] = None


class RulesInfo(BaseModel):
    """Metadata about the rule file used during this scan."""

    filename: str = Field(description="Base filename of the rules file")
    filepath: str = Field(description="Absolute path to the rules file")
    context_rule_count: int = Field(ge=0, description="Number of context rules loaded")
    text_scan_rule_count: int = Field(ge=0, description="Number of text-scan rules loaded")
    total_rule_count: int = Field(ge=0, description="Total rules (context + text-scan)")
    context_rules: List[ContextRuleSummary] = Field(
        default_factory=list,
        description="Summary of each context rule",
    )
    text_scan_rules: List[TextScanRuleSummary] = Field(
        default_factory=list,
        description="Summary of each text-scan rule",
    )


class ScanReport(BaseModel):
    """Standardised JSON report generated after every scan.

    Designed to be exported as-is or stored for later retrieval.
    """

    scan_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this scan run",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the scan completed",
    )
    risk_score: float = Field(
        ge=0,
        description="Normalised 0-100 risk score for this scan",
    )
    max_severity_found: int = Field(
        default=0,
        ge=0,
        description="Highest severity level (1-5) detected in this scan; 0 when no findings",
    )
    severity_ceiling_applied: bool = Field(
        default=False,
        description="True when a CVSS-inspired severity floor was applied to risk_score",
    )
    input_prompt: str = Field(
        default="",
        description="The prompt that was scanned",
    )
    matched_rule_details: List[MatchedRuleDetail] = Field(
        default_factory=list,
        description="For each matched rule: rule id, description, and the prompt fragments that matched",
    )
    findings: List[TextFinding] = Field(
        default_factory=list,
        description="Evidence-rich findings from the text-scan engine",
    )
    matched_rules: List[RuleMatch] = Field(
        default_factory=list,
        description="Context rule matches with name, severity, weight and match status",
    )
    rules_info: Optional[RulesInfo] = Field(
        default=None,
        description="Details about the rule file used: filename, counts, and rule list",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Scan context – target, input kind, detection flags, etc.",
    )
    policy_decisions: List["PolicyDecision"] = Field(
        default_factory=list,
        description="Decision emitted by each enabled governance policy during this scan",
    )
    final_decision: "PolicyDecisionLiteral" = Field(
        default="allow",
        description="Aggregate governance decision (precedence: deny > warn > allow)",
    )


class ScanInputResponse(BaseModel):
    accepted: bool
    target: str
    content_length: int
    message: str
    matched_rules: List[RuleMatch] = Field(default_factory=list)
    total_score: float = Field(default=0.0, ge=0)
    passed_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    # ── text-scan results ────────────────────────────────────────────────
    text_findings: List[TextFinding] = Field(default_factory=list)
    text_scan_score: float = Field(default=0.0, ge=0, description="Normalised 0-100 text-scan risk score")
    text_matched_count: int = Field(default=0, ge=0, description="Number of individual text matches")
    # ── exportable report ────────────────────────────────────────────────
    report: Optional[ScanReport] = Field(default=None, description="Structured JSON report ready for export")


# ── Pipeline schemas ──────────────────────────────────────────────────────────

InputKind = Literal["text", "json", "bytes"]


class NormalizedInput(BaseModel):
    """Canonical form produced by the normalizer from any accepted input type."""

    target: str = Field(default="unknown", description="Source identifier")
    content: str = Field(description="Clean, decoded text content ready for analysis")
    metadata: dict[str, Any] = Field(default_factory=dict)
    input_kind: InputKind = Field(default="text", description="How the input arrived")
    content_length: int = Field(ge=0)
    encoding: Optional[str] = Field(default=None, description="Detected or declared encoding")


class DetectionFlags(BaseModel):
    """Quick-scan flags emitted by the detection-utilities step."""

    content_type: str = Field(default="text", description="Inferred content type (code, json, text, …)")
    detected_language: Optional[str] = Field(default=None, description="Probable programming language if code")
    token_count: int = Field(default=0, ge=0)
    line_count: int = Field(default=0, ge=0)
    flags: List[str] = Field(default_factory=list, description="Quick-hit flags e.g. 'contains_email'")


class ReportBranding(BaseModel):
    """Optional branding for executive PDF reports."""

    company_name: Optional[str] = Field(
        default=None,
        description="Company name to display on the PDF report",
    )
    logo_base64: Optional[str] = Field(
        default=None,
        description=(
            "Base64-encoded logo image (optionally a data URL with a base64 payload)"
        ),
    )

    @field_validator("logo_base64")
    @classmethod
    def _validate_logo_base64(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = value.strip()
        if text.startswith("data:") and not text.startswith(_ALLOWED_LOGO_MIME_PREFIXES):
            raise ValueError("logo_base64 must be a PNG or JPEG data URL")

        payload = text
        if text.startswith("data:"):
            payload = text.split(",", 1)[-1]
        # Rough size check before decoding: base64 expands by ~4/3
        if len(payload) > int(_MAX_LOGO_BYTES * 4 / 3) + 16:
            raise ValueError("logo_base64 exceeds 1MB limit")
        return value


class PipelineRequest(BaseModel):
    """Request body for the prompt-injection scan pipeline.

    The pipeline accepts a single prompt string and runs only prompt-injection
    detection rules (no context rules). Risk is identified and flagged from
    the prompt content alone.
    """

    prompt: Optional[str] = Field(default=None, min_length=1, description="User prompt to scan for injection risk")
    target: str = Field(default="prompt", description="Optional source label for the prompt")
    report_branding: Optional[ReportBranding] = Field(
        default=None,
        description="Optional branding data used when exporting PDF reports",
    )
    # Backward compatibility: 'text' is alias for 'prompt'
    text: Optional[str] = Field(default=None, description="Alias for prompt (use 'prompt' for new code)")

    @model_validator(mode="after")
    def _prompt_required(self) -> "PipelineRequest":
        if not self.prompt and not self.text:
            raise ValueError("Provide 'prompt' or 'text'")
        if not self.prompt and self.text:
            object.__setattr__(self, "prompt", self.text)
        return self


class PipelineResult(BaseModel):
    """Complete result of the Accept → Normalize → Detect → Rule Engine pipeline."""

    # ── input prompt (what was scanned) ───────────────────────────────────────
    input_prompt: str = Field(
        default="",
        description="The prompt that was scanned (same as normalized.content)",
    )
    # ── which rules matched and what part of the prompt matched ────────────────
    matched_rule_details: List[MatchedRuleDetail] = Field(
        default_factory=list,
        description="For each matched rule: rule id, description, and the prompt fragments that matched",
    )
    # ── normalizer output ─────────────────────────────────────────────────────
    normalized: NormalizedInput
    # ── detection utilities output ────────────────────────────────────────────
    detection: DetectionFlags
    # ── context rule engine output ────────────────────────────────────────────
    matched_rules: List[RuleMatch] = Field(default_factory=list)
    context_score: float = Field(default=0.0, ge=0, description="Normalised 0-100 context-rule score")
    passed_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    # ── text-scan engine output ───────────────────────────────────────────────
    text_findings: List[TextFinding] = Field(default_factory=list)
    text_scan_score: float = Field(default=0.0, ge=0, description="Normalised 0-100 text-scan score")
    text_matched_count: int = Field(default=0, ge=0)
    # ── combined risk ─────────────────────────────────────────────────────────
    combined_score: float = Field(default=0.0, ge=0, description="Average of context + text-scan scores")
    # ── policy engine output (governance) ─────────────────────────────────────
    policy_decisions: List["PolicyDecision"] = Field(
        default_factory=list,
        description="Decision emitted by each enabled governance policy",
    )
    final_decision: "PolicyDecisionLiteral" = Field(
        default="allow",
        description="Aggregate policy decision (precedence: deny > warn > allow)",
    )
    # ── exportable report ────────────────────────────────────────────────────
    report: Optional[ScanReport] = Field(default=None, description="Structured JSON report ready for export")
    # ── correlation engine fingerprint ───────────────────────────────────────
    prompt_fingerprint: Optional[str] = Field(
        default=None,
        description=(
            "Stable SHA-256 fingerprint of the normalized prompt content, used "
            "by the Correlation Engine to link the same prompt observed across "
            "tenants without storing the plaintext."
        ),
    )


class AnalyzeResponse(BaseModel):
    """Minimal API response contract for POST /analyze."""

    input_prompt: str = Field(
        default="",
        description="The prompt that was scanned (same as normalized.content)",
    )
    matched_rule_details: List[MatchedRuleDetail] = Field(
        default_factory=list,
        description="For each matched rule: rule id, description, and the prompt fragments that matched",
    )
    normalized: NormalizedInput
    detection: DetectionFlags
    matched_rules: List[RuleMatch] = Field(default_factory=list)
    context_score: float = Field(default=0.0, ge=0, description="Normalised 0-100 context-rule score")
    passed_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    combined_score: float = Field(default=0.0, ge=0, description="Combined deterministic risk score")
    policy_decisions: List["PolicyDecision"] = Field(
        default_factory=list,
        description="Decision emitted by each enabled governance policy during this analyze run",
    )
    final_decision: "PolicyDecisionLiteral" = Field(
        default="allow",
        description="Aggregate governance decision (precedence: deny > warn > allow)",
    )
    report: Optional["AnalyzeScanReport"] = Field(
        default=None,
        description="Structured JSON report ready for export (without rules_info)",
    )


class AnalyzeScanReport(BaseModel):
    """Report contract returned by POST /analyze (intentionally excludes rules_info)."""

    scan_id: str = Field(description="Unique identifier for this scan run")
    timestamp: datetime = Field(description="UTC timestamp when the scan completed")
    risk_score: float = Field(ge=0, description="Normalised 0-100 risk score for this scan")
    max_severity_found: int = Field(
        default=0,
        ge=0,
        description="Highest severity level (1-5) detected in this scan; 0 when no findings",
    )
    severity_ceiling_applied: bool = Field(
        default=False,
        description="True when a CVSS-inspired severity floor was applied to risk_score",
    )
    input_prompt: str = Field(default="", description="The prompt that was scanned")
    matched_rule_details: List[MatchedRuleDetail] = Field(
        default_factory=list,
        description="For each matched rule: rule id, description, and the prompt fragments that matched",
    )
    findings: List[TextFinding] = Field(
        default_factory=list,
        description="Evidence-rich findings from the text-scan engine",
    )
    matched_rules: List[RuleMatch] = Field(
        default_factory=list,
        description="Context rule matches with name, severity, weight and match status",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Scan context – target, input kind, detection flags, etc.",
    )
    policy_decisions: List["PolicyDecision"] = Field(
        default_factory=list,
        description="Decision emitted by each enabled governance policy during this scan",
    )
    final_decision: "PolicyDecisionLiteral" = Field(
        default="allow",
        description="Aggregate governance decision (precedence: deny > warn > allow)",
    )


class ScanFinding(BaseModel):
    """Finding payload used for portfolio-level aggregation inputs."""

    severity: int | str = Field(description="Severity value (numeric 1-5 or label)")
    category: str = Field(min_length=1, description="Finding category label")


class ScanResult(BaseModel):
    """Persisted, lightweight summary of a completed scan."""

    scan_id: str = Field(description="Unique identifier for this scan run")
    target: str = Field(default="unknown", description="Input target/source label")
    risk_score: float = Field(ge=0, le=100, description="Combined risk score for this scan")
    max_severity_found: int = Field(default=0, ge=0, le=5)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when this scan completed",
    )
    finding_count: int = Field(default=0, ge=0, description="Number of findings in this scan")
    severity_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Count of findings grouped by severity level",
    )
    category_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Count of findings grouped by category",
    )
    findings: List[ScanFinding] = Field(
        default_factory=list,
        description="Raw finding list used for portfolio aggregation",
    )


class PortfolioTrendPoint(BaseModel):
    """Single point in risk trend over time."""

    timestamp: datetime
    scan_id: str
    score: float = Field(ge=0, le=100)


class PortfolioSummary(BaseModel):
    """Executive-level portfolio aggregation output."""

    total_scans: int = Field(default=0, ge=0)
    average_score: float = Field(default=0.0, ge=0, le=100)
    highest_score: float = Field(default=0.0, ge=0, le=100)
    critical_count: int = Field(default=0, ge=0)
    distribution: dict[str, int] = Field(
        default_factory=dict,
        description="Risk-band distribution (critical/high/medium/low/minimal)",
    )
    severity_distribution: dict[str, int] = Field(
        default_factory=dict,
        description="Finding counts by severity (1..5)",
    )
    category_breakdown: dict[str, int] = Field(
        default_factory=dict,
        description="Category frequency heatmap for findings",
    )
    risk_trend: List[PortfolioTrendPoint] = Field(
        default_factory=list,
        description="Risk score trend ordered by scan timestamp",
    )


class PortfolioResponse(BaseModel):
    """Response contract for GET /portfolio."""

    summary: PortfolioSummary
    scans: List[ScanResult] = Field(default_factory=list, description="Scans sorted by risk score desc")
    risk_trend: List[PortfolioTrendPoint] = Field(default_factory=list)


class IngestNormalizeError(BaseModel):
    """One rejected record during ingest-normalize processing."""

    index: int = Field(ge=0, description="Zero-based index of the rejected candidate")
    reason: str = Field(min_length=1, description="Validation or normalization error")


class IngestNormalizeResponse(BaseModel):
    """Result of normalizing external payloads into ScanResult records and ingesting them."""

    accepted_count: int = Field(default=0, ge=0)
    rejected_count: int = Field(default=0, ge=0)
    normalized_scans: List[ScanResult] = Field(default_factory=list)
    errors: List[IngestNormalizeError] = Field(default_factory=list)
    portfolio_summary: PortfolioSummary


class PortfolioScanSummary(BaseModel):
    """Per-scan summary used in portfolio roll-up responses."""

    index: int = Field(ge=1, description="1-based position of this scan in the submitted list")
    scan_id: str = Field(description="Generated scan identifier")
    target: str = Field(description="Input target/source label")
    risk_score: float = Field(ge=0, le=100, description="Combined risk score for this scan")
    risk_level: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "MINIMAL"] = Field(
        description="Risk band derived from risk_score"
    )
    finding_count: int = Field(ge=0, description="Number of text findings in this scan")


class PortfolioRiskDistribution(BaseModel):
    """Count of scans per risk band."""

    critical: int = Field(default=0, ge=0)
    high: int = Field(default=0, ge=0)
    medium: int = Field(default=0, ge=0)
    low: int = Field(default=0, ge=0)
    minimal: int = Field(default=0, ge=0)


class PortfolioRollupRequest(BaseModel):
    """Request body for portfolio-level roll-up scoring across multiple scans."""

    scans: List[PipelineRequest] = Field(
        min_length=1,
        description="List of scan requests to aggregate into a single portfolio summary",
    )


class PortfolioRollupResponse(BaseModel):
    """Aggregated score and distribution across multiple scans."""

    scan_count: int = Field(ge=1, description="Total number of scans aggregated")
    portfolio_score: float = Field(ge=0, le=100, description="Average combined risk score across scans")
    max_risk_score: float = Field(ge=0, le=100, description="Maximum combined risk score in the portfolio")
    min_risk_score: float = Field(ge=0, le=100, description="Minimum combined risk score in the portfolio")
    total_findings: int = Field(ge=0, description="Total text findings across all scans")
    risk_distribution: PortfolioRiskDistribution = Field(
        description="Number of scans that fall into each risk band"
    )
    top_risky_scan: PortfolioScanSummary = Field(description="Scan summary with the highest risk score")
    scans: List[PortfolioScanSummary] = Field(
        default_factory=list,
        description="Per-scan portfolio breakdown in submission order",
    )


# ── Rules hot-reload schemas ──────────────────────────────────────────────────


class RuleReloadDiff(BaseModel):
    """What changed between the cached rule set and the freshly loaded one."""

    added: List[str] = Field(default_factory=list, description="Rule IDs/names new in the file")
    removed: List[str] = Field(default_factory=list, description="Rule IDs/names no longer in the file")
    changed: List[str] = Field(default_factory=list, description="Rules whose weight, enabled flag, or patterns differ")
    unchanged: int = Field(default=0, ge=0, description="Count of rules identical in both versions")


class RuleReloadResponse(BaseModel):
    """Response returned by POST /rules/reload."""

    reloaded_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the reload",
    )
    rules_file: str = Field(description="Filename of the loaded rules file")
    previous_rule_count: int = Field(ge=0, description="Total rules before reload")
    new_rule_count: int = Field(ge=0, description="Total rules after reload")
    diff: RuleReloadDiff = Field(description="Diff between old and new rule sets")


# ── Rule evaluation request/response schemas ─────────────────────────────────


class RuleEvalRequest(BaseModel):
    """Request body for POST /rules/evaluate (context to match against)."""

    model_config = ConfigDict(extra="forbid")

    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value context evaluated against context rules",
    )


# ── Policy Engine schemas (governance / compliance gates) ────────────────────


PolicyConditionOp = Literal[
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "contains",
    "matches",
    "exists",
    "not_exists",
]

PolicyDecisionLiteral = Literal["allow", "warn", "deny"]


class PolicyCondition(BaseModel):
    """One AND-conjoined predicate evaluated against the policy context."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, description="Dot-path into the policy context")
    op: PolicyConditionOp = Field(description="Comparison operator")
    value: Any | None = Field(
        default=None,
        description="Value to compare (omit for exists / not_exists)",
    )


class PolicyAction(BaseModel):
    """Outcome attached to a policy match."""

    model_config = ConfigDict(extra="forbid")

    decision: PolicyDecisionLiteral = Field(description="Allow, warn, or deny")
    severity: int = Field(ge=0, le=10, default=5, description="Severity of the decision (0-10)")
    message: str = Field(min_length=1, description="Human-readable rationale shown to operators")


class Policy(BaseModel):
    """A single governance policy persisted as YAML."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        min_length=1,
        max_length=80,
        description="Unique slug-style identifier; also used as the YAML filename",
    )
    name: str = Field(min_length=1, description="Display name")
    description: Optional[str] = Field(default=None, description="Free-form description")
    enabled: bool = Field(default=True, description="Disabled policies are skipped at evaluation time")
    enforce: bool = Field(
        default=True,
        description=(
            "When True, a matched deny policy actually blocks the request in enforce mode. "
            "When False, the policy still emits its decision but the enforcement layer logs it as "
            "'would_block' instead of returning 403 (per-policy soft rollout)."
        ),
    )
    when: List[PolicyCondition] = Field(
        default_factory=list,
        description="AND-conjoined conditions; empty matches every context",
    )
    then: PolicyAction = Field(description="Decision to emit when all conditions match")
    tags: List[str] = Field(
        default_factory=list,
        description="Categorisation labels (e.g. compliance:soc2, pii)",
    )
    version: int = Field(default=1, ge=1, description="Operator-managed version counter")
    updated_at: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp of the last persisted update",
    )

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        slug = str(value or "").strip()
        if not slug:
            raise ValueError("Policy id must not be empty")
        if not re.match(r"^[a-zA-Z0-9_\-]+$", slug):
            raise ValueError(
                "Policy id must contain only letters, digits, underscores, or hyphens"
            )
        return slug


class PolicySet(BaseModel):
    """Collection of governance policies loaded from disk."""

    policies: List[Policy] = Field(default_factory=list)


class PolicyDecision(BaseModel):
    """Outcome of evaluating one policy against a context."""

    policy_id: str = Field(description="Policy that produced this decision")
    name: str = Field(description="Policy display name")
    matched: bool = Field(description="True when all when-conditions matched")
    decision: PolicyDecisionLiteral = Field(
        description="Final action (allow when not matched, otherwise from policy.then)"
    )
    severity: int = Field(ge=0, le=10, description="Severity carried from the policy action")
    message: str = Field(description="Human-readable rationale")
    reasons: List[str] = Field(
        default_factory=list,
        description="Per-condition trace describing which fields matched",
    )
    tags: List[str] = Field(default_factory=list, description="Tags inherited from the policy")


class PolicyEvaluateRequest(BaseModel):
    """Request body for POST /policies/evaluate (context to evaluate)."""

    model_config = ConfigDict(extra="forbid")

    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary policy context (e.g. pipeline output)",
    )


class PolicyEvaluateResponse(BaseModel):
    """Aggregated decisions returned by POST /policies/evaluate."""

    decisions: List[PolicyDecision] = Field(default_factory=list)
    final_decision: PolicyDecisionLiteral = Field(
        default="allow",
        description="Aggregate decision (precedence: deny > warn > allow)",
    )


class PolicyListResponse(BaseModel):
    """Response payload for GET /policies."""

    policies: List[Policy] = Field(default_factory=list)
    total: int = Field(ge=0, description="Number of policies on disk")
    fingerprints: dict[str, str] = Field(
        default_factory=dict,
        description="policy_id -> stable fingerprint for change detection",
    )


class PolicyValidateResponse(BaseModel):
    """Response payload for POST /policies/validate."""

    valid: bool = Field(description="True when the body parses as a Policy")
    policy: Optional[Policy] = Field(
        default=None,
        description="Parsed policy when valid is True",
    )
    errors: List[str] = Field(
        default_factory=list,
        description="Validation errors when valid is False",
    )


class PolicyReloadResponse(BaseModel):
    """Response returned by POST /policies/reload."""

    reloaded_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the reload",
    )
    policies_path: str = Field(description="Configured policies directory")
    previous_policy_count: int = Field(ge=0, description="Total policies before reload")
    new_policy_count: int = Field(ge=0, description="Total policies after reload")
    diff: RuleReloadDiff = Field(
        description="Diff (added / removed / changed / unchanged) using policy ids"
    )


# ── Enforcement schemas (AI Firewall layer) ──────────────────────────────────


EnforcementMode = Literal["off", "monitor", "enforce"]


class EnforcementOutcome(BaseModel):
    """Result of running a payload through the policy enforcement layer.

    Shared between the ingress middleware and the egress LLM proxy so both
    surfaces speak a single decision contract.
    """

    trace_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Per-evaluation correlation id surfaced as X-Valo-Trace-Id",
    )
    mode: EnforcementMode = Field(description="Enforcement mode in effect at evaluation time")
    final_decision: PolicyDecisionLiteral = Field(
        default="allow",
        description="Aggregate decision from the policy engine (deny > warn > allow)",
    )
    decisions: List[PolicyDecision] = Field(
        default_factory=list,
        description="Per-policy decisions captured during evaluation",
    )
    matched_policy_ids: List[str] = Field(
        default_factory=list,
        description="Ids of the policies whose conditions matched",
    )
    blocked: bool = Field(
        default=False,
        description="True when the request was actually short-circuited (mode=enforce + enforce flag)",
    )
    would_block: bool = Field(
        default=False,
        description=(
            "True when the policies would have blocked under stricter settings "
            "(e.g. monitor mode, or per-policy enforce=False)"
        ),
    )
    pipeline_result: Optional["PipelineResult"] = Field(
        default=None,
        description="Cached PipelineResult used by handlers to avoid re-running the pipeline",
    )
    duration_ms: float = Field(
        default=0.0,
        ge=0,
        description="Wall-clock duration of the enforcement evaluation in milliseconds",
    )


# ── Enforcement event store + admin API schemas ──────────────────────────────


EnforcementDirection = Literal["ingress", "egress"]


class EnforcementEvent(BaseModel):
    """Persisted summary of one enforcement evaluation, served by the API.

    Trimmed view of :class:`EnforcementOutcome`: drops the heavy
    ``pipeline_result`` and serialises matched-decision fields only, since
    only matched decisions are interesting to dashboards / SIEM.
    """

    trace_id: str = Field(description="Correlation id (matches X-Valo-Trace-Id)")
    timestamp: datetime = Field(description="UTC timestamp when the evaluation completed")
    route: str = Field(description="HTTP path that was evaluated")
    direction: EnforcementDirection = Field(
        description="ingress for request-side, egress for response-side (proxy)"
    )
    mode: EnforcementMode = Field(description="Enforcement mode in effect at evaluation time")
    final_decision: PolicyDecisionLiteral = Field(description="Aggregate verdict")
    blocked: bool = Field(description="True when the request was actually short-circuited")
    would_block: bool = Field(
        description="True when a deny matched (regardless of mode / per-policy enforce)"
    )
    matched_policy_ids: List[str] = Field(default_factory=list)
    matched_decisions: List[PolicyDecision] = Field(
        default_factory=list,
        description="Per-policy decisions for the matched policies only",
    )
    duration_ms: float = Field(default=0.0, ge=0)


class EnforcementEventList(BaseModel):
    """Paginated listing returned by GET /enforcement/events."""

    total: int = Field(ge=0, description="Total events currently retained in the ring buffer")
    returned: int = Field(ge=0, description="Number of events returned by this query")
    capacity: int = Field(ge=0, description="Configured ring-buffer capacity")
    events: List[EnforcementEvent] = Field(default_factory=list)


class EnforcementDecisionCounts(BaseModel):
    """Aggregate counts for one decision dimension."""

    allow: int = Field(default=0, ge=0)
    warn: int = Field(default=0, ge=0)
    deny: int = Field(default=0, ge=0)


class EnforcementTopPolicy(BaseModel):
    policy_id: str
    matches: int = Field(ge=0)


class EnforcementTopRoute(BaseModel):
    route: str
    requests: int = Field(ge=0)


class EnforcementStats(BaseModel):
    """Aggregated enforcement stats returned by GET /enforcement/stats."""

    window_seconds: int = Field(
        ge=0,
        description="Time window the stats cover (0 = all retained events)",
    )
    total_events: int = Field(ge=0, description="Number of events in the window")
    blocked: int = Field(default=0, ge=0, description="Events that were actually blocked")
    would_block: int = Field(
        default=0,
        ge=0,
        description="Events whose verdict was deny (regardless of mode / enforce)",
    )
    by_decision: EnforcementDecisionCounts = Field(default_factory=EnforcementDecisionCounts)
    by_direction: dict[str, int] = Field(
        default_factory=dict,
        description="Counts grouped by direction (ingress / egress)",
    )
    top_policies: List[EnforcementTopPolicy] = Field(
        default_factory=list,
        description="Top policies by matched count, descending",
    )
    top_routes: List[EnforcementTopRoute] = Field(
        default_factory=list,
        description="Top routes by request count, descending",
    )
    p50_duration_ms: float = Field(default=0.0, ge=0)
    p95_duration_ms: float = Field(default=0.0, ge=0)
    block_rate: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description="blocked / total_events (0 when total_events == 0)",
    )


class EnforcementConfigResponse(BaseModel):
    """Read-only view of the runtime enforcement configuration."""

    enforcement_mode: EnforcementMode
    enforcement_protected_routes: List[str]
    enforcement_max_body_bytes: int = Field(ge=0)
    proxy_upstream_url: str
    proxy_request_timeout_seconds: float = Field(ge=0)
    event_buffer_capacity: int = Field(ge=0)
    event_buffer_used: int = Field(ge=0)


class EnforcementConfigUpdateRequest(BaseModel):
    """Patch payload for runtime enforcement configuration updates."""

    model_config = ConfigDict(extra="forbid")

    enforcement_mode: Optional[EnforcementMode] = Field(default=None)
    enforcement_protected_routes: Optional[List[str]] = Field(default=None)
    enforcement_max_body_bytes: Optional[int] = Field(default=None, ge=1024)
    proxy_upstream_url: Optional[str] = Field(default=None, min_length=1)
    proxy_request_timeout_seconds: Optional[float] = Field(default=None, gt=0)

    @field_validator("enforcement_protected_routes")
    @classmethod
    def _validate_routes(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        for path in cleaned:
            if not path.startswith("/"):
                raise ValueError(f"Protected route must start with '/': {path!r}")
        return cleaned


class EnforcementSimulateRequest(BaseModel):
    """Body for POST /enforcement/simulate (firewall playground)."""

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, description="Prompt text to dry-run through the firewall")
    target: str = Field(default="firewall-playground", description="Source label for audit trail")
    mode: Optional[EnforcementMode] = Field(
        default=None,
        description=(
            "Override the global enforcement mode for this simulation only. "
            "When omitted, the current settings.enforcement_mode is used."
        ),
    )


class EnforcementSimulateResponse(BaseModel):
    """Result envelope for POST /enforcement/simulate.

    Mirrors the headers + body that the real proxy / middleware would emit so
    the playground UI can render the same drawer as live traffic.
    """

    outcome: EnforcementEvent = Field(description="Trimmed enforcement event for the simulated run")
    decisions: List[PolicyDecision] = Field(
        default_factory=list,
        description="Full per-policy decisions (matched + unmatched)",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Headers the firewall would attach to a real response",
    )
    block_envelope: Optional[dict[str, Any]] = Field(
        default=None,
        description="The 403 PolicyDenied envelope that would be returned (when blocked=True)",
    )


# ── OpenAI-compatible chat.completions proxy schemas ─────────────────────────


class ChatMessage(BaseModel):
    """OpenAI-style chat message used by the proxy endpoint."""

    model_config = ConfigDict(extra="allow")

    role: str = Field(description="Message author role: system / user / assistant / tool")
    content: Optional[str] = Field(
        default=None,
        description="Message text content (may be None for tool/function calls)",
    )
    name: Optional[str] = Field(default=None)


class ChatCompletionRequest(BaseModel):
    """Minimal mirror of the OpenAI Chat Completions request body.

    `extra='allow'` so unknown fields (tools, response_format, ...) pass through
    untouched to the upstream provider.
    """

    model_config = ConfigDict(extra="allow")

    model: str = Field(min_length=1, description="Upstream model id, e.g. gpt-4o-mini")
    messages: List[ChatMessage] = Field(
        min_length=1,
        description="Conversation history sent to the upstream LLM",
    )
    stream: bool = Field(
        default=False,
        description="When True, responses are streamed with buffered policy filtering",
    )
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    max_tokens: Optional[int] = Field(default=None, ge=1)


class ChatCompletionChoice(BaseModel):
    model_config = ConfigDict(extra="allow")

    index: int = Field(default=0, ge=0)
    message: ChatMessage
    finish_reason: Optional[str] = Field(default=None)


class ChatCompletionResponse(BaseModel):
    """Minimal mirror of the OpenAI Chat Completions response body."""

    model_config = ConfigDict(extra="allow")

    id: str
    object: str = Field(default="chat.completion")
    created: int
    model: str
    choices: List[ChatCompletionChoice] = Field(default_factory=list)


# ── Plugin schemas ────────────────────────────────────────────────────────────


class PluginInfoResponse(BaseModel):
    """Metadata for a single loaded plugin returned by GET /plugins/list."""

    name: str = Field(description="Human-readable plugin name")
    version: str = Field(description="Semantic version string, e.g. '1.0.0'")
    description: str = Field(description="Short description of what the plugin does")
    author: str = Field(description="Author name or team")
    tags: List[str] = Field(default_factory=list, description="Categorisation labels")
    enabled: bool = Field(default=True, description="Whether the plugin is currently active")
    hook_names: List[str] = Field(
        default_factory=list,
        description="Names of callable hooks the plugin exposes",
    )


class PluginListResponse(BaseModel):
    """Response for GET /plugins/list."""

    loaded_count: int = Field(ge=0, description="Number of plugins currently loaded")
    plugins: List[PluginInfoResponse] = Field(
        default_factory=list,
        description="Metadata for each loaded plugin",
    )


# ── Executive Dashboard schemas ──────────────────────────────────────────────


ExecutiveWindow = Literal["24h", "7d", "30d", "90d"]
ExecutiveBucket = Literal["5m", "1h", "1d"]
ExecutiveExportFormat = Literal["pdf", "csv"]


class ExposureKpi(BaseModel):
    """Volume + block rate slice of the dashboard."""

    total_requests: int = Field(default=0, ge=0)
    blocked: int = Field(default=0, ge=0)
    would_block: int = Field(default=0, ge=0)
    block_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    by_decision: dict[str, int] = Field(default_factory=dict)
    by_direction: dict[str, int] = Field(default_factory=dict)
    top_blocking_policy_id: Optional[str] = Field(default=None)
    top_blocking_policy_count: int = Field(default=0, ge=0)


class RiskKpi(BaseModel):
    """Risk score slice rolled up from pipeline scans."""

    average_risk_score: float = Field(default=0.0, ge=0.0)
    p95_risk_score: float = Field(default=0.0, ge=0.0)
    critical_findings: int = Field(default=0, ge=0)
    severity_distribution: dict[str, int] = Field(default_factory=dict)


class AutomationKpi(BaseModel):
    """Playbook execution slice."""

    events_total: int = Field(default=0, ge=0)
    playbooks_fired: int = Field(default=0, ge=0)
    actions_executed: int = Field(default=0, ge=0)
    actions_by_type: dict[str, int] = Field(default_factory=dict)
    mean_time_to_action_ms: float = Field(default=0.0, ge=0.0)


class CoverageKpi(BaseModel):
    """One-line summary of authored policies + playbooks."""

    policies_total: int = Field(default=0, ge=0)
    policies_enabled: int = Field(default=0, ge=0)
    policies_enforce_mode: int = Field(default=0, ge=0)
    playbooks_total: int = Field(default=0, ge=0)
    playbooks_enabled: int = Field(default=0, ge=0)
    playbooks_live: int = Field(
        default=0,
        ge=0,
        description="Playbooks enabled while the engine itself is on AND not in dry-run",
    )


class ComplianceTagRollup(BaseModel):
    """Per-tag rollup joining policies + playbooks to enforcement counts."""

    tag: str
    policies: int = Field(default=0, ge=0)
    playbooks: int = Field(default=0, ge=0)
    matched_events: int = Field(default=0, ge=0)
    blocked_events: int = Field(default=0, ge=0)


class TopOffender(BaseModel):
    """Top entity by deny / block count."""

    subject_type: str
    subject_id: str
    deny_count: int = Field(default=0, ge=0)
    last_seen: Optional[datetime] = None


class ExecutiveSummary(BaseModel):
    """Aggregated KPI payload returned by GET /executive/summary."""

    window: ExecutiveWindow
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    window_start: datetime
    window_end: datetime
    exposure: ExposureKpi = Field(default_factory=ExposureKpi)
    risk: RiskKpi = Field(default_factory=RiskKpi)
    automation: AutomationKpi = Field(default_factory=AutomationKpi)
    coverage: CoverageKpi = Field(default_factory=CoverageKpi)
    compliance: List[ComplianceTagRollup] = Field(default_factory=list)
    top_offenders: List[TopOffender] = Field(default_factory=list)


class ExecutiveTrendPoint(BaseModel):
    """One bucket on a trend chart."""

    bucket_start: datetime
    metric: str
    value: float = Field(default=0.0)


class ExecutiveTrendSeries(BaseModel):
    """One labelled series on a trend chart."""

    metric: str
    points: List[ExecutiveTrendPoint] = Field(default_factory=list)


class ExecutiveTrends(BaseModel):
    """Time-series payload returned by GET /executive/trends."""

    window: ExecutiveWindow
    bucket: ExecutiveBucket
    window_start: datetime
    window_end: datetime
    series: List[ExecutiveTrendSeries] = Field(default_factory=list)


# Resolve forward references so PipelineResult / ScanReport / AnalyzeResponse
# can include policy_decisions / final_decision typed against models declared
# later in this module.
PipelineResult.model_rebuild()
ScanReport.model_rebuild()
AnalyzeScanReport.model_rebuild()
AnalyzeResponse.model_rebuild()
EnforcementOutcome.model_rebuild()
ChatMessage.model_rebuild()
ChatCompletionRequest.model_rebuild()
ChatCompletionChoice.model_rebuild()
ChatCompletionResponse.model_rebuild()
EnforcementEvent.model_rebuild()
EnforcementEventList.model_rebuild()
EnforcementStats.model_rebuild()
EnforcementConfigResponse.model_rebuild()
EnforcementConfigUpdateRequest.model_rebuild()
EnforcementSimulateRequest.model_rebuild()
EnforcementSimulateResponse.model_rebuild()
