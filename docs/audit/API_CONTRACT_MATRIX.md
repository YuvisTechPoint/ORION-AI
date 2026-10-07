# Binary-v2 / ORION — API Contract Matrix (Phase 0)

**Purpose:** Document actual HTTP/WebSocket contracts per stack, prefix differences, and known mismatches.

---

## 1. URL conventions

| Stack | API base | Version prefix | Intelligence prefix |
|-------|----------|----------------|---------------------|
| Canonical | `http://127.0.0.1:8000` | mixed (`/api/v1` for auth/tools/intelligence) | `/api/v1/intelligence` |
| ORION | `http://127.0.0.1:8001` | `/api/v1` | `/api/v1/intelligence` |
| Platform | `http://127.0.0.1:8002` | `/api` (no v1) | `/api/intelligence` |

**Hub intelligence fan-out** (`hub/hub.js`) uses the three URLs above — client-side CORS required.

---

## 2. Canonical (`backend/`) — complete route list

### Pipeline (no `/api/v1` prefix)

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| POST | `/submit-code` | optional | Paste/upload code |
| POST | `/submit-archive` | optional | Zip upload |
| POST | `/submit-github` | optional | GitHub zipball |
| GET | `/pipeline-status/{pipeline_id}` | optional | |
| GET | `/pipelines` | optional | |
| POST | `/pipelines/{pipeline_id}/cancel` | optional | |
| POST | `/pipelines/{pipeline_id}/retry` | optional | |
| POST | `/pipelines/{pipeline_id}/resume` | optional | |
| GET | `/pipelines/{pipeline_id}/audit` | optional | |
| POST | `/trigger-deployment` | API key | Manual deploy gate |
| POST | `/analyze-logs` | optional | Sync log analysis |
| GET | `/health` | none | |
| GET | `/api/v1/pipeline/health` | none | Alias |
| GET | `/runtime-config` | none | |
| POST | `/api/v1/webhook/github` | HMAC | |
| POST | `/api/v1/webhook/github/pr` | HMAC | |

### WebSocket

| Path | Payload |
|------|---------|
| `/ws/pipeline-status/{pipeline_id}` | Orchestrator events |
| `/ws/analyze-logs` | Client sends analyze request JSON |

### Auth (`/api/v1/auth/*`)

| Method | Path |
|--------|------|
| GET | `/api/v1/auth/github` |
| GET | `/api/v1/auth/github/callback` |
| GET | `/api/v1/auth/me` |
| GET | `/api/v1/auth/logout` |
| GET | `/api/v1/auth/status` |
| GET | `/api/v1/auth/github/permissions` |

### Tools (`/api/v1/tools/*`)

| Method | Path |
|--------|------|
| POST | `/api/v1/tools/text-analyze` |
| POST | `/api/v1/tools/text-sanitize` |
| POST | `/api/v1/tools/text-compare` |

### Multimodal (`/api/v1/multimodal/*`)

| Method | Path | Status |
|--------|------|--------|
| POST | `/api/v1/multimodal/analyze` | ✅ implemented |
| POST | `/api/v1/multimodal/triage` | ✅ implemented |
| POST | `/api/v1/multimodal/git-logs` | ✅ implemented |
| POST | `/api/v1/multimodal/payment` | ✅ implemented |

### Intelligence

| Method | Path |
|--------|------|
| GET | `/api/v1/intelligence/dashboard` |

### Ops

| Method | Path |
|--------|------|
| GET | `/ready` |
| GET | `/metrics` |

---

## 3. ORION (`ai-cicd-pipeline/`) — complete route list

### Root

| Method | Path |
|--------|------|
| GET | `/`, `/health`, `/ready`, `/metrics` |
| WS | `/ws/pipeline/{pipeline_id}` |

### Auth (`/api/v1/auth/*`)

Includes: `github`, `callback`, `me`, `logout`, `status`, **`profile`**, **`PATCH /preferences`**

### Webhook

| Method | Path |
|--------|------|
| POST | `/api/v1/webhook/github` |
| POST | `/api/v1/webhook/github/pr` |

### Pipeline (`/api/v1/pipeline/*`)

| Method | Path |
|--------|------|
| GET | `/health` |
| GET | `/runs` |
| GET | `/runs/{run_id}` |
| GET | `/runs/{run_id}/artifacts` |
| GET | `/runs/{run_id}/artifacts/{artifact_type}` |
| GET | `/runs/{run_id}/diagnostics` |
| GET | `/runs/{run_id}/audit` |
| POST | `/runs/{run_id}/retry` |
| POST | `/runs/{run_id}/resume` |
| POST | `/runs/{run_id}/cancel` |
| POST | `/trigger` |

**Trigger body:** `{ "clone_url", "branch", "repo_full_name?" }` → 202 `{ "pipeline_run_id", ... }`

### Tools — same 3 paths as canonical under `/api/v1/tools`

