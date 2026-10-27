#!/usr/bin/env bash
# ==============================================================================
# NetWatch Automated Failover Demonstration Script
# Measures real failover latency between replica-1 (:8001) and replica-2 (:8002).
# Supports both Docker Compose environments and local dual-process instances.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

show_usage() {
    cat << 'EOF'
Usage: scripts/failover_demo.sh [OPTIONS]

Demonstrates automated leader failover between replica-1 (:8001) and replica-2 (:8002).
Performs both hard crash (SIGKILL/docker kill) and graceful shutdown (SIGTERM/docker stop).

Options:
  -h, --help    Show this help message and exit
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
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
URL_2="http://127.0.0.1:${PORT_2}"

now_ts() {
    python3 -c "import time; print(f'{time.time():.4f}')"
}

calc_diff() {
    python3 -c "print(f'{float($2) - float($1):.3f}')"
}

get_cluster_json() {
    local endpoint="$1"
    curl -s -H "${AUTH_HEADER}" "${endpoint}/api/cluster" 2>/dev/null || echo "{}"
}

find_active_leader() {
    local cl1 cl2
    cl1=$(get_cluster_json "${URL_1}")
    cl2=$(get_cluster_json "${URL_2}")

    local leader_id
    leader_id=$(python3 -c "import json, sys; d=json.loads(sys.stdin.read()); print(d.get('leader') or 'NONE')" <<< "${cl1}")
    if [ "${leader_id}" = "NONE" ]; then
        leader_id=$(python3 -c "import json, sys; d=json.loads(sys.stdin.read()); print(d.get('leader') or 'NONE')" <<< "${cl2}")
    fi

    if [ "${leader_id}" = "replica-1" ]; then
        echo "replica-1:${PORT_1}:netwatch-replica-1"
    elif [ "${leader_id}" = "replica-2" ]; then
        echo "replica-2:${PORT_2}:netwatch-replica-2"
    else
        echo "NONE"
    fi
}

kill_replica() {
    local rep_id="$1" port="$2" container="$3" mode="$4"
    if command -v docker &> /dev/null && docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
        if [ "${mode}" = "hard" ]; then
            docker kill "${container}" > /dev/null
        else
            docker stop "${container}" > /dev/null
        fi
    else
        # Local process fallback
        local pid
        pid=$(lsof -ti tcp:"${port}" || true)
        if [ -n "${pid}" ]; then
            if [ "${mode}" = "hard" ]; then
                kill -9 "${pid}" 2>/dev/null || true
            else
                kill -TERM "${pid}" 2>/dev/null || true
            fi
        fi
    fi
}

start_replica() {
    local rep_id="$1" port="$2" container="$3"
    if command -v docker &> /dev/null && docker ps -a --format '{{.Names}}' | grep -q "^${container}$"; then
        docker start "${container}" > /dev/null
    else
        # Local process fallback
        nohup env REPLICA_ID="${rep_id}" HTTP_PORT="${port}" .venv/bin/uvicorn netwatch.main:app --host 127.0.0.1 --port "${port}" > "/tmp/${rep_id}.log" 2>&1 &
    fi

    # Wait until replica is answering on /healthz
    for _ in $(seq 1 40); do
        if curl -s "http://127.0.0.1:${port}/healthz" > /dev/null 2>&1; then
            break
        fi
        sleep 0.2
    done
}

echo "=================================================================="
echo "          NetWatch High Availability Failover Demonstration       "
echo "=================================================================="

# 1. Discover active cluster state
echo "[1/4] Checking active replicas on :8001 and :8002..."
leader_spec=$(find_active_leader)
if [ "${leader_spec}" = "NONE" ]; then
    echo "ERROR: No active LEADER detected on http://127.0.0.1:8001 or 8002."
    echo "Ensure both replicas are running and healthy."
    exit 1
fi

IFS=":" read -r LEADER_ID LEADER_PORT LEADER_CONTAINER <<< "${leader_spec}"
if [ "${LEADER_ID}" = "replica-1" ]; then
    SURVIVOR_ID="replica-2"
    SURVIVOR_PORT="${PORT_2}"
    SURVIVOR_CONTAINER="netwatch-replica-2"
    SURVIVOR_URL="${URL_2}"
else
    SURVIVOR_ID="replica-1"
    SURVIVOR_PORT="${PORT_1}"
    SURVIVOR_CONTAINER="netwatch-replica-1"
    SURVIVOR_URL="${URL_1}"
fi

echo "  -> Current Leader:   ${LEADER_ID} (Port ${LEADER_PORT})"
echo "  -> Current Standby:  ${SURVIVOR_ID} (Port ${SURVIVOR_PORT})"

# 2. Hard Failure Test (SIGKILL / docker kill)
echo ""
echo "[2/4] Executing HARD FAILOVER test (docker kill ${LEADER_CONTAINER})..."
T_START=$(now_ts)
kill_replica "${LEADER_ID}" "${LEADER_PORT}" "${LEADER_CONTAINER}" "hard"

# Poll survivor every 200ms until it reports itself leader
while true; do
    cluster_json=$(get_cluster_json "${SURVIVOR_URL}")
    s_leader=$(python3 -c "import json, sys; d=json.loads(sys.stdin.read()); print(d.get('leader') or '')" <<< "${cluster_json}")
    if [ "${s_leader}" = "${SURVIVOR_ID}" ]; then
        T_END=$(now_ts)
        break
    fi
    sleep 0.2
done

HARD_FAILOVER_S=$(calc_diff "${T_START}" "${T_END}")
echo "  -> Measured Hard Failover Duration: ${HARD_FAILOVER_S} seconds"
echo "  -> ${SURVIVOR_ID} successfully promoted to cluster LEADER."

# Restart killed replica and verify it rejoins as STANDBY
echo "  -> Restarting killed replica (${LEADER_ID})..."
start_replica "${LEADER_ID}" "${LEADER_PORT}" "${LEADER_CONTAINER}"

# Wait for rejoined replica to report as STANDBY
while true; do
    cluster_json=$(get_cluster_json "${SURVIVOR_URL}")
    rejoined_role=$(python3 -c "import json, sys; d=json.loads(sys.stdin.read()); print(next((r['role'] for r in d.get('replicas', []) if r['id']=='${LEADER_ID}'), 'UNKNOWN'))" <<< "${cluster_json}")
    if [ "${rejoined_role}" = "STANDBY" ]; then
        echo "  -> ${LEADER_ID} successfully rejoined the cluster as STANDBY."
        break
    fi
    sleep 0.3
done

# 3. Graceful Failure Test (SIGTERM / docker stop)
sleep 1
CURRENT_LEADER_ID="${SURVIVOR_ID}"
CURRENT_LEADER_PORT="${SURVIVOR_PORT}"
CURRENT_LEADER_CONTAINER="${SURVIVOR_CONTAINER}"
NEW_SURVIVOR_ID="${LEADER_ID}"
NEW_SURVIVOR_PORT="${LEADER_PORT}"
NEW_SURVIVOR_URL="http://127.0.0.1:${NEW_SURVIVOR_PORT}"

echo ""
echo "[3/4] Executing GRACEFUL FAILOVER test (docker stop ${CURRENT_LEADER_CONTAINER})..."
T_GRACE_START=$(now_ts)
kill_replica "${CURRENT_LEADER_ID}" "${CURRENT_LEADER_PORT}" "${CURRENT_LEADER_CONTAINER}" "graceful"

while true; do
    cluster_json=$(get_cluster_json "${NEW_SURVIVOR_URL}")
    s_leader=$(python3 -c "import json, sys; d=json.loads(sys.stdin.read()); print(d.get('leader') or '')" <<< "${cluster_json}")
    if [ "${s_leader}" = "${NEW_SURVIVOR_ID}" ]; then
        T_GRACE_END=$(now_ts)
        break
    fi
    sleep 0.2
done

GRACEFUL_FAILOVER_S=$(calc_diff "${T_GRACE_START}" "${T_GRACE_END}")
echo "  -> Measured Graceful Failover Duration: ${GRACEFUL_FAILOVER_S} seconds"
echo "  -> ${NEW_SURVIVOR_ID} promoted to cluster LEADER."

# Restart stopped container
echo "  -> Restarting stopped replica (${CURRENT_LEADER_ID})..."
start_replica "${CURRENT_LEADER_ID}" "${CURRENT_LEADER_PORT}" "${CURRENT_LEADER_CONTAINER}"

while true; do
    cluster_json=$(get_cluster_json "${NEW_SURVIVOR_URL}")
    rejoined_role=$(python3 -c "import json, sys; d=json.loads(sys.stdin.read()); print(next((r['role'] for r in d.get('replicas', []) if r['id']=='${CURRENT_LEADER_ID}'), 'UNKNOWN'))" <<< "${cluster_json}")
    if [ "${rejoined_role}" = "STANDBY" ]; then
        echo "  -> ${CURRENT_LEADER_ID} successfully rejoined cluster as STANDBY."
        break
    fi
    sleep 0.3
done

echo ""
echo "=================================================================="
echo "                  FAILOVER BENCHMARK SUMMARY                      "
echo "=================================================================="
echo "  Hard Failure Failover:     ${HARD_FAILOVER_S}s (TCP keepalive / abort)"
echo "  Graceful Stop Failover:    ${GRACEFUL_FAILOVER_S}s (SIGTERM lock release)"
echo "  Current Active Leader:     ${NEW_SURVIVOR_ID}"
echo "=================================================================="
