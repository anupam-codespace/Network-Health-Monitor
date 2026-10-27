from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings parsed from environment variables with safe defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+asyncpg://anupamsaha@localhost:5432/netwatch",
        description="Async PostgreSQL connection string using asyncpg driver",
    )
    replica_id: str = Field(
        default="replica-1",
        description="Unique identifier distinguishing this replica within the cluster",
    )
    http_port: int = Field(
        default=8001,
        description="HTTP port bound by the Uvicorn web server",
    )
    admin_api_key: str = Field(
        default="netwatch-admin-secret-key-123",
        description="Plaintext secret key seeded for admin role access",
    )
    viewer_api_key: str = Field(
        default="netwatch-viewer-secret-key-456",
        description="Plaintext secret key seeded for viewer role access",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level for standard output",
    )
    max_concurrent_probes: int = Field(
        default=50,
        description="Maximum concurrent probes allowed across the system",
    )
    retention_days: int = Field(
        default=7,
        description="Number of days to retain probe results in the database",
    )
    targets_seed_file: str = Field(
        default="targets.yaml",
        description="Path to YAML seed file containing initial targets",
    )


# Singleton settings instance accessed across application lifecycle
settings = Settings()
