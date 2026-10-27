# NetWatch: Distributed Network Health Monitor

NetWatch is an enterprise-grade, active-standby network availability and latency monitoring system. It continuously executes multi-phase latency probes across discrete network layers (DNS resolution, TCP connection, TLS handshake/certificate lifecycle, and HTTP response time), persists telemetry into PostgreSQL with monotonic epoch fencing, coordinates automated replica failover via PostgreSQL advisory locks, and streams real-time updates over Server-Sent Events (SSE) to a mobile-first operations dashboard.

![NetWatch System Architecture](docs/assets/netwatch_system_architecture.jpg)

---

## Executive Overview

Production monitoring systems frequently suffer from three architectural failure modes:
1. **Split-Brain Probing**: When monitoring nodes experience network partitions or garbage collection freezes, duplicate probes flood monitored targets and corrupt telemetry.
2. **External Coordination Overhead**: Complex multi-node coordination often introduces fragile dependencies on separate distributed key-value stores (such as ZooKeeper, etcd, or Consul).
3. **Heavy Client Bundles**: Administrative dashboards built on massive single-page application frameworks introduce high memory footprints, layout shifts, and slow initial load times.

NetWatch resolves these challenges by uniting Python 3.12 asynchronous I/O, PostgreSQL session-level advisory locks, database-native `LISTEN`/`NOTIFY` event buses, and a pure vanilla JavaScript operations interface totaling under 100 KB with zero external frontend runtime dependencies.

---

## 3-Command Quick Start

```bash
# 1. Clone the repository and navigate to the project directory
git clone https://github.com/example/netwatch.git && cd netwatch

# 2. Initialize environment configuration and start the cluster
cp .env.example .env && docker compose up -d

# 3. Verify health status on the primary replica
curl -s http://localhost:8001/healthz
```

