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


class ProbeResultResponse(BaseModel):
    """Response schema representing a single historical probe telemetry record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    target_id: int
    ts: datetime
    ok: bool
    dns_ms: float | None = None
    tcp_ms: float | None = None
    tls_ms: float | None = None
    http_ms: float | None = None
    total_ms: float | None = None
    status_code: int | None = None
    tls_days_left: float | None = None
    error: str | None = None
    replica_id: str
    epoch: int


class LatencyPoint(BaseModel):
    """Aggregated latency datapoint for summary line charts."""

    ts: datetime
    avg_latency_ms: float | None = None


class SummaryResponse(BaseModel):
    """Aggregated health statistics and trend series across all targets."""

    targets_up: int
    targets_total: int
    avg_latency_ms: float | None = None
    failing: int
    nearest_cert_expiry_days: float | None = None
    uptime_percent: float
    latency_series: list[LatencyPoint] = Field(default_factory=list)


class PhaseSeriesPoint(BaseModel):
    """Time-bucketed latency averages across all 4 probe pipeline phases."""

    bucket: datetime
    dns_ms: float | None = None
    tcp_ms: float | None = None
    tls_ms: float | None = None
    http_ms: float | None = None
    total_ms: float | None = None
    sample_count: int


class ProbeOutcomeSummary(BaseModel):
    """Abbreviated probe outcome representing one of the last 20 probe events."""

    id: int
    ts: datetime
    ok: bool
    total_ms: float | None = None
    status_code: int | None = None
    error: str | None = None


class TargetTlsSummary(BaseModel):
    """TLS certificate expiration overview for a monitored host."""

    days_left: float | None = None
    status: str = "valid"


class TargetDetailResponse(BaseModel):
    """Target entity enriched with latest telemetry, recent outcomes, and TLS info."""

    id: int
    host: str
    port: int
    interval_s: int
    enabled: bool
    created_at: datetime
    latest_result: ProbeResultResponse | None = None
    recent_outcomes: list[ProbeOutcomeSummary] = Field(default_factory=list)
    tls_info: TargetTlsSummary | None = None