### Intelligence

| Method | Path |
|--------|------|
| GET | `/dashboard` |
| GET | `/fleet` |
| GET | `/audit-explorer` |
| GET | `/agents` |
| GET | `/rag?q=&run_id=` |

### Runtime

| Method | Path |
|--------|------|
| GET | `/navigation` |
| GET | `/config` |

### Multimodal

| Method | Path |
|--------|------|
| POST | `/analyze` |
| POST | `/triage` |
| POST | `/git-logs` |
| POST | `/payment` |

---

## 4. DevOps Platform (`devops-platform/backend/`)

| Method | Path | ORION equivalent |
|--------|------|------------------|
| GET | `/health`, `/ready`, `/metrics` | similar |
| POST | `/webhook/github` | no `/api/v1` |
| POST | `/api/pipeline/trigger` | `/api/v1/pipeline/trigger` |
| GET | `/api/pipelines` | `/api/v1/pipeline/runs` |
| GET | `/api/pipeline/{id}` | `/runs/{id}` + artifacts |
| GET | `/api/pipeline/{id}/status` | — |
| GET | `/api/pipeline/{id}/audit` | same concept |
| POST | `/api/pipeline/{id}/retry` | same |
| POST | `/api/pipeline/{id}/resume` | same |
| POST | `/api/pipeline/{id}/cancel` | same |
| POST | `/api/pipeline/{id}/deploy` | manual deploy |
| POST | `/api/pipeline/{id}/logs/analyze` | — |
| POST | `/api/tools/text-*` | no v1 prefix |
| POST | `/api/multimodal/analyze` | **proxies to ORION** |
| GET | `/api/intelligence/dashboard` | shape similar |
| WS | `/ws/{pipeline_id}` | ORION `/ws/pipeline/{id}` |

---

## 5. Cross-stack contract mismatches

| Issue | Impact | Severity |
|-------|--------|----------|
| Pipeline list path | `/pipelines` vs `/api/v1/pipeline/runs` vs `/api/pipelines` | Hub federation needs adapters |
| Intelligence path | `/api/v1/intelligence` vs `/api/intelligence` | Hub handles explicitly |
| Multimodal git/payment on canonical | 404 from frontend modals | **High** — broken UX |
| WebSocket paths differ | 3 different URL patterns | Federation complexity |
| Auth headers | Session OAuth vs `X-ORION-API-Key` vs optional platform key | No unified auth |
| Pipeline ID field names | `pipeline_id` vs `pipeline_run_id` vs UUID in ORION | Adapter normalization required |
| Canonical submit-code vs ORION trigger | Different ingestion models | Cannot merge without bridge |
| Platform port docs (8000) vs launcher (8002) | Operator confusion | Medium |

---

## 6. Intelligence dashboard response (normalized subset)

All three stacks return JSON with overlapping keys (not identical):

| Field | Typical use |
|-------|-------------|
| `stack` | `"orion"` / `"canonical"` / `"platform"` |
| `pipelines.by_status` | Status histogram |
| `pipelines.pass_rate` | Float 0–1 |
| `pipelines.top_blockers` | String list |
| `slo` | Success rate, duration stats |
| `alerts` | SLO alert objects |
| `capabilities` | Feature flags map (ORION richest) |

Hub aggregates pass rates and blockers client-side — no server-side federation API.

---

## 7. WebSocket event schema (ORION)

Channel: `pipeline:{run_id}` (Redis + in-process)

| `kind` | Source |
|--------|--------|
| `snapshot` | WS connect |
| `heartbeat` | 15s timeout |
| `stage-update` | Orchestrator / agents |
| `agent-complete` | Full scan |
| `artifact` | `_save_artifact` |

Payload includes `run_id`, `ts`. **No `correlation_id` field.**

---

## 8. Authentication matrix

| Stack | Session OAuth | API key header | Webhook HMAC |
|-------|---------------|----------------|--------------|
| Canonical | ✅ GitHub | `X-API-Key` / query | ✅ |
| ORION | ✅ GitHub | `X-ORION-API-Key`, `X-API-Key` | ✅ |
| Platform | ❌ | optional `X-API-Key` | ✅ |

`API_REQUIRE_AUTH` / `AUTH_ENABLED` default **false** in dev.

---

## 9. Compatibility rules for Phase 1 control plane

When building federated views:

1. **Do not rename** existing endpoints.
2. Add **Hub BFF** or **ORION federation service** that normalizes:
   - `PipelineRun` → `{ id, stack, repo, branch, commit, status, correlation_id?, started_at, duration }`
   - `Artifact` → `{ run_id, stack, type, summary, verdict }`
3. Preserve stack-native artifact storage; federation is **read model** only.
4. Document adapter mapping in OpenAPI for the new layer only.

---

*See SECURITY_GAP_REPORT.md for auth gaps; ARCHITECTURE_AUDIT.md for stack roles.*
