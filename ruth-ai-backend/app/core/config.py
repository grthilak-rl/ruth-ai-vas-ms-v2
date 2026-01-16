"""Application configuration management.

All configuration is loaded from environment variables.
No hardcoded values except sensible defaults for development.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Environment variables are automatically loaded and validated.
    Use RUTH_AI_ prefix for all application-specific settings.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    ruth_ai_env: Literal["development", "test", "production"] = Field(
        default="development",
        description="Application environment",
    )
    ruth_ai_log_level: Literal["debug", "info", "warning", "error"] = Field(
        default="info",
        description="Logging level",
    )
    ruth_ai_log_format: Literal["json", "text"] = Field(
        default="json",
        description="Log output format",
    )

    # Server
    host: str = Field(default="0.0.0.0", description="Server bind host")
    port: int = Field(default=8080, description="Server bind port")

    # Database
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://ruth:ruth@localhost:5432/ruth_ai",
        description="PostgreSQL connection URL (async driver)",
    )
    database_pool_size: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Database connection pool size",
    )
    database_pool_overflow: int = Field(
        default=5,
        ge=0,
        le=50,
        description="Max overflow connections beyond pool size",
    )

    # Redis
    redis_url: RedisDsn = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
    )
    redis_max_connections: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Max Redis connections",
    )

    # AI Runtime
    ai_runtime_url: str = Field(
        default="ruth-ai-runtime:50051",
        description="AI Runtime gRPC endpoint",
    )
    ai_runtime_timeout_ms: int = Field(
        default=5000,
        ge=100,
        le=60000,
        description="AI Runtime request timeout in milliseconds",
    )
    ai_runtime_retry_count: int = Field(
        default=3,
        ge=0,
        le=10,
        description="AI Runtime retry attempts",
    )

    # VAS Integration
    vas_base_url: str = Field(
        default="http://10.30.250.245:8085",
        description="VAS Backend API base URL",
    )
    vas_client_id: str = Field(
        default="ruth-ai-backend",
        description="VAS API client ID",
    )
    vas_client_secret: str = Field(
        default="",
        description="VAS API client secret",
    )
    vas_token_refresh_margin_sec: int = Field(
        default=300,
        ge=60,
        le=1800,
        description="Refresh VAS token this many seconds before expiry",
    )

    # JWT Authentication
    jwt_secret_key: str = Field(
        default="CHANGE_ME_IN_PRODUCTION",
        description="JWT signing key",
        min_length=16,
    )
    jwt_algorithm: str = Field(
        default="HS256",
        description="JWT algorithm",
    )
    jwt_expiry_minutes: int = Field(
        default=60,
        ge=5,
        le=1440,
        description="Access token expiry in minutes",
    )

    # Health Check Timeouts (in seconds)
    health_check_db_timeout: float = Field(
        default=5.0,
        ge=1.0,
        le=30.0,
        description="Database health check timeout in seconds",
    )
    health_check_redis_timeout: float = Field(
        default=3.0,
        ge=1.0,
        le=30.0,
        description="Redis health check timeout in seconds",
    )
    health_check_ai_runtime_timeout: float = Field(
        default=10.0,
        ge=1.0,
        le=60.0,
        description="AI Runtime health check timeout in seconds",
    )
    health_check_vas_timeout: float = Field(
        default=5.0,
        ge=1.0,
        le=30.0,
        description="VAS health check timeout in seconds",
    )
    health_check_nlp_chat_timeout: float = Field(
        default=5.0,
        ge=1.0,
        le=30.0,
        description="NLP Chat Service health check timeout in seconds",
    )

    # NLP Chat Service Configuration
    nlp_chat_service_url: str = Field(
        default="http://localhost:8081",
        description="NLP Chat Service base URL",
    )
    nlp_chat_timeout_seconds: int = Field(
        default=120,
        ge=30,
        le=300,
        description="NLP Chat Service request timeout (LLM calls can be slow)",
    )

    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.ruth_ai_env == "development"

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.ruth_ai_env == "production"

    @property
    def is_test(self) -> bool:
        """Check if running in test mode."""
        return self.ruth_ai_env == "test"


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings.

    Settings are loaded once and cached for the lifetime of the application.
    """
    return Settings()
