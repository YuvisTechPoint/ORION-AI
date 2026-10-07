# ORION DevOps — VS Code Extension

IDE integration for the ORION CI/CD control plane.

## Features

- Status bar health/readiness polling
- Recent pipeline runs quick-pick
- Manual pipeline trigger
- Open dashboard and intelligence APIs

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `orion.apiUrl` | `http://127.0.0.1:8001` | ORION API base URL |
| `orion.apiKey` | — | `X-ORION-API-Key` when auth is enabled |
| `orion.pollIntervalSeconds` | `30` | Status bar refresh interval |

## Development

```bash
cd developer/vscode-orion
# In VS Code: Run > Start Debugging (F5) with "Extension Development Host"
```

Manifest is also exposed at `GET /api/v1/developer/vscode`.
