#!/usr/bin/env python3
"""End-to-end smoke test: boot ORION, send a signed GitHub push webhook and verify a pipeline run is recorded.

    python scripts/smoke_test.py                      # spawn a throwaway server (SQLite, pipeline dispatch stubbed)
    python scripts/smoke_test.py --with-queue         # spawn, but enqueue to the real Celery broker (REDIS_URL)
    python scripts/smoke_test.py --url http://localhost:8000 --secret $GITHUB_WEBHOOK_SECRET   # existing server
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SMOKE_SECRET = "orion-smoke-secret"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(port: int, with_queue: bool) -> None:
    sys.path.insert(0, str(ROOT))
    import uvicorn

    from app.main import app

    if not with_queue:
        from app.api.routes import webhook

        def _stub_dispatch(run_id: object, **_: object) -> str:
            print(f"[smoke] pipeline dispatch stubbed for run {run_id}", flush=True)
            return "stub"

        webhook.dispatch_pipeline = _stub_dispatch
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def spawn(with_queue: bool, workdir: Path) -> tuple[subprocess.Popen[bytes], str]:
    port = free_port()
    db = (workdir / "smoke.db").as_posix()
    env = {
        **os.environ,
        "APP_ENV": "test",
        "DATABASE_URL": f"sqlite+aiosqlite:///{db}",
        "SYNC_DATABASE_URL": f"sqlite:///{db}",
        "GITHUB_WEBHOOK_SECRET": SMOKE_SECRET,
        "GITHUB_TOKEN": "",
        "SLACK_WEBHOOK_URL": "",
        "API_REQUIRE_AUTH": "false",
        "JOURNALD_ENABLED": "false",
        "PIPELINE_EXECUTOR": "celery" if with_queue else "inline",
    }
    cmd = [sys.executable, str(Path(__file__).resolve()), "--serve", "--port", str(port)]
    if with_queue:
        cmd.append("--with-queue")
    proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env)
    return proc, f"http://127.0.0.1:{port}"


def wait_healthy(base: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{base}/api/v1/pipeline/health", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"server at {base} did not become healthy within {timeout:.0f}s")


def signed_push(secret: str, commit: str) -> tuple[bytes, dict[str, str]]:
    payload = {
        "ref": "refs/heads/main",
        "before": "0" * 39 + "1",
        "after": commit,
        "repository": {
            "full_name": "orion-smoke/sample-app",
            "clone_url": "https://github.com/orion-smoke/sample-app.git",
            "default_branch": "main",
        },
        "pusher": {"name": "orion-smoke"},
        "head_commit": {"id": commit, "message": "smoke test commit"},
        "commits": [{"id": commit, "message": "smoke test commit"}],
    }
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, {"X-Hub-Signature-256": sig, "X-GitHub-Event": "push", "Content-Type": "application/json"}


def run_checks(base: str, secret: str) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}", flush=True)

    r = httpx.get(f"{base}/health", timeout=10)
    check("GET /health", r.status_code == 200, str(r.status_code))

    commit = uuid.uuid4().hex + uuid.uuid4().hex[:8]
    body, headers = signed_push(secret, commit)

    bad = httpx.post(f"{base}/api/v1/webhook/github", content=body,
                     headers={**headers, "X-Hub-Signature-256": "sha256=" + "0" * 64}, timeout=10)
    check("webhook rejects a bad signature", bad.status_code == 403, str(bad.status_code))

    r = httpx.post(f"{base}/api/v1/webhook/github", content=body, headers=headers, timeout=60)
    accepted = r.status_code == 202 and r.json().get("status") == "accepted"
    check("webhook accepts a signed push", accepted, f"{r.status_code} {r.text[:200]}")

    time.sleep(2)
    r = httpx.get(f"{base}/api/v1/pipeline/runs", params={"repo": "orion-smoke/sample-app", "limit": 50}, timeout=10)
    runs = r.json().get("items", []) if r.status_code == 200 else []
    match = next((run for run in runs if run.get("commit_id") == commit), None)
    check("pipeline run recorded", match is not None, f"status={match['status']}" if match else f"{r.status_code}")

    if match:
        r = httpx.get(f"{base}/api/v1/pipeline/runs/{match['id']}", timeout=10)
        check("GET run by id", r.status_code == 200 and r.json()["commit_id"] == commit, str(r.status_code))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", help="test an already-running server instead of spawning one")
    parser.add_argument("--secret", default=os.environ.get("GITHUB_WEBHOOK_SECRET"), help="webhook secret for --url mode")
    parser.add_argument("--with-queue", action="store_true", help="dispatch to the real Celery broker")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.serve:
        serve(args.port, args.with_queue)
        return 0

    if args.url:
        if not args.secret:
            parser.error("--secret (or GITHUB_WEBHOOK_SECRET) is required with --url")
        wait_healthy(args.url.rstrip("/"))
        results = run_checks(args.url.rstrip("/"), args.secret)
    else:
        with tempfile.TemporaryDirectory(prefix="orion-smoke-") as tmp:
            proc, base = spawn(args.with_queue, Path(tmp))
            try:
                wait_healthy(base)
                results = run_checks(base, SMOKE_SECRET)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()

    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} smoke checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
