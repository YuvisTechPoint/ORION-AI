import ast
import asyncio
import builtins
import json
import re
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import LLM_ERROR_KEY, BaseAgent
from app.config import settings
from app.services.git_service import GitService
from app.utils.tools import repo_env, tool_cmd
from app.utils.text_analysis import diff_stats, files_in_diff
_PYLINT_TYPE_MAP = {
    "fatal": "error",
    "error": "error",
    "warning": "warning",
    "refactor": "convention",
    "convention": "convention",
    "info": "info",
}

SYSTEM_PROMPT = """You are a senior software engineer performing a code review.
Analyze the provided code diff and lint results. Return ONLY valid JSON in this exact schema:
{
  "issues": [{"file": string, "line": int, "type": "error"|"warning"|"convention"|"info", "description": string, "suggestion": string}],
  "severity": "pass"|"warn"|"fail",
  "summary": string (2-3 sentences),
  "good_practices_found": [string],
  "critical_issues_count": int,
  "warnings_count": int
}
severity rules: "fail" if any fatal/error type AND critical_issues_count >= 3. "warn" if warnings_count >= 5. Otherwise "pass". Return ONLY valid JSON."""

MAX_FILES = 20
WHOLE_REPO_PYLINT_ARGS = (
    "--recursive=y",
    "--ignore=.git,.venv,venv,env,node_modules,build,dist,.tox,.eggs,site-packages,migrations",
)


