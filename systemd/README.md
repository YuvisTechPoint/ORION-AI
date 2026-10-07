# Systemd units

| Path | Service | Application |
|------|---------|-------------|
| `ai-cicd-pipeline/systemd/orion-api.service` | ORION CI/CD API | `app.main:app` on port 8001 |
| `ai-cicd-pipeline/systemd/orion-worker.service` | Celery worker | Pipeline executor |
| `ai-cicd-pipeline/systemd/orion-beat.service` | Celery beat | Stale run reaper |
| `systemd/orion-api.service` | Canonical API | `main:app` in `backend/` on port 8000 |

Install ORION production units:

```bash
sudo cp ai-cicd-pipeline/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now orion-api orion-worker orion-beat
```

Use `/etc/orion/orion.env` for ORION and `/etc/orion/canonical.env` for the canonical stack.
