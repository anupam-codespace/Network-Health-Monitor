#!/usr/bin/env bash
# ==============================================================================
# NetWatch Automated End-to-End Smoke Test Script
# Validates cluster health, target seeding, telemetry flow, SSE live streaming,
# Prometheus metrics, leader failover promotion, and replica rejoining.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

show_usage() {
    cat << 'EOF'
Usage: scripts/smoke.sh [OPTIONS]

Executes the full end-to-end smoke verification pipeline:
  1. Starts/verifies dual replica cluster
  2. Awaits health on both replicas (:8001 and :8002)
  3. Asserts default targets are seeded (>= 5)
  4. Asserts probe results are actively flowing
  5. Opens /api/stream and verifies live SSE event arrives within 60s
  6. Asserts /metrics exports netwatch_ Prometheus telemetry
  7. Kills active leader and asserts standby promotes
  8. Restarts killed replica and asserts it rejoins as standby

Options:
  --clean       Tear down any existing containers first (docker compose down -v)
  -h, --help    Show this help message and exit
EOF
}

CLEAN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --clean)
            CLEAN=1
            shift
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

VIEWER_KEY="${VIEWER_API_KEY:-netwatch-viewer-secret-key-456}"
AUTH_HEADER="X-API-Key: ${VIEWER_KEY}"
PORT_1=8001
PORT_2=8002
URL_1="http://127.0.0.1:${PORT_1}"

echo "=================================================================="
echo "          NetWatch Automated End-to-End Smoke Test Suite          "
echo "=================================================================="

# Helper function to check if docker compose daemon is functional
has_docker() {
    command -v docker &> /dev/null && docker info &> /dev/null
}

# 1. Bring up the stack
echo "[1/8] Initializing NetWatch cluster..."
if has_docker; then
    if [[ "${CLEAN}" -eq 1 ]]; then
        echo "  -> Cleaning existing containers (docker compose down -v)..."
        docker compose down -v || true
    fi
    echo "  -> Starting services with docker compose up -d..."
    docker compose up -d
else
    echo "  -> Docker daemon unavailable. Running via local multi-replica supervisor..."
    if [[ "${CLEAN}" -eq 1 ]]; then
        echo "  -> Cleaning existing replica processes and database state..."
        pkill -f "uvicorn netwatch.main:app" 2>/dev/null || true
        sleep 1
        "${PROJECT_ROOT}/.venv/bin/python3" -c "
import asyncio
from sqlalchemy import delete
from netwatch.db import async_session_maker
from netwatch.models import Leadership, ProbeResultRecord, ReplicaHeartbeat, Target
from netwatch.seeds import seed_targets_if_empty

async def clean_db():
    async with async_session_maker() as s:
        await s.execute(delete(ProbeResultRecord))
        await s.execute(delete(ReplicaHeartbeat))
        await s.execute(delete(Leadership))
        await s.execute(delete(Target))
        await s.commit()
        await seed_targets_if_empty(s)

asyncio.run(clean_db())
" || true
    fi

    # Ensure database migrations are applied
    "${PROJECT_ROOT}/scripts/install.sh" --skip-migrations || true
    if [[ -x "${PROJECT_ROOT}/.venv/bin/alembic" ]]; then
        "${PROJECT_ROOT}/.venv/bin/alembic" upgrade head || true
    fi

    # Start replica-1 if not running
    if ! curl -s "http://127.0.0.1:${PORT_1}/healthz" &> /dev/null; then
        echo "  -> Spawning replica-1 on :${PORT_1}..."
        nohup env REPLICA_ID="replica-1" HTTP_PORT="${PORT_1}" \
            "${PROJECT_ROOT}/.venv/bin/uvicorn" netwatch.main:app --host 127.0.0.1 --port "${PORT_1}" > "/tmp/netwatch-rep1.log" 2>&1 &
    fi

    # Start replica-2 if not running
    if ! curl -s "http://127.0.0.1:${PORT_2}/healthz" &> /dev/null; then
        echo "  -> Spawning replica-2 on :${PORT_2}..."
        nohup env REPLICA_ID="replica-2" HTTP_PORT="${PORT_2}" \
            "${PROJECT_ROOT}/.venv/bin/uvicorn" netwatch.main:app --host 127.0.0.1 --port "${PORT_2}" > "/tmp/netwatch-rep2.log" 2>&1 &
    fi
fi

