# Binary-v2 / ORION — Security Gap Report (Phase 0)

**Scope:** Security controls, weaknesses, and fail-open paths evidenced in code.  
**Severity:** Critical · High · Medium · Low

---

## 1. Executive summary

ORION (`ai-cicd-pipeline/`) has the **strongest security posture** of the three stacks: real SAST/SCA tools, non-downgradable scanner severity, secrets/policy/injection gates, webhook HMAC, and secret redaction before LLM calls.

Canonical and Platform stacks rely more on **LLM/heuristic security** with weaker deterministic gates.

**Top risks:** broken ORION WebSocket handler (availability/ops), canonical frontend calling non-existent multimodal routes, missing correlation/tracing (incident forensics), auth disabled by default in dev configs propagating to prod misconfiguration.

---

## 2. Strengths (preserve)

| Control | Location | Notes |
|---------|----------|-------|
| GitHub webhook HMAC | All stacks | Signature validation before processing |
| Webhook idempotency ledger | Canonical, ORION | Prevents duplicate pipeline runs |
| Bandit + pip-audit | ORION SecurityAgent | Real subprocess scanners |
| Security severity gate | ORION | `highest_severity > MAX_SECURITY_SEVERITY` → block |
| LLM cannot downgrade scanner | ORION SecurityAgent | Documented + enforced |
| Secret redaction | `text_analysis.redact_secrets` | Before LLM/agent input |
| Prompt injection gate | ORION Phase 5 | Can block at ingest |
| Secrets scan gate | ORION Phase 1 | `critical_count > 0` → block |
| Rate limiting | All stacks `RateLimitMiddleware` | Memory or Redis (`RATE_LIMIT_BACKEND=auto`) |
| Canonical SAST/SCA | `backend/core/security_scanners.py` | bandit + pip-audit on repo snapshot |
| Branch/URL validation | ORION pipeline trigger | Injection hardening on clone URLs |
| Approval hard rules | ORION ApprovalAgent | Code/security/QA/stress fail → reject |
| Policy engine fail-closed option | ORION Phase 4 | When `POLICY_ENFORCEMENT_ENABLED` |
| WS auth when API_REQUIRE_AUTH | ORION `ws_require_auth` | Query `api_key` / session |
| Multimodal upload size limits | All stacks | `MULTIMODAL_MAX_FILE_BYTES` |
| Production secret validation | ORION `validate_startup` | Can require runtime secrets |

---

## 3. Critical findings

### SEC-C1: ORION WebSocket handler runtime failure — **RESOLVED**

**File:** `ai-cicd-pipeline/app/main.py`  
**Status:** Fixed — `channel_for` / event bus imported from `app.services.events`.

### SEC-C2: Auth disabled by default — **PARTIALLY MITIGATED**

**Files:** `backend/core/config.py`, `ai-cicd-pipeline/app/config.py`, platform settings  
**Issue:** Dev defaults leave auth off.  
**Mitigation (2026-10-07):** ORION + DevOps + Canonical auto-enable `API_REQUIRE_AUTH` when `APP_ENV=production`; intelligence dashboards on Canonical/DevOps require auth when enabled; run `scripts/production_preflight.py` before deploy.

### SEC-C3: DevOps webhook fail-open when secret empty — **RESOLVED**

**File:** `devops-platform/backend/app/routers/webhooks.py`  
**Fix:** `webhook_security.resolve_webhook_secret()` — always verify HMAC; production returns 503 if secret unset.

### SEC-C4: Canonical webhook used GITHUB_TOKEN as HMAC secret — **RESOLVED**

**File:** `backend/api/routes.py`  
**Fix:** Dedicated `GITHUB_WEBHOOK_SECRET` only; dev test fallback `test-webhook-secret`.

---

## 4. High findings

### SEC-H1: Canonical multimodal route gap — **RESOLVED**

**File:** `backend/api/multimodal.py`  
**Status:** Routes registered; verify frontend paths match deployed API version.

### SEC-H2: Heuristic security scanners presented as scans

**Files:** `container_security.py`, `iac_security.py`, `secrets_guardian.py`, `sbom.py`  
**Issue:** Regex/heuristic outputs stored as scan artifacts; could be mistaken for Trivy/Checkov/Gitleaks results.  
**Impact:** False confidence in supply-chain posture.  
**Mitigation:** Label `analysis_mode` / `scanner: heuristic` in UI; Phase 4 roadmap integrates real tools.

### SEC-H3: Simulated signed builds / attestation

**File:** `signed_builds.py`  
**Issue:** Cosign-like reports generated without cryptographic verification unless `REQUIRE_SIGNED_BUILDS` strict path.  
**Impact:** Policy may pass unsigned images in default config (`POLICY_STRICT_REQUIREMENTS=false`).

