"""DevOps platform security scanners — shared bandit + pip-audit."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.security_scanners import (  # noqa: E402
    bandit_available,
    parse_pip_audit,
    pip_audit_available,
    run_bandit,
    run_pip_audit,
    run_security_scanners,
    split_requirements,
)

__all__ = [
    "bandit_available",
    "parse_pip_audit",
    "pip_audit_available",
    "run_bandit",
    "run_pip_audit",
    "run_security_scanners",
    "split_requirements",
]
