import asyncio
import json
import os
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
from app.utils.external_scanners import run_semgrep
from app.utils.severity import max_severity, severity_rank
from app.utils.tools import tool_cmd, tool_env

SYSTEM_PROMPT = """You are a security engineer reviewing code vulnerabilities.
Analyze bandit, semgrep (when present), and dependency vulnerabilities. Return ONLY valid JSON:
{
  "vulnerabilities": [{"type": string, "severity": "low"|"medium"|"high"|"critical", "file": string, "line": int, "description": string, "recommendation": string, "cve": string|null}],
  "highest_severity": "none"|"low"|"medium"|"high"|"critical",
  "security_score": int (0-100, 100=perfect),
  "summary": string,
  "immediate_actions": [string],
  "total_count": int,
  "high_critical_count": int
}
severity mapping: bandit HIGH=high, MEDIUM=medium, LOW=low. dependency (pip-audit) findings default to high.
Return ONLY valid JSON."""

_PINNED_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[^\]]*\])?\s*==\s*[^\s;,=]+\s*(;.*)?$")


def split_requirements(text: str) -> tuple[list[str], list[str]]:
    """(exact pins pip-audit can check offline-from-pip, everything else that cannot be audited)."""
    pinned: list[str] = []
    unpinned: list[str] = []
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-"):
            unpinned.append(line)
        elif _PINNED_RE.match(line):
            pinned.append(line)
        else:
            unpinned.append(line)
    return pinned, unpinned


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
        self.diff_text = diff_text or ""
        self.agent_model = settings.security_model

    def _rel(self, path: str) -> str:
        try:
            return os.path.relpath(path, self.repo_path).replace("\\", "/")
        except ValueError:
            return path.replace("\\", "/")

    def _run_bandit(self) -> tuple[list[dict[str, Any]], str, str | None]:
        """(findings, raw output, error) — error is set when bandit itself did not run."""
        try:
            p = subprocess.run(
                tool_cmd("bandit", "-r", self.repo_path, "-f", "json", "-ll"),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=tool_env(),
                timeout=120,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            self.logger.warning("bandit failed: %s", exc)
            return [], "", f"bandit could not run: {exc}"
        # bandit exits 1 when it finds issues; the JSON is still valid.
        raw = p.stdout or ""
        try:
            data = json.loads(raw) if raw.strip() else None
        except json.JSONDecodeError:
            data = None
        if not isinstance(data, dict):
            tail = (p.stderr or raw).strip()[-300:]
            self.logger.warning("bandit produced no report (exit %s): %s", p.returncode, tail)
            return [], raw + (p.stderr or ""), f"bandit failed (exit {p.returncode}): {tail}"
        findings = []
        for r in data.get("results", []):
            findings.append(
                {
                    "filename": self._rel(str(r.get("filename", ""))),
                    "test_id": r.get("test_id"),
                    "test_name": r.get("test_name"),
                    "issue_severity": str(r.get("issue_severity", "LOW")).upper(),
                    "issue_confidence": r.get("issue_confidence"),
                    "issue_text": r.get("issue_text", ""),
                    "line_number": int(r.get("line_number") or 0),
                    "cwe": (r.get("issue_cwe") or {}).get("id"),
                }
            )
        return findings, raw, None

    @staticmethod
    def parse_pip_audit(raw: str) -> list[dict[str, Any]] | None:
        try:
            data = json.loads(raw) if raw.strip() else None
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict) or not isinstance(data.get("dependencies"), list):
            return None
        findings: list[dict[str, Any]] = []
        for dep in data["dependencies"]:
            seen: set[str] = set()
            for vuln in dep.get("vulns") or []:
                vid = str(vuln.get("id") or "")
                if not vid or vid in seen:
                    continue
                seen.add(vid)
                aliases = vuln.get("aliases") or []
                findings.append(
                    {
                        "package": dep.get("name"),
                        "installed_version": dep.get("version"),
                        "vulnerability_id": next((a for a in aliases if a.startswith("CVE-")), vid),
                        "fix_versions": vuln.get("fix_versions") or [],
                        "description": str(vuln.get("description") or "")[:200],
                    }
                )
        return findings

    def _run_dependency_audit(self, req_path: Path) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
        """Audit exact pins with pip-audit (PyPI/OSV advisories; no account, no environment install)."""
        if not req_path.is_file():
            return [], "", {"tool": "pip-audit", "status": "skipped", "reason": "no requirements.txt"}
        pinned, unpinned = split_requirements(req_path.read_text(encoding="utf-8", errors="replace"))
        status: dict[str, Any] = {"tool": "pip-audit", "audited": len(pinned), "not_audited": unpinned[:50]}
        if not pinned:
            return [], "", {**status, "status": "skipped", "reason": "no exactly pinned (==) requirements"}

        pinned_file = GitService().reports_dir(self.pipeline_run_id) / "requirements.pinned.txt"
        pinned_file.write_text("\n".join(pinned) + "\n", encoding="utf-8")
        try:
            p = subprocess.run(
                tool_cmd(
                    "pip-audit", "-r", str(pinned_file), "-f", "json",
                    "--no-deps", "--disable-pip", "--progress-spinner", "off",
                ),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=tool_env(),
                timeout=180,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            self.logger.warning("pip-audit failed: %s", exc)
            return [], "", {**status, "status": "failed", "reason": f"pip-audit could not run: {exc}"}
        raw = p.stdout or ""
        findings = self.parse_pip_audit(raw)
        if findings is None:
            tail = (p.stderr or raw).strip()[-300:]
            self.logger.warning("pip-audit produced no report (exit %s): %s", p.returncode, tail)
            return [], raw + (p.stderr or ""), {**status, "status": "failed", "reason": tail}
        return findings, raw, {**status, "status": "ok"}

    @staticmethod
    def _heuristic(
        bandit: list[dict[str, Any]],
        dependencies: list[dict[str, Any]],
        semgrep: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        vulns: list[dict[str, Any]] = []
        for b in bandit:
            vulns.append(
                {
                    "type": b.get("test_name") or b.get("test_id") or "bandit",
                    "severity": str(b.get("issue_severity", "LOW")).lower(),
                    "file": b.get("filename", ""),
                    "line": b.get("line_number", 0),
                    "description": b.get("issue_text", ""),
                    "recommendation": f"Review bandit rule {b.get('test_id')} and remediate.",
                    "cve": None,
                }
            )
        for s in semgrep or []:
            vulns.append(
                {
                    "type": s.get("check_id") or "semgrep",
                    "severity": str(s.get("severity") or "medium").lower(),
                    "file": s.get("file", ""),
                    "line": s.get("line", 0),
                    "description": s.get("message", ""),
                    "recommendation": f"Fix Semgrep rule {s.get('check_id')}.",
                    "cve": None,
                }
            )
        for s in dependencies:
            fixes = s.get("fix_versions") or []
            vulns.append(
                {
                    "type": "vulnerable_dependency",
                    "severity": "high",
                    "file": "requirements.txt",
                    "line": 0,
                    "description": f"{s.get('package')} {s.get('installed_version')}: {s.get('description')}",
                    "recommendation": (
                        f"Upgrade {s.get('package')} to {fixes[-1]} or later."
                        if fixes
                        else f"Upgrade {s.get('package')} to a patched version."
                    ),
                    "cve": s.get("vulnerability_id"),
                }
            )
        weights = {"critical": 25, "high": 15, "medium": 5, "low": 1}
        highest = max_severity(*(v["severity"] for v in vulns))
        high_critical = sum(1 for v in vulns if severity_rank(v["severity"]) >= 2)
        return {
            "vulnerabilities": vulns[:100],
            "highest_severity": highest,
            "security_score": max(0, 100 - sum(weights.get(v["severity"], 0) for v in vulns)),
            "summary": f"{len(vulns)} findings ({high_critical} high/critical) from bandit, semgrep, and pip-audit (heuristic mode).",
            "immediate_actions": [v["recommendation"] for v in vulns if severity_rank(v["severity"]) >= 2][:10],
            "total_count": len(vulns),
            "high_critical_count": high_critical,
            "analysis_mode": "heuristic",
        }

    async def execute(self) -> dict[str, Any]:
        req = Path(self.repo_path) / "requirements.txt"

        def _scan() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], str, dict[str, Any]]:
            bandit, bandit_raw, bandit_error = self._run_bandit()
            deps, deps_raw, deps_status = self._run_dependency_audit(req)
            semgrep_findings, semgrep_status = run_semgrep(self.repo_path)
            scanners = {
                "bandit": {"status": "failed", "reason": bandit_error} if bandit_error else {"status": "ok"},
                "dependencies": deps_status,
                "semgrep": semgrep_status,
            }
            return bandit, deps, semgrep_findings, f"BANDIT:\n{bandit_raw}\n\nPIP-AUDIT:\n{deps_raw}", scanners

        bandit_findings, dep_findings, semgrep_findings, raw, scanners = await asyncio.to_thread(_scan)
        fallback = self._heuristic(bandit_findings, dep_findings, semgrep_findings)

        user_message = (
            f"BANDIT FINDINGS:\n{json.dumps(bandit_findings[:30])}\n\n"
            f"SEMGREP FINDINGS:\n{json.dumps(semgrep_findings[:30])}\n\n"
            f"DEPENDENCY VULNERABILITIES (pip-audit):\n{json.dumps(dep_findings[:20])}\n\n"
            f"DIFF CONTEXT:\n{self.diff_text[:3000]}"
        )
        result = await self._call_claude_json(SYSTEM_PROMPT, user_message, max_tokens=2500)
        if LLM_ERROR_KEY in result or "highest_severity" not in result:
            result = fallback
        else:
            for key, value in fallback.items():
                result.setdefault(key, value)
            # Never let the model downgrade what the scanners actually found.
            result["highest_severity"] = max_severity(
                result.get("highest_severity"), fallback["highest_severity"]
            )
            result["analysis_mode"] = "llm"

        result["scanners"] = scanners
        failed = [name for name, s in scanners.items() if s.get("status") == "failed"]
        if failed:
            # A scanner that crashed must not read as a clean bill of health.
            result["summary"] = f"{result.get('summary', '')} Scanner(s) failed: {', '.join(failed)}.".strip()

        await self._save_artifact(
            "security_scan",
            result,
            raw_output=raw[:50000],
            duration_seconds=self.elapsed_seconds,
        )
        return result
