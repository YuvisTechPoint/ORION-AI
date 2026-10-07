import os
import sys
from pathlib import Path

# Run analysis tools through ORION's own interpreter: systemd units and `python -m uvicorn` do not
# put the virtualenv's bin/Scripts directory on PATH, so bare `pylint`/`pytest` would not resolve.
_MODULES = {
    "pylint": "pylint",
    "bandit": "bandit",
    "pip-audit": "pip_audit",
    "pytest": "pytest",
    "locust": "locust",
}


def tool_cmd(name: str, *args: str) -> list[str]:
    return [sys.executable, "-m", _MODULES[name], *args]


def tool_env() -> dict[str, str]:
    """Child tools must emit UTF-8: on Windows they otherwise write in the console code page."""
    return {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def repo_env(repo_path: str) -> dict[str, str]:
    """Environment that lets tools import the repository's own packages (flat and src/ layouts).

    pylint strips the working directory from sys.path, so without this every first-party import
    in a test or sub-package is reported as E0401.
    """
    repo = Path(repo_path).resolve()
    roots = [str(repo)]
    if (repo / "src").is_dir():
        roots.append(str(repo / "src"))
    existing = os.environ.get("PYTHONPATH")
    if existing:
        roots.append(existing)
    return {**tool_env(), "PYTHONPATH": os.pathsep.join(roots)}
