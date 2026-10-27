"""Network health probe package."""

from netwatch.probes.dns import probe_dns
from netwatch.probes.http import probe_http, send_http_request
from netwatch.probes.models import (
    DnsResult,
    HttpResult,
    ProbeCompositeResult,
    TcpResult,
    TlsResult,
)
from netwatch.probes.runner import run_probes
from netwatch.probes.tcp import connect_tcp, probe_tcp
from netwatch.probes.tls import probe_tls, upgrade_to_tls

__all__ = [
    "DnsResult",
    "TcpResult",
    "TlsResult",
    "HttpResult",
    "ProbeCompositeResult",
    "probe_dns",
    "probe_tcp",
    "connect_tcp",
    "probe_tls",
    "upgrade_to_tls",
    "probe_http",
    "send_http_request",
    "run_probes",
]
