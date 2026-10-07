#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

from passlib.hash import apr_md5_crypt


def main() -> None:
    username = os.getenv("FLOWER_BASIC_AUTH_USER", "").strip()
    password = os.getenv("FLOWER_BASIC_AUTH_PASSWORD", "").strip()

    if not username or not password:
        raise SystemExit("FLOWER_BASIC_AUTH_USER and FLOWER_BASIC_AUTH_PASSWORD must be set")

    project_root = Path(__file__).resolve().parents[1]
    out_path = project_root / "nginx" / ".htpasswd"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    hashed = apr_md5_crypt.hash(password)
    out_path.write_text(f"{username}:{hashed}\n", encoding="utf-8")
    print(f"Wrote htpasswd for user '{username}' to {out_path}")


if __name__ == "__main__":
    main()
