#!/usr/bin/env python3
"""
Structural verification for Binary-v2 / ORION multi-stack wiring.

Ensures catalog, control-plane BFF, shared libraries, and critical routes stay
connected. Run locally and in CI before/after changes.

Exit 0 = all checks passed. Exit 1 = failures printed to stderr.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _fail(msg: str, problems: list[str]) -> None:
    problems.append(msg)


def _hub_view_from_config(stacks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for stack in stacks:
        if stack.get("id") == "hub":
            continue
        out.append(
            {
                "id": stack.get("id"),
                "title": stack.get("title"),
                "desc": stack.get("description"),
                "ui": stack.get("ui"),
                "health": stack.get("health"),
                "ready": stack.get("ready"),
                "intelligence": stack.get("intelligence"),
                "metaKeys": stack.get("metaKeys"),
            }
        )
    return sorted(out, key=lambda x: str(x.get("id")))


def check_stack_catalog(problems: list[str]) -> None:
    config_path = ROOT / "config" / "stacks.json"
    hub_path = ROOT / "hub" / "stacks.json"
    if not config_path.is_file():
        _fail(f"missing {config_path.relative_to(ROOT)}", problems)
        return
    catalog = json.loads(config_path.read_text(encoding="utf-8"))
    stacks = catalog.get("stacks") or []
    required_ids = {"canonical", "orion", "platform"}
    found = {s.get("id") for s in stacks}
    if not required_ids.issubset(found):
        _fail(f"config/stacks.json missing stack ids: {sorted(required_ids - found)}", problems)
    for stack in stacks:
        sid = stack.get("id")
        if sid in required_ids:
            for key in ("api", "health", "ready", "intelligence", "ui"):
                if not stack.get(key):
                    _fail(f"stack {sid} missing {key} in config/stacks.json", problems)

    if not hub_path.is_file():
        _fail(f"missing {hub_path.relative_to(ROOT)} — run scripts/sync_stack_catalog.ps1", problems)
        return
    hub_stacks = json.loads(hub_path.read_text(encoding="utf-8-sig"))
    expected = _hub_view_from_config(stacks)
    actual = sorted(hub_stacks, key=lambda x: str(x.get("id")))
    if json.dumps(expected, sort_keys=True) != json.dumps(actual, sort_keys=True):
        _fail(
            "hub/stacks.json is out of sync with config/stacks.json — run: .\\scripts\\sync_stack_catalog.ps1",
            problems,
        )


def check_required_paths(problems: list[str]) -> None:
    paths = [
        "hub/server.py",
        "hub/federation/adapters.py",
        "hub/federation/catalog.py",
        "hub/federation/operations_center.py",
        "hub/federation/platform_events.py",
        "config/stacks.json",
        "shared/memory_gateway/gateway.py",
        "shared/memory_gateway/factory.py",
        "shared/event_bus/bus.py",
        "backend/core/gate_fusion.py",
        "ai-cicd-pipeline/app/utils/gate_fusion.py",
        "devops-platform/backend/app/utils/gate_fusion.py",
        "ai-cicd-pipeline/app/agents/orchestrator.py",
        "ai-cicd-pipeline/app/middleware/correlation.py",
        "backend/services/pipeline_terminal_hooks.py",
        "ai-cicd-pipeline/app/services/platform_events.py",
        "ai-cicd-pipeline/app/services/memory_gateway_service.py",
        "ai-cicd-pipeline/app/api/routes/memory_v2.py",
        "ai-cicd-pipeline/app/api/routes/events_v2.py",
        "run_e2e_all.ps1",
        "run_all_stacks.ps1",
    ]
    for rel in paths:
        if not (ROOT / rel).is_file():
            _fail(f"missing required path: {rel}", problems)


def check_orion_main_routers(problems: list[str]) -> None:
    main_py = (ROOT / "ai-cicd-pipeline" / "app" / "main.py").read_text(encoding="utf-8")
    required_snippets = [
        "memory_v2.router",
        "events_v2.router",
        "CorrelationMiddleware",
        "pipeline.router",
        "webhook.router",
        "intelligence.router",
        "production.router",
    ]
    for snippet in required_snippets:
        if snippet not in main_py:
            _fail(f"ORION app/main.py missing wiring: {snippet}", problems)


def check_hub_control_plane_routes(problems: list[str]) -> None:
    server = (ROOT / "hub" / "server.py").read_text(encoding="utf-8")
    routes = [
        "/api/v1/control-plane/health",
        "/api/v1/control-plane/pipelines",
        "/api/v1/control-plane/operations",
        "/api/v1/control-plane/platform-events",
        "/api/v1/control-plane/platform-events/stream",
    ]
    for route in routes:
        if route not in server:
            _fail(f"Hub server missing route registration: {route}", problems)


def check_shared_imports(problems: list[str]) -> None:
    sys.path.insert(0, str(ROOT))
    try:
        from shared.memory_gateway.config import MemoryGatewayConfig  # noqa: F401
        from shared.memory_gateway.factory import build_memory_store  # noqa: F401
        from shared.event_bus.bus import build_platform_event_bus  # noqa: F401
        from shared.event_bus.models import PlatformEvent  # noqa: F401

        cfg = MemoryGatewayConfig(enabled=True, backend="sqlite", sqlite_path=":memory:")
        # sqlite path :memory: works for MemorySqliteStore
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cfg.sqlite_path = str(Path(tmp) / "m.db")
            store = build_memory_store(cfg)
            from shared.memory_gateway.store import MemorySqliteStore

            if not isinstance(store, MemorySqliteStore):
                _fail("memory factory sqlite backend returned unexpected store type", problems)
            else:
                store._conn.close()

        bus = build_platform_event_bus(redis_url=None, backend="memory")
        eid = bus.publish(
            PlatformEvent(event_type="wiring.check", correlation_id="wiring", payload={"ok": True})
        )
        recent = bus.recent(limit=5, event_type="wiring.check")
        if not recent or not eid:
            _fail("platform event bus in-memory publish/read failed", problems)
    except Exception as exc:  # noqa: BLE001
        _fail(f"shared library import/smoke failed: {exc}", problems)


def check_orion_orchestrator_hooks(problems: list[str]) -> None:
    text = (ROOT / "ai-cicd-pipeline" / "app" / "agents" / "orchestrator.py").read_text(encoding="utf-8")
    if "publish_platform_event" not in text:
        _fail("ORION orchestrator missing publish_platform_event hooks", problems)
    if "extract_pipeline_episodic_memory" not in text:
        _fail("ORION orchestrator missing episodic memory hook", problems)


def check_canonical_hooks(problems: list[str]) -> None:
    orch = (ROOT / "backend" / "services" / "orchestrator.py").read_text(encoding="utf-8")
    if "publish_pipeline_started" not in orch or "run_terminal_hooks" not in orch:
        _fail("canonical orchestrator missing terminal/platform event hooks", problems)


def check_federation_catalog_path(problems: list[str]) -> None:
    catalog_py = (ROOT / "hub" / "federation" / "catalog.py").read_text(encoding="utf-8")
    if "config" not in catalog_py or "stacks.json" not in catalog_py:
        _fail("hub federation catalog must load config/stacks.json", problems)


def check_ci_workflow(problems: list[str]) -> None:
    ci = ROOT / ".github" / "workflows" / "ci.yml"
    if not ci.is_file():
        _fail("missing .github/workflows/ci.yml", problems)
        return
    body = ci.read_text(encoding="utf-8")
    if "verify_architecture_wiring" not in body:
        _fail("CI workflow should run scripts/verify_architecture_wiring.py", problems)


def run_checks() -> list[str]:
    problems: list[str] = []
    check_required_paths(problems)
    check_stack_catalog(problems)
    check_federation_catalog_path(problems)
    check_orion_main_routers(problems)
    check_hub_control_plane_routes(problems)
    check_orion_orchestrator_hooks(problems)
    check_canonical_hooks(problems)
    check_shared_imports(problems)
    check_ci_workflow(problems)
    return problems


def main() -> int:
    problems = run_checks()
    if problems:
        print("Architecture wiring verification FAILED:", file=sys.stderr)
        for item in problems:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print("Architecture wiring verification OK (catalog, BFF, shared libs, orchestrator hooks).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
