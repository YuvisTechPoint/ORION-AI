import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent


class SecurityAgent(BaseAgent):
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

    def _run_bandit(self) -> dict[str, Any]:
        try:
            p = subprocess.run(
                ["bandit", "-r", self.repo_path, "-f", "json", "-ll"],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            return json.loads(p.stdout) if p.stdout.strip() else {"results": []}
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            return {"results": []}

    def _run_safety(self, req_path: str) -> dict[str, Any]:
        try:
            p = subprocess.run(
                ["safety", "check", "-r", req_path, "--json"],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            return json.loads(p.stdout) if p.stdout.strip() else {}
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            return {}

    async def execute(self) -> dict[str, Any]:
        req = Path(self.repo_path) / "requirements.txt"

        def _scan() -> tuple[dict[str, Any], dict[str, Any]]:
            b = self._run_bandit()
            s = self._run_safety(str(req)) if req.is_file() else {}
            return b, s

        bandit, safety = await asyncio.to_thread(_scan)
        merged = {
            "bandit": bandit,
            "safety": safety,
            "diff_excerpt": self.diff_text[:8000],
        }
        user = json.dumps(merged)
        system = (
            "You are an application security engineer. Merge bandit and safety findings. "
            "Return JSON with keys highest_severity (low|medium|high|critical), security_score (0-100), "
            "high_critical_count (int), enriched_findings (list with type, severity, recommendation)."
        )
        out = await self._call_claude_json(system, user, max_tokens=2500)
        if "highest_severity" not in out:
            results = bandit.get("results", [])
            high = sum(
                1
                for r in results
                if isinstance(r, dict) and str(r.get("issue_severity", "")).lower() in ("high", "medium")
            )
            out = {
                "highest_severity": "medium" if high else "low",
                "security_score": max(0, 100 - high * 5),
                "high_critical_count": high,
                "enriched_findings": results[:50],
            }
        await self._save_artifact(
            "security_scan",
            out,
            raw_output=json.dumps(merged)[:50000],
            duration_seconds=self.elapsed_seconds,
        )
        return out
