import asyncio
import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.pipeline_artifact import PipelineArtifact
from app.utils.auth_utils import get_effective_github_token
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class IssueBundle:
    category: str
    issues: list[dict[str, Any]]
    file_patches: list[dict[str, Any]]
    branch_name: str
    pr_title: str
    pr_body: str
    pr_number: int | None = None


class AutoPRService:
    def __init__(
        self,
        github_token: str | None,
        repo_full_name: str,
        clone_url: str,
        base_branch: str = "main",
    ) -> None:
        self.github_token = get_effective_github_token(github_token)
        self.repo_full_name = repo_full_name
        self.clone_url = clone_url
        self.base_branch = base_branch
        self._client = httpx.AsyncClient(
            timeout=120.0,
            headers={
                "Authorization": f"Bearer {self.github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        self.created_branches: list[str] = []

    async def close(self) -> None:
        await self._client.aclose()

    async def generate_fix_patches(
        self,
        issues: list[dict[str, Any]],
        repo_path: str,
        category: str,
        anthropic_client: AsyncAnthropic,
    ) -> list[dict[str, Any]]:
        patches: list[dict[str, Any]] = []
        paths: set[str] = set()
        for issue in issues:
            fp = issue.get("file") or issue.get("path") or issue.get("filename")
            if isinstance(fp, str) and fp:
                paths.add(fp)

        for rel in sorted(paths):
            try:
                full = Path(repo_path) / rel
                if not full.is_file():
                    continue
                content = full.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            system = (
                "You are an expert software engineer. Return ONLY valid JSON with keys "
                'file_path, fixed_content, explanation, changes_made (array of strings). '
                "Provide the complete fixed file content."
            )
            user = json.dumps(
                {
                    "category": category,
                    "relative_path": rel,
                    "current_content": content[:120000],
                    "issues": issues,
                }
            )
            data, _ = await self._call_claude_json(
                anthropic_client, system, user, max_tokens=4000
            )
            if isinstance(data, dict) and data.get("fixed_content"):
                patches.append(
                    {
                        "file_path": data.get("file_path", rel),
                        "fixed_content": data["fixed_content"],
                        "explanation": data.get("explanation", ""),
                        "changes_made": data.get("changes_made", []),
                    }
                )
        return patches

    async def _call_claude_json(
        self,
        client: AsyncAnthropic,
        system: str,
        user: str,
        max_tokens: int,
    ) -> tuple[dict[str, Any], int]:
        msg = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=max_tokens,
            system=system + "\nReturn ONLY valid JSON, no markdown, no backticks.",
            messages=[{"role": "user", "content": user}],
        )
        raw = ""
        for block in msg.content:
            if hasattr(block, "text"):
                raw += block.text
        raw = raw.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        try:
            return json.loads(raw), getattr(msg.usage, "output_tokens", 0) or 0
        except json.JSONDecodeError:
            return {"error": "invalid_json", "raw": raw}, 0

    async def _get_default_branch(self) -> str:
        r = await self._client.get(
            f"https://api.github.com/repos/{self.repo_full_name}"
        )
        r.raise_for_status()
        data = r.json()
        return data.get("default_branch") or self.base_branch

    async def create_branch_with_fixes(
        self, bundle: IssueBundle, run_id: UUID | str
    ) -> str:
        base = await self._get_default_branch()
        r = await self._client.get(
            f"https://api.github.com/repos/{self.repo_full_name}/git/ref/heads/{base}"
        )
        r.raise_for_status()
        sha = r.json()["object"]["sha"]
        branch_name = bundle.branch_name or f"orion-fix-{str(run_id)[:8]}-{bundle.category[:20]}"
        ref_path = f"refs/heads/{branch_name}"
        await self._client.post(
            f"https://api.github.com/repos/{self.repo_full_name}/git/refs",
            json={"ref": f"refs/heads/{branch_name}", "sha": sha},
        )
        self.created_branches.append(branch_name)

        for patch in bundle.file_patches:
            path = patch["file_path"].lstrip("/")
            content_b64 = base64.b64encode(
                patch["fixed_content"].encode("utf-8")
            ).decode("ascii")
            get_url = f"https://api.github.com/repos/{self.repo_full_name}/contents/{path}"
            gr = await self._client.get(get_url, params={"ref": branch_name})
            sha_file = None
            if gr.status_code == 200:
                sha_file = gr.json().get("sha")
            body: dict[str, Any] = {
                "message": f"ORION auto-fix: {bundle.category} ({path})",
                "content": content_b64,
                "branch": branch_name,
            }
            if sha_file:
                body["sha"] = sha_file
            pr = await self._client.put(get_url, json=body)
            pr.raise_for_status()
        return branch_name

    async def _build_pr_body(self, bundle: IssueBundle, run_id: UUID | str) -> str:
        rows = "| # | Title | Severity |\n|---|-------|----------|\n"
        for i, issue in enumerate(bundle.issues, start=1):
            title = str(issue.get("title") or issue.get("message") or "issue")[:120]
            sev = str(issue.get("severity") or issue.get("level") or "n/a")
            rows += f"| {i} | {title} | {sev} |\n"
        changes = "\n".join(
            f"- {p.get('file_path')}" for p in bundle.file_patches[:50]
        )
        return (
            f"## ORION automated remediation\n\n"
            f"**Run ID:** `{run_id}`  \n"
            f"**Category:** `{bundle.category}`\n\n"
            f"### Issues\n{rows}\n"
            f"### Patches applied\n{changes}\n\n"
            f"---\n*Generated by ORION AI CI/CD*"
        )

    async def create_pr(self, bundle: IssueBundle) -> int:
        base = await self._get_default_branch()
        body = await self._build_pr_body(bundle, "unknown")
        r = await self._client.post(
            f"https://api.github.com/repos/{self.repo_full_name}/pulls",
            json={
                "title": bundle.pr_title,
                "body": body,
                "head": bundle.branch_name,
                "base": base,
            },
        )
        r.raise_for_status()
        data = r.json()
        return int(data["number"])

    async def open_all_prs(
        self,
        combined_issues: dict[str, Any],
        repo_path: str,
        run_id: UUID | str,
        anthropic_client: AsyncAnthropic,
    ) -> list[IssueBundle]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for key in ("code_issues", "security_issues", "qa_issues"):
            chunk = combined_issues.get(key)
            if isinstance(chunk, dict):
                issues = chunk.get("issues") or chunk.get("findings") or []
            elif isinstance(chunk, list):
                issues = chunk
            else:
                issues = []
            if issues:
                groups[key] = list(issues)

        bundles: list[IssueBundle] = []
        for cat, issues in groups.items():
            patches = await self.generate_fix_patches(
                issues, repo_path, cat, anthropic_client
            )
            bundle = IssueBundle(
                category=cat,
                issues=issues,
                file_patches=patches,
                branch_name=f"orion-{cat}-{str(run_id)[:8]}",
                pr_title=f"ORION fix: {cat.replace('_', ' ')}",
                pr_body="",
            )
            bundles.append(bundle)

        for b in bundles:
            if b.file_patches:
                b.branch_name = await self.create_branch_with_fixes(b, run_id)

        async def _pr(b: IssueBundle) -> None:
            if not b.file_patches:
                return
            num = await self.create_pr(b)
            b.pr_number = num

        await asyncio.gather(*[_pr(b) for b in bundles])
        return bundles

    async def verify_permissions(self) -> bool:
        r = await self._client.get("https://api.github.com/")
        if r.status_code not in (200, 304):
            return False
        scopes_header = r.headers.get("X-OAuth-Scopes") or ""
        parts = [s.strip() for s in scopes_header.split(",") if s.strip()]
        return "repo" in parts

    async def save_pr_registry(
        self,
        db: AsyncSession,
        pipeline_run_id: UUID,
        bundles: list[IssueBundle],
    ) -> None:
        registry = {
            "bundles": [
                {
                    "category": b.category,
                    "branch": b.branch_name,
                    "pr_number": b.pr_number,
                    "issues_count": len(b.issues),
                }
                for b in bundles
            ]
        }
        art = PipelineArtifact(
            pipeline_run_id=pipeline_run_id,
            artifact_type="auto_pr_registry",
            content=registry,
            raw_output=None,
            agent_model=settings.anthropic_model,
        )
        db.add(art)
        await db.commit()
