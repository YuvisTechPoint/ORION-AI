# Continuous verification — architecture, wiring, and runtime health

Binary-v2 stays aligned with the ORION control-plane design when these commands run regularly (locally, in CI, and after deploy).

## Structural wiring (no stacks required)

```powershell
.\.venv\Scripts\python.exe scripts\verify_architecture_wiring.py
```

Validates:

- `config/stacks.json` ↔ `hub/stacks.json` catalog sync
- Hub control-plane BFF routes (pipelines, operations, platform-events SSE)
- ORION router registration (`/api/v2/memory`, `/api/v2/events`, correlation middleware)
- Shared Memory Gateway + platform event bus smoke
- Canonical and ORION orchestrator hooks (events + episodic memory)

Fix catalog drift:

```powershell
.\scripts\sync_stack_catalog.ps1
```

## Full automated test matrix

```powershell
.\run_e2e_all.ps1 -Offline
```

Canonical + ORION (459+ tests) + offline pipeline E2E + DevOps + Hub federation + Playwright.

## Live stacks (after `run_all_stacks.ps1`)

```powershell
.\.venv\Scripts\python.exe scripts\verify_stacks_live.py
```

Probes `/health` and `/ready` for every stack in the catalog plus Hub `GET /api/v1/control-plane/health`.

## Production

```powershell
python scripts\production_preflight.py
.\run_production.ps1 -SkipInstall
```

## CI

GitHub Actions job **wiring** runs `verify_architecture_wiring.py` on every push/PR. Matrix suites run per-stack pytest; Playwright covers Hub offline smoke.

## Operational loop (recommended)

| When | Command |
|------|---------|
| Every code change | `verify_architecture_wiring.py` (also first step of `run_e2e_all.ps1`) |
| Before merge | `run_e2e_all.ps1 -Offline` |
| After starting stacks | `verify_stacks_live.py` |
| Production deploy | `production_preflight.py` + `orion production ready` |

See also: [`docs/CURSOR_PHASE_ROADMAP.md`](CURSOR_PHASE_ROADMAP.md), [`agents.md`](../agents.md).
