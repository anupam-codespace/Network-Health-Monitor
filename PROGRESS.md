# NetWatch Project Progress

Tracking the 6 core development milestones of the NetWatch Network Health Monitor.

- [ ] **Prompt 1: Skeleton, DB Migrations under Advisory Lock, RBAC, Probes & CLI**
  - [ ] Package skeleton, config with pydantic-settings, `.env.example`, `.gitignore`
  - [ ] PostgreSQL models for all 6 tables: `targets`, `results`, `api_keys`, `replica_heartbeats`, `leadership`, `events`
  - [ ] Alembic initial migration with startup execution under PostgreSQL advisory lock
  - [ ] API-key authentication (SHA-256 hashed keys, admin/viewer RBAC, env seeding)
  - [ ] Targets CRUD API endpoints with field validation
  - [ ] 4-phase network probes returning dataclasses with millisecond latencies (DNS, TCP, TLS, HTTP)
  - [ ] Plain-text table CLI (`netwatch probe <host> [--port 443]`) without Rich dependency
  - [ ] Multi-stage Dockerfile and docker-compose.yml
  - [ ] Test suite covering probes, RBAC rules, and advisory lock migration race prevention
  - [ ] Real verification output verified

- [ ] **Prompt 2: Scheduler, Results Storage, Prometheus Metrics & YAML Seeding**
  - [ ] Bounded concurrency scheduler with asyncio semaphores
  - [ ] Telemetry persistence into `results` table
  - [ ] Seed initial targets from `seeds/targets.yaml`
  - [ ] Prometheus metrics exporter (`probe_duration_seconds`, `probe_success`, `tls_cert_expiry_days`, `netwatch_is_leader`, `probes_total`)

- [ ] **Prompt 3: Leader Election, Heartbeats & Two Replicas Failover**
  - [ ] Dedicated long-lived PostgreSQL advisory lock election engine
  - [ ] 2-second replica heartbeat engine updating `replica_heartbeats`
  - [ ] Two-replica Docker Compose configuration (replica-1 on 8001, replica-2 on 8002)
  - [ ] `scripts/failover_demo.sh` demonstrating measured leader failover

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
