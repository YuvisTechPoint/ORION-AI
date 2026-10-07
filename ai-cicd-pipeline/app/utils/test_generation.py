"""Heuristic AI test case suggestions for changed Python functions."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

_CASE_TEMPLATES = (
    "normal case",
    "zero case",
    "negative case",
    "boundary case",
    "null/None case",
    "exception case",
)


def _functions_in_file(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            names.append(node.name)
    return names[:20]


def suggest_tests_for_changes(changed_files: list[str], repo_path: str) -> dict[str, Any]:
    root = Path(repo_path)
    suggestions: list[dict[str, Any]] = []

    for rel in changed_files:
        if not rel.endswith(".py") or rel.startswith("tests/"):
            continue
        path = root / rel.replace("\\", "/")
        if not path.is_file():
            continue
        funcs = _functions_in_file(path)
        for fn in funcs:
            suggestions.append(
                {
                    "file": rel,
                    "function": fn,
                    "suggested_cases": list(_CASE_TEMPLATES),
                    "recommended_test_file": f"tests/test_{Path(rel).stem}.py",
                }
            )

    return {
        "functions_analyzed": len(suggestions),
        "suggestions": suggestions[:30],
        "summary": f"Generated test suggestions for {len(suggestions)} function(s).",
        "analysis_mode": "heuristic",
    }
