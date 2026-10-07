# ORION GitHub App

GitHub App manifest and webhook endpoint for repository-scoped ORION integrations.

## Webhook

```
POST /api/v1/webhook/github/app
```

Validates `X-Hub-Signature-256` using `GITHUB_APP_WEBHOOK_SECRET` (falls back to `GITHUB_WEBHOOK_SECRET` in dev).

## API

- `GET /api/v1/developer/github-app` — status and configuration
- `GET /api/v1/developer/github-app/manifest` — live manifest with resolved hook URL

## Environment

```env
GITHUB_APP_ENABLED=true
GITHUB_APP_ID=
GITHUB_APP_CLIENT_ID=
GITHUB_APP_PRIVATE_KEY=
GITHUB_APP_WEBHOOK_SECRET=
GITHUB_APP_CONFIG_JSON={}
```

Push pipeline dispatch remains on `POST /api/v1/webhook/github`; the App endpoint handles installation lifecycle, PR review hooks, and check correlation.
