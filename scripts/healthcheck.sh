#!/usr/bin/env bash
# ==============================================================================
# NetWatch Healthcheck Script
# Exit codes usable by Docker Compose and systemd (0 = healthy, 1 = unhealthy).
# ==============================================================================

set -euo pipefail

show_usage() {
    cat << 'EOF'
Usage: scripts/healthcheck.sh [OPTIONS]

Checks the health of a NetWatch instance.

Options:
  --url URL        Full healthz URL (default: http://127.0.0.1:8001/healthz)
  --port PORT      Check localhost on specific port (e.g. 8001 or 8002)
  --timeout SECS   HTTP request timeout in seconds (default: 3)
  -h, --help       Show this help message and exit

Exit Codes:
  0: Service is healthy (HTTP 200 with ok status)
  1: Service is unreachable, timed out, or returned non-200
EOF
}

TARGET_URL="${HEALTHCHECK_URL:-http://127.0.0.1:8001/healthz}"
TIMEOUT_S=3

while [[ $# -gt 0 ]]; do
    case "$1" in
        --url)
            TARGET_URL="$2"
            shift 2
            ;;
        --port)
            TARGET_URL="http://127.0.0.1:$2/healthz"
            shift 2
            ;;
        --timeout)
            TIMEOUT_S="$2"
            shift 2
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            show_usage >&2
            exit 1
            ;;
    esac
done

# Perform health check request
RESPONSE=$(curl -s -f --max-time "${TIMEOUT_S}" "${TARGET_URL}" 2>/dev/null) || {
    echo "HEALTHCHECK FAILED: Unable to reach ${TARGET_URL}" >&2
    exit 1
}

# Verify response body indicates healthy status
if echo "${RESPONSE}" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"'; then
    exit 0
else
    echo "HEALTHCHECK FAILED: Unexpected response from ${TARGET_URL}: ${RESPONSE}" >&2
    exit 1
fi
