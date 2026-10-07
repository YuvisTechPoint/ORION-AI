#!/usr/bin/env python3
"""Real end-to-end pipeline run: no mocks, no Redis, no Docker, no GitHub.

Builds a sample service repository, starts it as the staging target, boots ORION (SQLite, inline
executor), triggers pipelines through the public API and follows them over the WebSocket.

    python scripts/e2e_run.py                  # all scenarios (pass, broken test, vulnerable dep), LLM per .env
    python scripts/e2e_run.py --offline        # heuristic analysis only (no Anthropic calls)
    python scripts/e2e_run.py --scenario pass  # just the clean commit
    python scripts/e2e_run.py --keep           # keep the temp dir (sample repo, orion DB) for inspection
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {
    "deployed", "approved", "rolled_back", "auto_rolled_back", "blocked_code", "blocked_security",
    "blocked_tests", "blocked_stress", "blocked_with_prs_sent", "rejected", "failed", "cancelled",
}

SAMPLE_FILES = {
    "inventory/__init__.py": "",
    "inventory/core.py": '''
        """Tiny inventory domain used to exercise the ORION pipeline."""

        from dataclasses import dataclass


        @dataclass(frozen=True)
        class Item:
            """A stocked item."""

            sku: str
            quantity: int
            unit_price: float


        def total_value(items: list[Item]) -> float:
            """Return the stock value of all items."""
            return round(sum(i.quantity * i.unit_price for i in items), 2)


        def restock(item: Item, amount: int) -> Item:
            """Return a copy of item with amount more units."""
            if amount <= 0:
                raise ValueError("amount must be positive")
            return Item(item.sku, item.quantity + amount, item.unit_price)
    ''',
    "server.py": '''
        """Staging HTTP service for the sample app (stdlib only)."""

        import argparse
        import json
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        from inventory.core import Item, total_value

        STOCK = [Item("A-1", 3, 2.5), Item("B-2", 10, 1.25)]


        class Handler(BaseHTTPRequestHandler):
            """Serve /, /health and /items."""

            def _send(self, code: int, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:  # noqa: N802 - http.server API
                """Route GET requests."""
                if self.path == "/health":
                    self._send(200, {"status": "ok"})
                elif self.path == "/":
                    self._send(200, {"service": "inventory", "value": total_value(STOCK)})
                elif self.path == "/items":
                    self._send(200, {"items": [i.__dict__ for i in STOCK]})
                else:
                    self._send(404, {"detail": "not found"})

            def log_message(self, *_args) -> None:
                """Silence per-request logging."""


        if __name__ == "__main__":
            parser = argparse.ArgumentParser()
            parser.add_argument("--port", type=int, default=8080)
            args = parser.parse_args()
            ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    ''',
    "locustfile.py": '''
        """Load profile for the inventory service."""

        from locust import HttpUser, between, task


        class InventoryUser(HttpUser):
            """Browse the inventory."""

            wait_time = between(0.1, 0.5)

            @task(3)
            def items(self):
                """List items."""
                self.client.get("/items")

            @task(1)
            def health(self):
                """Health probe."""
                self.client.get("/health")
    ''',
    "tests/test_core.py": '''
        import pytest

        from inventory.core import Item, restock, total_value


        def test_total_value():
            assert total_value([Item("a", 2, 1.5), Item("b", 1, 0.25)]) == 3.25


        def test_restock():
            assert restock(Item("a", 1, 1.0), 4).quantity == 5


        def test_restock_rejects_non_positive():
            with pytest.raises(ValueError):
                restock(Item("a", 1, 1.0), 0)
    ''',
    "requirements.txt": "six==1.17.0\n",
    ".gitignore": "__pycache__/\n.pytest_cache/\n",
}

BROKEN_TEST = '''
from inventory.core import Item, total_value


def test_total_value_with_discount():
    # Intentionally wrong expectation: the gate must block this commit.
    assert total_value([Item("a", 2, 1.5)]) == 2.0
'''


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def git(repo: Path, *args: str) -> str:
    p = subprocess.run(
        ["git", "-c", "user.email=e2e@orion.local", "-c", "user.name=orion-e2e", *args],
        cwd=repo, capture_output=True, encoding="utf-8", errors="replace", check=True,
    )
    return p.stdout.strip()


def build_sample_repo(repo: Path) -> None:
    repo.mkdir(parents=True)
    git(repo, "init", "-b", "main")
    for rel, content in SAMPLE_FILES.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Inventory service skeleton")
    with (repo / "inventory" / "core.py").open("a", encoding="utf-8") as fh:
        fh.write(textwrap.dedent('''

            def low_stock(items: list[Item], threshold: int = 5) -> list[str]:
                """Return SKUs at or below threshold."""
                return [i.sku for i in items if i.quantity <= threshold]
        '''))
    git(repo, "commit", "-am", "Add low-stock report")


def add_feature_branches(repo: Path) -> None:
    git(repo, "checkout", "-b", "feature/discounts")
    (repo / "tests" / "test_discount.py").write_text(BROKEN_TEST.lstrip(), encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Add discount test")
    git(repo, "checkout", "main")

    git(repo, "checkout", "-b", "feature/http-client")
    (repo / "requirements.txt").write_text("six==1.17.0\nrequests==2.19.0\n", encoding="utf-8")
    git(repo, "commit", "-am", "Add HTTP client dependency")
    git(repo, "checkout", "main")


def wait_http(url: str, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.4)
    raise RuntimeError(f"{url} did not come up within {timeout:.0f}s")


def follow_ws(base: str, run_id: str, events: list[dict[str, Any]], stop: threading.Event) -> None:
    from websockets.sync.client import connect

    ws_url = base.replace("http://", "ws://", 1) + f"/ws/pipeline/{run_id}"
    try:
        with connect(ws_url, open_timeout=10) as ws:
            while not stop.is_set():
                try:
                    raw = ws.recv(timeout=1.0)
                except TimeoutError:
                    continue
                msg = json.loads(raw)
                if msg.get("kind") == "heartbeat":
                    continue
                events.append(msg)
                print(f"    ws  {describe(msg)}", flush=True)
    except Exception as exc:  # noqa: BLE001
        if not stop.is_set():
            print(f"    ws  closed: {type(exc).__name__}: {exc}", flush=True)


def describe(msg: dict[str, Any]) -> str:
    kind = msg.get("kind") or msg.get("type") or "event"
    if kind == "artifact":
        return f"artifact {msg.get('artifact_type')} ({msg.get('agent')}): {str(msg.get('summary') or '')[:110]}"
    if kind == "snapshot":
        return f"snapshot status={msg.get('status')}"
    stage = msg.get("stage") or msg.get("status")
    extra = msg.get("message") or msg.get("detail") or ""
    return f"{kind} {stage} {str(extra)[:110]}".rstrip()


def run_scenario(base: str, name: str, payload: dict[str, str], expect: set[str], timeout: float) -> bool:
    print(f"\n=== scenario: {name} ({payload['branch']}) ===", flush=True)
    r = httpx.post(f"{base}/api/v1/pipeline/trigger", json=payload, timeout=90)
    if r.status_code != 202:
        print(f"FAIL  trigger -> {r.status_code} {r.text[:300]}")
        return False
    body = r.json()
    run_id = body["pipeline_run_id"]
    print(f"    triggered run {run_id} commit={body['commit_id'][:8]} executor={body['executor']}", flush=True)

    events: list[dict[str, Any]] = []
    stop = threading.Event()
    watcher = threading.Thread(target=follow_ws, args=(base, run_id, events, stop), daemon=True)
    watcher.start()

    started = time.monotonic()
    run: dict[str, Any] = {}
    while time.monotonic() - started < timeout:
        run = httpx.get(f"{base}/api/v1/pipeline/runs/{run_id}", timeout=10).json()
        if run.get("status") in TERMINAL:
            break
        time.sleep(1.5)
    time.sleep(1.0)
    stop.set()
    watcher.join(timeout=5)

    status = run.get("status")
    elapsed = time.monotonic() - started
    arts = httpx.get(f"{base}/api/v1/pipeline/runs/{run_id}/artifacts", timeout=10).json()
    items = arts.get("items", arts) if isinstance(arts, dict) else arts
    print(f"    finished status={status} in {elapsed:.0f}s; error={run.get('error_message')!r}")
    for a in items:
        content = a.get("content") or {}
        summary = content.get("summary") or content.get("reason") or content.get("verdict") or ""
        print(f"    artifact {a['artifact_type']:<20} {str(summary)[:120]}")

    ok = status in expect
    stage_events = [e for e in events if e.get("kind") in ("stage-update", "stage_update") or "stage" in e]
    checks = [
        (f"terminal status in {sorted(expect)}", ok, str(status)),
        ("live WebSocket events received", len(stage_events) > 0, f"{len(events)} events"),
        ("artifacts recorded", len(items) >= 3, f"{len(items)} artifacts"),
    ]
    for label, passed, detail in checks:
        print(f"{'PASS' if passed else 'FAIL'}  {label} - {detail}")
    return all(passed for _, passed, _ in checks)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", choices=("pass", "fail", "vuln", "all"), default="all")
    parser.add_argument("--offline", action="store_true", help="disable Anthropic calls (heuristic analysis)")
    parser.add_argument("--keep", action="store_true", help="keep the temp directory")
    parser.add_argument("--timeout", type=float, default=900.0, help="per-run timeout in seconds")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="orion-e2e-"))
    procs: list[subprocess.Popen[bytes]] = []
    results: list[bool] = []
    try:
        repo = tmp / "inventory-service"
        build_sample_repo(repo)
        add_feature_branches(repo)
        print(f"sample repo: {repo} (main={git(repo, 'rev-parse', '--short', 'main')})")

        staging_port = free_port()
        procs.append(subprocess.Popen([sys.executable, "server.py", "--port", str(staging_port)], cwd=repo))
        staging = f"http://127.0.0.1:{staging_port}"
        wait_http(f"{staging}/health")
        print(f"staging service: {staging}")

        port = free_port()
        db = (tmp / "orion-e2e.db").as_posix()
        env = {
            **os.environ,
            "APP_ENV": "development",
            "DATABASE_URL": f"sqlite+aiosqlite:///{db}",
            "SYNC_DATABASE_URL": f"sqlite:///{db}",
            "PIPELINE_EXECUTOR": "inline",
            "DEPLOY_MODE": "auto",
            "PIPELINE_WORKDIR": str(tmp / "work"),
            "STAGING_URL": staging,
            "STRESS_TEST_USERS": "10",
            "STRESS_TEST_SPAWN_RATE": "5",
            "STRESS_TEST_DURATION": "10",
            "GITHUB_TOKEN": "",
            "SLACK_WEBHOOK_URL": "",
            "API_REQUIRE_AUTH": "false",
            "JOURNALD_ENABLED": "false",
            "PYTHONIOENCODING": "utf-8",
        }
        if args.offline:
            env["ANTHROPIC_API_KEY"] = "sk-ant-api03-your-key-here"
        log = (tmp / "orion.log").open("wb")
        procs.append(
            subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            )
        )
        base = f"http://127.0.0.1:{port}"
        wait_http(f"{base}/health")
        health = httpx.get(f"{base}/health", timeout=15).json()
        print(f"orion: {base} executor={health['executor']} redis={health['redis']} "
              f"deploy_mode={health['deploy_mode']} llm={health['llm_mode']}")

        if args.scenario in ("pass", "all"):
            results.append(
                run_scenario(base, "clean commit passes every gate",
                             {"clone_url": str(repo), "branch": "main"}, {"approved", "deployed"}, args.timeout)
            )
        if args.scenario in ("fail", "all"):
            results.append(
                run_scenario(base, "broken test is blocked",
                             {"clone_url": str(repo), "branch": "feature/discounts"},
                             {"blocked_tests", "blocked_with_prs_sent"}, args.timeout)
            )
        if args.scenario in ("vuln", "all"):
            results.append(
                run_scenario(base, "vulnerable dependency is blocked",
                             {"clone_url": str(repo), "branch": "feature/http-client"},
                             {"blocked_security", "blocked_with_prs_sent"}, args.timeout)
            )

        ui = httpx.get(f"{base}/ui/", timeout=10, follow_redirects=True)
        print(f"{'PASS' if ui.status_code == 200 else 'FAIL'}  dashboard served at /ui/ - {ui.status_code}")
        results.append(ui.status_code == 200)
    finally:
        for p in reversed(procs):
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        if args.keep:
            print(f"\nkept {tmp} (orion.log has the server log)")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(results)
    print(f"\n{passed}/{len(results)} end-to-end check groups passed")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
