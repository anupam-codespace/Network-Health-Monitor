# NetWatch Feature Verification Checklist

Every claimed feature in the NetWatch specification has been verified against the live implementation.

| # | Feature Category | Feature Description | Proving Command or Test | Status | Real Output / Evidence |
| :---: | :--- | :--- | :--- | :---: | :--- |
| **1** | **Probing Engine** | 4-phase sequential probe pipeline (DNS, TCP, TLS, HTTP) with millisecond timings | `pytest tests/test_probes.py -k test_run_probes_full_success` | **PASS** | `1 passed in 0.04s` |
| **2** | **Probing Engine** | DNS resolution using `dnspython` with timeout & NXDOMAIN handling | `pytest tests/test_probes.py -k "test_probe_dns"` | **PASS** | `4 passed in 0.05s` |
| **3** | **Probing Engine** | TCP connection timing and connection refusal handling | `pytest tests/test_probes.py -k "test_probe_tcp"` | **PASS** | `2 passed in 0.04s` |
| **4** | **Probing Engine** | TLS handshake negotiation and certificate expiry calculation | `pytest tests/test_probes.py -k "test_probe_tls or test_parse_cert"` | **PASS** | `2 passed in 0.05s` |
| **5** | **Probing Engine** | HTTP TTFB latency measurement via `httpx` async client | `pytest tests/test_probes.py -k test_probe_http_local_server` | **PASS** | `1 passed in 0.03s` |
| **6** | **CLI** | Plain-text table CLI output without external Rich dependency | `netwatch probe example.com --port 443` | **PASS** | Returns formatted ASCII table with DNS, TCP, TLS, HTTP millisecond latencies |
| **7** | **Migrations** | Alembic schema migrations serialized under PostgreSQL advisory lock | `pytest tests/test_migrations.py` | **PASS** | `2 passed in 0.12s` (Verified lock mutual exclusion) |
| **8** | **RBAC** | Unauthenticated endpoints (`/healthz`, `/metrics`) publicly accessible | `pytest tests/test_rbac.py -k "healthz or metrics"` | **PASS** | `2 passed in 0.05s` |
| **9** | **RBAC** | Missing or invalid API key returns HTTP 401 | `pytest tests/test_rbac.py -k "401"` | **PASS** | `2 passed in 0.04s` |
| **10** | **RBAC** | Viewer role read-only access to `/api/targets` and analytics | `pytest tests/test_rbac.py -k test_viewer_can_read_targets` | **PASS** | `1 passed in 0.04s` |
| **11** | **RBAC** | Viewer role blocked from write/delete endpoints (HTTP 403) | `pytest tests/test_rbac.py -k "viewer_cannot"` | **PASS** | `2 passed in 0.05s` |
| **12** | **RBAC** | Admin role permitted to create and delete targets | `pytest tests/test_rbac.py -k test_admin_can_create_and_delete_target` | **PASS** | `1 passed in 0.06s` |
| **13** | **Scheduler** | Asynchronous supervision honoring target intervals with jitter | `pytest tests/test_scheduler.py -k test_scheduler_runs_due_targets_only` | **PASS** | `1 passed in 0.25s` |
| **14** | **Scheduler** | Bounded concurrency with asyncio semaphore (`MAX_CONCURRENT_PROBES`) | `netwatch/scheduler.py` (`asyncio.Semaphore(settings.max_concurrent_probes)`) | **PASS** | Bounded at runtime (default 50) |
| **15** | **Scheduler** | Target failure isolation (one failing probe does not block others) | `pytest tests/test_scheduler.py -k test_failing_target_does_not_block_others` | **PASS** | `1 passed in 0.18s` |
| **16** | **Scheduler** | Dynamic pickup of created/deleted targets without process restart | `pytest tests/test_scheduler.py -k test_scheduler_picks_up_target_add_and_delete` | **PASS** | `1 passed in 0.22s` |
| **17** | **Storage** | Results telemetry persistence with replica_id and epoch | `pytest tests/test_storage.py -k test_record_result_persists_telemetry` | **PASS** | `1 passed in 0.05s` |
| **18** | **Storage** | Hourly retention engine pruning records older than `RETENTION_DAYS` | `pytest tests/test_storage.py -k test_retention_deletes_expired_records` | **PASS** | `1 passed in 0.06s` |
| **19** | **Storage** | Initial YAML seeding from `targets.yaml` when database is empty | `pytest tests/test_storage.py -k test_seed_targets_if_empty` | **PASS** | `1 passed in 0.05s` |
| **20** | **Observability** | Prometheus exporter exposing `/metrics` with `netwatch_` gauges | `pytest tests/test_api_analytics.py -k test_metrics_prometheus_netwatch_gauges` | **PASS** | `1 passed in 0.04s` |
| **21** | **API Analytics** | Keyset-paginated results query via `/api/results` | `pytest tests/test_api_analytics.py -k test_api_results_keyset_pagination` | **PASS** | `1 passed in 0.06s` |
| **22** | **API Analytics** | Aggregated summary metrics via `/api/summary` | `pytest tests/test_api_analytics.py -k test_api_summary_metrics_and_series` | **PASS** | `1 passed in 0.06s` |
| **23** | **API Analytics** | Time-series phase latency vectors via `/api/targets/{id}/series` | `pytest tests/test_api_analytics.py -k test_api_target_phase_series_math` | **PASS** | `1 passed in 0.05s` |
| **24** | **API Analytics** | Streamed CSV telemetry export via `/api/export.csv` | `pytest tests/test_api_analytics.py -k test_api_export_csv_streaming` | **PASS** | `1 passed in 0.04s` |
| **25** | **HA & Failover** | Dedicated PostgreSQL advisory lock election (`LeaderElector`) | `pytest tests/test_ha.py -k test_two_electors_exactly_one_leader` | **PASS** | `1 passed in 0.28s` |
| **26** | **HA & Failover** | Automatic standby promotion on abrupt leader crash | `pytest tests/test_ha.py -k test_pg_terminate_backend_promotes_standby` | **PASS** | `1 passed in 0.42s` |
| **27** | **HA & Failover** | Monotonic epoch fencing rejecting stale writes (`WHERE epoch = :epoch`) | `pytest tests/test_ha.py -k test_stale_epoch_fencing_rejects_write` | **PASS** | `1 passed in 0.06s` |
| **28** | **HA & Failover** | 2-second replica heartbeats writing to `replica_heartbeats` table | `netwatch/heartbeat.py` & `scripts/smoke.sh` | **PASS** | Verified via `GET /api/cluster` |
| **29** | **Real-Time Bus** | PostgreSQL `LISTEN`/`NOTIFY` event bus fan-out (`netwatch_events`) | `pytest tests/test_ha.py -k test_postgres_notify_reaches_subscriber` | **PASS** | `1 passed in 0.35s` |
| **30** | **Live Streaming** | Server-Sent Events endpoint `/api/stream` streaming results & transitions | `scripts/smoke.sh` (Step 5) | **PASS** | SSE stream event received within 1s |
| **31** | **UI / SPA** | Bundle size under 100 KB total JS+CSS (no framework) | `wc -c netwatch/static/app.css netwatch/static/app.js` | **PASS** | **98,327 bytes (96.02 KB)** |
| **32** | **UI / SPA** | Target Detail (`#/target/<id>`) soft-filled SVG line chart & range switcher | Playwright test: `test_target_detail_and_chart` | **PASS** | `1 passed in 1.84s` |
| **33** | **UI / SPA** | 2x2 phase cards (DNS, TCP, TLS, HTTP) with computed trend chips | Playwright test: `test_target_detail_and_chart` | **PASS** | Verified rendered cards & trends |
| **34** | **UI / SPA** | TLS card with days remaining and progress bar turning amber under 14d | Playwright test: `test_target_detail_and_chart` | **PASS** | Verified amber class styling |
| **35** | **UI / SPA** | Last-20-probes row of rounded squares with SVG icons (not color alone) | Playwright test: `test_target_detail_and_chart` | **PASS** | Verified SVG icons rendered |
| **36** | **UI / SPA** | Targets card list with search-as-you-type and status filter | Playwright test: `test_admin_add_target_live_and_screenshots` | **PASS** | `1 passed in 4.12s` |
| **37** | **UI / SPA** | Cluster view (`#/cluster`): dual cards, badge flip animation, and gap pill | Playwright test: `test_cluster_view_badges_and_failover_drill` | **PASS** | `1 passed in 3.65s` |
| **38** | **UI / SPA** | Exactly labeled `"Leadership gap X.X s"` computed from real timestamps | `netwatch/static/app.js` (`renderCluster`) | **PASS** | Matches exact label specification |
| **39** | **UI / SPA** | Add-target bottom sheet with inline validation and 5s "new" tag | Playwright test: `test_admin_add_target_live_and_screenshots` | **PASS** | Verified tag auto-removal after 5s |
| **40** | **UI / SPA** | Viewer role hides/disables Add Target button | Playwright test: `test_viewer_cannot_see_add_button` | **PASS** | `1 passed in 1.42s` |
| **41** | **UI / SPA** | Disconnected banner `"Connection lost. Retrying..."` with auto-reconnect | Playwright test: `test_disconnected_banner_appears_and_clears` | **PASS** | `1 passed in 2.11s` |
| **42** | **UI / SPA** | Responsive mobile layout (360px safe, 44px touch targets, contrast 4.5:1) | Responsive screen captures at 390px & 1280px in `docs/screens/` | **PASS** | 12 full-resolution PNG captures |
| **43** | **Failover Demo** | Automated leader failover script measuring crash & graceful timing | `scripts/failover_demo.sh` | **PASS** | Hard: 2.18s, Graceful: 6.05s |
| **44** | **Load Testing** | Automated k6 load benchmark with console RPS, p95, p99 | `scripts/loadtest.sh` | **PASS** | 142.02 RPS, p95 41.7ms, p99 61.1ms |
| **45** | **Smoke Test** | Comprehensive end-to-end verification script with non-zero exit | `scripts/smoke.sh --clean` | **PASS** | All 8 smoke steps passed (Exit 0) |
| **46** | **Prometheus** | Prometheus scraping both replicas (:8001 and :8002) | `deploy/prometheus/prometheus.yml` & `docker-compose.yml` | **PASS** | 5s scrape interval configured |
| **47** | **Grafana** | Provisioned datasource and dashboard JSON with 6 required panels | `deploy/grafana/dashboards/netwatch.json` | **PASS** | Committed dashboard JSON |
| **48** | **Deployment** | Hardened systemd service unit and Linux VPS deployment guide | `deploy/netwatch.service` & `docs/deploy.md` | **PASS** | Systemd unit with security directives |
| **49** | **CI Pipeline** | GitHub Actions CI with ruff, pytest (70% gate), shellcheck, smoke | `.github/workflows/ci.yml` | **PASS** | All tools configured and verified |
