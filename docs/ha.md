# High Availability and Failover Architecture in NetWatch

NetWatch uses an active-standby redundancy architecture across two replicas (`replica-1` and `replica-2`), coordinated via PostgreSQL 16 advisory locks, monotonic epochs, and real-time LISTEN/NOTIFY event streaming.

```mermaid
graph TD
    subgraph Cluster Coordination
        AdvLock["PostgreSQL Advisory Lock (ID: 827364501)"]
        LeadTable["leadership table (Singleton epoch, holder)"]
        EventBus["LISTEN / NOTIFY ('netwatch_events')"]
    end

    subgraph Replica 1 (:8001)
        R1_Elec["LeaderElector (Dedicated asyncpg conn)"]
        R1_Sched["ProbeScheduler (Probes active)"]
        R1_HB["HeartbeatService (every 2s)"]
    end

    subgraph Replica 2 (:8002)
        R2_Elec["LeaderElector (Dedicated asyncpg conn)"]
        R2_Sched["ProbeScheduler (Standby, idle)"]
        R2_HB["HeartbeatService (every 2s)"]
    end

    R1_Elec -->|Holds Advisory Lock| AdvLock
    R2_Elec -.->|Polls pg_try_advisory_lock every 1s| AdvLock

    R1_Sched -->|Conditional Insert: WHERE epoch = :epoch| LeadTable
    R1_Sched -->|pg_notify on commit| EventBus
    EventBus -->|Live stream| R1_Elec
    EventBus -->|Live stream| R2_Elec
```

---

## 1. How Failover Is Bounded

NetWatch guarantees predictable, low-latency failover between the two replicas:

1. **Graceful Failover (`SIGTERM` / Container Stop)**:
   - When a replica is stopped cleanly, its `LeaderElector` immediately records an audited `leader_released` event in the `events` table and executes `SELECT pg_advisory_unlock(827364501)`.
   - The standby replica polls `pg_try_advisory_lock` every 1.0 second. Upon lock release, it acquires the lock and promotes within **< 1.0 second**.

2. **Abrupt Failure (`SIGKILL` / Node Crash / Kernel Panic)**:
   - The leader holds its advisory lock on a **dedicated raw `asyncpg` connection** with aggressive TCP keepalive settings configured directly on the underlying socket:
     - `keepalives_idle = 1` (send first keepalive probe after 1 second of inactivity)
     - `keepalives_interval = 1` (repeat keepalive probes every 1 second)
     - `keepalives_count = 3` (drop connection after 3 unacknowledged probes)
   - When the leader node crashes or the operating system terminates without closing TCP sockets gracefully, PostgreSQL detects connection loss within 3-4 seconds, automatically releasing all session-level advisory locks. The standby acquires the lock and promotes on its next tick.

---

## 2. Split-Brain Prevention: Monotonic Epoch Fencing

A common failure mode in distributed monitoring is a **paused leader** (e.g. stop-the-world garbage collection pause, CPU throttling, or transient network partition). If the standby promotes while the ex-leader is paused, the ex-leader could resume and emit duplicate, stale, or conflicting probe telemetry.

NetWatch prevents this with **strict epoch fencing**:

1. **Atomic Epoch Increments**:
   - On lock acquisition, the promoting replica increments `leadership.epoch` inside a serializable transaction:
     ```sql
     UPDATE leadership SET epoch = epoch + 1, holder = :replica_id, acquired_at = NOW();
     ```
2. **Conditional Insertion Gate**:
   - Every probe result persist query requires the local replica's epoch to match the active leadership epoch:
     ```sql
     INSERT INTO results (target_id, ts, ok, dns_ms, tcp_ms, tls_ms, http_ms, total_ms, status_code, tls_days_left, error, replica_id, epoch)
     SELECT :target_id, :ts, :ok, :dns_ms, :tcp_ms, :tls_ms, :http_ms, :total_ms, :status_code, :tls_days_left, :error, :replica_id, :epoch
     WHERE (SELECT epoch FROM leadership) = :epoch
     RETURNING id;
     ```
3. **Fenced Writes Metric**:
   - If an ex-leader resumes after promotion of a peer, its database write yields 0 inserted rows.
   - NetWatch rejects the write, logs a warning, and increments the Prometheus counter `netwatch_fenced_writes_total`. Stale telemetry never corrupts the historical database.

---

## 3. PostgreSQL Outage Behavior: Fail-Safe Inactive State

PostgreSQL serves as the single source of coordination truth for advisory locks, epochs, and real-time event broadcasting.

> [!IMPORTANT]
> **Honest Failure Declaration**: If PostgreSQL experiences an outage or becomes completely unreachable:
> - **Both replicas step down immediately**.
> - The leader detects connection loss, sets `is_leader = False`, updates `netwatch_is_leader = 0`, and cancels all active probe tasks.
> - No replica will attempt to probe targets or invent telemetry while disconnected from the database.
> - Both replicas enter a reconnect loop (retrying every 1s). When PostgreSQL recovers, exactly one replica acquires the advisory lock, increments the epoch, and resumes probing automatically.
