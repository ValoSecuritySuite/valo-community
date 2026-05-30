"""Application configuration for Valo Community Edition."""

from pathlib import Path
from typing import List, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_PROTECTED_ROUTES: tuple[str, ...] = (
    "/analyze",
    "/scan/report",
    "/report/pdf",
)


class Settings(BaseSettings):
    """Community Edition settings loaded from APP_* environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    edition: Literal["community"] = Field(
        default="community",
        description="Product edition (Community Edition only).",
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
            "Community Edition supports off and monitor only; enforce requires Enterprise."
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

    @field_validator("enforcement_protected_routes", mode="before")
    @classmethod
    def _split_protected_routes(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _apply_community_edition_defaults(self) -> "Settings":
        object.__setattr__(self, "edition", "community")
        if self.enforcement_mode == "enforce":
            raise ValueError(
                "APP_ENFORCEMENT_MODE=enforce is not allowed in Valo Community Edition. "
                "Use monitor or off, or upgrade to Valo Enterprise."
            )
        return self


settings = Settings()
