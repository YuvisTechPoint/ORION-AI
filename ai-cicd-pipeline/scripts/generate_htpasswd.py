#!/usr/bin/env python3
"""Generate nginx htpasswd lines for Flower basic auth."""

from __future__ import annotations

import argparse
from pathlib import Path

from passlib.apache import HtpasswdFile


def main() -> None:
    p = argparse.ArgumentParser(description="Generate nginx htpasswd file")
    p.add_argument("--user", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()

    ht = HtpasswdFile(str(args.out), new=True, default_scheme="apr_md5")
    ht.set_password(args.user, args.password)
    ht.save()
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
