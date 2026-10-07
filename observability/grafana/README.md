# Grafana dashboards

Import `orion-dashboard.json` into Grafana and point the `datasource` variable at your Prometheus scrape target.

## Prometheus scrape config (example)

```yaml
scrape_configs:
  - job_name: orion
    static_configs:
      - targets: ["host.docker.internal:8001"]
    metrics_path: /metrics
  - job_name: canonical
    static_configs:
      - targets: ["host.docker.internal:8000"]
    metrics_path: /metrics
  - job_name: devops-platform
    static_configs:
      - targets: ["host.docker.internal:8002"]
    metrics_path: /metrics
```

Metrics exposed:

| Stack | Key series |
|-------|------------|
| ORION | `orion_http_requests_total`, `orion_http_request_duration_seconds_*`, `orion_pipeline_runs_total`, `orion_webhook_deliveries_total` |
| Canonical | `canonical_http_requests_total`, `canonical_pipeline_submissions_total` |
| DevOps | `devops_platform_up` |

SLO Slack alerts fire from each stack's intelligence dashboard when `SLACK_WEBHOOK_URL` is set and `SLO_ALERT_SLACK_ENABLED=true` (default). Duplicate alerts for the same code are suppressed for `SLO_ALERT_COOLDOWN_SECONDS` (default 3600).