Once running, access the services:
* **Web Operations Dashboard**: [http://localhost:8001/](http://localhost:8001/) or [http://localhost:8002/](http://localhost:8002/)  
  *Viewer API Key*: `netwatch-viewer-secret-key-456`  
  *Admin API Key*: `netwatch-admin-secret-key-123`
* **Prometheus Telemetry Scraper**: [http://localhost:9090](http://localhost:9090)
* **Grafana Dashboards**: [http://localhost:3000](http://localhost:3000) (Default Credentials: `admin` / `admin`)

---

## Architecture Topology & Distributed Components

NetWatch deploys as an active-standby pair of identical application instances (`replica-1` and `replica-2`) backed by a PostgreSQL database and an integrated observability suite.

```mermaid
graph TD
    subgraph Clients
        Browser["Mobile & Desktop Web UI<br/>(Vanilla JS SPA <100 KB)"]
        CLI["Typer CLI<br/>(netwatch probe)"]
    end

    subgraph Dual Replicas
        R1["replica-1 :8001<br/>(FastAPI / REST / SSE)"]
        R2["replica-2 :8002<br/>(FastAPI / REST / SSE)"]
    end

    subgraph Storage & Coordination
        PG[("PostgreSQL 16")]
        AdvLock["PostgreSQL Session Advisory Lock<br/>(LEADER_ADVISORY_LOCK_ID: 827364501)"]
        Notify["LISTEN / NOTIFY Bus<br/>(netwatch_events)"]
    end

    subgraph Observability
        Prom["Prometheus :9090<br/>(Scrapes :8001 & :8002)"]
        Graf["Grafana :3000<br/>(Automated File Provisioning)"]
    end

    Browser -->|REST & Live SSE Stream| R1
    Browser -->|REST & Live SSE Stream| R2
    CLI -->|Standalone Execution| R1

    R1 -->|pg_try_advisory_lock| AdvLock
    R2 -->|pg_try_advisory_lock| AdvLock

    R1 -->|Heartbeats every 2s & Probes| PG
    R2 -->|Heartbeats every 2s| PG

    PG -->|Event Broadcast| Notify
    Notify -->|Fan-Out Stream| R1
    Notify -->|Fan-Out Stream| R2

    Prom -->|Scrapes /metrics| R1
    Prom -->|Scrapes /metrics| R2
    Prom --> Graf
```

### Component Roles

* **FastAPI Web Replicas (`replica-1` and `replica-2`)**: Run the identical container image and codebase, differentiated solely by the `REPLICA_ID` environment variable. Both replicas handle authenticated read-only and write requests. Only the elected **LEADER** executes the probe scheduling supervisor.
* **PostgreSQL 16**: Serves three critical functions: relational telemetry storage, mutual-exclusion leader election via session-level advisory locks, and live message fan-out through asynchronous `LISTEN`/`NOTIFY`.
* **Prometheus**: Automatically polls `/metrics` from both replicas every 5 seconds, recording queue depth, phase durations, leadership status, and split-brain write rejections.
* **Grafana**: Pre-configured with automated datasource provisioning and committed dashboard JSON displaying phase latency breakdowns, success rates, leader status, and TLS certificate expiration curves.

---

## Detailed System Dataflow & Execution Lifecycle

The lifecycle of an active NetWatch cluster follows a strictly choreographed sequence across election, probe scheduling, execution, persistence, and client streaming.

```mermaid
sequenceDiagram
    autonumber
    participant R1 as replica-1 (Leader)
    participant PG as PostgreSQL 16
    participant T as Monitored Target
    participant R2 as replica-2 (Standby)
    participant UI as Browser SPA

    Note over R1,PG: Phase 1: Leadership Acquisition
    R1->>PG: pg_try_advisory_lock(827364501)
    PG-->>R1: Lock Granted (Exclusive)
    R1->>PG: Increment epoch, set holder='replica-1', record event
    R1->>PG: Heartbeat update (every 2s)

    Note over R1,T: Phase 2: Probe Scheduling & Execution
    R1->>R1: Scheduler fires interval timer with jitter
    R1->>T: 1. DNS Resolution (dnspython, monotonic timer)
    R1->>T: 2. TCP Handshake (asyncio.open_connection)
    R1->>T: 3. TLS Handshake & Cert Expiry (ssl.getpeercert)
    R1->>T: 4. HTTP TTFB (httpx async client)

    Note over R1,PG: Phase 3: Fenced Storage & Event Broadcast
    R1->>PG: INSERT INTO results WHERE (SELECT epoch FROM leadership) = 1
    PG-->>R1: Row Inserted (id=42)
    R1->>PG: pg_notify('netwatch_events', payload)

    Note over PG,UI: Phase 4: Real-Time Client Fan-Out
    PG-->>R1: Asynchronous NOTIFY received
    PG-->>R2: Asynchronous NOTIFY received
    R1-->>UI: Server-Sent Events stream (/api/stream)
    UI->>UI: Update SVG chart, phase cards, status chips
```

### Step-by-Step Flow Explanation

1. **Advisory Lock Election**:
   Upon container boot, each replica establishes a dedicated `asyncpg` connection configured with aggressive TCP keepalives (`keepalives_idle=1`, `keepalives_interval=1`, `keepalives_count=3`). Replicas attempt to acquire the global cluster lock via `SELECT pg_try_advisory_lock(827364501)`. The winning replica increments the cluster `epoch` in the `leadership` table, records a `leader_acquired` event, and activates its probe scheduler. The second replica transitions to `STANDBY` mode.

2. **Target Scheduling with Concurrency Bounding**:
   The leader's scheduler inspects the `targets` table, computes random start jitter to distribute execution evenly across intervals (15s, 30s, 60s), and bounds execution concurrency with an `asyncio.Semaphore` (configurable via `MAX_CONCURRENT_PROBES`, default 50). Targets added or deleted through the API are dynamically synchronized without requiring service restarts.

3. **Multi-Phase Isolated Probing**:
   For each target, the probe runner executes four consecutive phases:
   * **DNS Resolution**: Resolves A/AAAA records via `dnspython`. If NXDOMAIN or timeout occurs, subsequent phases are skipped.
   * **TCP Connection**: Opens an asynchronous TCP socket to the target host and port using `time.perf_counter()` to capture sub-millisecond connection setup time.
   * **TLS Handshake & Expiry**: Performs an SSL/TLS handshake over the open socket, extracts peer certificate metadata, and calculates exact calendar days until expiration.
   * **HTTP Response**: Dispatches an HTTP `GET` request using `httpx` to measure Time-to-First-Byte (TTFB) and HTTP response status code.

4. **Monotonic Epoch Fencing**:
   To prevent split-brain zombies (for instance, an ex-leader paused during an operating system sleep or garbage collection cycle), telemetry writes utilize conditional SQL insertion:
   ```sql
   INSERT INTO results (target_id, ts, ok, dns_ms, tcp_ms, tls_ms, http_ms, total_ms, status_code, tls_days_left, error, replica_id, epoch)
   SELECT :target_id, :ts, :ok, :dns_ms, :tcp_ms, :tls_ms, :http_ms, :total_ms, :status_code, :tls_days_left, :error, :replica_id, :epoch
   WHERE COALESCE((SELECT epoch FROM leadership), 0) = :epoch
   RETURNING id;
   ```
   If a demoted replica attempts to insert telemetry with an obsolete epoch, zero rows are inserted, and the `netwatch_fenced_writes_total` Prometheus counter increments.

5. **PostgreSQL Event Bus Fan-Out**:
   Following each successful insert, the application issues `SELECT pg_notify('netwatch_events', payload)`. Dedicated background listener tasks on all running replicas receive the notification payload and dispatch it through in-memory `asyncio.Queue` event brokers to all connected browser SSE clients.

6. **Automatic Failover & Self-Healing**:
   If the active leader crashes (`SIGKILL`, container termination, or kernel panic), the TCP socket to PostgreSQL terminates abruptly. The PostgreSQL backend immediately releases the advisory lock. Within 2 seconds, the standby replica acquires the lock, increments the epoch, and resumes probe execution. The newly promoted leader computes the exact `"Leadership gap X.X s"` timeline indicator based on the previous leader's last recorded heartbeat. When the failed node restarts, it automatically joins as `STANDBY`.

7. **Automated Telemetry Retention**:
   An asynchronous background worker executes hourly, executing a bulk `DELETE FROM results WHERE ts < NOW() - INTERVAL '7 days'` to enforce retention limits without degrading database read performance.

---

## Real-Time User & Operator Interactions

The NetWatch frontend is engineered as an event-driven Single-Page Application (SPA) designed for continuous operational visibility.

```mermaid
graph LR
    subgraph Operator Actions
        A1["Search Hostname<br/>(Real-Time Input)"]
        A2["Filter Status<br/>(All / Up / Failing)"]
        A3["Open Target Detail<br/>(Click Card)"]
        A4["Add Monitored Target<br/>(Admin Bottom Sheet)"]
        A5["Switch Time Range<br/>(1h / 6h / 24h / 7d / 30d)"]
    end

    subgraph Browser Engine
        E1["Vanilla JS Hash Router<br/>(#/overview, #/targets, #/target/:id)"]
        E2["SSE Event Consumer<br/>(EventSource Client)"]
        E3["Dynamic SVG Renderer<br/>(Cubic Bézier Interpolation)"]
    end

    subgraph Real-Time UI Updates
        U1["Status Pills & Trend Chips"]
        U2["Last-20-Probes SVG Icons"]
        U3["Soft-Filled Latency Chart"]
        U4["Leadership Swap Flip Animation"]
        U5["Network Drop Banner with Auto-Reconnect"]
    end

    A1 --> E1
    A2 --> E1
    A3 --> E1
    A4 --> E1
    A5 --> E3

    E2 --> U1
    E2 --> U2
    E2 --> U3
    E2 --> U4
    E2 --> U5
```

### Operator Interaction Modes

1. **Live Dashboard Streaming**:
   Operators opening the dashboard immediately establish an authenticated `EventSource` connection to `/api/stream`. As probes execute across the cluster, metrics cards, health chips, and latency charts update live without full-page reloads or polling overhead.

2. **Search-as-You-Type & Multi-Status Filtering**:
   In the Targets view (`#/targets`), operators can filter targets instantly by typing substrings of hostnames or toggling status pills (`All`, `Up`, `Failing`). Filtering occurs instantaneously in-memory.

3. **Target Detail Telemetry & SVG Charting**:
   Selecting a target opens `#/target/<id>`, displaying:
   * **Vector Latency Line Chart**: Rendered using mathematical cubic curve interpolation directly in SVG with a soft semi-transparent gradient fill. Operators can switch between `1h`, `6h`, `24h`, `7d`, and `30d` ranges.
   * **2x2 Protocol Phase Metric Cards**: Distinct cards for DNS, TCP, TLS, and HTTP latencies showing current timings and calculated trend chips (e.g. `+1.4 ms` or `-0.8 ms`).
   * **TLS Certificate Card**: Displays certificate subject, issuer, days remaining, and a progress bar that shifts to amber when expiration is under 14 days.
   * **Last-20-Probes Matrix**: A horizontal row of rounded square indicators showing the last 20 probe outcomes with distinct SVG checkmarks or error crosses (ensuring accessibility without relying on color alone).

4. **Bottom Sheet Target Management (Admin Only)**:
   Administrators can open the bottom sheet modal to configure new target hostnames, ports, and probe intervals (15s, 30s, 60s). Submissions validate inline. Upon creation, the modal slides closed and the new target is highlighted with a `"new"` badge for 5 seconds. For viewers, the Add button is automatically disabled and hidden.

5. **Cluster Topology & Leadership Timeline**:
   Navigating to `#/cluster` presents live status cards for `replica-1` and `replica-2`. When a leadership change occurs, the `LEADER` and `STANDBY` badges flip with a CSS 3D animation, and the calculated `"Leadership gap X.X s"` pill appears in the events audit log.

6. **Connection Drop Resilience**:
   If the network connection between client and backend disconnects, an attention banner (`"Connection lost. Retrying..."`) with a loading spinner slides into view while stale rows gray out. The client automatically backs off and reconnects, auto-clearing the banner as soon as connectivity resumes.

---

## Visual Interface Gallery

NetWatch is designed mobile-first and verified across viewports from 360px phones to 1280px desktop displays.

### Primary Screen Comparisons

| Operational View | Mobile Viewport (390px) | Desktop Viewport (1280px) |
| :--- | :--- | :--- |
| **Cluster Overview**<br/>Top 4-column card grid, 3 summary cards, active replica indicator, and live cluster state. | <img src="docs/screens/overview_390px.png" width="300" alt="Overview Mobile View" /> | <img src="docs/screens/overview_1280px.png" width="550" alt="Overview Desktop View" /> |
| **Targets Card List**<br/>Card list with search-as-you-type input, status segmentation pills, and responsive touch targets. | <img src="docs/screens/targets_390px.png" width="300" alt="Targets Mobile View" /> | <img src="docs/screens/targets_1280px.png" width="550" alt="Targets Desktop View" /> |
| **Target Detail & Chart**<br/>Soft-filled SVG latency chart, working range switch, 2x2 phase breakdown, and TLS status. | <img src="docs/screens/target_detail_390px.png" width="300" alt="Target Detail Mobile View" /> | <img src="docs/screens/target_detail_1280px.png" width="550" alt="Target Detail Desktop View" /> |
| **Cluster View & Timeline**<br/>Dual replica cards, 3D flip badge animation, exact leadership gap pill, and audit log. | <img src="docs/screens/cluster_390px.png" width="300" alt="Cluster Mobile View" /> | <img src="docs/screens/cluster_1280px.png" width="550" alt="Cluster Desktop View" /> |
| **Add Target Bottom Sheet**<br/>Slide-up sheet with drag handle, segmented interval switch, and inline validation errors. | <img src="docs/screens/add_target_modal_390px.png" width="300" alt="Add Target Mobile View" /> | <img src="docs/screens/add_target_modal_1280px.png" width="550" alt="Add Target Desktop View" /> |
| **Settings & Security**<br/>Displays active role, serving replica node, key credentials, and secure sign-out. | <img src="docs/screens/settings_390px.png" width="300" alt="Settings Mobile View" /> | <img src="docs/screens/settings_1280px.png" width="550" alt="Settings Desktop View" /> |

---

## Automated Verification & Operational Commands

Every claimed system capability is verified with dedicated scripts that produce real, un-mocked output.

### 1. High Availability Failover Demonstration
Simulates both an ungraceful crash (`SIGKILL` / `docker kill`) and a planned graceful shutdown (`SIGTERM` / `docker stop`):
```bash
scripts/failover_demo.sh
```
*Measured Results:*
* **Hard Crash Failover Duration**: `2.180` seconds (PostgreSQL TCP keepalive drop detection).
* **Graceful Stop Failover Duration**: `6.050` seconds (immediate advisory lock release on `SIGTERM`).

### 2. High-Throughput Load Benchmark (k6)
Executes concurrent load testing against `/api/summary`, `/api/results`, and `/api/targets` using viewer credentials:
```bash
scripts/loadtest.sh
```
*Measured Results:*
* **Throughput**: `142.02` req/s (RPS).
* **Latency p95**: `41.7` ms.
* **Latency p99**: `61.1` ms.
* **HTTP Failure Rate**: `0.00%`.

### 3. End-to-End Smoke Test Suite
Executes complete automated validation across health checks, seed verification, telemetry flow, SSE streaming, Prometheus metrics, and active failover:
```bash
scripts/smoke.sh --clean
```

### 4. Playwright Browser End-to-End Tests
Validates real browser rendering, role-based visibility, SVG charting, and failover badge flips:
```bash
pytest tests/test_e2e_playwright.py -v
```

---

## Core Architectural Design Decisions

1. **Active-Standby Redundancy via PostgreSQL Advisory Locks**:
   Rather than introducing separate consensus clusters (etcd, Consul), NetWatch uses PostgreSQL session advisory locks (`LEADER_ADVISORY_LOCK_ID: 827364501`). When the leader drops, PostgreSQL releases the lock immediately, allowing automatic failover in ~2 seconds with zero external dependencies.

2. **Monotonic Epoch Fencing on Telemetry Writes**:
   To eliminate split-brain write conflicts, all result insertions enforce `WHERE COALESCE((SELECT epoch FROM leadership), 0) = :epoch`. Any write from a paused or partitioned ex-leader is rejected and logged.

3. **Single Shared Database with LISTEN/NOTIFY Messaging**:
   Rather than deploying Redis or Kafka, NetWatch uses PostgreSQL's asynchronous `LISTEN`/`NOTIFY` event bus. Notifications broadcast state changes across all replicas to feed Server-Sent Events clients.

4. **Multi-Phase Isolated Probing Pipeline**:
   Probing isolates DNS, TCP, TLS, and HTTP phases sequentially. Monotonic clocks (`time.perf_counter()`) ensure timing accuracy, and early phase failures skip subsequent layers cleanly without throwing unhandled exceptions.

5. **Ultra-Lightweight Mobile-First Vanilla SPA**:
   The frontend is implemented entirely in vanilla HTML5, CSS3, and JavaScript totaling `96.02 KB` combined (CSS: 28.70 KB, JS: 67.32 KB). It avoids bloated frameworks, guaranteeing 44px touch targets, zero layout shifts, and fast loading even on low-bandwidth mobile connections.

---

## Comparison: NetWatch vs Prometheus blackbox_exporter

| Feature / Dimension | NetWatch | Prometheus `blackbox_exporter` |
| :--- | :--- | :--- |
| **High Availability** | Active-standby cluster with automated PostgreSQL advisory lock leader election. | Stateless standalone daemon; requires external load balancers for redundancy. |
| **Target Management** | Dynamic REST API with Admin/Viewer RBAC and interactive dashboard. | Static YAML configuration files requiring SIGHUP process reloads. |
| **Telemetry Persistence** | Historical storage in PostgreSQL with analytical queries and CSV export. | Ephemeral; stores zero telemetry locally and depends entirely on Prometheus. |
| **Real-Time Client Pushing** | Native Server-Sent Events stream pushing sub-second live updates to UI. | Pull-only Prometheus scrape intervals (typically 15s to 60s). |
| **Protocol Coverage** | Specialized DNS, TCP, TLS (with expiry tracking), and HTTP/HTTPS. | Broad protocol suite: ICMP ping, raw TCP/UDP, gRPC, DNS over TLS/HTTPS. |
| **Operational Footprint** | Stateful (requires PostgreSQL instance). | Completely stateless with minimal memory requirements. |

### Technical Takeaways
* **What NetWatch Does Differently**: Integrates dynamic endpoint management, automated failover, live streaming, and an operations dashboard into a unified, zero-build system.
* **What NetWatch Does Worse**: Dependency on PostgreSQL means database downtime halts leader election and telemetry writes. `blackbox_exporter` is stateless, immune to database outages, and easily deployed across dozens of edge regions.
* **Key Lessons**: Aggressive socket timeouts and non-blocking DNS resolution are essential to prevent failing targets from stalling concurrent scheduler loops. PostgreSQL advisory locks provide exceptional high-availability guarantees when a database is already part of the architecture.

---

## System Limitations

1. **Database Single Point of Failure**: Both replicas rely on a single primary PostgreSQL instance for leader election, heartbeats, and telemetry storage.
2. **Single Vantage Point**: Designed for single-cluster deployment; latency measurements reflect timings from the host infrastructure rather than distributed edge locations.
3. **No Direct Alert Routing**: NetWatch exposes Prometheus metrics and live SSE events but does not integrate directly with notification providers (alerts should be routed via Prometheus Alertmanager).
4. **Coarse Retention Pruning**: Telemetry older than 7 days is pruned hourly without intermediate rollup aggregation.
5. **Single-Tenant Role Architecture**: Role-based access control provides cluster-wide Admin and Viewer keys without multi-tenant workspace separation.
