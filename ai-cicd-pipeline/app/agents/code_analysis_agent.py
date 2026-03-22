import ast
import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.services.git_service import GitService


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
        self.diff_text = diff_text

    def _run_pylint(self, file_path: str) -> list[dict[str, Any]]:
        try:
            p = subprocess.run(
                ["pylint", "--output-format=json", file_path],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            return json.loads(p.stdout) if p.stdout.strip() else []
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            return []

    def _ast_scan(self, file_path: str) -> dict[str, Any]:
        try:
            src = Path(file_path).read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except SyntaxError:
            return {"unused_imports": 0, "undocumented_functions": 0}
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    imports.add(n.asname or n.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for n in node.names:
                        imports.add(n.asname or n.name)
        used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used.add(node.id)
        unused = len([i for i in imports if i and i not in used])
        undoc = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not ast.get_docstring(node):
                    undoc += 1
        return {"unused_imports": unused, "undocumented_functions": undoc}

    async def execute(self) -> dict[str, Any]:
        repo = Path(self.repo_path)
        gs = GitService()
        changed = await gs.get_changed_files(self.repo_path)
        py_files = []
        for rel in changed:
            if rel.endswith(".py"):
                p = repo / rel
                if p.is_file():
                    py_files.append(p)
        if not py_files:
            py_files = [p for p in repo.rglob("*.py") if p.is_file()][:20]
        if not py_files:
            result = {
                "severity": "pass",
                "issues": [],
                "critical_issues_count": 0,
                "warnings_count": 0,
                "summary": "No Python files to analyze.",
            }
            await self._save_artifact(
                "code_analysis",
                result,
                duration_seconds=self.elapsed_seconds,
            )
            return result

        pylint_results: list[dict[str, Any]] = []
        ast_stats: list[dict[str, Any]] = []

        def _analyze_file(fp: str) -> None:
            pylint_results.extend(self._run_pylint(fp))
            ast_stats.append({"file": fp, **self._ast_scan(fp)})

        await asyncio.to_thread(
            lambda: [_analyze_file(str(p)) for p in py_files[:50]]
        )

        diff_trunc = self.diff_text[:8000]
        user = json.dumps(
            {
                "pylint": pylint_results[:400],
                "ast_stats": ast_stats,
                "diff_truncated": diff_trunc,
            }
        )
        system = (
            "You are a senior Python reviewer. Analyze pylint output and AST hints. "
            "Return JSON with keys severity (pass|warn|fail), issues (list of objects), "
            "critical_issues_count, warnings_count, summary."
        )
        out = await self._call_claude_json(system, user, max_tokens=2000)
        if "severity" not in out:
            out = {
                "severity": "warn" if pylint_results else "pass",
                "issues": pylint_results[:50],
                "critical_issues_count": sum(
                    1 for e in pylint_results if isinstance(e, dict) and e.get("type") == "error"
                ),
                "warnings_count": len(pylint_results),
                "summary": "Heuristic analysis; Claude enrichment unavailable.",
            }
        await self._save_artifact(
            "code_analysis",
            out,
            raw_output=json.dumps(pylint_results[:200]),
            duration_seconds=self.elapsed_seconds,
        )
        return out
