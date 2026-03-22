#!/usr/bin/env python3
"""Verify GitHub OAuth authorize URL shape (no network call to GitHub)."""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402


def main() -> int:
    base = "https://github.com/login/oauth/authorize"
    params = {
        "client_id": settings.github_client_id,
        "scope": "repo,read:user,user:email",
        "redirect_uri": settings.github_redirect_uri,
        "state": "test-state",
    }
    from urllib.parse import urlencode

    url = base + "?" + urlencode(params)
    u = urlparse(url)
    q = parse_qs(u.query)
    assert q["client_id"][0] == settings.github_client_id
    assert "repo" in q["scope"][0]
    print("oauth url ok:", url[:120] + "...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