### SEC-H4: No correlation_id / trace propagation — **RESOLVED**

**Files:** `*/middleware/correlation.py`, `pipeline_run.correlation_id`, `app/tasks/pipeline_tasks.py`  
**Fix:** Celery workers load `correlation_id`/`trace_id` from `pipeline_runs` and attach to JSON logs.

### SEC-H5: Canonical security agent is LLM-primary — **RESOLVED**

**Files:** `backend/core/security_scanners.py`, `backend/agents/full_scan_orchestrator.py`  
**Fix:** bandit + pip-audit run on materialized repo snapshot; scanner findings merge into security gate (LLM cannot downgrade scanner severity).

### SEC-H6: Local clone paths in ORION trigger

**File:** `pipeline.py` trigger endpoint  
**Issue:** Local git paths allowed outside production.  
**Impact:** SSRF/path issues if production misconfigured to allow local paths.

---

## 5. Medium findings

### SEC-M1: Duplicate API key header names

ORION accepts `X-ORION-API-Key` and `X-API-Key`; canonical uses different auth service shapes. Increases misconfiguration risk for operators.

### SEC-M2: Hub client-side cross-origin intelligence fetch — **PARTIALLY MITIGATED**

**Files:** `hub/server.py`, `hub/hub.js`  
**Fix:** Hub BFF CORS restricted via `HUB_CORS_ORIGINS` (no longer `*`); stack APIs should still use production CORS allowlists.

### SEC-M3: Session secret defaults

**Status:** Mitigated — root `.env.example` sanitized (placeholders only); production templates in `*.env.production.example`; `validate_startup()` + `GET /api/v1/production/checklist` enforce rotation before deploy.

### SEC-M4: Slack webhook URL in env

Single URL secret; no signing verification on inbound Slack (outbound only) — acceptable but document.

### SEC-M5: Platform minimal metrics

No security event counters on platform `/metrics` — blind spot for SOC monitoring.

### SEC-M6: Unused ORM models (canonical)

Dead `PipelineRun` tables may confuse security reviewers about actual audit trail location (JSON blobs).

### SEC-M7: Agent eval gate off by default

`AGENT_EVAL_GATE_ENABLED=false` — low AI governance enforcement unless enabled.

### SEC-M8: DevOps RAG without injection hardening on retrieval

RAG queries artifact text; BaseAgent sanitizes LLM input but RAG assembly should ensure redaction on all chunks.

---

## 6. Low findings

### SEC-L1: datetime.utcnow deprecation warnings in canonical orchestrator

Not direct security issue; future maintenance.

### SEC-L2: Root `scripts/orion_cli.py` defaults to :8000

Wrong stack targeting in multi-stack dev — operational mistake risk.

### SEC-L3: Playwright E2E does not test auth flows

No automated regression for protected endpoints.

### SEC-L4: `.env` files in repo workspace

Ensure `.gitignore` covers secrets (verify not committed).

---

## 7. Missing controls vs target architecture (Phases 4–24)

| Control | Status |
|---------|--------|
| Semgrep / Trivy / Gitleaks / Checkov integration | Missing |
| DAST (ZAP) | Missing |
| Runtime security agent | Missing |
| OCI/Sigstore verification | Mock only |
| ABAC / environment-scoped deploy | Missing |
| MFA / SSO enforcement | Readiness check only |
| IP restrictions | Missing |
| Short-lived tokens | Missing |
| Signed audit export | Missing |
| Secret scanning in canonical/platform | Missing |
| SBOM-driven block on critical CVE (OSV/Grype) | Missing |

---

## 8. Fail-closed verification checklist

| Gate | Fail-closed? | Stack |
|------|--------------|-------|
| Security scanner severity | ✅ ORION | O |
| QA fail | ✅ all | C/O/P |
| Stress fail | ✅ ORION/Platform | O/P |
| Secrets critical | ✅ ORION | O |
| Prompt injection | ✅ ORION (when enabled) | O |
| Policy evaluation | ✅ ORION (when enabled) | O |
| Approval hard rules | ✅ ORION | O |
| Auth on privileged ops | ⚠️ config-dependent | all |
| Webhook without HMAC | ✅ rejected | all |
| LLM down | ⚠️ heuristic may pass QA/simulated | C especially |

---

## 9. Recommended remediation order

1. **Fix ORION WebSocket imports** (immediate)
2. **Add canonical multimodal routes** or redirect frontend to ORION proxy
3. **Production auth enforcement** documentation + startup guard
4. **Introduce correlation_id** middleware (Phase 1)
5. **Label heuristic vs authoritative scans** in API + UI
6. **Integrate Trivy/Gitleaks** on ORION path (Phase 4/5 roadmap)

---

*See TECHNICAL_DEBT.md for engineering items; FEATURE_MATRIX.md for capability truth table.*
