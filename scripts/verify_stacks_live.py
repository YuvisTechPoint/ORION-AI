#!/usr/bin/env python3
"""Live health/readiness probe for stacks defined in config/stacks.json."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 5


def _get_json(url: str) -> tuple[int, dict | None]:
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
            data = json.loads(body) if body.strip() else {}
        except Exception:  # noqa: BLE001
            data = None
        return exc.code, data
    except Exception:  # noqa: BLE001
        return 0, None


def _healthy(status: int, body: dict | None) -> bool:
    if status != 200 or not isinstance(body, dict):
        return False
    if body.get("status") in {"ok", "healthy"}:
        return True
    if body.get("api") == "ok":
        return True
    if body.get("ready") is True:
        return True
    return False


def main() -> int:
    catalog_path = ROOT / "config" / "stacks.json"
    if not catalog_path.is_file():
        print("missing config/stacks.json", file=sys.stderr)
        return 1
    stacks = json.loads(catalog_path.read_text(encoding="utf-8")).get("stacks") or []
    problems: list[str] = []
    checked = 0
    for stack in stacks:
        sid = stack.get("id") or "?"
        for label, key in (("health", "health"), ("ready", "ready")):
            url = stack.get(key)
            if not url:
                continue
            checked += 1
            status, body = _get_json(url)
            if not _healthy(status, body):
                problems.append(f"{sid} {label} {url} -> http={status} body={body!r}")

    hub_cp = "http://127.0.0.1:5180/api/v1/control-plane/health"
    checked += 1
    status, body = _get_json(hub_cp)
    if status != 200 or not isinstance(body, dict) or not body.get("stacks"):
        problems.append(f"hub control-plane health {hub_cp} -> http={status}")

    if problems:
        print("Live stack verification FAILED (is .\\run_all_stacks.ps1 running?):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"Live stack verification OK ({checked} probes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
