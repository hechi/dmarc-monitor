
# DMARC Monitor

## Overview

DMARC Monitor is a **Prometheus-exporting service** that automatically fetches DMARC (Domain-based Message Authentication, Reporting & Conformance) reports from an **email inbox**, extracts key metrics, and exposes them for monitoring via Prometheus. These metrics can then be visualized using **Grafana** or another dashboard tool.

## Features

- Automatically fetches DMARC reports from email attachments (`.zip` or `.gz`)
- Parses XML reports and extracts relevant metrics
- Exposes DMARC data via a **Prometheus metrics endpoint** (`:8000/metrics`)
- Removes unnecessary `xmlns` namespaces for XML compatibility
- Deployable via Docker and Docker Compose
- Configured via a TOML file (see `config.example.toml`)
- Supports Grafana for visualization of DMARC trends over time

---

## Metrics Exposed in Prometheus

Once the service is running, metrics are available at:
```
http://localhost:8000/metrics
```

### Available Metrics

| Metric Name                              | Type    | Description                                          | Labels                        |
|------------------------------------------|---------|------------------------------------------------------|-------------------------------|
| `dmarc_reports_total`                    | Counter | DMARC disposition counts from processed reports      | `domain`, `provider`, `disposition` |
| `dmarc_last_processed_timestamp_seconds` | Gauge   | Unix timestamp of the last processed DMARC report    | `domain`, `provider`          |

The `disposition` label reflects the DMARC policy outcome:
- `none` — email passed (no action taken)
- `quarantine` — soft-fail
- `reject` — hard-fail

Example output:
```
dmarc_reports_total{domain="example.com",disposition="none",provider="Google"} 500.0
dmarc_reports_total{domain="example.com",disposition="reject",provider="Google"} 20.0
dmarc_last_processed_timestamp_seconds{domain="example.com",provider="Google"} 1708334567.123
```

---

## Installation & Usage

### 1. Clone the Repository
```sh
git clone https://github.com/yourusername/dmarc-monitor.git
cd dmarc-monitor
```

### 2. Create the Configuration File
```sh
cp config.example.toml config.toml
```

Edit `config.toml` with your email credentials:
```toml
[email]
username = "your-email@example.com"
password = "your-app-password"
imap_server = "imap.example.com"
```

### 3. Build & Start the Service
```sh
docker compose up -d --build
```

This will:
- Build the Docker image
- Start the DMARC monitoring service
- Expose Prometheus metrics on port `8000`

### 4. Verify It's Running
```sh
docker compose logs -f
```

### 5. Query Prometheus Metrics
```
http://localhost:8000/metrics
```

### 6. Stop & Remove the Container
```sh
docker compose down
```

---

## Grafana Integration

Add Prometheus as a data source in Grafana and create a dashboard using the exported metrics.

Example — passed emails by domain:
```promql
sum(dmarc_reports_total{disposition="none"}) by (domain)
```

Example — rejected emails by domain:
```promql
sum(dmarc_reports_total{disposition="reject"}) by (domain)
```

---

## Configuration Reference

All configuration is done via a TOML file passed with `-c <path>`. See `config.example.toml` for a full example.

| Key                    | Required | Default   | Description                                              |
|------------------------|----------|-----------|----------------------------------------------------------|
| `email.username`       | Yes      | —         | Email address to fetch DMARC reports from                |
| `email.password`       | Yes      | —         | Email password or App Password                           |
| `email.imap_server`    | Yes      | —         | IMAP server hostname                                     |
| `email.folder`         | No       | `INBOX`   | IMAP folder to watch for unread mail                     |
| `prometheus.port`      | No       | `8000`    | Port to expose the Prometheus metrics endpoint on        |
| `prometheus.interval`  | No       | `60`      | Seconds between metric update cycles (minimum: 30)       |

**Tip:** If using Gmail, generate an **App Password** instead of using your account password.

---

## Troubleshooting

### Container not running?
```sh
docker compose logs -f
```

### Metrics not updating?
- Ensure emails with DMARC reports (`.zip` or `.gz` attachments) are arriving in the configured folder.
- Check that the IMAP credentials and server are correct.

### Invalid credentials?
- Use an **App Password** instead of your real password (required for Gmail, Outlook, etc.).

---

## Contributing

Feel free to open an **issue** or submit a **pull request** if you have improvements!

---

## License

This project is open-source and licensed under the **MIT License**.
