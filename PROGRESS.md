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

- [ ] **Prompt 4: Live Event Streaming (SSE) & Advanced API Endpoints**
  - [ ] PostgreSQL LISTEN/NOTIFY event bus for real-time fan-out
  - [ ] SSE endpoint `/api/stream` streaming probe results and cluster transitions
  - [ ] `/api/summary`, `/api/targets/{id}/series`, `/api/cluster`, `/api/export.csv`

- [ ] **Prompt 5: Live Dashboard SPA (Vanilla HTML/CSS/JS)**
  - [ ] Single-page responsive mobile-first dashboard served by FastAPI at `/`
  - [ ] Real-time phase latency breakdown, target health cards, and replica status badges
  - [ ] Add-target modal with Admin API key authorization

- [ ] **Prompt 6: Infrastructure, Load Testing, Observability & Documentation**
  - [ ] Grafana datasource and dashboard JSON provisioning
  - [ ] `loadtest/api.js` k6 benchmark script printing RPS and p95/p99
  - [ ] systemd unit `deploy/netwatch.service`
  - [ ] Shell scripts (`scripts/install.sh`, `scripts/healthcheck.sh`, `scripts/loadtest.sh`)
  - [ ] GitHub Actions CI workflow (linting, tests, >=70% coverage gate)
  - [ ] Final comprehensive README.md
