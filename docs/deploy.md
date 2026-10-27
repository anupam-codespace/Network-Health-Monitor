# NetWatch Linux VPS Deployment Guide

This guide walks through deploying the NetWatch cluster in production on a single or multi-node Linux VPS (Ubuntu 22.04 / 24.04 LTS or Debian 12).

---

## Architecture in Production

On a Linux VPS, NetWatch runs as a containerized stack managed by `systemd`:
* **PostgreSQL 16**: Relational storage, advisory lock leader election, and `LISTEN`/`NOTIFY` real-time bus.
* **replica-1 (:8001)** & **replica-2 (:8002)**: Dual application replicas running the identical codebase. The elected leader runs probes; both serve the dashboard SPA, REST API, and Server-Sent Events stream.
* **Prometheus (:9090)**: Automated telemetry scraper polling `/metrics` from both replicas every 5 seconds.
* **Grafana (:3000)**: Pre-provisioned dashboards visualizing latencies, success rates, leader status, and cert expiry.

```
                    Internet / Operators
                             │
                  [ NGINX / Caddy Reverse Proxy ]
                   (:80 / :443 with Let's Encrypt)
                             │
           ┌─────────────────┴─────────────────┐
           ▼                                   ▼
    replica-1 (:8001)                   replica-2 (:8002)
    (FastAPI / SSE)                     (FastAPI / SSE)
           │                                   │
           └─────────────────┬─────────────────┘
                             ▼
                     PostgreSQL 16 (:5432)
         (Advisory Lock Election + LISTEN/NOTIFY Bus)
```

---

## 1. Prerequisites & Host Provisioning

1. Update package manager and install Docker engine:
   ```bash
   sudo apt-get update && sudo apt-get install -y curl git ufw
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker "$USER"
   ```

2. Configure Host Firewall (`ufw`):
   ```bash
   sudo ufw default deny incoming
   sudo ufw default allow outgoing
   sudo ufw allow ssh
   sudo ufw allow 80/tcp    # HTTP
   sudo ufw allow 443/tcp   # HTTPS
   sudo ufw allow 3000/tcp  # Grafana (or restrict to VPN/admin IP)
   sudo ufw enable
   ```

---

## 2. Clone Codebase & Configure Secrets

1. Clone the repository into `/opt/netwatch`:
   ```bash
   sudo mkdir -p /opt/netwatch
   sudo chown -R "$USER":"$USER" /opt/netwatch
   git clone https://github.com/example/netwatch.git /opt/netwatch
   cd /opt/netwatch
   ```

2. Generate strong, random API keys and database credentials:
   ```bash
   ADMIN_KEY=$(openssl rand -hex 24)
   VIEWER_KEY=$(openssl rand -hex 24)
   PG_PASS=$(openssl rand -hex 16)

   cat <<EOF > /opt/netwatch/.env
   DATABASE_URL=postgresql+asyncpg://netwatch:${PG_PASS}@postgres:5432/netwatch
   POSTGRES_USER=netwatch
   POSTGRES_PASSWORD=${PG_PASS}
   POSTGRES_DB=netwatch
   ADMIN_API_KEY=${ADMIN_KEY}
   VIEWER_API_KEY=${VIEWER_KEY}
   LOG_LEVEL=INFO
   MAX_CONCURRENT_PROBES=50
   RETENTION_DAYS=7
   EOF

   chmod 600 /opt/netwatch/.env
   ```

---

## 3. Configure systemd Service

1. Copy the systemd unit file:
   ```bash
   sudo cp /opt/netwatch/deploy/netwatch.service /etc/systemd/system/netwatch.service
   sudo systemctl daemon-reload
   ```

2. Enable and start the service:
   ```bash
   sudo systemctl enable netwatch.service
   sudo systemctl start netwatch.service
   ```

3. Verify service status:
   ```bash
   sudo systemctl status netwatch.service
   sudo journalctl -u netwatch.service -f
   ```

---

## 4. Reverse Proxy & HTTPS (Caddy Example)

Install Caddy for automatic Let's Encrypt TLS:
```bash
sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update && sudo apt-get install -y caddy
```

Configure `/etc/caddy/Caddyfile`:
```caddy
netwatch.yourdomain.com {
    reverse_proxy 127.0.0.1:8001 127.0.0.1:8002 {
        lb_policy round_robin
        health_uri /healthz
        health_interval 5s
        health_timeout 2s
    }
}

grafana.yourdomain.com {
    reverse_proxy 127.0.0.1:3000
}
```

Reload Caddy:
```bash
sudo systemctl reload caddy
```

---

## 5. Verification & Health Monitoring

1. **Verify Health Endpoint**:
   ```bash
   /opt/netwatch/scripts/healthcheck.sh --port 8001
   /opt/netwatch/scripts/healthcheck.sh --port 8002
   ```

2. **Verify Leader Failover**:
   ```bash
   /opt/netwatch/scripts/failover_demo.sh
   ```

3. **Verify Load Performance**:
   ```bash
   /opt/netwatch/scripts/loadtest.sh
   ```
