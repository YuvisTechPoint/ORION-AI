#!/usr/bin/env python3
"""Copy real GitHub OAuth credentials into stack .env.production files.

Reads GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET from the first valid source:
  .env, ai-cicd-pipeline/.env, backend/.env

Updates redirect URIs per stack. Does not rotate other production secrets.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

OAUTH_KEYS = ("GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET")
PLACEHOLDER_MARKERS = ("your-oauth", "replace_oauth", "changeme")


def _load_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _valid_oauth(env: dict[str, str]) -> tuple[str, str] | None:
    cid = (env.get("GITHUB_CLIENT_ID") or "").strip()
    csec = (env.get("GITHUB_CLIENT_SECRET") or "").strip()
    if not cid or not csec:
        return None
    low = cid.lower()
    if any(m in low for m in PLACEHOLDER_MARKERS):
        return None
    if re.fullmatch(r"Ov[0-9a-f]{16}", cid):
        return None
    return cid, csec


def find_oauth_credentials() -> tuple[str, str] | None:
    sources = [
        ROOT / ".env",
        ROOT / "ai-cicd-pipeline" / ".env",
        ROOT / "backend" / ".env",
    ]
    for path in sources:
        creds = _valid_oauth(_load_env(path))
        if creds:
            return creds
    return None


def _patch_file(path: Path, updates: dict[str, str]) -> bool:
    if not path.is_file():
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync GitHub OAuth into .env.production files")
    parser.add_argument("--host", default="127.0.0.1", help="OAuth callback host")
    args = parser.parse_args()

    creds = find_oauth_credentials()
    if not creds:
        print(
            json_msg(
                {
                    "ok": False,
                    "error": "No valid GITHUB_CLIENT_ID/SECRET in .env or stack .env files",
                }
            )
        )
        return 1

    client_id, client_secret = creds
    host = args.host
    oauth_host = "localhost" if host in {"127.0.0.1", "localhost"} else host
    targets = {
        ROOT / "ai-cicd-pipeline" / ".env.production": {
            "GITHUB_CLIENT_ID": client_id,
            "GITHUB_CLIENT_SECRET": client_secret,
            "GITHUB_REDIRECT_URI": f"http://{oauth_host}:8001/api/v1/auth/github/callback",
            "FRONTEND_URL": f"http://{oauth_host}:8001/ui/",
        },
        ROOT / "backend" / ".env.production": {
            "GITHUB_CLIENT_ID": client_id,
            "GITHUB_CLIENT_SECRET": client_secret,
            "GITHUB_REDIRECT_URI": f"http://{oauth_host}:8000/api/v1/auth/github/callback",
            "FRONTEND_URL": f"http://{oauth_host}:5173",
        },
    }

    patched: list[str] = []
    for path, updates in targets.items():
        if _patch_file(path, updates):
            patched.append(str(path.relative_to(ROOT)))

    print(json_msg({"ok": True, "client_id": client_id, "patched": patched}))
    return 0


def json_msg(data: dict) -> str:
    import json

    return json.dumps(data, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
