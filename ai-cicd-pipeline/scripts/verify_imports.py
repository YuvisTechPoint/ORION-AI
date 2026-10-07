#!/usr/bin/env python3
"""Import every module under app/ and report failures (run: python scripts/verify_imports.py)."""

from __future__ import annotations

import importlib
import pkgutil
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def iter_modules() -> list[str]:
    import app

    names = ["app"]
    for info in pkgutil.walk_packages(app.__path__, prefix="app."):
        names.append(info.name)
    return sorted(names)


def main() -> int:
    failures: list[tuple[str, str]] = []
    modules = iter_modules()
    for name in modules:
        try:
            importlib.import_module(name)
            print(f"OK    {name}")
        except Exception as exc:  # noqa: BLE001 - report every broken module, not just the first
            print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
            failures.append((name, traceback.format_exc()))

    print(f"\n{len(modules) - len(failures)}/{len(modules)} modules imported successfully")
    for name, tb in failures:
        print(f"\n--- {name} ---\n{tb}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
