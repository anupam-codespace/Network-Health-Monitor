from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class PhaseResult(BaseModel):
    """Result of an individual network probe phase."""

    phase: str
    success: bool
    duration_seconds: float | None = None
    error: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    @property
    def duration_ms(self) -> float | None:
        """Helper to expose latency in milliseconds for UI and CLI displays."""
        if self.duration_seconds is None:
            return None
        return round(self.duration_seconds * 1000.0, 2)


class TargetProbeResult(BaseModel):
    """Aggregated results across all network probe phases for a given target."""

    target: str
    url: str
    host: str
    port: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    dns: PhaseResult
    tcp: PhaseResult
    tls: PhaseResult
    http: PhaseResult
    tls_cert_expiry_days: float | None = None
    success: bool
