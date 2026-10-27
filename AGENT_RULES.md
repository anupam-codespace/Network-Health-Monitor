# Agent Rules for NetWatch

These standing rules apply across all implementation phases of the NetWatch project.

## 1. Fixed Tech Stack
- **Runtime & Language**: Python 3.12 with `asyncio`.
- **Web API**: FastAPI + Uvicorn (REST API and Server-Sent Events).
- **Database & ORM**: PostgreSQL 16, SQLAlchemy 2.0 (async), `asyncpg`, Alembic migrations.
- **Probes**: `dnspython` for DNS; standard library `asyncio` and `ssl` for TCP, TLS, and HTTP phase timing.
- **CLI**: Typer (Rich-free plain text table output).
- **Observability**: `prometheus_client` exporter, Grafana dashboards.
- **Containers**: Docker multi-stage build, Docker Compose.
- **Automation & OS**: Bash scripts, systemd service unit (`deploy/netwatch.service`).
- **Testing & Quality**: `pytest`, `pytest-asyncio`, `pytest-cov`, `httpx` (for test requests), Ruff linter/formatter.
- **Performance**: `k6` load testing.
- **Frontend**: Vanilla HTML/CSS/JavaScript single-page application (no framework, mobile-first).
- **Rule**: Add no other major dependencies.

## 2. Measurement Integrity
- **NEVER invent measurements**: Never hardcode or fake RPS, latency, failover duration, or test coverage numbers in any file or report.
- Verification scripts and tests must print real measurements; developers copy real outputs directly.

## 3. Code Standards & Simplicity
- **No Placeholders**: Never commit files containing `TODO`, `[N]`, or placeholder comments.
- **Strict Typing**: Type hints must be used across all function parameters and return types.
- **Concise Functions**: Functions should remain short (under ~30 lines wherever practical) to ensure clarity for technical interviews.
- **Self-Documenting Architectural Decisions**: Provide a one-line docstring explaining **WHY** (not merely what) for every non-obvious design decision.

## 4. Test Discipline & Delivery
- Every module must ship with its unit and integration tests in the same prompt.
- Network probes must be tested against local mock/in-memory servers without requiring external internet reachability.
- At the end of each prompt: run every verification command, paste real output, update `PROGRESS.md`, then pause and await user confirmation.
- If an environmental or platform feature cannot work as specified (e.g. absent system daemon or container runtime), declare it plainly rather than simulating or faking behavior.