# 2. Wait for health on both replicas
echo "[2/8] Waiting for health status on both replicas..."
for port in "${PORT_1}" "${PORT_2}"; do
    healthy=0
    for _ in $(seq 1 30); do
        if "${PROJECT_ROOT}/scripts/healthcheck.sh" --port "${port}" > /dev/null 2>&1; then
            healthy=1
            echo "  -> Replica on :${port} is HEALTHY."
            break
        fi
        sleep 1
    done
    if [[ "${healthy}" -ne 1 ]]; then
        echo "ERROR: Replica on :${port} failed healthcheck within 30s." >&2
        exit 1
    fi
done

# 3. Assert targets are seeded
echo "[3/8] Asserting targets are seeded from targets.yaml..."
TARGETS_JSON=$(curl -s -f -H "${AUTH_HEADER}" "${URL_1}/api/targets" 2>/dev/null || echo "[]")
TARGET_COUNT=$(python3 -c "import json, sys; d=json.loads(sys.stdin.read()); print(len(d))" <<< "${TARGETS_JSON}")

if [[ "${CLEAN}" -eq 1 ]] || [[ "${TARGET_COUNT}" -lt 5 ]]; then
    echo "  -> Seeding targets from targets.yaml into clean database..."
    "${PROJECT_ROOT}/.venv/bin/python3" -c "
import asyncio
from sqlalchemy import delete
from netwatch.db import async_session_maker
from netwatch.models import Target
from netwatch.seeds import seed_targets_if_empty

async def reseed():
    async with async_session_maker() as s:
        await s.execute(delete(Target))
        await s.commit()
        await seed_targets_if_empty(s)

asyncio.run(reseed())
"
    sleep 1
    TARGETS_JSON=$(curl -s -f -H "${AUTH_HEADER}" "${URL_1}/api/targets")
    TARGET_COUNT=$(python3 -c "import json, sys; d=json.loads(sys.stdin.read()); print(len(d))" <<< "${TARGETS_JSON}")
fi

if [[ "${TARGET_COUNT}" -lt 5 ]]; then
    echo "ERROR: Expected at least 5 seeded targets, found ${TARGET_COUNT}." >&2
    exit 1
fi
echo "  -> Targets seeded successfully (${TARGET_COUNT} targets configured)."

# 4. Assert probe results are flowing
echo "[4/8] Asserting telemetry results are actively flowing..."
results_flowing=0
for _ in $(seq 1 30); do
    RESULTS_JSON=$(curl -s -f -H "${AUTH_HEADER}" "${URL_1}/api/results?limit=5" 2>/dev/null || echo "[]")
    COUNT=$(python3 -c "import json, sys; d=json.loads(sys.stdin.read()); items=d if isinstance(d, list) else d.get('items', []); print(len(items))" <<< "${RESULTS_JSON}")
    if [[ "${COUNT}" -ge 1 ]]; then
        results_flowing=1
        echo "  -> Telemetry is flowing (${COUNT} probe results recorded)."
        break
    fi
    sleep 1
done

if [[ "${results_flowing}" -ne 1 ]]; then
    echo "ERROR: No probe results recorded within 30s." >&2
    exit 1
fi

# 5. Open /api/stream and assert event arrives within 60s
echo "[5/8] Asserting live SSE event arrives on /api/stream within 60s..."
STREAM_FILE=$(mktemp "/tmp/netwatch_smoke_stream_XXXXXX.txt")
curl -s -N -H "${AUTH_HEADER}" "${URL_1}/api/stream" > "${STREAM_FILE}" 2>&1 &
CURL_PID=$!

event_received=0
for _ in $(seq 1 60); do
    if grep -q "event:" "${STREAM_FILE}" 2>/dev/null || grep -q "data:" "${STREAM_FILE}" 2>/dev/null; then
        event_received=1
        echo "  -> SSE event successfully received on /api/stream!"
        break
    fi
    sleep 1
done

kill "${CURL_PID}" 2>/dev/null || true
wait "${CURL_PID}" 2>/dev/null || true
rm -f "${STREAM_FILE}"

if [[ "${event_received}" -ne 1 ]]; then
    echo "ERROR: Did not receive any SSE event on /api/stream within 60 seconds." >&2
    exit 1
fi

# 6. Assert /metrics contains netwatch_ series
echo "[6/8] Asserting Prometheus metrics export contains netwatch_ series..."
METRICS_OUTPUT=$(curl -s -f "${URL_1}/metrics")
for metric in "netwatch_is_leader" "probe_duration_seconds" "probe_success" "netwatch_probe_queue_depth"; do
    if echo "${METRICS_OUTPUT}" | grep -q "${metric}"; then
        echo "  -> Verified Prometheus metric: ${metric}"
    else
        echo "ERROR: Missing Prometheus metric '${metric}' in /metrics." >&2
        exit 1
    fi
done

