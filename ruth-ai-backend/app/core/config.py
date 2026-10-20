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

    # Unified AI Runtime
    unified_runtime_url: str = Field(
        default="http://ruth-ai-unified-runtime:8000",
        description="Ruth AI Unified Runtime endpoint (GPU-enabled service)",
    )

    # VAS Integration
    vas_base_url: str = Field(
        default="http://10.30.250.245:8085",
        description="VAS Backend API base URL",
    )
    vas_redis_url: str = Field(
        default="",
        description=(
            "URL of the VAS Redis instance (used to subscribe to "
            "vas:stream_events). Empty string disables the VAS event consumer."
        ),
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

    # Hardware Monitoring Configuration
    hardware_model_service_timeout: float = Field(
        default=5.0,
        ge=1.0,
        le=30.0,
        description="Timeout for querying AI model services for hardware status",
    )
    hardware_avg_vram_per_camera_gb: float = Field(
        default=0.8,
        ge=0.1,
        le=4.0,
        description="Estimated VRAM usage per camera for capacity calculation",
    )
    hardware_avg_ram_per_camera_gb: float = Field(
        default=0.5,
        ge=0.1,
        le=2.0,
        description="Estimated RAM usage per camera in CPU-only mode",
    )
    hardware_capacity_safety_factor: float = Field(
        default=0.8,
        ge=0.5,
        le=1.0,
        description="Safety factor for capacity estimation (0.8 = 80% utilization target)",
    )

    # NLP Chat Service Configuration
    nlp_chat_enabled: bool = Field(
        default=True,
        description=(
            "Whether NLP Chat is part of this deployment. When false, the "
            "chat client is not started, the chat endpoint returns 503, and "
            "the health aggregator reports nlp_chat as 'disabled' rather "
            "than 'unhealthy' (so overall status isn't dragged down)."
        ),
    )
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

    database_echo: bool = Field(
        default=False,
        description=(
            "Log every SQL statement. Was tied to ruth_ai_env == "
            "'development', which this deployment runs as — so the plant has "
            "been logging every statement at INFO, tens of lines per second, "
            "drowning the application log. Separated out because the other "
            "things that flag controls (/docs, /redoc, /openapi.json) are "
            "wanted here and SQL echo is not."
        ),
    )

    # Auto-resume (BL-11 A)
    inference_reconcile_seconds: float = Field(
        default=60.0,
        ge=10.0,
        description=(
            "How often to check that every camera an operator wants running "
            "actually is. 0 disables auto-resume entirely."
        ),
    )
    inference_reconcile_enabled: bool = Field(
        default=True,
        description="Put inference back when a session stops on its own.",
    )

    # Violation evidence: the inferred frame, saved by Ruth
    evidence_frame_dir: str = Field(
        default="/evidence/frames",
        description=(
            "Where the JPEG the model actually inferred is written when a "
            "violation fires. Must be a mounted volume. If it is missing or "
            "unwritable, frame evidence is skipped with a warning and the "
            "violation is still written — losing a picture must never lose "
            "the violation."
        ),
    )
    evidence_frame_enabled: bool = Field(
        default=True,
        description="Save the inferred frame with each violation.",
    )
    evidence_thumb_dir: str = Field(
        default="/evidence/thumbs",
        description=(
            "Cache for the cropped card thumbnails made from inferred frames. "
            "Safe to delete: thumbnails are regenerated on demand."
        ),
    )

    # False-alarm dismissals copied for the AI engineer
    labelling_root: str = Field(
        default="/store/labelling",
        description=(
            "Where false-alarm dismissals are exported (false_positives/<model>/"
            "<date>/). /store is the model store volume, /mnt/storage/ruth-models "
            "on the host."
        ),
    )

    # Bulk evidence export ("Download snapshots" on the Violations page)
    violation_export_dir: str = Field(
        default="/evidence/exports",
        description=(
            "Where built ZIPs are written. Under the evidence volume "
            "(/mnt/storage/ruth-evidence on the host) so it needs no extra "
            "mount; deliberately a sibling of frames/ rather than inside it, "
            "because exports are disposable and frames are not."
        ),
    )
    violation_export_max_violations: int = Field(
        default=5000,
        ge=1,
        le=50000,
        description=(
            "Refuse an export covering more violations than this. At the "
            "site's current rate 5000 is roughly three days; a month-long "
            "export has to be narrowed. Counted before any work starts, so "
            "the operator is told the number and can adjust the filters."
        ),
    )
    violation_export_ttl_hours: int = Field(
        default=24,
        ge=1,
        le=24 * 14,
        description="How long a built ZIP stays downloadable before it is swept.",
    )
    violation_export_snapshot_concurrency: int = Field(
        default=4,
        ge=1,
        le=32,
        description=(
            "Parallel snapshot fetches when the scene-snapshot fallback is "
            "enabled. Each one is a VAS request for a ~810KB full-resolution "
            "image, and VAS runs a single event loop that every camera's "
            "frame fetch shares (BL-12), so this stays deliberately low."
        ),
    )

    # Clip status: background sync from VAS
    clip_sync_enabled: bool = Field(
        default=True,
        description="Poll VAS for clips still being prepared, so cards show 🎞 without a page visit.",
    )
    clip_sync_interval_seconds: int = Field(default=20, ge=5, le=3600)
    clip_sync_batch_size: int = Field(default=50, ge=1, le=500)
    clip_sync_max_age_hours: int = Field(
        default=48,
        ge=1,
        le=24 * 30,
        description="Clips requested longer ago than this are no longer polled.",
    )

    # Violations page: repeated violations shown as one incident
    incident_gap_minutes: int = Field(
        default=5,
        ge=1,
        le=120,
        description=(
            "Same camera + same specific type within this many minutes of the "
            "previous violation joins the same incident. Median repeat gap "
            "measured at 53 s; 75% within 5 min."
        ),
    )
    incident_max_span_minutes: int = Field(
        default=60,
        ge=1,
        le=24 * 60,
        description=(
            "An incident never spans more than this from its first violation, "
            "so a camera that fires all day is not one card."
        ),
    )
    evidence_bookmark_cooldown_seconds: int = Field(
        default=60,
        ge=0,
        description=(
            "Per camera, the minimum gap between requesting video clips. A "
            "busy camera can fire violations every few seconds and each clip "
            "costs VAS real work; within the cooldown the violation is still "
            "written and linked to the most recent clip for that camera."
        ),
    )

    # Project archiving ("Start new project")
    project_backup_dir: str = Field(
        default="/var/backups/ruth-ai",
        description=(
            "Directory for the pg_dump taken before a project is archived. "
            "Must exist and be writable, and should be a mounted volume — a "
            "dump inside the container layer is lost on the next deploy. "
            "Starting a project refuses rather than proceeding unbacked."
        ),
    )
    project_pg_dump_path: str = Field(
        default="pg_dump",
        description=(
            "pg_dump executable. Looked up on PATH by default; set an "
            "absolute path if the image carries a specific client version. "
            "Must be >= the server's major version (Postgres 15 here)."
        ),
    )
    project_backup_timeout_seconds: int = Field(
        default=1800,
        ge=60,
        le=14400,
        description="Hard timeout for the pre-archive pg_dump",
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
