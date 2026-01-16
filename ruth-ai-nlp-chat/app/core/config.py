"""NLP Chat Service configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """NLP Chat Service settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    nlp_env: Literal["development", "test", "production"] = Field(
        default="development",
        description="Application environment",
    )
    nlp_log_level: Literal["debug", "info", "warning", "error"] = Field(
        default="info",
        description="Logging level",
    )

    # Server
    host: str = Field(default="0.0.0.0", description="Server bind host")
    port: int = Field(default=8081, description="Server bind port")

    # Database (read-only access to Ruth AI database)
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://ruth:ruth@localhost:5432/ruth_ai",
        description="PostgreSQL connection URL (async driver) - READ ONLY",
    )
    database_pool_size: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Database connection pool size (smaller for read-only)",
    )

    # Ollama LLM Configuration
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama API base URL",
    )
    ollama_sql_model: str = Field(
        default="anindya/prem1b-sql-ollama-fp16",
        description="Ollama model for SQL generation",
    )
    ollama_nlg_model: str = Field(
        default="llama3.2:1b",
        description="Ollama model for natural language generation (lightweight)",
    )
    ollama_sql_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="Temperature for SQL generation",
    )
    ollama_nlg_temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=2.0,
        description="Temperature for NLG",
    )
    ollama_timeout_seconds: int = Field(
        default=60,
        ge=10,
        le=300,
        description="Ollama API request timeout",
    )

    # Chat Configuration
    chat_max_result_rows: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Maximum rows returned from queries",
    )
    chat_allowed_tables: str = Field(
        default="devices,stream_sessions,events,violations,evidence",
        description="Tables accessible via chat queries (comma-separated)",
    )

    @property
    def allowed_tables_list(self) -> list[str]:
        """Get allowed tables as a list."""
        return [t.strip() for t in self.chat_allowed_tables.split(",") if t.strip()]

    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.nlp_env == "development"


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()
