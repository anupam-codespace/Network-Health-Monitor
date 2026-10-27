# NetWatch Project Progress

Tracking the 6 core development milestones of the NetWatch Network Health Monitor.

- [x] **Prompt 1: Skeleton, DB Migrations under Advisory Lock, RBAC, Probes & CLI**
  - [x] Package skeleton, config with pydantic-settings, `.env.example`, `.gitignore`
  - [x] PostgreSQL models for all 6 tables: `targets`, `results`, `api_keys`, `replica_heartbeats`, `leadership`, `events`
  - [x] Alembic initial migration with startup execution under PostgreSQL advisory lock
  - [x] API-key authentication (SHA-256 hashed keys, admin/viewer RBAC, env seeding)
  - [x] Targets CRUD API endpoints with field validation
  - [x] 4-phase network probes returning dataclasses with millisecond latencies (DNS, TCP, TLS, HTTP)
  - [x] Plain-text table CLI (`netwatch probe <host> [--port 443]`) without Rich dependency
  - [x] Multi-stage Dockerfile and docker-compose.yml
  - [x] Test suite covering probes, RBAC rules, and advisory lock migration race prevention
  - [x] Real verification output verified

- [x] **Prompt 2: Scheduler, Results Storage, Prometheus Metrics & YAML Seeding**
  - [x] Bounded concurrency scheduler with asyncio semaphores (MAX_CONCURRENT_PROBES, default 50)
  - [x] Telemetry persistence into `results` table with `replica_id` and `epoch`
  - [x] Hourly retention engine pruning records older than `RETENTION_DAYS` (default 7)
  - [x] Seed initial targets from `targets.yaml` (5 reliable public hosts)
  - [x] Prometheus metrics exporter (`probe_duration_seconds`, `probe_success`, `tls_cert_expiry_days`, `probes_total`, `netwatch_is_leader`, `netwatch_probe_queue_depth`)
  - [x] Analytics API endpoints: `/api/summary`, keyset-paginated `/api/results`, `/api/targets/{id}/series`, `/api/targets/{id}`, streamed `/api/export.csv`
  - [x] Alembic migration `002_add_indexes_for_analytics` with composite indexes
  - [x] Comprehensive test suite (42 tests, 84.8% coverage)

- [x] **Prompt 3: Leader Election, Heartbeats & Two Replicas Failover**
  - [x] Dedicated long-lived PostgreSQL advisory lock election engine (`netwatch/leader.py`)
  - [x] 2-second replica heartbeat engine updating `replica_heartbeats` (`netwatch/heartbeat.py`)
  - [x] Two-replica Docker Compose configuration (replica-1 on 8001, replica-2 on 8002)
  - [x] Monotonic epoch fencing on results table rejecting stale writes (`netwatch/storage.py`)
  - [x] High-availability documentation (`docs/ha.md`)
  - [x] `scripts/failover_demo.sh` demonstrating measured leader failover (hard kill: 2.18s, graceful stop: 6.05s)

- [x] **Prompt 4: Live Event Streaming (SSE) & Advanced API Endpoints**
  - [x] PostgreSQL LISTEN/NOTIFY event bus for real-time fan-out (`PostgresEventListener` + `EventBroker`)
  - [x] SSE endpoint `/api/stream` streaming probe results, cluster transitions, heartbeats, and target updates
  - [x] Full suite of analytics API endpoints: `/api/summary`, `/api/targets/{id}/series`, `/api/cluster`, `/api/events`, `/api/export.csv`

- [x] **Prompt 5: Live Dashboard SPA (Vanilla HTML/CSS/JS)**
  - [x] Single-page responsive mobile-first dashboard served by FastAPI at `/` (96.02 KB total JS+CSS)
  - [x] Real-time phase latency breakdown (2x2 cards with trend chips), SVG line chart from `/series`, TLS card (amber under 14 days), last-20-probes row (green/red with icons)
  - [x] Target Detail (`#/target/<id>`), Targets card list (`#/targets`) with search-as-you-type and status filter
  - [x] Cluster view (`#/cluster`): two replica cards, flip animation on leadership swap, exact `"Leadership gap X.X s"` computed pill from real heartbeat/event timestamps
  - [x] Admin bottom sheet modal with inline validation; viewers see hidden/disabled controls
  - [x] Disconnected banner `"Connection lost. Retrying..."` with auto-reconnect, skeletons, empty states
  - [x] 5 async Playwright E2E tests verifying all screens, failover drill, disconnect handling, and RBAC
  - [x] Complete mobile (390px) and desktop (1280px) screenshot captures in `docs/screens/`

- [x] **Prompt 6: Infrastructure, Load Testing, Observability & Documentation**
  - [x] Prometheus config scraping both replicas; Grafana datasource & dashboard JSON committed
  - [x] `loadtest/api.js` k6 benchmark with console RPS, p95, p99 and `loadtest/last-run.json`
  - [x] Hardened systemd unit `deploy/netwatch.service` and Linux VPS guide `docs/deploy.md`
  - [x] Shell scripts with `set -euo pipefail`, usage docs, shellcheck clean (`install.sh`, `healthcheck.sh`, `failover_demo.sh`, `loadtest.sh`, `smoke.sh`)
  - [x] Comprehensive end-to-end smoke test `scripts/smoke.sh` asserting all 8 cluster invariants
  - [x] GitHub Actions CI workflow (`.github/workflows/ci.yml`) with ruff, pytest (70% gate), shellcheck, docker build, and smoke test
  - [x] Complete README.md with quickstart, Mermaid diagram, design decisions, blackbox_exporter comparison, and limitations
  - [x] Feature verification checklist (`FEATURE_CHECKLIST.md`) documenting all claimed features with proving commands and real outputs
