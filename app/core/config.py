"""Application configuration with environment variable support."""

from pathlib import Path
from typing import List, Literal, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_PROTECTED_ROUTES: tuple[str, ...] = (
    "/analyze",
    "/scan/report",
    "/report/pdf",
    "/ingest/normalize",
)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    edition: Literal["community", "enterprise"] = Field(
        default="community",
        description="Product edition (Community Edition only; enterprise is not supported).",
    )

    rules_path: Path = Field(
        default=Path(__file__).parent.parent / "rules" / "default_yml_rule.yml",
        description="Path to YAML rules file",
    )
    policies_path: Path = Field(
        default=Path(__file__).parent.parent / "policies" / "governance",
        description="Directory containing one YAML file per governance policy",
    )
    log_level: str = Field(default="INFO", description="Logging level")
    rate_limit: str = Field(
        default="100/minute",
        description="Default rate limit (e.g., 100/minute)",
    )
    rules_cache_ttl_seconds: int = Field(
        default=60,
        ge=0,
        description="Seconds to cache rules (0=disabled)",
    )
    policies_cache_ttl_seconds: int = Field(
        default=60,
        ge=0,
        description="Seconds to cache governance policies (0=disabled)",
    )

    enforcement_mode: Literal["off", "monitor", "enforce"] = Field(
        default="monitor",
        description=(
            "Global enforcement mode for the AI Firewall middleware. "
            "off: bypass middleware. monitor: evaluate and log only (never block). "
            "enforce: actually return 403 when a deny policy matches and is enforce-flagged."
        ),
    )
    enforcement_protected_routes: List[str] = Field(
        default_factory=lambda: list(_DEFAULT_PROTECTED_ROUTES),
        description="HTTP paths the enforcement middleware inspects (POST only).",
    )
    enforcement_max_body_bytes: int = Field(
        default=1_048_576,
        ge=1024,
        description=(
            "Hard cap on request body size the enforcement middleware will buffer. "
            "Requests larger than this bypass enforcement and are logged."
        ),
    )
    proxy_upstream_url: str = Field(
        default="https://api.openai.com/v1/chat/completions",
        description="Upstream URL for /v1/proxy/chat/completions (OpenAI-compatible).",
    )
    proxy_request_timeout_seconds: float = Field(
        default=60.0,
        gt=0,
        description="Timeout for upstream LLM proxy requests in seconds.",
    )
    enforcement_event_buffer_capacity: int = Field(
        default=1000,
        ge=10,
        le=100_000,
        description=(
            "Maximum number of enforcement events retained in the in-memory ring buffer "
            "(used by GET /enforcement/events and stats). Older events are evicted FIFO."
        ),
    )
    correlation_engine_enabled: bool = Field(
        default=True,
        description=(
            "When true, every enforcement outcome is shipped to the Correlation Engine "
            "via a background HTTP POST. On by default; the emitter still no-ops when "
            "correlation_engine_url is empty, so flipping this flag without configuring "
            "the URL is a safe identity."
        ),
    )
    correlation_engine_url: str = Field(
        default="",
        description=(
            "Base URL of the Correlation Engine (e.g. http://correlation:8100). "
            "The emitter appends /ingest/valo to this value."
        ),
    )
    correlation_engine_secret: str = Field(
        default="",
        description="Shared HMAC secret used to sign correlation emitter requests.",
    )
    playbooks_enabled: bool = Field(
        default=True,
        description=(
            "Master kill switch for the Automated Response Playbooks engine. "
            "When False, every dispatch returns immediately with an empty trace. "
            "On by default; playbooks_dry_run stays True so no real side effects "
            "fire until an operator wires real adapters."
        ),
    )
    playbooks_dry_run: bool = Field(
        default=True,
        description=(
            "When True, every action returns 'planned' without performing real "
            "side effects. Default-secure: real adapters must opt in by setting "
            "this to False in the deployment environment."
        ),
    )
    playbooks_path: Path = Field(
        default=Path(__file__).parent.parent / "playbooks" / "library",
        description="Directory containing one YAML file per playbook.",
    )
    playbooks_cache_ttl_seconds: int = Field(
        default=60,
        ge=0,
        description="Seconds to cache the loaded playbook library (0=disabled).",
    )
    playbook_trace_buffer_capacity: int = Field(
        default=500,
        ge=10,
        le=100_000,
        description=(
            "Maximum number of playbook execution traces retained in the "
            "in-memory ring buffer (used by GET /playbooks/traces). "
            "Older traces are evicted FIFO."
        ),
    )
    executive_metrics_enabled: bool = Field(
        default=True,
        description=(
            "Master kill switch for the Executive Dashboard. When False, the "
            "rollup aggregator does not run and /executive/* endpoints return "
            "503. On by default; the rollup SQLite file is created lazily on "
            "first write so opt-out remains as easy as flipping this flag."
        ),
    )
    executive_metrics_db_path: Path = Field(
        default=Path("data/executive_metrics.sqlite"),
        description=(
            "Path to the SQLite file backing the executive metrics rollups. "
            "Parent directory is created on first write."
        ),
    )
    executive_aggregator_interval_seconds: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="Cadence in seconds at which the rollup aggregator runs.",
    )
    executive_retention_5m_hours: int = Field(
        default=48,
        ge=1,
        le=24 * 30,
        description="Retention for 5-minute rollups (in hours).",
    )
    executive_retention_1h_days: int = Field(
        default=35,
        ge=1,
        le=365,
        description="Retention for 1-hour rollups (in days).",
    )
    executive_retention_1d_days: int = Field(
        default=400,
        ge=7,
        le=365 * 5,
        description="Retention for 1-day rollups (in days).",
    )
    outcome_store_path: Path = Field(
        default=Path("data/learning_outcomes.sqlite"),
        description=(
            "Path to the SQLite file backing the Phase 4 Learning Loop "
            "outcome store. Parent directory is created on first write."
        ),
    )
    outcome_ingest_secret: str = Field(
        default="",
        description=(
            "Shared HMAC secret used to authenticate cross-product outcome "
            "envelopes posted to /outcomes/ingest. When unset, the endpoint "
            "still accepts unsigned bodies but logs a warning."
        ),
    )
    learning_loop_enabled: bool = Field(
        default=True,
        description=(
            "Master kill switch for the Phase 4 Learning Loop refiner. "
            "When False, the refiner background task does not run and "
            "/learning/* endpoints still serve any proposals already on disk "
            "but never generate new ones. On by default; learning_loop_auto_apply "
            "stays False so proposals require an explicit accept."
        ),
    )
    learning_loop_auto_apply: bool = Field(
        default=False,
        description=(
            "When True, accepted refiner proposals are written to the live "
            "policy / playbook stores without waiting for a /learning/proposals "
            "{id}/accept call. Default off (human-in-the-loop is the contract)."
        ),
    )
    learning_loop_min_samples: int = Field(
        default=50,
        ge=1,
        description=(
            "Minimum total fires for a rule before the refiner is allowed to "
            "propose a change. Smaller values risk overreacting to noise."
        ),
    )
    learning_loop_fp_threshold: float = Field(
        default=0.30,
        ge=0.0,
        le=1.0,
        description=(
            "False-positive rate above which the refiner proposes that a "
            "playbook be disabled or a policy threshold be tightened."
        ),
    )
    learning_loop_healthy_fp_ceiling: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description=(
            "False-positive rate at or below which a rule is considered "
            "healthy and the refiner emits no proposal for it."
        ),
    )
    learning_loop_schedule_seconds: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Cadence in seconds at which the refiner background task runs.",
    )
    reports_enabled: bool = Field(
        default=True,
        description=(
            "Master switch for the Phase 4 Reporting Automation surface. "
            "When False, the /reports API returns 503 and the scheduler "
            "is skipped. Default on (the API is read-only until reports "
            "are generated, and existing PDF endpoints are unaffected)."
        ),
    )
    report_store_path: Path = Field(
        default=Path("data/reports"),
        description=(
            "Directory where generated report payloads (PDF / CSV) are "
            "persisted. Created on first write. Files are named "
            "{report_id}.{format} and indexed by report_index_path."
        ),
    )
    report_index_path: Path = Field(
        default=Path("data/reports.sqlite"),
        description=(
            "Path to the SQLite file that indexes generated reports "
            "(metadata, status, last-run-at). Parent directory is created "
            "on first write."
        ),
    )
    report_scheduler_enabled: bool = Field(
        default=True,
        description=(
            "When True, a background task generates the configured weekly "
            "report kinds on a fixed weekday/hour cadence. On by default; "
            "the scheduler is idempotent (one run per weekly window per kind) "
            "so toggling it back off via APP_REPORT_SCHEDULER_ENABLED=false "
            "stops new runs without losing already-persisted reports."
        ),
    )
    report_schedule_weekly_weekday: int = Field(
        default=0,
        ge=0,
        le=6,
        description=(
            "Weekday for the weekly report cadence (Mon=0, Sun=6, UTC). "
            "A run is considered due once the current time crosses the "
            "configured weekday and hour after the last successful run."
        ),
    )
    report_schedule_weekly_hour: int = Field(
        default=6,
        ge=0,
        le=23,
        description="Hour of day (UTC, 0-23) for the weekly report cadence.",
    )
    report_scheduler_tick_seconds: int = Field(
        default=60,
        ge=10,
        le=3600,
        description=(
            "How often the scheduler checks whether a weekly run is due "
            "(in seconds). The scheduler still runs at most once per "
            "weekly window per kind."
        ),
    )
    report_retention_days: int = Field(
        default=90,
        ge=1,
        le=365 * 5,
        description=(
            "Reports older than this are pruned from disk and the index "
            "after each successful scheduler run."
        ),
    )
    report_default_kinds: List[str] = Field(
        default_factory=lambda: [
            "executive_pdf_7d",
            "executive_csv_7d",
            "portfolio_rollup_pdf",
        ],
        description=(
            "Report kinds the weekly scheduler generates on each run. "
            "Comma-separated when set via the environment."
        ),
    )
    report_branding_company_name: str = Field(
        default="",
        max_length=200,
        description=(
            "Optional company name to print on the executive KPI cover "
            "('Prepared for ...'). Empty disables the branding block."
        ),
    )
    report_branding_logo_path: Optional[Path] = Field(
        default=None,
        description=(
            "Optional path to a PNG/JPEG logo for the executive KPI cover. "
            "Files larger than report_branding_logo_max_bytes are ignored "
            "to protect against misconfiguration."
        ),
    )
    report_branding_logo_max_bytes: int = Field(
        default=4 * 1024 * 1024,
        ge=1024,
        le=64 * 1024 * 1024,
        description=(
            "Maximum bytes the report branding logo loader will read from "
            "disk. Defends against accidentally-pointed-at large files."
        ),
    )

    @field_validator("enforcement_protected_routes", mode="before")
    @classmethod
    def _split_protected_routes(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("report_default_kinds", mode="before")
    @classmethod
    def _split_report_default_kinds(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _apply_community_edition_defaults(self) -> "Settings":
        if self.edition == "enterprise":
            raise ValueError(
                "APP_EDITION=enterprise is not supported in Valo Community Edition. "
                "Enterprise features require Valo Enterprise."
            )
        object.__setattr__(self, "edition", "community")
        if self.enforcement_mode == "enforce":
            raise ValueError(
                "APP_ENFORCEMENT_MODE=enforce is not allowed when APP_EDITION=community. "
                "Use monitor or off."
            )
        object.__setattr__(self, "correlation_engine_enabled", False)
        object.__setattr__(self, "playbooks_enabled", False)
        object.__setattr__(self, "executive_metrics_enabled", False)
        object.__setattr__(self, "learning_loop_enabled", False)
        object.__setattr__(self, "reports_enabled", False)
        object.__setattr__(self, "report_scheduler_enabled", False)
        object.__setattr__(self, "report_branding_company_name", "")
        object.__setattr__(self, "report_branding_logo_path", None)
        return self


settings = Settings()