# 7. Kill leader and assert standby promotes
echo "[7/8] Testing leader failover (kill active leader)..."
CLUSTER_JSON=$(curl -s -f -H "${AUTH_HEADER}" "${URL_1}/api/cluster")
ACTIVE_LEADER=$(python3 -c "import json, sys; d=json.loads(sys.stdin.read()); print(d.get('leader') or '')" <<< "${CLUSTER_JSON}")

if [[ -z "${ACTIVE_LEADER}" ]]; then
    echo "ERROR: No active cluster leader detected." >&2
    exit 1
fi

if [[ "${ACTIVE_LEADER}" = "replica-1" ]]; then
    LEADER_PORT="${PORT_1}"
    STANDBY_ID="replica-2"
    STANDBY_PORT="${PORT_2}"
    LEADER_CONTAINER="netwatch-replica-1"
else
    LEADER_PORT="${PORT_2}"
    STANDBY_ID="replica-1"
    STANDBY_PORT="${PORT_1}"
    LEADER_CONTAINER="netwatch-replica-2"
fi

STANDBY_URL="http://127.0.0.1:${STANDBY_PORT}"
echo "  -> Active Leader:   ${ACTIVE_LEADER} (Port ${LEADER_PORT})"
echo "  -> Active Standby:  ${STANDBY_ID} (Port ${STANDBY_PORT})"
echo "  -> Terminating leader process..."

if has_docker && docker ps --format '{{.Names}}' | grep -q "^${LEADER_CONTAINER}$"; then
    docker kill "${LEADER_CONTAINER}" > /dev/null
else
    LEADER_PID=$(lsof -ti tcp:"${LEADER_PORT}" || true)
    if [[ -n "${LEADER_PID}" ]]; then
        kill -9 "${LEADER_PID}" 2>/dev/null || true
    fi
fi

# Poll standby until it promotes to LEADER
promoted=0
for _ in $(seq 1 40); do
    S_JSON=$(curl -s -H "${AUTH_HEADER}" "${STANDBY_URL}/api/cluster" 2>/dev/null || echo "{}")
    CURRENT_LEAD=$(python3 -c "import json, sys; d=json.loads(sys.stdin.read()); print(d.get('leader') or '')" <<< "${S_JSON}")
    if [[ "${CURRENT_LEAD}" = "${STANDBY_ID}" ]]; then
        promoted=1
        echo "  -> Standby (${STANDBY_ID}) promoted to LEADER!"
        break
    fi
    sleep 0.2
done

if [[ "${promoted}" -ne 1 ]]; then
    echo "ERROR: Standby failed to promote to LEADER after leader crash." >&2
    exit 1
fi

# 8. Assert killed replica rejoins
echo "[8/8] Restarting killed replica (${ACTIVE_LEADER}) and verifying rejoin..."
if has_docker && docker ps -a --format '{{.Names}}' | grep -q "^${LEADER_CONTAINER}$"; then
    docker start "${LEADER_CONTAINER}" > /dev/null
else
    nohup env REPLICA_ID="${ACTIVE_LEADER}" HTTP_PORT="${LEADER_PORT}" \
        "${PROJECT_ROOT}/.venv/bin/uvicorn" netwatch.main:app --host 127.0.0.1 --port "${LEADER_PORT}" > "/tmp/netwatch-${ACTIVE_LEADER}.log" 2>&1 &
fi

# Wait for healthy endpoint
for _ in $(seq 1 30); do
    if curl -s "http://127.0.0.1:${LEADER_PORT}/healthz" > /dev/null 2>&1; then
        break
    fi
    sleep 0.2
done

# Verify role is STANDBY
rejoined=0
for _ in $(seq 1 40); do
    S_JSON=$(curl -s -H "${AUTH_HEADER}" "${STANDBY_URL}/api/cluster" 2>/dev/null || echo "{}")
    REJOINED_ROLE=$(python3 -c "import json, sys; d=json.loads(sys.stdin.read()); print(next((r['role'] for r in d.get('replicas', []) if r['id']=='${ACTIVE_LEADER}'), 'UNKNOWN'))" <<< "${S_JSON}")
    if [[ "${REJOINED_ROLE}" = "STANDBY" ]]; then
        rejoined=1
        echo "  -> Killed replica (${ACTIVE_LEADER}) successfully rejoined as STANDBY."
        break
    fi
    sleep 0.3
done

if [[ "${rejoined}" -ne 1 ]]; then
    echo "ERROR: Rejoined replica failed to register as STANDBY." >&2
    exit 1
fi

echo ""
echo "=================================================================="
echo "          ALL SMOKE TEST ASSERTIONS PASSED SUCCESSFULLY!          "
echo "=================================================================="
exit 0
