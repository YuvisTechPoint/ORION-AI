"""DevOps security scanner integration tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.utils.security_scanners import run_security_scanners


def test_run_security_scanners_on_clean_repo():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "main.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
        (root / "requirements.txt").write_text("requests==2.31.0\n", encoding="utf-8")
        report = run_security_scanners(str(root))
    assert "issues" in report
    assert "highest_severity" in report
    assert isinstance(report.get("scanners"), dict)
