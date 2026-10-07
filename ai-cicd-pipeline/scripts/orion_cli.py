#!/usr/bin/env python3
"""ORION management CLI (installed as /usr/local/bin/orion)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = ROOT / "venv" / "bin" / "python"

# The symlinked entrypoint runs under the system python; hop into the ORION venv for dependencies.
if VENV_PYTHON.exists() and Path(sys.prefix).resolve() != (ROOT / "venv").resolve() and not os.environ.get("ORION_CLI_REEXEC"):
    os.environ["ORION_CLI_REEXEC"] = "1"
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])

import argparse  # noqa: E402
import hashlib  # noqa: E402
import hmac  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import Any  # noqa: E402
from urllib.parse import unquote, urlparse  # noqa: E402

import httpx  # noqa: E402
import psutil  # noqa: E402

ENV_FILE = Path(os.environ.get("ORION_ENV_FILE", "/etc/orion/orion.env"))
SERVICES = ("orion-api", "orion-worker", "orion-beat", "orion-monitor")
BACKUP_DIR = Path("/var/lib/orion/backups")


def load_env_file(path: Path = ENV_FILE) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()
sys.path.insert(0, str(ROOT))
from app.config import settings  # noqa: E402


def api_base() -> str:
    return os.environ.get("ORION_API_URL", f"http://127.0.0.1:{settings.app_port}").rstrip("/")


def hub_base() -> str:
    return os.environ.get("HUB_URL", os.environ.get("VITE_HUB_URL", "http://127.0.0.1:5180")).rstrip("/")


def hub_request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    url = f"{hub_base()}{path}"
    headers = kwargs.pop("headers", {})
    headers.setdefault("Accept", "application/json")
    key = os.environ.get("ORION_API_KEY") or settings.orion_api_key
    if key:
        headers["X-ORION-API-Key"] = key
    return httpx.request(method, url, headers=headers, timeout=30.0, **kwargs)


# ---- output helpers ------------------------------------------------------------------------
def emit(args: argparse.Namespace, data: Any, table: list[list[Any]] | None = None, headers: list[str] | None = None) -> None:
    if args.json:
        print(json.dumps(data, indent=2, default=str))
        return
    if table is not None and headers is not None:
        print_table(headers, table)
    elif isinstance(data, (dict, list)):
        print(json.dumps(data, indent=2, default=str))
    else:
        print(data)


def print_table(headers: list[str], rows: list[list[Any]]) -> None:
    cells = [[str(c) for c in row] for row in rows]
    widths = [max(len(h), *(len(r[i]) for r in cells)) if cells else len(h) for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print("  ".join("-" * w for w in widths))
    for row in cells:
        print(fmt.format(*row))


def human_bytes(n: int | None) -> str:
    if n is None:
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def human_duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d{hours}h{minutes}m"
    if hours:
        return f"{hours}h{minutes}m"
    return f"{minutes}m{secs}s"


def resolve_services(name: str | None) -> list[str]:
    if not name or name == "all":
        return list(SERVICES)
    name = name.removesuffix(".service")
    if not name.startswith("orion-"):
        name = f"orion-{name}"
    if name not in SERVICES:
        raise SystemExit(f"Unknown service '{name}'. Choose from: {', '.join(SERVICES)} or 'all'")
    return [name]


# ---- systemd -------------------------------------------------------------------------------
def systemctl_show(unit: str) -> dict[str, str]:
    try:
        out = subprocess.run(
            ["systemctl", "show", unit, "--property=ActiveState,SubState,MainPID,ExecMainStartTimestamp"],
            capture_output=True,
            encoding="utf-8", errors="replace",
            timeout=15,
        ).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def process_stats(pid: int) -> tuple[int | None, float | None]:
    if pid <= 0:
        return None, None
    try:
        proc = psutil.Process(pid)
        rss = proc.memory_info().rss + sum(c.memory_info().rss for c in proc.children(recursive=True))
        return rss, time.time() - proc.create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None, None


def service_status(unit: str) -> dict[str, Any]:
    info = systemctl_show(unit)
    pid = int(info.get("MainPID", "0") or 0)
    rss, uptime = process_stats(pid)
    return {
        "service": unit,
        "active": info.get("ActiveState", "unknown"),
        "sub": info.get("SubState", "unknown"),
        "pid": pid or None,
        "memory_bytes": rss,
        "uptime_seconds": round(uptime) if uptime is not None else None,
    }


def cmd_status(args: argparse.Namespace) -> int:
    statuses = [service_status(s) for s in SERVICES]
    rows = [
        [s["service"], s["active"], s["sub"], s["pid"] or "-", human_bytes(s["memory_bytes"]), human_duration(s["uptime_seconds"])]
        for s in statuses
    ]
    emit(args, {"services": statuses}, rows, ["SERVICE", "ACTIVE", "SUB", "PID", "MEMORY", "UPTIME"])
    return 0 if all(s["active"] == "active" for s in statuses) else 3


def cmd_restart(args: argparse.Namespace) -> int:
    results = []
    for unit in resolve_services(args.service):
        proc = subprocess.run(["systemctl", "restart", unit], capture_output=True, encoding="utf-8", errors="replace")
        results.append({"service": unit, "ok": proc.returncode == 0, "error": proc.stderr.strip() or None})
    emit(args, {"restarted": results}, [[r["service"], "ok" if r["ok"] else f"FAILED: {r['error']}"] for r in results], ["SERVICE", "RESULT"])
    return 0 if all(r["ok"] for r in results) else 1


def cmd_logs(args: argparse.Namespace) -> int:
    units = resolve_services(args.service)
    cmd = ["journalctl", "--no-pager", "-n", str(args.lines)]
    for unit in units:
        cmd += ["-u", unit]
    if args.json:
        from app.services.journald_service import normalize_entry

        out = subprocess.run([*cmd, "-o", "json"], capture_output=True, encoding="utf-8", errors="replace").stdout
        entries = []
        for line in out.splitlines():
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            entries.append(normalize_entry(raw, raw.get("_SYSTEMD_UNIT", units[0]).removesuffix(".service")))
        print(json.dumps(entries, indent=2))
        return 0
    if args.follow:
        cmd.append("-f")
    return subprocess.run(cmd).returncode


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, encoding="utf-8", errors="replace", check=True).stdout.strip()


def build_deploy_payload(repo: Path) -> dict[str, Any]:
    head = _git(repo, "rev-parse", "HEAD")
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    message = _git(repo, "log", "-1", "--pretty=%s")
    try:
        before = _git(repo, "rev-parse", "HEAD~1")
    except subprocess.CalledProcessError:
        before = "0" * 40
    try:
        remote = _git(repo, "remote", "get-url", "origin")
    except subprocess.CalledProcessError:
        remote = ""
    if "github.com" in remote:
        full_name = remote.rstrip("/").removesuffix(".git").split("github.com")[-1].lstrip(":/")
        clone_url = f"https://github.com/{full_name}.git"
    else:
        full_name = f"local/{repo.name}"
        clone_url = repo.as_uri()
    return {
        "ref": f"refs/heads/{branch}",
        "before": before,
        "after": head,
        "repository": {"full_name": full_name, "clone_url": clone_url, "default_branch": branch},
        "pusher": {"name": "orion-cli"},
        "head_commit": {"id": head, "message": message},
        "commits": [{"id": head, "message": message}],
    }


def cmd_deploy(args: argparse.Namespace) -> int:
    repo = Path(args.repo_path).resolve()
    try:
        payload = build_deploy_payload(repo)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        emit(args, {"ok": False, "error": f"{repo} is not a git repository: {exc}"})
        return 1
    if getattr(args, "canary", False):
        note = " [orion-cli:canary]"
        payload["head_commit"]["message"] = str(payload["head_commit"].get("message", "")) + note
        if payload.get("commits"):
            payload["commits"][0]["message"] = str(payload["commits"][0].get("message", "")) + note
    body = json.dumps(payload).encode("utf-8")
    signature = "sha256=" + hmac.new(settings.github_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    try:
        resp = httpx.post(
            f"{api_base()}/api/v1/webhook/github",
            content=body,
            headers={**api_headers(), "X-Hub-Signature-256": signature, "X-GitHub-Event": "push", "Content-Type": "application/json"},
            timeout=60,
        )
    except httpx.HTTPError as exc:
        emit(args, {"ok": False, "error": str(exc)})
        return 1
    data: dict[str, Any] = {
        "ok": resp.status_code in (200, 202),
        "status_code": resp.status_code,
        "response": _json_or_text(resp),
        "progressive_delivery_enabled": settings.progressive_delivery_enabled,
    }
    if getattr(args, "canary", False):
        data["canary_requested"] = True
        if not settings.progressive_delivery_enabled:
            data["warning"] = "PROGRESSIVE_DELIVERY_ENABLED=false; deploy will not use canary stages"
    emit(args, data)
    return 0 if data["ok"] else 1


def _json_or_text(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return resp.text


def cmd_health(args: argparse.Namespace) -> int:
    try:
        resp = httpx.get(f"{api_base()}/api/v1/pipeline/health", timeout=10)
    except httpx.HTTPError as exc:
        emit(args, {"ok": False, "error": str(exc)})
        return 1
    emit(args, {"ok": resp.status_code == 200, "status_code": resp.status_code, "response": _json_or_text(resp)})
    return 0 if resp.status_code == 200 else 1


def cmd_db_migrate(args: argparse.Namespace) -> int:
    proc = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=str(ROOT), capture_output=True, encoding="utf-8", errors="replace")
    emit(args, {"ok": proc.returncode == 0, "output": (proc.stdout + proc.stderr).strip()})
    return proc.returncode


def cmd_workers(args: argparse.Namespace) -> int:
    flower = os.environ.get("FLOWER_URL", "http://localhost:5555").rstrip("/")
    auth = (settings.flower_basic_auth_user, settings.flower_basic_auth_password)
    for path in ("/api/workers", "/flower/api/workers"):
        try:
            resp = httpx.get(f"{flower}{path}", params={"refresh": "true"}, auth=auth, timeout=10)
        except httpx.HTTPError:
            continue
        if resp.status_code == 200:
            workers = resp.json()
            rows = [
                [name, info.get("stats", {}).get("pool", {}).get("max-concurrency", "-"), len(info.get("active", []) or [])]
                for name, info in workers.items()
            ]
            emit(args, {"source": "flower", "workers": workers}, rows, ["WORKER", "CONCURRENCY", "ACTIVE TASKS"])
            return 0

    from app.tasks.pipeline_tasks import celery_app

    replies = celery_app.control.inspect(timeout=5).ping() or {}
    rows = [[name, reply.get("ok", reply)] for name, reply in replies.items()]
    emit(args, {"source": "celery-inspect", "workers": replies}, rows, ["WORKER", "PING"])
    return 0 if replies else 1


def pg_env_from_url(url: str) -> tuple[list[str], dict[str, str]]:
    parsed = urlparse(url.replace("+asyncpg", "").replace("+psycopg2", ""))
    env = os.environ.copy()
    if parsed.password:
        env["PGPASSWORD"] = unquote(parsed.password)
    args = [
        "-h", parsed.hostname or "localhost",
        "-p", str(parsed.port or 5432),
        "-U", unquote(parsed.username or "postgres"),
        "-d", parsed.path.lstrip("/") or "postgres",
    ]
    return args, env


# ---- HTTP API (developer / intelligence commands) --------------------------------------------
def api_headers() -> dict[str, str]:
    headers: dict[str, str] = {"Accept": "application/json"}
    key = (os.environ.get("ORION_API_KEY") or settings.orion_api_key or "").strip()
    if key:
        headers["X-ORION-API-Key"] = key
    return headers


def api_request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    url = f"{api_base()}{path}"
    return httpx.request(method, url, headers={**api_headers(), **kwargs.pop("headers", {})}, timeout=kwargs.pop("timeout", 60), **kwargs)


def resolve_repo(repo_path: str | None = None) -> Path:
    repo = Path(repo_path or ".").resolve()
    if not (repo / ".git").is_dir():
        raise SystemExit(f"{repo} is not a git repository")
    return repo


def repo_trigger_fields(repo: Path) -> dict[str, str]:
    payload = build_deploy_payload(repo)
    repo_info = payload["repository"]
    branch = payload["ref"].removeprefix("refs/heads/")
    return {
        "clone_url": repo_info["clone_url"],
        "branch": branch,
        "repo_full_name": repo_info["full_name"],
    }


def trigger_pipeline(repo: Path) -> dict[str, Any]:
    fields = repo_trigger_fields(repo)
    resp = api_request(
        "POST",
        "/api/v1/pipeline/trigger",
        json={"clone_url": fields["clone_url"], "branch": fields["branch"], "repo_full_name": fields["repo_full_name"]},
    )
    if resp.status_code not in (200, 202):
        raise SystemExit(f"Pipeline trigger failed ({resp.status_code}): {_json_or_text(resp)}")
    body = resp.json()
    run_id = body.get("pipeline_run_id") or body.get("id")
    if not run_id:
        raise SystemExit(f"Unexpected trigger response: {body}")
    return {"run_id": str(run_id), "response": body, **fields}


def fetch_run(run_id: str) -> dict[str, Any]:
    resp = api_request("GET", f"/api/v1/pipeline/runs/{run_id}")
    if resp.status_code != 200:
        raise SystemExit(f"Run lookup failed ({resp.status_code}): {_json_or_text(resp)}")
    return resp.json()


def fetch_artifact(run_id: str, artifact_type: str) -> dict[str, Any]:
    resp = api_request("GET", f"/api/v1/pipeline/runs/{run_id}/artifacts/{artifact_type}")
    if resp.status_code != 200:
        return {}
    data = resp.json()
    content = data.get("content")
    return content if isinstance(content, dict) else {}


def wait_for_run(run_id: str, timeout: int = 900, interval: float = 3.0) -> dict[str, Any]:
    from app.models.pipeline_run import TERMINAL_STATUSES

    deadline = time.time() + timeout
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = fetch_run(run_id)
        if last.get("status") in TERMINAL_STATUSES:
            return last
        time.sleep(interval)
    raise SystemExit(f"Timed out waiting for run {run_id} (last status: {last.get('status', 'unknown')})")


def git_diff_range(repo: Path, ref: str) -> tuple[str, list[str], str, str]:
    ref = (ref or "HEAD").strip()
    head = "HEAD" if ref.upper() == "HEAD" else ref
    try:
        base = _git(repo, "merge-base", head, "main")
    except subprocess.CalledProcessError:
        try:
            base = _git(repo, "merge-base", head, "master")
        except subprocess.CalledProcessError:
            base = f"{head}~1" if head != "HEAD" else "HEAD~1"
    diff_text = _git(repo, "diff", f"{base}...{head}")
    names = [line for line in _git(repo, "diff", "--name-only", f"{base}...{head}").splitlines() if line.strip()]
    return diff_text, names, base, head


def cmd_scan(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo_path)
    triggered = trigger_pipeline(repo)
    result: dict[str, Any] = {"action": "scan", **triggered}
    if args.wait:
        result["run"] = wait_for_run(triggered["run_id"], timeout=args.timeout)
        arts = fetch_artifact(triggered["run_id"], "full_scan_combined") or fetch_artifact(triggered["run_id"], "change_risk_report")
        if arts:
            result["summary"] = arts
    emit(args, result)
    status = (result.get("run") or {}).get("status")
    return 0 if not args.wait or status in {"deployed", "approved", "monitoring"} else 1


def cmd_test(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo_path)
    triggered = trigger_pipeline(repo)
    result: dict[str, Any] = {"action": "test", **triggered}
    if args.wait:
        run = wait_for_run(triggered["run_id"], timeout=args.timeout)
        result["run"] = run
        result["qa_report"] = fetch_artifact(triggered["run_id"], "qa_report")
        result["test_intelligence"] = fetch_artifact(triggered["run_id"], "test_intelligence")
    emit(args, result)
    qa = result.get("qa_report") or {}
    if args.wait and (qa.get("verdict") == "fail" or qa.get("passed") is False):
        return 1
    return 0


def cmd_risk(args: argparse.Namespace) -> int:
    from app.utils.change_risk import compute_change_risk

    repo = resolve_repo(args.repo_path)
    try:
        diff_text, files, base, head = git_diff_range(repo, args.ref)
    except subprocess.CalledProcessError as exc:
        emit(args, {"ok": False, "error": f"git diff failed: {exc}"})
        return 1
    report = compute_change_risk(diff_text=diff_text, changed_files=files)
    emit(args, {"ok": True, "repo": str(repo), "base": base, "head": head, "files_changed": len(files), "report": report})
    level = str(report.get("risk_level", "")).lower()
    return 1 if level in {"high", "critical"} else 0


def cmd_repo(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo_path)
    payload: dict[str, Any] = {
        "repo_path": str(repo.resolve()),
        "use_llm": not args.no_llm,
    }
    if args.ref and args.ref != "HEAD":
        try:
            diff_text, files, base, head = git_diff_range(repo, args.ref)
        except subprocess.CalledProcessError as exc:
            emit(args, {"ok": False, "error": f"git diff failed: {exc}"})
            return 1
        payload["diff_text"] = diff_text
        payload["changed_files"] = files
    resp = api_request("POST", "/api/v1/intelligence/repository", json=payload)
    if resp.status_code != 200:
        emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
        return 1
    report = resp.json().get("report") or {}
    emit(args, {"ok": True, "repo": str(repo), "report": report})
    return 0


def cmd_code_review(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {}
    if args.run_id:
        payload["pipeline_run_id"] = args.run_id
    else:
        repo = resolve_repo(args.repo_path)
        payload["changed_files"] = []
        if args.ref and args.ref != "HEAD":
            try:
                diff_text, files, base, head = git_diff_range(repo, args.ref)
            except subprocess.CalledProcessError as exc:
                emit(args, {"ok": False, "error": f"git diff failed: {exc}"})
                return 1
            payload["changed_files"] = files
        payload.update(
            {
                "code_analysis": {"severity": "pass", "issues": [], "warnings_count": 0, "analysis_mode": "heuristic"},
                "security_scan": {"highest_severity": "low", "vulnerabilities": []},
                "qa_report": {"verdict": "pass"},
            }
        )
        if payload["changed_files"]:
            from app.utils.change_risk import compute_change_risk

            payload["change_risk_report"] = compute_change_risk(changed_files=payload["changed_files"])
    resp = api_request("POST", "/api/v1/intelligence/code-review", json=payload)
    if resp.status_code != 200:
        emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
        return 1
    report = resp.json().get("report") or {}
    emit(args, {"ok": True, "report": report})
    gate = report.get("gate_verdict")
    return 1 if gate == "fail" else 0


def cmd_test_intel(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo_path)
    payload: dict[str, Any] = {
        "repo_path": str(repo.resolve()),
        "use_llm": not args.no_llm,
        "run_live_coverage": args.live_coverage,
    }
    if args.ref and args.ref != "HEAD":
        try:
            diff_text, files, base, head = git_diff_range(repo, args.ref)
        except subprocess.CalledProcessError as exc:
            emit(args, {"ok": False, "error": f"git diff failed: {exc}"})
            return 1
        payload["diff_text"] = diff_text
        payload["changed_files"] = files
    resp = api_request("POST", "/api/v1/intelligence/tests", json=payload)
    if resp.status_code != 200:
        emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
        return 1
    report = resp.json().get("report") or {}
    emit(args, {"ok": True, "repo": str(repo), "report": report})
    gate = report.get("gate_verdict")
    return 1 if gate == "fail" else 0


def cmd_policy(args: argparse.Namespace) -> int:
    sub = args.policy_cmd
    if sub == "catalog":
        resp = api_request("GET", "/api/v1/policies/catalog")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "effective":
        params = {"repo": args.repo}
        if args.environment:
            params["environment"] = args.environment
        resp = api_request("GET", "/api/v1/policies/effective", params=params)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "evaluate":
        payload: dict[str, Any] = {"persist": not args.no_persist}
        if args.run_id:
            payload["pipeline_run_id"] = args.run_id
        if args.repo:
            payload["repo"] = args.repo
        if args.environment:
            payload["environment"] = args.environment
        resp = api_request("POST", "/api/v1/policies/evaluate", json=payload)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        report = resp.json().get("report") or {}
        emit(args, {"ok": True, "report": report})
        gate = report.get("gate_verdict")
        return 1 if gate == "fail" else 0
    emit(args, {"ok": False, "error": f"Unknown policy subcommand: {sub}"})
    return 1


def cmd_approve(args: argparse.Namespace) -> int:
    sub = args.approve_cmd
    if sub == "workflow":
        params: dict[str, Any] = {"repo": args.repo}
        if args.environment:
            params["environment"] = args.environment
        if args.change_risk is not None:
            params["change_risk"] = args.change_risk
        resp = api_request("GET", "/api/v1/approvals/workflow", params=params)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "status":
        resp = api_request("GET", f"/api/v1/approvals/runs/{args.run_id}")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        body = resp.json()
        emit(args, body)
        gate = (body.get("report") or {}).get("gate_verdict")
        return 1 if gate == "fail" else 0
    if sub == "sign":
        payload = {
            "approver": args.approver,
            "role": args.role,
            "comment": args.comment or "",
        }
        if args.signature_token:
            payload["signature_token"] = args.signature_token
        resp = api_request("POST", f"/api/v1/approvals/runs/{args.run_id}/sign", json=payload)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        body = resp.json()
        emit(args, {"ok": True, **body})
        return 0 if body.get("ready_for_deploy") else 0
    emit(args, {"ok": False, "error": f"Unknown approve subcommand: {sub}"})
    return 1


def cmd_multimodal(args: argparse.Namespace) -> int:
    sub = args.multimodal_cmd
    if sub == "catalog":
        resp = api_request("GET", "/api/v1/intelligence/multimodal/catalog")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "route":
        data: dict[str, Any] = {"text_input": args.text or ""}
        if args.agent:
            data["agent_type"] = args.agent
        resp = api_request("POST", "/api/v1/multimodal/route", data=data)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "intel":
        payload: dict[str, Any] = {"persist": not args.no_persist}
        if args.run_id:
            payload["pipeline_run_id"] = args.run_id
        if args.text:
            payload["route_text"] = args.text
        if args.agent:
            payload["preferred_agent"] = args.agent
        resp = api_request("POST", "/api/v1/intelligence/multimodal", json=payload)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        report = resp.json().get("report") or {}
        emit(args, {"ok": True, "report": report})
        gate = report.get("gate_verdict")
        return 1 if gate == "fail" else 0
    emit(args, {"ok": False, "error": f"Unknown multimodal subcommand: {sub}"})
    return 1


def cmd_cloud(args: argparse.Namespace) -> int:
    sub = args.cloud_cmd
    if sub == "targets":
        resp = api_request("GET", "/api/v1/intelligence/cloud/targets", params={"repo": args.repo} if args.repo else None)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "analyze":
        payload: dict[str, Any] = {"persist": not args.no_persist}
        if args.run_id:
            payload["pipeline_run_id"] = args.run_id
        if args.repo:
            payload["repo"] = args.repo
        if args.repo_path:
            payload["repo_path"] = args.repo_path
        if args.environment:
            payload["environment"] = args.environment
        resp = api_request("POST", "/api/v1/intelligence/cloud", json=payload)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        report = resp.json().get("report") or {}
        emit(args, {"ok": True, "report": report})
        gate = report.get("gate_verdict")
        return 1 if gate == "fail" else 0
    emit(args, {"ok": False, "error": f"Unknown cloud subcommand: {sub}"})
    return 1


def cmd_catalog(args: argparse.Namespace) -> int:
    sub = args.catalog_cmd
    if sub == "idp":
        resp = api_request("GET", "/api/v1/intelligence/catalog/idp")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "services":
        params: dict[str, str] = {}
        if args.repo:
            params["repo"] = args.repo
        if args.repo_path:
            params["repo_path"] = args.repo_path
        resp = api_request("GET", "/api/v1/intelligence/catalog/services", params=params or None)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "fleet":
        resp = api_request("GET", "/api/v1/intelligence/fleet")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "analyze":
        payload: dict[str, Any] = {
            "persist": not args.no_persist,
            "include_fleet": not args.no_fleet,
        }
        if args.run_id:
            payload["pipeline_run_id"] = args.run_id
        if args.repo:
            payload["repo"] = args.repo
        if args.repo_path:
            payload["repo_path"] = args.repo_path
        resp = api_request("POST", "/api/v1/intelligence/catalog", json=payload)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        report = resp.json().get("report") or {}
        emit(args, {"ok": True, "report": report})
        gate = report.get("gate_verdict")
        return 1 if gate == "fail" else 0
    emit(args, {"ok": False, "error": f"Unknown catalog subcommand: {sub}"})
    return 1


def cmd_remediate(args: argparse.Namespace) -> int:
    if args.remediate_cmd == "levels":
        resp = api_request("GET", "/api/v1/remediation/levels")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if args.remediate_cmd == "analyze":
        payload: dict[str, Any] = {"pipeline_run_id": args.run_id, "use_llm": not args.no_llm}
        resp = api_request("POST", "/api/v1/remediation/analyze", json=payload)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        report = resp.json().get("report") or {}
        emit(args, {"ok": True, "report": report})
        gate = report.get("gate_verdict")
        return 1 if gate == "fail" else 0
    if args.remediate_cmd == "show":
        resp = api_request("GET", f"/api/v1/remediation/runs/{args.run_id}")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    emit(args, {"ok": False, "error": f"Unknown remediate subcommand: {args.remediate_cmd}"})
    return 1


def cmd_incident(args: argparse.Namespace) -> int:
    sub = args.incident_cmd
    if sub == "list":
        params: dict[str, Any] = {"limit": args.limit}
        if args.status:
            params["status"] = args.status
        if args.severity:
            params["severity"] = args.severity
        resp = api_request("GET", "/api/v1/incidents", params=params)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        body = resp.json()
        items = body.get("items") or []
        if args.json:
            emit(args, body)
            return 0
        rows = [[i.get("incident_id"), i.get("severity"), i.get("status"), i.get("repo"), i.get("run_id")] for i in items]
        emit(args, body, rows, ["INCIDENT", "SEV", "STATUS", "REPO", "RUN"])
        return 0
    if sub == "show":
        resp = api_request("GET", f"/api/v1/incidents/{args.incident_id}")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "transition":
        resp = api_request(
            "POST",
            f"/api/v1/incidents/{args.incident_id}/transition",
            json={"status": args.status, "note": args.note or ""},
        )
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "trigger":
        payload: dict[str, Any] = {"pipeline_run_id": args.run_id}
        if args.log_excerpt:
            payload["log_excerpt"] = args.log_excerpt
        resp = api_request("POST", "/api/v1/incidents/trigger", json=payload)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    emit(args, {"ok": False, "error": f"Unknown incident subcommand: {sub}"})
    return 1


def cmd_observability(args: argparse.Namespace) -> int:
    if args.run_id:
        payload: dict[str, Any] = {"pipeline_run_id": args.run_id, "use_llm": not args.no_llm}
        if args.log_excerpt:
            payload["log_excerpt"] = args.log_excerpt
    else:
        synthetic = {
            "journeys": [
                {"journey": "health", "passed": args.synthetic_ok, "latency_ms": args.latency_ms, "simulated": True}
            ],
            "passed": 1 if args.synthetic_ok else 0,
            "total": 1,
            "all_passed": args.synthetic_ok,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "simulated": True,
        }
        payload = {
            "deployment_info": {
                "success": True,
                "simulated": True,
                "environment": args.environment,
                "deployed_at": datetime.now(timezone.utc).isoformat(),
                "health_check_passed": True,
            },
            "otel_trace_context": {"trace_id": "abc123def456", "spans": [{"name": "pipeline.deploy"}]},
            "synthetic_monitoring_report": synthetic,
            "use_llm": not args.no_llm,
        }
    resp = api_request("POST", "/api/v1/intelligence/observability", json=payload)
    if resp.status_code != 200:
        emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
        return 1
    report = resp.json().get("report") or {}
    emit(args, {"ok": True, "report": report})
    gate = report.get("gate_verdict")
    return 1 if gate == "fail" else 0


def cmd_deploy_intel(args: argparse.Namespace) -> int:
    if args.run_id:
        payload: dict[str, Any] = {"pipeline_run_id": args.run_id, "use_llm": not args.no_llm}
    else:
        deployment_info: dict[str, Any] = {
            "success": args.success,
            "simulated": args.simulated,
            "environment": args.environment,
            "health_check_passed": args.health_ok,
        }
        payload = {
            "deployment_info": deployment_info,
            "use_llm": not args.no_llm,
        }
        if args.strategy:
            payload["progressive_delivery"] = {
                "strategy": args.strategy,
                "passed": args.progressive_passed,
                "final_traffic_percent": 100 if args.progressive_passed else 0,
            }
    resp = api_request("POST", "/api/v1/intelligence/deployment", json=payload)
    if resp.status_code != 200:
        emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
        return 1
    report = resp.json().get("report") or {}
    emit(args, {"ok": True, "report": report})
    gate = report.get("gate_verdict")
    return 1 if gate == "fail" else 0


def cmd_perf(args: argparse.Namespace) -> int:
    stress_report = {
        "performance_verdict": args.verdict,
        "p95_ms": args.p95,
        "error_rate_pct": args.error_rate,
        "requests_per_second": args.rps,
        "stress_profile": args.profile,
    }
    payload: dict[str, Any] = {
        "stress_report": stress_report,
        "stress_profile": args.profile,
        "use_llm": not args.no_llm,
    }
    if args.run_id:
        payload = {"pipeline_run_id": args.run_id, "use_llm": not args.no_llm}
    resp = api_request("POST", "/api/v1/intelligence/performance", json=payload)
    if resp.status_code != 200:
        emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
        return 1
    report = resp.json().get("report") or {}
    emit(args, {"ok": True, "report": report})
    gate = report.get("gate_verdict")
    return 1 if gate == "fail" else 0


def cmd_memory(args: argparse.Namespace) -> int:
    sub = args.memory_cmd
    if sub == "list":
        params: dict[str, str] = {"limit": str(args.limit)}
        if args.agent:
            params["agent"] = args.agent
        resp = api_request("GET", "/api/v1/intelligence/memory", params=params)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "context":
        if not args.agent or not args.scope_id:
            emit(args, {"ok": False, "error": "Usage: orion memory context --agent <name> --scope-id <run_id>"})
            return 1
        resp = api_request(
            "GET",
            "/api/v1/intelligence/memory",
            params={"agent": args.agent, "scope_id": args.scope_id, "limit": str(args.limit)},
        )
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    emit(args, {"ok": False, "error": f"Unknown memory subcommand: {sub}"})
    return 1


def cmd_hub(args: argparse.Namespace) -> int:
    sub = args.hub_cmd
    if sub == "health":
        resp = hub_request("GET", "/api/v1/control-plane/health")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "operations":
        resp = hub_request("GET", "/api/v1/control-plane/operations")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        data = resp.json()
        if not args.json:
            slo = data.get("slo_summary") or {}
            emit(
                args,
                data,
                headers=["metric", "value"],
                table=[
                    ["Active pipelines", str(data.get("active_pipelines", 0))],
                    ["Blocked", str(data.get("blocked_pipelines", 0))],
                    ["Open incidents", str(data.get("incidents_open", 0))],
                    ["Avg pass rate", f"{(slo.get('avg_pass_rate') or 0) * 100:.0f}%"],
                ],
            )
            return 0
        emit(args, data)
        return 0
    if sub == "fleet":
        resp = hub_request("GET", "/api/v1/control-plane/fleet")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "intelligence":
        resp = hub_request("GET", "/api/v1/control-plane/intelligence")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "pipelines":
        params: dict[str, str] = {"limit": str(args.limit)}
        if args.stack:
            params["stack"] = args.stack
        if args.repo:
            params["repo"] = args.repo
        resp = hub_request("GET", "/api/v1/control-plane/pipelines", params=params)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    emit(args, {"ok": False, "error": f"Unknown hub subcommand: {sub}"})
    return 1


def cmd_dev(args: argparse.Namespace) -> int:
    sub = args.dev_cmd
    if sub == "status":
        resp = api_request("GET", "/api/v1/developer/status")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        data = resp.json()
        readiness = data.get("readiness") or {}
        if not args.json:
            emit(
                args,
                data,
                headers=["surface", "status"],
                table=[
                    ["CLI", "ready" if readiness.get("cli_ready") else "warn"],
                    ["VS Code", "ready" if readiness.get("vscode_ready") else "warn"],
                    ["GitHub App", "ready" if readiness.get("github_app_ready") else "pending"],
                    ["Score", f"{readiness.get('readiness_score', 0)}%"],
                ],
            )
            return 0
        emit(args, data)
        return 0
    if sub == "catalog":
        resp = api_request("GET", "/api/v1/developer/catalog")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "vscode":
        resp = api_request("GET", "/api/v1/developer/vscode")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "github-app":
        path = "/api/v1/developer/github-app/manifest" if args.manifest else "/api/v1/developer/github-app"
        resp = api_request("GET", path)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "analyze":
        payload: dict[str, Any] = {"persist": not args.no_persist}
        if args.run_id:
            payload["pipeline_run_id"] = args.run_id
        resp = api_request("POST", "/api/v1/developer/analyze", json=payload)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        report = resp.json().get("report") or {}
        emit(args, {"ok": True, "report": report})
        return 0
    emit(args, {"ok": False, "error": f"Unknown dev subcommand: {sub}"})
    return 1


def cmd_release(args: argparse.Namespace) -> int:
    sub = args.release_cmd
    if sub == "policy":
        params = {"repo": args.repo} if args.repo else None
        resp = api_request("GET", "/api/v1/intelligence/release/policy", params=params)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "dora":
        params: dict[str, str] = {"limit": str(args.limit)}
        if args.repo:
            params["repo"] = args.repo
        resp = api_request("GET", "/api/v1/intelligence/release/dora", params=params)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "passport":
        params = {"limit": str(args.limit)}
        if args.repo:
            params["repo"] = args.repo
        resp = api_request("GET", "/api/v1/intelligence/release", params=params)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        data = resp.json()
        if not args.json:
            rows = [
                [
                    row.get("run_id", "")[:8],
                    row.get("repository", ""),
                    "PASS" if row.get("passport_passed") else "WARN",
                    row.get("failure_probability", "—"),
                    row.get("gate_verdict", "—"),
                ]
                for row in data.get("runs") or []
            ]
            emit(args, data, headers=["run", "repository", "passport", "fail%", "gate"], table=rows)
            return 0
        emit(args, data)
        return 0
    if sub == "analyze":
        payload: dict[str, Any] = {
            "persist": not args.no_persist,
            "include_fleet": not args.no_fleet,
            "environment": args.environment,
            "deploy_mode": args.deploy_mode,
        }
        if args.run_id:
            payload["pipeline_run_id"] = args.run_id
        resp = api_request("POST", "/api/v1/intelligence/release", json=payload)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        report = resp.json().get("report") or {}
        emit(args, {"ok": True, "report": report})
        gate = report.get("gate_verdict")
        return 1 if gate == "fail" else 0
    emit(args, {"ok": False, "error": f"Unknown release subcommand: {sub}"})
    return 1


def cmd_reliability(args: argparse.Namespace) -> int:
    sub = args.reliability_cmd
    if sub == "policy":
        params = {"repo": args.repo} if args.repo else None
        resp = api_request("GET", "/api/v1/reliability/policy", params=params)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "experiments":
        resp = api_request("GET", "/api/v1/reliability/experiments")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        data = resp.json()
        if not args.json:
            rows = [
                [e.get("name", ""), e.get("category", ""), e.get("severity", ""), e.get("description", "")[:50]]
                for e in data.get("experiments") or []
            ]
            emit(args, data, headers=["name", "category", "severity", "description"], table=rows)
            return 0
        emit(args, data)
        return 0
    if sub == "chaos":
        params: dict[str, str] = {"simulated": "true" if args.simulated else "false"}
        if args.repo:
            params["repo"] = args.repo
        resp = api_request("GET", "/api/v1/reliability/chaos", params=params)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "status":
        params = {"repo": args.repo} if args.repo else None
        resp = api_request("GET", "/api/v1/reliability/status", params=params)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "analyze":
        payload: dict[str, Any] = {"persist": not args.no_persist}
        if args.run_id:
            payload["pipeline_run_id"] = args.run_id
        resp = api_request("POST", "/api/v1/reliability/analyze", json=payload)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        report = resp.json().get("report") or {}
        emit(args, {"ok": True, "report": report})
        gate = report.get("gate_verdict")
        return 1 if gate == "fail" else 0
    emit(args, {"ok": False, "error": f"Unknown reliability subcommand: {sub}"})
    return 1


def cmd_iam(args: argparse.Namespace) -> int:
    sub = args.iam_cmd
    if sub == "policy":
        params = {"repo": args.repo} if args.repo else None
        resp = api_request("GET", "/api/v1/iam/policy", params=params)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "sso":
        resp = api_request("GET", "/api/v1/iam/sso")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "status":
        params = {"repo": args.repo} if args.repo else None
        resp = api_request("GET", "/api/v1/iam/status", params=params)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "analyze":
        payload: dict[str, Any] = {"persist": not args.no_persist}
        if args.run_id:
            payload["pipeline_run_id"] = args.run_id
        resp = api_request("POST", "/api/v1/iam/analyze", json=payload)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        report = resp.json().get("report") or {}
        emit(args, {"ok": True, "report": report})
        gate = report.get("gate_verdict")
        return 1 if gate == "fail" else 0
    emit(args, {"ok": False, "error": f"Unknown iam subcommand: {sub}"})
    return 1


def cmd_finops(args: argparse.Namespace) -> int:
    sub = args.finops_cmd
    if sub == "budgets":
        params = {"repo": args.repo} if args.repo else None
        resp = api_request("GET", "/api/v1/intelligence/finops/budgets", params=params)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "fleet" or sub == "cost":
        params: dict[str, str] = {"limit": str(args.limit)}
        if args.repo:
            params["repo"] = args.repo
        resp = api_request("GET", "/api/v1/intelligence/finops", params=params)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        data = resp.json()
        if sub == "cost" and not args.json:
            fleet = data.get("fleet") or {}
            emit(
                args,
                data,
                headers=["repository", "total_usd"],
                table=[
                    [repo, f"${usd:.4f}"]
                    for repo, usd in (fleet.get("by_repository") or {}).items()
                ],
            )
            return 0
        emit(args, data)
        return 0
    if sub == "analyze":
        payload: dict[str, Any] = {
            "persist": not args.no_persist,
            "include_fleet": not args.no_fleet,
        }
        if args.run_id:
            payload["pipeline_run_id"] = args.run_id
        resp = api_request("POST", "/api/v1/intelligence/finops", json=payload)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        report = resp.json().get("report") or {}
        emit(args, {"ok": True, "report": report})
        gate = report.get("gate_verdict")
        return 1 if gate == "fail" else 0
    emit(args, {"ok": False, "error": f"Unknown finops subcommand: {sub}"})
    return 1


def cmd_governance(args: argparse.Namespace) -> int:
    sub = args.governance_cmd
    if sub == "policy":
        resp = api_request("GET", "/api/v1/intelligence/governance/policy")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "escalations":
        params = {"run_id": args.run_id} if args.run_id else None
        resp = api_request("GET", "/api/v1/intelligence/governance/escalations", params=params)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 1 if resp.json().get("human_review_required") else 0
    if sub == "analyze":
        payload: dict[str, Any] = {"persist": not args.no_persist}
        if args.run_id:
            payload["pipeline_run_id"] = args.run_id
        resp = api_request("POST", "/api/v1/intelligence/governance", json=payload)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        report = resp.json().get("report") or {}
        emit(args, {"ok": True, "report": report})
        gate = report.get("gate_verdict")
        return 1 if gate == "fail" else 0
    emit(args, {"ok": False, "error": f"Unknown governance subcommand: {sub}"})
    return 1


def cmd_mesh(args: argparse.Namespace) -> int:
    sub = args.mesh_cmd
    if sub == "agents":
        resp = api_request("GET", "/api/v1/intelligence/mesh/agents")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "topology":
        resp = api_request("GET", "/api/v1/intelligence/mesh/topology")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "route":
        payload: dict[str, Any] = {}
        if args.event:
            payload["event_id"] = args.event
        else:
            payload["intent"] = args.intent or ""
        if args.agent:
            payload["preferred_agent"] = args.agent
        resp = api_request("POST", "/api/v1/intelligence/mesh/route", json=payload)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "analyze":
        payload = {"persist": not args.no_persist, "intent": args.intent or ""}
        if args.run_id:
            payload["pipeline_run_id"] = args.run_id
        resp = api_request("POST", "/api/v1/intelligence/mesh", json=payload)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        report = resp.json().get("report") or {}
        emit(args, {"ok": True, "report": report})
        gate = report.get("gate_verdict")
        return 1 if gate == "fail" else 0
    emit(args, {"ok": False, "error": f"Unknown mesh subcommand: {sub}"})
    return 1


def cmd_rag(args: argparse.Namespace) -> int:
    sub = args.rag_cmd
    if sub == "query":
        params: dict[str, str] = {"q": args.query or ""}
        if args.run_id:
            params["run_id"] = args.run_id
        if args.repo_path:
            params["repo_path"] = args.repo_path
        resp = api_request("GET", "/api/v1/intelligence/rag", params=params)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, {"ok": True, "result": resp.json()})
        return 0
    if sub == "analyze":
        payload: dict[str, Any] = {
            "query": args.query or "",
            "persist": not args.no_persist,
            "index_repo": not args.no_index,
        }
        if args.run_id:
            payload["pipeline_run_id"] = args.run_id
        if args.repo_path:
            payload["repo_path"] = args.repo_path
        resp = api_request("POST", "/api/v1/intelligence/rag", json=payload)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        report = resp.json().get("report") or {}
        emit(args, {"ok": True, "report": report})
        return 0
    emit(args, {"ok": False, "error": f"Unknown rag subcommand: {sub}"})
    return 1


def cmd_explain(args: argparse.Namespace) -> int:
    skip = {"--json", "--help", "-h"}
    if "--json" in (args.rest or []):
        args.json = True
    rest = [part for part in (args.rest or []) if part not in skip and part != "--"]
    if args.subject == "incident":
        if not rest:
            emit(args, {"ok": False, "error": "Usage: orion explain incident INC-204 [extra context]"})
            return 1
        incident_id = rest[0]
        extra = " ".join(rest[1:]).strip()
        query = f"incident {incident_id} {extra}".strip()
    else:
        query = " ".join(rest).strip() or "pipeline status summary"
    params: dict[str, str] = {"q": query}
    if args.run_id:
        params["run_id"] = args.run_id
    resp = api_request("GET", "/api/v1/intelligence/rag", params=params)
    if resp.status_code != 200:
        emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
        return 1
    emit(args, {"ok": True, "query": query, "result": resp.json()})
    return 0


FIX_STATUS_ALIASES: dict[str, str] = {
    "code": "blocked_code",
    "security": "blocked_security",
    "tests": "blocked_tests",
    "test": "blocked_tests",
    "qa": "blocked_tests",
    "stress": "blocked_stress",
    "secrets": "blocked_secrets",
    "policy": "blocked_policy",
    "injection": "blocked_injection",
    "eval": "blocked_agent_eval",
}


def _list_runs(limit: int = 30) -> list[dict[str, Any]]:
    resp = api_request("GET", "/api/v1/pipeline/runs", params={"limit": limit})
    if resp.status_code != 200:
        raise SystemExit(f"Runs list failed ({resp.status_code}): {_json_or_text(resp)}")
    body = resp.json()
    items = body.get("items") or body.get("runs") or []
    return items if isinstance(items, list) else []


def cmd_fix(args: argparse.Namespace) -> int:
    target = (args.target or "").strip().lower()
    status_filter = FIX_STATUS_ALIASES.get(target)
    runs = _list_runs(limit=50)
    candidates = [r for r in runs if str(r.get("status", "")).startswith("blocked") or r.get("status") in {"failed", "rejected"}]
    if status_filter:
        candidates = [r for r in candidates if r.get("status") == status_filter]
    elif target:
        candidates = [r for r in candidates if target in str(r.get("repo_full_name", "")).lower()]
    if not candidates:
        emit(args, {"ok": False, "error": "No matching blocked or failed runs found", "target": target or None})
        return 1
    run_id = str(candidates[0]["id"])
    resp = api_request("POST", f"/api/v1/pipeline/runs/{run_id}/resume")
    if resp.status_code == 409:
        resp = api_request("POST", f"/api/v1/pipeline/runs/{run_id}/retry")
    if resp.status_code not in (200, 202):
        emit(args, {"ok": False, "run_id": run_id, "error": _json_or_text(resp), "status_code": resp.status_code})
        return 1
    emit(args, {"ok": True, "run_id": run_id, "response": resp.json()})
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    if args.runs_cmd == "list":
        runs = _list_runs(limit=args.limit)
        if args.json:
            emit(args, {"runs": runs})
            return 0
        rows = [[r.get("id"), r.get("status"), r.get("repo_full_name"), r.get("branch"), r.get("short_commit_id")] for r in runs]
        emit(args, {"runs": runs}, rows, ["RUN ID", "STATUS", "REPO", "BRANCH", "COMMIT"])
        return 0
    if args.runs_cmd == "show":
        run = fetch_run(args.run_id)
        emit(args, run)
        return 0
    content = fetch_artifact(args.run_id, args.artifact_type)
    emit(args, {"run_id": args.run_id, "artifact_type": args.artifact_type, "content": content})
    return 0 if content else 1


def cmd_intelligence(args: argparse.Namespace) -> int:
    path = "/api/v1/intelligence/dashboard"
    if args.view == "fleet":
        path = "/api/v1/intelligence/fleet"
    elif args.view == "agents":
        path = "/api/v1/intelligence/agents"
    resp = api_request("GET", path)
    if resp.status_code != 200:
        emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
        return 1
    emit(args, resp.json())
    return 0


def cmd_backup_db(args: argparse.Namespace) -> int:
    from app.utils.dr_backup import run_database_backup

    output_dir = Path(args.output_dir) if args.output_dir else BACKUP_DIR
    result = run_database_backup(output_dir=output_dir)
    emit(args, result)
    return 0 if result.get("ok") else 1


def cmd_autopilot(args: argparse.Namespace) -> int:
    sub = args.autopilot_cmd
    if sub == "policy":
        params: dict[str, str] = {}
        if args.repo:
            params["repo"] = args.repo
        if args.environment:
            params["environment"] = args.environment
        resp = api_request("GET", "/api/v1/autopilot/policy", params=params or None)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "catalog":
        resp = api_request("GET", "/api/v1/autopilot/catalog")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "plan":
        params = {"run_id": args.run_id}
        if args.environment:
            params["environment"] = args.environment
        resp = api_request("GET", "/api/v1/autopilot/plan", params=params)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        data = resp.json()
        if not args.json:
            rows = [
                [
                    a.get("id", ""),
                    a.get("level", ""),
                    "yes" if a.get("allowed") else "no",
                    a.get("execute_mode", ""),
                    a.get("reason", "")[:60],
                ]
                for a in data.get("actions") or []
            ]
            emit(args, data, headers=["action", "level", "allowed", "mode", "reason"], table=rows)
            return 0
        emit(args, data)
        return 0
    if sub == "status":
        params = {}
        if args.repo:
            params["repo"] = args.repo
        if args.environment:
            params["environment"] = args.environment
        resp = api_request("GET", "/api/v1/autopilot/status", params=params or None)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "analyze":
        payload: dict[str, Any] = {"persist": not args.no_persist}
        if args.run_id:
            payload["pipeline_run_id"] = args.run_id
        if args.environment:
            payload["environment"] = args.environment
        resp = api_request("POST", "/api/v1/autopilot/analyze", json=payload)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        report = resp.json().get("report") or {}
        emit(args, {"ok": True, "report": report})
        gate = report.get("gate_verdict")
        return 1 if gate == "fail" else 0
    emit(args, {"ok": False, "error": f"Unknown autopilot subcommand: {sub}"})
    return 1


def cmd_production(args: argparse.Namespace) -> int:
    sub = args.production_cmd
    if sub == "checklist":
        resp = api_request("GET", "/api/v1/production/checklist")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        data = resp.json()
        if not args.json:
            rows = [
                [i.get("code"), "ok" if i.get("ok") else "FAIL", i.get("severity"), i.get("detail", "")[:60]]
                for i in data.get("items", [])
            ]
            emit(
                args,
                data,
                headers=["code", "status", "severity", "detail"],
                table=rows,
            )
            print(f"\n{data.get('summary', '')}")
            return 0 if data.get("ready_for_production") or not data.get("production_mode") else 1
        emit(args, data)
        return 0 if data.get("ready_for_production") or not data.get("production_mode") else 1
    if sub == "ready":
        resp = api_request("GET", "/api/v1/production/ready")
        if resp.status_code == 503:
            emit(args, resp.json())
            return 1
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        data = resp.json()
        emit(args, data)
        return 0 if data.get("ready") else 1
    emit(args, {"ok": False, "error": f"Unknown production subcommand: {sub}"})
    return 1


def cmd_unified_risk(args: argparse.Namespace) -> int:
    sub = args.unified_risk_cmd
    if sub == "policy":
        params: dict[str, str] = {}
        if args.repo:
            params["repo"] = args.repo
        if args.environment:
            params["environment"] = args.environment
        resp = api_request("GET", "/api/v1/unified-risk/policy", params=params or None)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "score":
        if not args.run_id:
            emit(args, {"ok": False, "error": "--run-id required for unified-risk score"})
            return 1
        params = {"run_id": args.run_id}
        if args.environment:
            params["environment"] = args.environment
        resp = api_request("GET", "/api/v1/unified-risk/score", params=params)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        data = resp.json()
        if not args.json:
            dims = data.get("dimensions") or {}
            rows = [[k, v] for k, v in sorted(dims.items(), key=lambda item: item[1], reverse=True)]
            emit(args, data, headers=["dimension", "score"], table=rows)
            return 0
        emit(args, data)
        return 0
    if sub == "status":
        resp = api_request("GET", "/api/v1/unified-risk/status")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "analyze":
        payload: dict[str, Any] = {"persist": not args.no_persist}
        if args.run_id:
            payload["pipeline_run_id"] = args.run_id
        if args.environment:
            payload["environment"] = args.environment
        resp = api_request("POST", "/api/v1/unified-risk/analyze", json=payload)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        report = resp.json()
        emit(args, {"ok": True, "report": report})
        gate = report.get("gate_verdict")
        return 1 if gate == "fail" else 0
    emit(args, {"ok": False, "error": f"Unknown unified-risk subcommand: {sub}"})
    return 1


def cmd_knowledge(args: argparse.Namespace) -> int:
    sub = args.knowledge_cmd
    if sub == "policy":
        params = {"repo": args.repo} if args.repo else None
        resp = api_request("GET", "/api/v1/knowledge/policy", params=params)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "graph":
        params: dict[str, str] = {}
        if args.run_id:
            params["run_id"] = args.run_id
        if args.query:
            params["q"] = args.query
        resp = api_request("GET", "/api/v1/knowledge/graph", params=params or None)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        data = resp.json()
        if not args.json and args.query:
            matches = (data.get("query") or {}).get("matches") or []
            rows = [[m.get("type", ""), m.get("label", ""), m.get("source", ""), m.get("score", "")] for m in matches]
            emit(args, data, headers=["type", "label", "source", "score"], table=rows)
            return 0
        emit(args, data)
        return 0
    if sub == "status":
        params = {"repo": args.repo} if args.repo else None
        resp = api_request("GET", "/api/v1/knowledge/status", params=params)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "analyze":
        payload: dict[str, Any] = {"persist": not args.no_persist}
        if args.run_id:
            payload["pipeline_run_id"] = args.run_id
        if args.query:
            payload["query"] = args.query
        resp = api_request("POST", "/api/v1/knowledge/analyze", json=payload)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        report = resp.json().get("report") or {}
        emit(args, {"ok": True, "report": report})
        gate = report.get("gate_verdict")
        return 1 if gate == "fail" else 0
    emit(args, {"ok": False, "error": f"Unknown knowledge subcommand: {sub}"})
    return 1


def cmd_dr(args: argparse.Namespace) -> int:
    sub = args.dr_cmd
    if sub == "policy":
        params = {"repo": args.repo} if args.repo else None
        resp = api_request("GET", "/api/v1/dr/policy", params=params)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "backups":
        resp = api_request("GET", "/api/v1/dr/backups")
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        data = resp.json()
        if not args.json:
            rows = [
                [b.get("name", ""), b.get("backend", ""), b.get("size_bytes", 0), b.get("modified_at", "")[:19]]
                for b in data.get("backups") or []
            ]
            emit(args, data, headers=["name", "backend", "bytes", "modified"], table=rows)
            return 0
        emit(args, data)
        return 0
    if sub == "backup":
        from app.utils.dr_backup import run_database_backup

        output_dir = Path(args.output_dir) if args.output_dir else BACKUP_DIR
        result = run_database_backup(output_dir=output_dir)
        emit(args, result)
        return 0 if result.get("ok") else 1
    if sub == "status":
        params = {"repo": args.repo} if args.repo else None
        resp = api_request("GET", "/api/v1/dr/status", params=params)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        emit(args, resp.json())
        return 0
    if sub == "analyze":
        payload: dict[str, Any] = {"persist": not args.no_persist}
        if args.run_id:
            payload["pipeline_run_id"] = args.run_id
        resp = api_request("POST", "/api/v1/dr/analyze", json=payload)
        if resp.status_code != 200:
            emit(args, {"ok": False, "error": _json_or_text(resp), "status_code": resp.status_code})
            return 1
        report = resp.json().get("report") or {}
        emit(args, {"ok": True, "report": report})
        gate = report.get("gate_verdict")
        return 1 if gate == "fail" else 0
    emit(args, {"ok": False, "error": f"Unknown dr subcommand: {sub}"})
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orion", description="ORION management and developer CLI")
    parser.add_argument("--json", action="store_true", help="output raw JSON")
    # SUPPRESS keeps `orion --json status` working: a subparser default would overwrite the global flag.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="output raw JSON")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", parents=[common], help="service status, memory, PID and uptime").set_defaults(func=cmd_status)

    p = sub.add_parser("restart", parents=[common], help="restart one service or all")
    p.add_argument("service", nargs="?", default="all")
    p.set_defaults(func=cmd_restart)

    p = sub.add_parser("logs", parents=[common], help="show journald logs")
    p.add_argument("service", nargs="?", default="api")
    p.add_argument("--lines", "-n", type=int, default=100)
    p.add_argument("--follow", "-f", action="store_true")
    p.set_defaults(func=cmd_logs)

    p = sub.add_parser("deploy", parents=[common], help="trigger a pipeline run for a local git repo")
    p.add_argument("repo_path", nargs="?", default=".")
    p.add_argument("--canary", action="store_true", help="request progressive canary delivery when enabled")
    p.set_defaults(func=cmd_deploy)

    p = sub.add_parser("scan", parents=[common], help="trigger full ORION pipeline scan for a repo")
    p.add_argument("repo_path", nargs="?", default=".")
    p.add_argument("--wait", action="store_true", help="poll until the run reaches a terminal status")
    p.add_argument("--timeout", type=int, default=900)
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("test", parents=[common], help="trigger pipeline and focus on QA / test intelligence")
    p.add_argument("repo_path", nargs="?", default=".")
    p.add_argument("--wait", action="store_true")
    p.add_argument("--timeout", type=int, default=900)
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("risk", parents=[common], help="local change-risk score from git diff (default ref: HEAD)")
    p.add_argument("ref", nargs="?", default="HEAD")
    p.add_argument("--repo-path", default=".")
    p.set_defaults(func=cmd_risk)

    p = sub.add_parser("repo", parents=[common], help="repository fingerprint, stack, license, and ownership scan")
    p.add_argument("repo_path", nargs="?", default=".")
    p.add_argument("ref", nargs="?", default="HEAD", help="git ref for optional diff impact (default HEAD)")
    p.add_argument("--no-llm", action="store_true", help="heuristic-only analysis")
    p.set_defaults(func=cmd_repo)

    p = sub.add_parser(
        "code-review",
        aliases=["codereview", "review"],
        parents=[common],
        help="multi-layer L0-L7 code review intelligence with bug prediction",
    )
    p.add_argument("repo_path", nargs="?", default=".")
    p.add_argument("ref", nargs="?", default="HEAD")
    p.add_argument("--run-id", help="analyze artifacts from an existing pipeline run")
    p.set_defaults(func=cmd_code_review)

    p = sub.add_parser("test-intel", aliases=["testintel"], parents=[common], help="test selection, flaky, coverage, mutation intel")
    p.add_argument("repo_path", nargs="?", default=".")
    p.add_argument("ref", nargs="?", default="HEAD")
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--live-coverage", action="store_true", help="run pytest-cov probe when installed")
    p.set_defaults(func=cmd_test_intel)

    p = sub.add_parser(
        "deploy-intel",
        aliases=["deployintel", "deploy-intelligence"],
        parents=[common],
        help="deployment strategy, environments, and SLO rollback signals",
    )
    p.add_argument("--run-id", help="analyze deployment artifacts from an existing pipeline run")
    p.add_argument("--strategy", choices=["canary", "blue_green", "direct"], help="progressive delivery strategy hint")
    p.add_argument("--environment", default="staging")
    p.add_argument("--simulated", action="store_true", help="mark deployment as simulated")
    p.add_argument("--no-health", dest="health_ok", action="store_false", help="health check failed")
    p.add_argument("--failed", dest="success", action="store_false", help="deployment failed")
    p.add_argument("--progressive-failed", dest="progressive_passed", action="store_false", help="progressive delivery aborted")
    p.add_argument("--no-llm", action="store_true")
    p.set_defaults(func=cmd_deploy_intel, health_ok=True, success=True, progressive_passed=True)

    p = sub.add_parser(
        "observability",
        aliases=["aiops", "obs"],
        parents=[common],
        help="deploy correlation, anomalies, and runtime service map",
    )
    p.add_argument("--run-id", help="analyze observability artifacts from an existing pipeline run")
    p.add_argument("--environment", default="staging")
    p.add_argument("--latency-ms", type=float, default=15.0, help="synthetic journey latency for inline mode")
    p.add_argument("--synthetic-failed", dest="synthetic_ok", action="store_false", help="mark synthetic checks failed")
    p.add_argument("--log-excerpt", help="optional log lines for signal analysis")
    p.add_argument("--no-llm", action="store_true")
    p.set_defaults(func=cmd_observability, synthetic_ok=True)

    p_inc = sub.add_parser("incident", aliases=["incidents"], parents=[common], help="incident command center lifecycle")
    inc_sub = p_inc.add_subparsers(dest="incident_cmd", required=True)
    p_list = inc_sub.add_parser("list", parents=[common], help="list recent incidents")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.add_argument("--status")
    p_list.add_argument("--severity")
    p_list.set_defaults(incident_cmd="list")
    p_show = inc_sub.add_parser("show", parents=[common], help="show incident commander bundle")
    p_show.add_argument("incident_id")
    p_show.set_defaults(incident_cmd="show")
    p_trans = inc_sub.add_parser("transition", parents=[common], help="transition incident lifecycle status")
    p_trans.add_argument("incident_id")
    p_trans.add_argument("status", choices=["investigating", "mitigated", "resolved", "closed"])
    p_trans.add_argument("--note", default="")
    p_trans.set_defaults(incident_cmd="transition")
    p_trig = inc_sub.add_parser("trigger", parents=[common], help="run incident commander for a pipeline run")
    p_trig.add_argument("--run-id", required=True)
    p_trig.add_argument("--log-excerpt", default="")
    p_trig.set_defaults(incident_cmd="trigger")
    p_inc.set_defaults(func=cmd_incident)

    p_rem = sub.add_parser("remediate", aliases=["remediation"], parents=[common], help="autonomous remediation levels L0-L6")
    rem_sub = p_rem.add_subparsers(dest="remediate_cmd", required=True)
    rem_sub.add_parser("levels", parents=[common], help="list remediation autonomy levels").set_defaults(remediate_cmd="levels")
    p_ra = rem_sub.add_parser("analyze", parents=[common], help="build remediation_intelligence for a run")
    p_ra.add_argument("--run-id", required=True)
    p_ra.add_argument("--no-llm", action="store_true")
    p_ra.set_defaults(remediate_cmd="analyze")
    p_rs = rem_sub.add_parser("show", parents=[common], help="show remediation report for a run")
    p_rs.add_argument("--run-id", required=True)
    p_rs.set_defaults(remediate_cmd="show")
    p_rem.set_defaults(func=cmd_remediate)

    p_pol = sub.add_parser("policy", aliases=["policies"], parents=[common], help="policy-as-code catalog and evaluation")
    pol_sub = p_pol.add_subparsers(dest="policy_cmd", required=True)
    pol_sub.add_parser("catalog", parents=[common], help="default and config policy catalog").set_defaults(policy_cmd="catalog")
    p_eff = pol_sub.add_parser("effective", parents=[common], help="effective org/repo/env policies")
    p_eff.add_argument("repo", help="org/repo full name")
    p_eff.add_argument("--environment", help="deploy environment (default from server)")
    p_eff.set_defaults(policy_cmd="effective")
    p_eval = pol_sub.add_parser("evaluate", parents=[common], help="evaluate policies for a run or repo")
    p_eval.add_argument("--run-id", help="pipeline run with artifacts")
    p_eval.add_argument("--repo", help="repo full name when no run-id")
    p_eval.add_argument("--environment")
    p_eval.add_argument("--no-persist", action="store_true")
    p_eval.set_defaults(policy_cmd="evaluate")
    p_pol.set_defaults(func=cmd_policy)

    p_apr = sub.add_parser("approve", aliases=["approvals"], parents=[common], help="enterprise approval workflow and sign-offs")
    apr_sub = p_apr.add_subparsers(dest="approve_cmd", required=True)
    p_wf = apr_sub.add_parser("workflow", parents=[common], help="resolve org/repo/env approval workflow")
    p_wf.add_argument("repo", help="org/repo full name")
    p_wf.add_argument("--environment", help="deploy environment (default from server)")
    p_wf.add_argument("--change-risk", type=int, dest="change_risk")
    p_wf.set_defaults(approve_cmd="workflow")
    p_st = apr_sub.add_parser("status", parents=[common], help="approval intelligence for a pipeline run")
    p_st.add_argument("run_id")
    p_st.set_defaults(approve_cmd="status")
    p_sg = apr_sub.add_parser("sign", parents=[common], help="record an enterprise sign-off")
    p_sg.add_argument("run_id")
    p_sg.add_argument("approver")
    p_sg.add_argument("--role", default="release_manager")
    p_sg.add_argument("--comment", default="")
    p_sg.add_argument("--signature-token")
    p_sg.set_defaults(approve_cmd="sign")
    p_apr.set_defaults(func=cmd_approve)

    p_mm = sub.add_parser("multimodal", aliases=["mm"], parents=[common], help="multimodal catalog, routing, and intelligence")
    mm_sub = p_mm.add_subparsers(dest="multimodal_cmd", required=True)
    mm_sub.add_parser("catalog", parents=[common], help="list multimodal agents and artifact types").set_defaults(multimodal_cmd="catalog")
    p_rt = mm_sub.add_parser("route", parents=[common], help="recommend agent from pasted text")
    p_rt.add_argument("--text", default="", help="log or incident text to classify")
    p_rt.add_argument("--agent", help="optional preferred agent alias")
    p_rt.set_defaults(multimodal_cmd="route")
    p_mi = mm_sub.add_parser("intel", parents=[common], help="aggregate multimodal artifacts on a run")
    p_mi.add_argument("--run-id", help="pipeline run with multimodal artifacts")
    p_mi.add_argument("--text", help="optional routing hint text")
    p_mi.add_argument("--agent", help="optional preferred agent alias")
    p_mi.add_argument("--no-persist", action="store_true")
    p_mi.set_defaults(multimodal_cmd="intel")
    p_mm.set_defaults(func=cmd_multimodal)

    p_cloud = sub.add_parser("cloud", aliases=["k8s"], parents=[common], help="Kubernetes/cloud target registry and intelligence")
    cloud_sub = p_cloud.add_subparsers(dest="cloud_cmd", required=True)
    p_ct = cloud_sub.add_parser("targets", parents=[common], help="list cloud deployment targets and recommendation")
    p_ct.add_argument("--repo", help="org/repo for signal-based recommendation")
    p_ct.set_defaults(cloud_cmd="targets")
    p_ca = cloud_sub.add_parser("analyze", parents=[common], help="cloud/K8s readiness intelligence")
    p_ca.add_argument("--run-id", help="pipeline run with scan artifacts")
    p_ca.add_argument("--repo", help="org/repo full name")
    p_ca.add_argument("--repo-path", help="local checkout for target resolution")
    p_ca.add_argument("--environment")
    p_ca.add_argument("--no-persist", action="store_true")
    p_ca.set_defaults(cloud_cmd="analyze")
    p_cloud.set_defaults(func=cmd_cloud)

    p_catalog = sub.add_parser("catalog", aliases=["idp"], parents=[common], help="service catalog and IDP portal")
    catalog_sub = p_catalog.add_subparsers(dest="catalog_cmd", required=True)
    catalog_sub.add_parser("idp", parents=[common], help="IDP golden paths and self-service actions").set_defaults(catalog_cmd="idp")
    p_cs = catalog_sub.add_parser("services", parents=[common], help="service catalog for repo or fleet")
    p_cs.add_argument("--repo", help="org/repo full name")
    p_cs.add_argument("--repo-path", help="local checkout path")
    p_cs.set_defaults(catalog_cmd="services")
    catalog_sub.add_parser("fleet", parents=[common], help="fleet risk view (alias for intelligence/fleet)").set_defaults(catalog_cmd="fleet")
    p_ca = catalog_sub.add_parser("analyze", parents=[common], help="service catalog intelligence report")
    p_ca.add_argument("--run-id", help="pipeline run with catalog artifacts")
    p_ca.add_argument("--repo", help="org/repo full name")
    p_ca.add_argument("--repo-path", help="local checkout path")
    p_ca.add_argument("--no-persist", action="store_true")
    p_ca.add_argument("--no-fleet", action="store_true", help="skip fleet overlay")
    p_ca.set_defaults(catalog_cmd="analyze")
    p_catalog.set_defaults(func=cmd_catalog)

    p_memory = sub.add_parser("memory", parents=[common], help="agent memory scopes and context")
    mem_sub = p_memory.add_subparsers(dest="memory_cmd", required=True)
    p_ml = mem_sub.add_parser("list", parents=[common], help="list memory scopes")
    p_ml.add_argument("--agent", help="filter by agent class name")
    p_ml.add_argument("--limit", type=int, default=20)
    p_ml.set_defaults(memory_cmd="list")
    p_mc = mem_sub.add_parser("context", parents=[common], help="fetch memory context for agent + run scope")
    p_mc.add_argument("--agent", required=True)
    p_mc.add_argument("--scope-id", required=True, help="pipeline run UUID scope")
    p_mc.add_argument("--limit", type=int, default=5)
    p_mc.set_defaults(memory_cmd="context")
    p_memory.set_defaults(func=cmd_memory)

    p_rag = sub.add_parser("rag", parents=[common], help="DevOps RAG query and intelligence")
    rag_sub = p_rag.add_subparsers(dest="rag_cmd", required=True)
    p_rq = rag_sub.add_parser("query", parents=[common], help="query artifacts + optional repo index")
    p_rq.add_argument("query", nargs="?", default="", help="natural language query")
    p_rq.add_argument("--run-id")
    p_rq.add_argument("--repo-path")
    p_rq.set_defaults(rag_cmd="query")
    p_ra = rag_sub.add_parser("analyze", parents=[common], help="full RAG intelligence report")
    p_ra.add_argument("query", nargs="?", default="")
    p_ra.add_argument("--run-id")
    p_ra.add_argument("--repo-path")
    p_ra.add_argument("--no-persist", action="store_true")
    p_ra.add_argument("--no-index", action="store_true")
    p_ra.set_defaults(rag_cmd="analyze")
    p_rag.set_defaults(func=cmd_rag)

    p_mesh = sub.add_parser("mesh", parents=[common], help="agent mesh registry, topology, and routing")
    mesh_sub = p_mesh.add_subparsers(dest="mesh_cmd", required=True)
    mesh_sub.add_parser("agents", parents=[common], help="O2-style agent descriptors").set_defaults(mesh_cmd="agents")
    mesh_sub.add_parser("topology", parents=[common], help="pipeline stage DAG and domain events").set_defaults(mesh_cmd="topology")
    p_mr = mesh_sub.add_parser("route", parents=[common], help="route intent or domain event to agent chain")
    p_mr.add_argument("intent", nargs="?", default="", help="natural language intent")
    p_mr.add_argument("--event", help="domain event id e.g. monitoring_alert")
    p_mr.add_argument("--agent", help="preferred agent name or alias")
    p_mr.set_defaults(mesh_cmd="route")
    p_ma = mesh_sub.add_parser("analyze", parents=[common], help="mesh coverage intelligence for a run")
    p_ma.add_argument("intent", nargs="?", default="")
    p_ma.add_argument("--run-id")
    p_ma.add_argument("--no-persist", action="store_true")
    p_ma.set_defaults(mesh_cmd="analyze")
    p_mesh.set_defaults(func=cmd_mesh)

    p_hub = sub.add_parser("hub", parents=[common], help="Command Hub control plane (federated ops on :5180)")
    hub_sub = p_hub.add_subparsers(dest="hub_cmd", required=True)
    hub_sub.add_parser("health", parents=[common], help="cross-stack health matrix").set_defaults(hub_cmd="health")
    hub_sub.add_parser("operations", parents=[common], help="operations center rollup").set_defaults(hub_cmd="operations")
    hub_sub.add_parser("fleet", parents=[common], help="ORION fleet risk via hub BFF").set_defaults(hub_cmd="fleet")
    hub_sub.add_parser("intelligence", parents=[common], help="federated intelligence fan-out").set_defaults(hub_cmd="intelligence")
    p_hp = hub_sub.add_parser("pipelines", parents=[common], help="federated pipeline list")
    p_hp.add_argument("--stack")
    p_hp.add_argument("--repo")
    p_hp.add_argument("--limit", type=int, default=30)
    p_hp.set_defaults(hub_cmd="pipelines")
    p_hub.set_defaults(func=cmd_hub)

    p_dev = sub.add_parser("dev", parents=[common], help="developer UX: VS Code extension, GitHub App, readiness")
    dev_sub = p_dev.add_subparsers(dest="dev_cmd", required=True)
    dev_sub.add_parser("status", parents=[common], help="developer surface readiness").set_defaults(dev_cmd="status")
    dev_sub.add_parser("catalog", parents=[common], help="CLI + IDE integration catalog").set_defaults(dev_cmd="catalog")
    dev_sub.add_parser("vscode", parents=[common], help="VS Code extension manifest").set_defaults(dev_cmd="vscode")
    p_dga = dev_sub.add_parser("github-app", parents=[common], help="GitHub App status or manifest")
    p_dga.add_argument("--manifest", action="store_true", help="return installable manifest JSON")
    p_dga.set_defaults(dev_cmd="github-app")
    p_da = dev_sub.add_parser("analyze", parents=[common], help="developer UX intelligence report")
    p_da.add_argument("--run-id")
    p_da.add_argument("--no-persist", action="store_true")
    p_da.set_defaults(dev_cmd="analyze")
    p_dev.set_defaults(func=cmd_dev)

    p_release = sub.add_parser("release", aliases=["rel"], parents=[common], help="release intelligence, DORA metrics, and promotion readiness")
    release_sub = p_release.add_subparsers(dest="release_cmd", required=True)
    p_rp = release_sub.add_parser("policy", parents=[common], help="release promotion policy and risk thresholds")
    p_rp.add_argument("--repo")
    p_rp.set_defaults(release_cmd="policy")
    p_rd = release_sub.add_parser("dora", parents=[common], help="DORA metrics from recent pipeline runs")
    p_rd.add_argument("--repo")
    p_rd.add_argument("--limit", type=int, default=30)
    p_rd.set_defaults(release_cmd="dora")
    p_rpass = release_sub.add_parser("passport", parents=[common], help="fleet release passport summary")
    p_rpass.add_argument("--repo")
    p_rpass.add_argument("--limit", type=int, default=20)
    p_rpass.set_defaults(release_cmd="passport")
    p_ra = release_sub.add_parser("analyze", parents=[common], help="full release intelligence report")
    p_ra.add_argument("--run-id")
    p_ra.add_argument("--environment", default="staging")
    p_ra.add_argument("--deploy-mode", default="auto")
    p_ra.add_argument("--no-persist", action="store_true")
    p_ra.add_argument("--no-fleet", action="store_true")
    p_ra.set_defaults(release_cmd="analyze")
    p_release.set_defaults(func=cmd_release)

    p_rel = sub.add_parser("reliability", aliases=["chaos"], parents=[common], help="chaos engineering, synthetic checks, and reliability intelligence")
    rel_sub = p_rel.add_subparsers(dest="reliability_cmd", required=True)
    p_rlp = rel_sub.add_parser("policy", parents=[common], help="reliability and chaos policy defaults")
    p_rlp.add_argument("--repo")
    p_rlp.set_defaults(reliability_cmd="policy")
    rel_sub.add_parser("experiments", parents=[common], help="chaos experiment catalog").set_defaults(reliability_cmd="experiments")
    p_rlc = rel_sub.add_parser("chaos", parents=[common], help="run chaos suite (simulated by default)")
    p_rlc.add_argument("--repo")
    p_rlc.add_argument("--live", dest="simulated", action="store_false", help="request live chaos (requires CHAOS_LIVE_ENABLED)")
    p_rlc.set_defaults(simulated=True, reliability_cmd="chaos")
    p_rls = rel_sub.add_parser("status", parents=[common], help="reliability readiness snapshot")
    p_rls.add_argument("--repo")
    p_rls.set_defaults(reliability_cmd="status")
    p_rla = rel_sub.add_parser("analyze", parents=[common], help="full reliability intelligence report")
    p_rla.add_argument("--run-id")
    p_rla.add_argument("--no-persist", action="store_true")
    p_rla.set_defaults(reliability_cmd="analyze")
    p_rel.set_defaults(func=cmd_reliability)

    p_iam = sub.add_parser("iam", parents=[common], help="enterprise IAM policy, SSO readiness, and intelligence")
    iam_sub = p_iam.add_subparsers(dest="iam_cmd", required=True)
    p_ip = iam_sub.add_parser("policy", parents=[common], help="IAM policy defaults and org/repo overrides")
    p_ip.add_argument("--repo")
    p_ip.set_defaults(iam_cmd="policy")
    iam_sub.add_parser("sso", parents=[common], help="SSO provider readiness assessment").set_defaults(iam_cmd="sso")
    p_is = iam_sub.add_parser("status", parents=[common], help="full IAM readiness status")
    p_is.add_argument("--repo")
    p_is.set_defaults(iam_cmd="status")
    p_ia = iam_sub.add_parser("analyze", parents=[common], help="IAM intelligence report for a run")
    p_ia.add_argument("--run-id")
    p_ia.add_argument("--no-persist", action="store_true")
    p_ia.set_defaults(iam_cmd="analyze")
    p_iam.set_defaults(func=cmd_iam)

    p_finops = sub.add_parser("finops", aliases=["costs"], parents=[common], help="FinOps budgets, fleet costs, and intelligence")
    finops_sub = p_finops.add_subparsers(dest="finops_cmd", required=True)
    p_fb = finops_sub.add_parser("budgets", parents=[common], help="per-run and monthly budget defaults")
    p_fb.add_argument("--repo", help="resolve org/repo-specific overrides from FINOPS_BUDGET_JSON")
    p_fb.set_defaults(finops_cmd="budgets")
    p_fc = finops_sub.add_parser("cost", parents=[common], help="fleet cost rollup table")
    p_fc.add_argument("--repo")
    p_fc.add_argument("--limit", type=int, default=30)
    p_fc.set_defaults(finops_cmd="cost")
    p_ff = finops_sub.add_parser("fleet", parents=[common], help="full fleet FinOps JSON")
    p_ff.add_argument("--repo")
    p_ff.add_argument("--limit", type=int, default=30)
    p_ff.set_defaults(finops_cmd="fleet")
    p_fa = finops_sub.add_parser("analyze", parents=[common], help="FinOps intelligence report for a run")
    p_fa.add_argument("--run-id")
    p_fa.add_argument("--no-persist", action="store_true")
    p_fa.add_argument("--no-fleet", action="store_true")
    p_fa.set_defaults(finops_cmd="analyze")
    p_finops.set_defaults(func=cmd_finops)

    p_gov = sub.add_parser("governance", aliases=["gov"], parents=[common], help="AI governance policy, escalations, and intelligence")
    gov_sub = p_gov.add_subparsers(dest="governance_cmd", required=True)
    gov_sub.add_parser("policy", parents=[common], help="governance controls and escalation rules").set_defaults(governance_cmd="policy")
    p_ge = gov_sub.add_parser("escalations", parents=[common], help="human-review escalation queue for a run")
    p_ge.add_argument("--run-id")
    p_ge.set_defaults(governance_cmd="escalations")
    p_ga = gov_sub.add_parser("analyze", parents=[common], help="full AI governance intelligence report")
    p_ga.add_argument("--run-id")
    p_ga.add_argument("--no-persist", action="store_true")
    p_ga.set_defaults(governance_cmd="analyze")
    p_gov.set_defaults(func=cmd_governance)

    p = sub.add_parser("perf", aliases=["performance"], parents=[common], help="performance baseline comparison from stress metrics")
    p.add_argument("--run-id", help="analyze stress_report from an existing pipeline run")
    p.add_argument("--profile", default="standard", choices=["smoke", "standard", "spike", "soak"])
    p.add_argument("--verdict", default="pass", choices=["pass", "warn", "fail"])
    p.add_argument("--p95", type=float, default=450.0)
    p.add_argument("--error-rate", type=float, default=0.1)
    p.add_argument("--rps", type=float, default=120.0)
    p.add_argument("--no-llm", action="store_true")
    p.set_defaults(func=cmd_perf)

    p_explain = sub.add_parser("explain", parents=[common], help="DevOps RAG explain (incidents, runs, artifacts)")
    p_explain.add_argument("subject", choices=["incident", "query"])
    p_explain.add_argument("rest", nargs=argparse.REMAINDER, help="incident id + optional context, or free-form query text")
    p_explain.add_argument("--run-id")
    p_explain.set_defaults(func=cmd_explain)

    p_fix = sub.add_parser("fix", parents=[common], help="resume/retry the latest blocked run (category or repo slug)")
    p_fix.add_argument("target", nargs="?", default="")
    p_fix.set_defaults(func=cmd_fix)

    p_intel = sub.add_parser("intelligence", aliases=["intel"], parents=[common], help="intelligence dashboard APIs")
    p_intel.add_argument("--view", choices=["dashboard", "fleet", "agents"], default="dashboard")
    p_intel.set_defaults(func=cmd_intelligence)

    p_runs = sub.add_parser("runs", parents=[common], help="inspect pipeline runs and artifacts")
    runs_sub = p_runs.add_subparsers(dest="runs_cmd", required=True)
    p_list = runs_sub.add_parser("list", help="list recent pipeline runs")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.set_defaults(func=cmd_runs)
    p_show = runs_sub.add_parser("show", help="show one pipeline run")
    p_show.add_argument("run_id")
    p_show.set_defaults(func=cmd_runs)
    p_art = runs_sub.add_parser("artifact", help="fetch one artifact JSON body")
    p_art.add_argument("run_id")
    p_art.add_argument("artifact_type")
    p_art.set_defaults(func=cmd_runs)

    sub.add_parser("health", parents=[common], help="GET /api/v1/pipeline/health").set_defaults(func=cmd_health)
    sub.add_parser("db-migrate", parents=[common], help="alembic upgrade head").set_defaults(func=cmd_db_migrate)
    sub.add_parser("workers", parents=[common], help="Celery worker status").set_defaults(func=cmd_workers)

    p_ap = sub.add_parser("autopilot", aliases=["ap"], parents=[common], help="policy-gated delivery and remediation autopilot")
    ap_sub = p_ap.add_subparsers(dest="autopilot_cmd", required=True)
    p_app = ap_sub.add_parser("policy", parents=[common], help="autopilot autonomy caps and action policy")
    p_app.add_argument("--repo")
    p_app.add_argument("--environment")
    p_app.set_defaults(autopilot_cmd="policy")
    ap_sub.add_parser("catalog", parents=[common], help="autopilot action catalog").set_defaults(autopilot_cmd="catalog")
    p_apl = ap_sub.add_parser("plan", parents=[common], help="planned actions for a pipeline run")
    p_apl.add_argument("--run-id", required=True)
    p_apl.add_argument("--environment")
    p_apl.set_defaults(autopilot_cmd="plan")
    p_aps = ap_sub.add_parser("status", parents=[common], help="autopilot readiness and simulate-only flag")
    p_aps.add_argument("--repo")
    p_aps.add_argument("--environment")
    p_aps.set_defaults(autopilot_cmd="status")
    p_apa = ap_sub.add_parser("analyze", parents=[common], help="full autopilot intelligence report")
    p_apa.add_argument("--run-id")
    p_apa.add_argument("--environment")
    p_apa.add_argument("--no-persist", action="store_true")
    p_apa.set_defaults(autopilot_cmd="analyze")
    p_ap.set_defaults(func=cmd_autopilot)

    p_ur = sub.add_parser(
        "unified-risk",
        aliases=["urisk", "ur"],
        parents=[common],
        help="fused change risk, gates, and intelligence rollup",
    )
    ur_sub = p_ur.add_subparsers(dest="unified_risk_cmd", required=True)
    p_urp = ur_sub.add_parser("policy", parents=[common], help="unified risk dimension weights and thresholds")
    p_urp.add_argument("--repo")
    p_urp.add_argument("--environment")
    p_urp.set_defaults(unified_risk_cmd="policy")
    p_urs = ur_sub.add_parser("score", parents=[common], help="unified risk score for a pipeline run")
    p_urs.add_argument("--run-id", required=True)
    p_urs.add_argument("--environment")
    p_urs.set_defaults(unified_risk_cmd="score")
    ur_sub.add_parser("status", parents=[common], help="unified risk engine configuration").set_defaults(
        unified_risk_cmd="status"
    )
    p_ura = ur_sub.add_parser("analyze", parents=[common], help="full unified risk intelligence report")
    p_ura.add_argument("--run-id")
    p_ura.add_argument("--environment")
    p_ura.add_argument("--no-persist", action="store_true")
    p_ura.set_defaults(unified_risk_cmd="analyze")
    p_ur.set_defaults(func=cmd_unified_risk)

    p_kg = sub.add_parser("knowledge", aliases=["graph", "kg"], parents=[common], help="unified knowledge graph and impact queries")
    kg_sub = p_kg.add_subparsers(dest="knowledge_cmd", required=True)
    p_kgp = kg_sub.add_parser("policy", parents=[common], help="knowledge graph policy and coverage thresholds")
    p_kgp.add_argument("--repo")
    p_kgp.set_defaults(knowledge_cmd="policy")
    p_kgg = kg_sub.add_parser("graph", parents=[common], help="build or query knowledge graph for a run")
    p_kgg.add_argument("--run-id")
    p_kgg.add_argument("--query", "-q", help="search nodes (e.g. auth, payment, redis)")
    p_kgg.set_defaults(knowledge_cmd="graph")
    p_kgs = kg_sub.add_parser("status", parents=[common], help="knowledge graph coverage snapshot")
    p_kgs.add_argument("--repo")
    p_kgs.set_defaults(knowledge_cmd="status")
    p_kga = kg_sub.add_parser("analyze", parents=[common], help="full knowledge graph intelligence report")
    p_kga.add_argument("--run-id")
    p_kga.add_argument("--query", "-q")
    p_kga.add_argument("--no-persist", action="store_true")
    p_kga.set_defaults(knowledge_cmd="analyze")
    p_kg.set_defaults(func=cmd_knowledge)

    p_dr = sub.add_parser("dr", parents=[common], help="disaster recovery policy, backups, and intelligence")
    dr_sub = p_dr.add_subparsers(dest="dr_cmd", required=True)
    p_drp = dr_sub.add_parser("policy", parents=[common], help="RTO/RPO targets and backup retention policy")
    p_drp.add_argument("--repo")
    p_drp.set_defaults(dr_cmd="policy")
    dr_sub.add_parser("backups", parents=[common], help="list on-disk database backups").set_defaults(dr_cmd="backups")
    p_drb = dr_sub.add_parser("backup", parents=[common], help="run database backup (pg_dump or SQLite copy)")
    p_drb.add_argument("--output-dir")
    p_drb.set_defaults(dr_cmd="backup")
    p_drs = dr_sub.add_parser("status", parents=[common], help="DR readiness and backup freshness")
    p_drs.add_argument("--repo")
    p_drs.set_defaults(dr_cmd="status")
    p_dra = dr_sub.add_parser("analyze", parents=[common], help="full DR intelligence report")
    p_dra.add_argument("--run-id")
    p_dra.add_argument("--no-persist", action="store_true")
    p_dra.set_defaults(dr_cmd="analyze")
    p_dr.set_defaults(func=cmd_dr)

    p_prod = sub.add_parser("production", aliases=["prod"], parents=[common], help="production hardening checklist and readiness")
    prod_sub = p_prod.add_subparsers(dest="production_cmd", required=True)
    prod_sub.add_parser("checklist", parents=[common], help="production hardening checklist").set_defaults(
        production_cmd="checklist"
    )
    prod_sub.add_parser("ready", parents=[common], help="runtime + hardening readiness gate").set_defaults(
        production_cmd="ready"
    )
    p_prod.set_defaults(func=cmd_production)

    p = sub.add_parser("backup-db", parents=[common], help="database backup (alias for orion dr backup)")
    p.add_argument("--output-dir")
    p.set_defaults(func=cmd_backup_db)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
