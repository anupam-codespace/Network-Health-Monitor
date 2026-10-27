#!/usr/bin/env bash
# ==============================================================================
# NetWatch Automated k6 Load Testing Script
# Benchmarks REST API endpoints (/api/summary, /api/results, /api/targets)
# Uses native k6 if available, or falls back to running k6 via Docker.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

show_usage() {
    cat << 'EOF'
Usage: scripts/loadtest.sh [OPTIONS]

Runs the k6 load test against a NetWatch replica.

Options:
  --url URL        Target NetWatch base URL (default: http://127.0.0.1:8001)
  --key KEY        Viewer API key (default: netwatch-viewer-secret-key-456)
  -h, --help       Show this help message and exit

Environment Variables:
  TARGET_URL       Alternative way to specify target URL
  VIEWER_API_KEY   Alternative way to specify API key
EOF
}

TARGET_URL="${TARGET_URL:-http://127.0.0.1:8001}"
VIEWER_API_KEY="${VIEWER_API_KEY:-netwatch-viewer-secret-key-456}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --url)
            TARGET_URL="$2"
            shift 2
            ;;
        --key)
            VIEWER_API_KEY="$2"
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

echo "=================================================================="
echo "          NetWatch Performance Benchmark Runner (k6)              "
echo "=================================================================="
echo " Target Endpoint:  ${TARGET_URL}"
echo " Load Script:      loadtest/api.js"
echo " Output Summary:   loadtest/last-run.json"
echo "=================================================================="

# Ensure loadtest directory exists
mkdir -p "${PROJECT_ROOT}/loadtest"

if command -v k6 &> /dev/null; then
    echo "Running native k6 binary..."
    k6 run \
        --env TARGET_URL="${TARGET_URL}" \
        --env VIEWER_API_KEY="${VIEWER_API_KEY}" \
        "${PROJECT_ROOT}/loadtest/api.js"
elif command -v docker &> /dev/null; then
    echo "k6 not found locally. Running via Docker (grafana/k6)..."
    docker run --rm \
        --network host \
        -v "${PROJECT_ROOT}:/work" \
        -w /work \
        -e TARGET_URL="${TARGET_URL}" \
        -e VIEWER_API_KEY="${VIEWER_API_KEY}" \
        grafana/k6:latest run loadtest/api.js
else
    echo "ERROR: Neither 'k6' nor 'docker' is installed on this system." >&2
    echo "Please install k6 (e.g. 'brew install k6' or 'apt-get install k6') or Docker." >&2
    exit 1
fi

if [[ -f "${PROJECT_ROOT}/loadtest/last-run.json" ]]; then
    echo ""
    echo "Load test completed successfully. Generated loadtest/last-run.json:"
    cat "${PROJECT_ROOT}/loadtest/last-run.json"
fi
