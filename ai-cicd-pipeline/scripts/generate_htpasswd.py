#!/usr/bin/env python3
"""Write nginx/.htpasswd for Flower basic auth from FLOWER_BASIC_AUTH_USER / FLOWER_BASIC_AUTH_PASSWORD."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from passlib.hash import apr_md5_crypt

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = PROJECT_ROOT / "nginx" / ".htpasswd"


def build_line(user: str, password: str) -> str:
    return f"{user}:{apr_md5_crypt.hash(password)}\n"


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=os.getenv("FLOWER_BASIC_AUTH_USER", "admin"))
    parser.add_argument("--password", default=os.getenv("FLOWER_BASIC_AUTH_PASSWORD", "orion_admin"))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if ":" in args.user or not args.user:
        print("Invalid username", file=sys.stderr)
        return 1
    if not args.password:
        print("FLOWER_BASIC_AUTH_PASSWORD is empty", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build_line(args.user, args.password), encoding="utf-8")
    print(f"Wrote {args.out} for user '{args.user}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