class CodeAnalysisAgent(BaseAgent):
    def __init__(
        self,
        pipeline_run_id: UUID,
        db: AsyncSession,
        anthropic_client: AsyncAnthropic,
        repo_path: str,
        diff_text: str,
    ) -> None:
        super().__init__(pipeline_run_id, db, anthropic_client)
        self.repo_path = repo_path
        self.diff_text = diff_text or ""
        self.agent_model = settings.code_analysis_model

    def _run_pylint(
        self, target: str, timeout: int = 30, extra: tuple[str, ...] = ()
    ) -> tuple[list[dict[str, Any]], str]:
        try:
            p = subprocess.run(
                tool_cmd("pylint", "--output-format=json", "--disable=C0111,W0611", *extra, target),
                capture_output=True,
                encoding="utf-8", errors="replace",
                timeout=timeout,
                check=False,
                cwd=self.repo_path,
                env=repo_env(self.repo_path),
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            self.logger.warning("pylint failed on %s: %s", target, exc)
            return [], ""
        raw = p.stdout or ""
        try:
            data = json.loads(raw) if raw.strip() else []
        except json.JSONDecodeError:
            return [], raw
        issues = []
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue
            issues.append(
                {
                    "file": str(item.get("path") or item.get("module") or target).replace("\\", "/"),
                    "line": int(item.get("line") or 0),
                    "column": int(item.get("column") or 0),
                    "message_id": item.get("message-id") or item.get("symbol"),
                    "message": item.get("message", ""),
                    "type": item.get("type", "warning"),
                }
            )
        return issues, raw

    def _ast_scan(self, rel_path: str) -> list[dict[str, Any]]:
        full = Path(self.repo_path) / rel_path
        try:
            tree = ast.parse(full.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, OSError) as exc:
            return [
                {
                    "file": rel_path,
                    "line": getattr(exc, "lineno", 0) or 0,
                    "type": "error",
                    "kind": "syntax_error",
                    "description": str(exc),
                }
            ]

        issues: list[dict[str, Any]] = []
        defined: set[str] = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}
        imported: dict[str, int] = {}
        loaded: dict[str, int] = {}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    imported[name] = node.lineno
                    defined.add(name)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    name = alias.asname or alias.name
                    imported[name] = node.lineno
                    defined.add(name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(node.name)
                if not isinstance(node, ast.ClassDef):
                    for arg in [*node.args.args, *node.args.kwonlyargs, *node.args.posonlyargs]:
                        defined.add(arg.arg)
                    if node.args.vararg:
                        defined.add(node.args.vararg.arg)
                    if node.args.kwarg:
                        defined.add(node.args.kwarg.arg)
                    if not ast.get_docstring(node):
                        issues.append(
                            {
                                "file": rel_path,
                                "line": node.lineno,
                                "type": "convention",
                                "kind": "missing_docstring",
                                "description": f"Function '{node.name}' has no docstring",
                            }
                        )
            elif isinstance(node, ast.Name):
                if isinstance(node.ctx, (ast.Store, ast.Del)):
                    defined.add(node.id)
                else:
                    loaded.setdefault(node.id, node.lineno)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                defined.add(node.name)
            elif isinstance(node, ast.arg):
                defined.add(node.arg)
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                defined.update(node.names)

        attr_roots = {
            n.value.id for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
        }
        for name, line in imported.items():
            if name != "*" and name not in loaded and name not in attr_roots:
                issues.append(
                    {
                        "file": rel_path,
                        "line": line,
                        "type": "warning",
                        "kind": "unused_import",
                        "description": f"Import '{name}' is unused",
                    }
                )
        for name, line in loaded.items():
            if name not in defined:
                issues.append(
                    {
                        "file": rel_path,
                        "line": line,
                        "type": "error",
                        "kind": "undefined_name",
                        "description": f"Name '{name}' may be undefined",
                    }
                )
        return issues

    async def _target_files(self) -> list[str]:
        repo = Path(self.repo_path)
        candidates = set(files_in_diff(self.diff_text))
        try:
            candidates.update(await GitService().get_changed_files(self.repo_path))
        except Exception as exc:
            self.logger.debug("changed-files lookup failed: %s", exc)
        changed = sorted(f for f in candidates if f.endswith(".py") and (repo / f).is_file())
        return changed[:MAX_FILES]

    @staticmethod
    def _heuristic(pylint_issues: list[dict[str, Any]], ast_issues: list[dict[str, Any]]) -> dict[str, Any]:
        issues = []
        for item in pylint_issues:
            issues.append(
                {
                    "file": item["file"],
                    "line": item["line"],
                    "type": _PYLINT_TYPE_MAP.get(str(item.get("type")), "warning"),
                    "description": f"{item.get('message_id')}: {item.get('message')}",
                    "suggestion": "Address the pylint finding.",
                }
            )
        for item in ast_issues:
            issues.append(
                {
                    "file": item["file"],
                    "line": item["line"],
                    "type": item["type"],
                    "description": item["description"],
                    "suggestion": "Fix the static-analysis finding.",
                }
            )
        critical = sum(1 for i in issues if i["type"] == "error")
        warnings = sum(1 for i in issues if i["type"] == "warning")
        if critical >= 3:
            severity = "fail"
        elif warnings >= 5 or critical:
            severity = "warn"
        else:
            severity = "pass"
        return {
            "issues": issues[:100],
            "severity": severity,
            "summary": f"Static analysis found {critical} errors and {warnings} warnings (heuristic mode).",
            "good_practices_found": [],
            "critical_issues_count": critical,
            "warnings_count": warnings,
            "analysis_mode": "heuristic",
        }

    async def execute(self) -> dict[str, Any]:
        files = await self._target_files()

        def _analyze() -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
            pylint_issues: list[dict[str, Any]] = []
            ast_issues: list[dict[str, Any]] = []
            raw_parts: list[str] = []
            for rel in files:
                found, raw = self._run_pylint(rel)
                pylint_issues.extend(found)
                raw_parts.append(raw)
                ast_issues.extend(self._ast_scan(rel))
            if not files:
                # A repo root is not a package: plain `pylint .` fails with F0010 instead of linting.
                found, raw = self._run_pylint(".", timeout=120, extra=WHOLE_REPO_PYLINT_ARGS)
                pylint_issues.extend(found)
                raw_parts.append(raw)
            return pylint_issues, ast_issues, "\n".join(p for p in raw_parts if p)

        pylint_issues, ast_issues, raw_pylint = await asyncio.to_thread(_analyze)

        fallback = self._heuristic(pylint_issues, ast_issues)
        user_message = (
            f"DIFF STATS:\n{json.dumps(diff_stats(self.diff_text))}\n\n"
            f"DIFF:\n{self._prepare_llm_text(self.diff_text, 8000)}\n\n"
            f"PYLINT ISSUES:\n{json.dumps(pylint_issues[:50])[:2500]}\n\n"
            f"AST ISSUES:\n{json.dumps(ast_issues[:20])[:1000]}"
        )
        result = await self._call_claude_json(SYSTEM_PROMPT, user_message, max_tokens=2000)
        if LLM_ERROR_KEY in result or "severity" not in result:
            result = fallback
        else:
            for key, value in fallback.items():
                result.setdefault(key, value)
            result["analysis_mode"] = "llm"
        result["files_analyzed"] = files
        result["diff_stats"] = diff_stats(self.diff_text)

        await self._save_artifact(
            "code_analysis",
            result,
            raw_output=raw_pylint[:50000] or None,
            duration_seconds=self.elapsed_seconds,
        )
        return result
