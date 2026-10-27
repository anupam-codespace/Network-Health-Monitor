import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TargetCreate(BaseModel):
    """Payload schema for registering a new monitored network target."""

    host: str = Field(
        ..., description="Target hostname or IP address", min_length=1, max_length=255
    )
    port: int = Field(default=443, ge=1, le=65535, description="Target TCP port (1-65535)")
    interval_s: int = Field(
        default=30, ge=10, le=3600, description="Probe frequency in seconds (10-3600)"
    )
    enabled: bool = Field(default=True, description="Active polling state")

    @field_validator("host")
    @classmethod
    def validate_host_format(cls, value: str) -> str:
        """Enforces clean hostname or IP format without URI schemes or invalid characters."""
        cleaned = value.strip().lower()
        if "://" in cleaned:
            raise ValueError("Host must not include a protocol scheme (e.g. use 'example.com')")
        if "/" in cleaned or " " in cleaned or ":" in cleaned:
            raise ValueError("Host must be a bare hostname or IP without paths, spaces, or ports")
        # Ensure valid RFC hostname / IPv4 characters
        if not re.match(r"^[a-zA-Z0-9.-]+$", cleaned):
            raise ValueError("Host contains invalid characters")
        return cleaned


class TargetResponse(BaseModel):
    """Response schema serializing target endpoint entity."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    host: str
    port: int
    interval_s: int
    enabled: bool
    created_at: datetime
