from prometheus_client import Counter, Gauge

from netwatch.probes.models import ProbeCompositeResult

# Prometheus metrics for NetWatch probe telemetry and cluster health
probe_duration_seconds = Gauge(
    "probe_duration_seconds",
    "Last measured probe duration in seconds by target host and phase",
    ["target", "phase"],
)

probe_success = Gauge(
    "probe_success",
    "Last probe outcome for target host (1 for success, 0 for failure)",
    ["target"],
)

tls_cert_expiry_days = Gauge(
    "tls_cert_expiry_days",
    "Days until TLS certificate expiration for target host",
    ["target"],
)

probes_total = Counter(
    "probes_total",
    "Total count of probe attempts by target host and outcome",
    ["target", "outcome"],
)

netwatch_is_leader = Gauge(
    "netwatch_is_leader",
    "Leadership status of this replica (1 if cluster leader, 0 if standby)",
)

netwatch_probe_queue_depth = Gauge(
    "netwatch_probe_queue_depth",
    "Number of probe tasks currently queued or running",
)


def update_probe_metrics(host: str, result: ProbeCompositeResult) -> None:
    """Updates Prometheus gauges and counters with the latest probe telemetry."""
    # Gauge values require seconds conversion from milliseconds
    if result.dns_ms is not None:
        probe_duration_seconds.labels(target=host, phase="dns").set(result.dns_ms / 1000.0)
    if result.tcp_ms is not None:
        probe_duration_seconds.labels(target=host, phase="tcp").set(result.tcp_ms / 1000.0)
    if result.tls_ms is not None:
        probe_duration_seconds.labels(target=host, phase="tls").set(result.tls_ms / 1000.0)
    if result.http_ms is not None:
        probe_duration_seconds.labels(target=host, phase="http").set(result.http_ms / 1000.0)
    if result.total_ms is not None:
        probe_duration_seconds.labels(target=host, phase="total").set(result.total_ms / 1000.0)

    probe_success.labels(target=host).set(1.0 if result.ok else 0.0)
    outcome = "success" if result.ok else "failure"
    probes_total.labels(target=host, outcome=outcome).inc()

    if result.tls_days_left is not None:
        tls_cert_expiry_days.labels(target=host).set(result.tls_days_left)
