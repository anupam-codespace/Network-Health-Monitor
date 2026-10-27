# NetWatch

A high-reliability network health monitor service featuring multi-phase probing (DNS, TCP, TLS, HTTP), automatic leader election via PostgreSQL advisory locks, real-time live browser dashboards via Server-Sent Events, and Prometheus observability.

## Overview

NetWatch runs continuously to probe configured target hosts across 4 distinct phases:
1. **DNS Lookup**: Latency and resolution of hostnames via asynchronous DNS resolver.
2. **TCP Connect**: Raw socket connection latency verifying network reachability and firewall traversal.
3. **TLS Handshake**: SSL/TLS negotiation latency, protocol handshake, and days-to-expiration extraction.
4. **HTTP TTFB**: Time-to-first-byte measurements evaluating application layer responsiveness.

## Quick Start

```bash
# 1. Install dependencies
uv sync --all-extras

# 2. Run one-off CLI probe against any host
netwatch probe example.com
```
