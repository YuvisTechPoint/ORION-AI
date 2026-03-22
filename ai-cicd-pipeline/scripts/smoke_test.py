#!/usr/bin/env python3
"""Basic smoke checks for ORION API and dependencies."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import redis

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402


def main() -> int:
    ok = True
    try:
        r = httpx.get(
            f"http://127.0.0.1:{settings.app_port}/api/v1/pipeline/health", timeout=5.0
        )
        print("health", r.status_code, r.json())
        ok = ok and r.status_code == 200
    except Exception as exc:
        print("health failed", exc)
        ok = False

    try:
        r2 = redis.Redis.from_url(settings.redis_url)
        r2.ping()
        print("redis ping ok")
    except Exception as exc:
        print("redis failed", exc)
        ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
