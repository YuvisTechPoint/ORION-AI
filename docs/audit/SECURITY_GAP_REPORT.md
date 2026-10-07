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
| Rate limiting | ORION `RateLimitMiddleware` | HTTP abuse mitigation |
| Branch/URL validation | ORION pipeline trigger | Injection hardening on clone URLs |
| Approval hard rules | ORION ApprovalAgent | Code/security/QA/stress fail → reject |
| Policy engine fail-closed option | ORION Phase 4 | When `POLICY_ENFORCEMENT_ENABLED` |
| WS auth when API_REQUIRE_AUTH | ORION `ws_require_auth` | Query `api_key` / session |
| Multimodal upload size limits | All stacks | `MULTIMODAL_MAX_FILE_BYTES` |
| Production secret validation | ORION `validate_startup` | Can require runtime secrets |

---

## 3. Critical findings

### SEC-C1: ORION WebSocket handler runtime failure

**File:** `ai-cicd-pipeline/app/main.py`  
**Issue:** `pipeline_ws` references `channel_for`, `event_bus` without import.  
**Impact:** Live pipeline telemetry broken; operators may miss stage failures.  
**Fix:** Import from `app.services.events`.

### SEC-C2: Auth disabled by default

**Files:** `backend/core/config.py`, `ai-cicd-pipeline/app/config.py`, platform settings  
**Issue:** `API_REQUIRE_AUTH` / `AUTH_ENABLED` default false.  
**Impact:** Unauthenticated pipeline trigger, artifact read, intelligence APIs if deployed without explicit hardening.  
**Mitigation:** Fail-closed in production via `APP_ENV=production` + `REQUIRE_RUNTIME_SECRETS`; verify ops runbooks.

---

## 4. High findings

### SEC-H1: Canonical multimodal route gap

**File:** `frontend/src/AnalyzerModals.jsx`  
**Issue:** Calls `/api/v1/multimodal/git-logs` and `/payment` — not on canonical backend.  
**Impact:** Broken features; possible client-side error leakage; users may paste sensitive data into wrong flows.

### SEC-H2: Heuristic security scanners presented as scans

**Files:** `container_security.py`, `iac_security.py`, `secrets_guardian.py`, `sbom.py`  
**Issue:** Regex/heuristic outputs stored as scan artifacts; could be mistaken for Trivy/Checkov/Gitleaks results.  
**Impact:** False confidence in supply-chain posture.  
**Mitigation:** Label `analysis_mode` / `scanner: heuristic` in UI; Phase 4 roadmap integrates real tools.

### SEC-H3: Simulated signed builds / attestation

**File:** `signed_builds.py`  
**Issue:** Cosign-like reports generated without cryptographic verification unless `REQUIRE_SIGNED_BUILDS` strict path.  
**Impact:** Policy may pass unsigned images in default config (`POLICY_STRICT_REQUIREMENTS=false`).

### SEC-H4: No correlation_id / trace propagation

**Issue:** Cannot tie webhook → pipeline → Celery → deploy → Slack across logs.  
**Impact:** Forensics and audit export gaps for enterprise requirements.

### SEC-H5: Canonical security agent is LLM-primary

**File:** `backend/agents/security.py`  
**Issue:** No bandit/pip-audit; regex rule engine only supplements LLM.  
**Impact:** Weaker deterministic security gate vs ORION.

### SEC-H6: Local clone paths in ORION trigger

**File:** `pipeline.py` trigger endpoint  
**Issue:** Local git paths allowed outside production.  
**Impact:** SSRF/path issues if production misconfigured to allow local paths.

---

## 5. Medium findings

### SEC-M1: Duplicate API key header names

ORION accepts `X-ORION-API-Key` and `X-API-Key`; canonical uses different auth service shapes. Increases misconfiguration risk for operators.

### SEC-M2: Hub client-side cross-origin intelligence fetch

**File:** `hub/hub.js`  
**Issue:** Browser fetches all stack APIs; relies on permissive CORS.  
**Impact:** CSRF not applicable to GET, but exposes intelligence data to any page user visits if CORS is `*`.

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
