#!/usr/bin/env bash
# ==============================================================================
# NetWatch Installation and Setup Script
# Configures local environment, virtualenv, dependencies, and database migrations.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

show_usage() {
    cat << 'EOF'
Usage: scripts/install.sh [OPTIONS]

Prepares local development environment, virtual environment, dependencies,
and executes Alembic migrations under PostgreSQL advisory lock.

Options:
  --skip-migrations    Skip running database migrations
  -h, --help           Show this help message and exit
EOF
}

SKIP_MIGRATIONS=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-migrations)
            SKIP_MIGRATIONS=1
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

echo "=================================================================="
echo "          NetWatch Automated Installation & Provisioning          "
echo "=================================================================="

# 1. Verify Python >= 3.12 availability
echo "[1/4] Checking Python version..."
PYTHON_BIN=""
for candidate in "${PROJECT_ROOT}/.venv/bin/python3" python3.12 python3 python; do
    if [[ -x "${candidate}" ]] || command -v "${candidate}" &> /dev/null; then
        if "${candidate}" -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" 2>/dev/null; then
            PYTHON_BIN="${candidate}"
            break
        fi
    fi
done

if [[ -z "${PYTHON_BIN}" ]]; then
    echo "ERROR: Python 3.12 or newer is required to run NetWatch." >&2
    exit 1
fi
echo "  -> Found Python: $("${PYTHON_BIN}" --version)"

# 2. Virtual environment setup
echo "[2/4] Setting up Python virtual environment (.venv)..."
if [[ ! -d "${PROJECT_ROOT}/.venv" ]]; then
    "${PYTHON_BIN}" -m venv "${PROJECT_ROOT}/.venv"
    echo "  -> Created new virtual environment in .venv"
else
    echo "  -> Existing virtual environment detected in .venv"
fi

VENV_PYTHON="${PROJECT_ROOT}/.venv/bin/python3"
VENV_PIP="${PROJECT_ROOT}/.venv/bin/pip"

# 3. Install project dependencies
echo "[3/4] Installing NetWatch package dependencies..."
if command -v uv &> /dev/null; then
    uv pip install --python "${VENV_PYTHON}" -e ".[dev]"
else
    "${VENV_PIP}" install --quiet --upgrade pip
    "${VENV_PIP}" install --quiet -e ".[dev]"
fi
echo "  -> Dependencies successfully installed."

# 4. Environment config & Database migrations
echo "[4/4] Verifying configuration and database schema..."
if [[ ! -f "${PROJECT_ROOT}/.env" ]]; then
    if [[ -f "${PROJECT_ROOT}/.env.example" ]]; then
        cp "${PROJECT_ROOT}/.env.example" "${PROJECT_ROOT}/.env"
        echo "  -> Initialized .env from .env.example"
    fi
fi

if [[ "${SKIP_MIGRATIONS}" -eq 0 ]]; then
    echo "  -> Applying Alembic migrations under PostgreSQL advisory lock..."
    if "${PROJECT_ROOT}/.venv/bin/alembic" upgrade head; then
        echo "  -> Database migrations up to date."
    else
        echo "  -> Warning: Alembic migrations failed. Ensure PostgreSQL is active." >&2
    fi
fi

echo "=================================================================="
echo "  NetWatch installation complete!"
echo "  Start local replica:   .venv/bin/uvicorn netwatch.main:app --port 8001"
echo "  Start full cluster:    docker compose up -d"
echo "  Run smoke tests:       scripts/smoke.sh"
echo "=================================================================="
