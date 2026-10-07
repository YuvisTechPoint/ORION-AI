import asyncio
import base64
import inspect
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.pipeline_artifact import PipelineArtifact
from app.utils.agent_sandbox import AgentSandbox
from app.utils.patch_confidence import compute_patch_confidence
from app.services.git_service import GitService
from app.utils.auth_utils import get_effective_github_token
from app.utils.json_utils import extract_json
from app.utils.logger import get_logger
from app.utils.severity import severity_rank

logger = get_logger("auto_pr_service")

FIX_SYSTEM_PROMPT = (
    "You are an expert software engineer. You will receive a source file and a list of issues found "
    "in it. Your job is to return a corrected version of the entire file that resolves all listed "
    "issues. Do not add placeholder comments or TODOs — make real, working fixes. Return ONLY valid "
    'JSON in this exact schema: `{"file_path": string, "fixed_content": string (the complete '
    'corrected file), "explanation": string (what was changed and why), "changes_made": [string]}`. '
    "The fixed_content must be the complete file, not a diff or snippet. Return ONLY valid JSON."
)
FIX_FAILED_EXPLANATION = "AI fix generation failed, manual review required"

CATEGORY_TITLES = {
    "security": "Resolve security vulnerabilities",
    "code-quality": "Resolve code quality issues",
    "test-failures": "Fix failing tests",
    "dockerfile": "Harden and fix Dockerfile",
}


@dataclass
class IssueBundle:
    category: str
    issues: list[dict[str, Any]]
    file_patches: list[dict[str, Any]]
    branch_name: str
    pr_title: str
    pr_body: str
    pr_number: int | None = None
    pr_url: str | None = None
    error: str | None = None
    changed_patches: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.changed_patches:
            self.changed_patches = [p for p in self.file_patches if not p.get("unchanged")]


def _issue_file(issue: dict[str, Any]) -> str | None:
    value = issue.get("file") or issue.get("file_path") or issue.get("path") or issue.get("filename")
    if not isinstance(value, str) or not value.strip():
        return None
    path = value.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def group_issues(combined_issues: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Group actionable, file-addressable issues from the full scan into PR categories."""
    groups: dict[str, list[dict[str, Any]]] = {"security": [], "code-quality": [], "test-failures": []}

    sec = combined_issues.get("security_issues") or {}
    if isinstance(sec, dict) and not sec.get("skipped"):
        for v in sec.get("vulnerabilities") or sec.get("enriched_findings") or []:
            if isinstance(v, dict) and _issue_file(v) and severity_rank(v.get("severity")) >= 1:
                groups["security"].append(v)

    code = combined_issues.get("code_issues") or {}
    if isinstance(code, dict) and not code.get("skipped"):
        for i in code.get("issues") or []:
            if isinstance(i, dict) and _issue_file(i) and str(i.get("type", "")).lower() in ("error", "warning", "fatal"):
                groups["code-quality"].append(i)

    qa = combined_issues.get("qa_issues") or {}
    if isinstance(qa, dict) and not qa.get("skipped"):
        for i in qa.get("issues") or []:
            if isinstance(i, dict) and _issue_file(i):
                groups["test-failures"].append(i)

    return {k: v for k, v in groups.items() if v}


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
        self.base_branch = base_branch or "main"
        self.client = httpx.AsyncClient(
            base_url="https://api.github.com",
            timeout=120.0,
            headers={
                "Authorization": f"token {self.github_token}",
                "Accept": "application/vnd.github.v3+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        self.git_service = GitService()
        self.created_branches: list[str] = []
        self.run_id: str = "unknown"

    async def close(self) -> None:
        await self.client.aclose()

    async def __aenter__(self) -> "AutoPRService":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    # ---- Phase 3: patch generation -------------------------------------------------------

    async def _ask_claude_for_fix(
        self,
        anthropic_client: AsyncAnthropic | None,
        rel_path: str,
        content: str,
        file_issues: list[dict[str, Any]],
        category: str,
    ) -> dict[str, Any] | None:
        if anthropic_client is None or (
            isinstance(anthropic_client, AsyncAnthropic) and not settings.llm_enabled
        ):
            return None
        user = json.dumps(
            {
                "file_path": rel_path,
                "category": category,
                "issues": file_issues[:40],
                "original_content": content[:120000],
            }
        )
        try:
            result = anthropic_client.messages.create(
                model=settings.anthropic_model,
                max_tokens=4000,
                system=FIX_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user}],
            )
            msg = await result if inspect.isawaitable(result) else result
            text = "".join(getattr(b, "text", "") for b in msg.content)
            data = extract_json(text)
        except Exception as exc:
            logger.error("fix generation failed for %s: %s", rel_path, exc)
            return None
        if not isinstance(data, dict) or not isinstance(data.get("fixed_content"), str) or not data["fixed_content"].strip():
            logger.error("fix generation returned empty/invalid content for %s", rel_path)
            return None
        return data

    async def generate_fix_patches(
        self,
        issues: list[dict[str, Any]],
        repo_path: str,
        category: str,
        anthropic_client: AsyncAnthropic | None,
    ) -> list[dict[str, Any]]:
        by_file: dict[str, list[dict[str, Any]]] = {}
        for issue in issues:
            rel = _issue_file(issue)
            if rel:
                by_file.setdefault(rel, []).append(issue)

        repo_root = Path(repo_path).resolve()
        patches: list[dict[str, Any]] = []
        for rel, file_issues in sorted(by_file.items()):
            full = (repo_root / rel).resolve()
            if repo_root not in full.parents or not full.is_file():
                logger.warning("skipping %s: not a file inside the repository", rel)
                continue
            try:
                original = open(os.path.join(repo_path, rel), encoding="utf-8", errors="replace").read()
            except OSError as exc:
                logger.warning("cannot read %s: %s", rel, exc)
                continue

            data = await self._ask_claude_for_fix(anthropic_client, rel, original, file_issues, category)
            if data is None or data["fixed_content"] == original:
                patches.append(
                    {
                        "file_path": rel,
                        "original_content": original,
                        "fixed_content": original,
                        "explanation": FIX_FAILED_EXPLANATION if data is None else "No changes were necessary",
                        "changes_made": [],
                        "issues": file_issues,
                        "unchanged": True,
                    }
                )
                continue
            patches.append(
                {
                    "file_path": rel,
                    "original_content": original,
                    "fixed_content": data["fixed_content"],
                    "explanation": str(data.get("explanation", "")),
                    "changes_made": list(data.get("changes_made") or []),
                    "issues": file_issues,
                }
            )
        return patches

    # ---- Phase 4: branch + commits -------------------------------------------------------

    async def _create_ref(self, branch: str, sha: str) -> httpx.Response:
        return await self.client.post(
            f"/repos/{self.repo_full_name}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )

    async def create_branch_with_fixes(self, bundle: IssueBundle, run_id: UUID | str) -> str:
        run_id = str(run_id)
        try:
            r = await self.client.get(
                f"/repos/{self.repo_full_name}/git/ref/heads/{quote(self.base_branch, safe='')}"
            )
            r.raise_for_status()
            head_sha = r.json()["object"]["sha"]

            r = await self._create_ref(bundle.branch_name, head_sha)
            # GitHub reports an existing ref as 422 ("Reference already exists"); some proxies use 409.
            if r.status_code in (409, 422):
                bundle.branch_name = f"{bundle.branch_name}-{run_id[:6]}"
                r = await self._create_ref(bundle.branch_name, head_sha)
            r.raise_for_status()

            for patch in bundle.changed_patches:
                path = patch["file_path"].lstrip("/")
                url = f"/repos/{self.repo_full_name}/contents/{quote(path)}"
                existing = await self.client.get(url, params={"ref": bundle.branch_name})
                issue_type = (
                    (patch.get("issues") or [{}])[0].get("type")
                    or (patch.get("issues") or [{}])[0].get("kind")
                    or "issues"
                )
                body: dict[str, Any] = {
                    "message": f"fix({bundle.category}): resolve {issue_type} in {path}",
                    "content": base64.b64encode(patch["fixed_content"].encode("utf-8")).decode("ascii"),
                    "branch": bundle.branch_name,
                }
                if existing.status_code == 200:
                    body["sha"] = existing.json().get("sha")
                put = await self.client.put(url, json=body)
                put.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "GitHub API error while preparing %s: %s %s",
                bundle.branch_name,
                exc.response.status_code,
                exc.response.text[:2000],
            )
            raise RuntimeError(
                f"Failed to create branch {bundle.branch_name} for {bundle.category}: "
                f"{exc.response.status_code} {exc.response.text[:300]}"
            ) from exc

        self.created_branches.append(bundle.branch_name)
        return bundle.branch_name

    # ---- Phase 5: PRs --------------------------------------------------------------------

    def _build_pr_body(self, bundle: IssueBundle) -> str:
        rows = ["| File | Line | Issue Type | Fix Applied |", "|------|------|------------|-------------|"]
        for patch in bundle.changed_patches:
            fix = (patch.get("explanation") or "").replace("|", "\\|").replace("\n", " ")[:160]
            for issue in patch.get("issues") or []:
                issue_type = str(issue.get("type") or issue.get("kind") or issue.get("category") or "issue")
                desc = str(issue.get("description") or issue.get("message") or "")[:80].replace("|", "\\|").replace("\n", " ")
                rows.append(
                    f"| `{patch['file_path']}` | {issue.get('line') or issue.get('line_number') or '-'} "
                    f"| {issue_type}: {desc} | {fix} |"
                )
        changes = []
        for patch in bundle.changed_patches:
            changes.append(f"- **`{patch['file_path']}`** — {patch.get('explanation') or 'updated'}")
            for change in patch.get("changes_made") or []:
                changes.append(f"  - {change}")
        return "\n".join(
            [
                f"## ORION automated remediation: {bundle.category}",
                "",
                f"ORION detected {len(bundle.issues)} {bundle.category} issue(s) and generated fixes.",
                "",
                "### Issues fixed",
                *rows,
                "",
                "### Changes Made",
                *changes,
                "",
                "### How to Review",
                "1. Review each changed file in the **Files changed** tab.",
                "2. Run the test suite locally or wait for CI on this branch.",
                "3. Merge when satisfied — ORION deletes this branch automatically after merge.",
                "",
                "---",
                f"🤖 Auto-generated by ORION Pipeline — Run ID: {self.run_id}",
            ]
        )

    async def create_pr(self, bundle: IssueBundle) -> int:
        bundle.pr_body = self._build_pr_body(bundle)
        r = await self.client.post(
            f"/repos/{self.repo_full_name}/pulls",
            json={
                "title": bundle.pr_title,
                "body": bundle.pr_body,
                "head": bundle.branch_name,
                "base": self.base_branch,
                "maintainer_can_modify": True,
            },
        )
        if r.is_error:
            logger.error("PR creation failed for %s: %s %s", bundle.branch_name, r.status_code, r.text[:2000])
        r.raise_for_status()
        data = r.json()
        bundle.pr_number = int(data["number"])
        bundle.pr_url = data.get("html_url")
        return bundle.pr_number

    async def open_all_prs(
        self,
        combined_issues: dict[str, Any],
        repo_path: str,
        run_id: UUID | str,
        anthropic_client: AsyncAnthropic | None,
    ) -> list[IssueBundle]:
        self.run_id = str(run_id)
        groups = group_issues(combined_issues)
        if not groups:
            logger.info("no file-addressable issues to fix for run %s", run_id)
            return []

        categories = list(groups)
        patch_results = await asyncio.gather(
            *[self.generate_fix_patches(groups[c], repo_path, c, anthropic_client) for c in categories],
            return_exceptions=True,
        )

        bundles: list[IssueBundle] = []
        for category, patches in zip(categories, patch_results, strict=True):
            if isinstance(patches, BaseException):
                logger.error("patch generation for %s failed: %s", category, patches)
                patches = []
            bundles.append(
                IssueBundle(
                    category=category,
                    issues=groups[category],
                    file_patches=patches,
                    branch_name=f"orion/fix-{category}-{self.run_id[:8]}",
                    pr_title=f"[ORION] {CATEGORY_TITLES.get(category, category)} ({len(groups[category])} issues)",
                    pr_body="",
                )
            )

        ready: list[IssueBundle] = []
        for bundle in bundles:
            if not bundle.changed_patches:
                bundle.error = "no fixes generated"
                continue
            if settings.patch_auto_pr_enforcement:
                with AgentSandbox() as sandbox:
                    sandbox_result = sandbox.verify_patches(repo_path, bundle.changed_patches)
                confidence = compute_patch_confidence(
                    sandbox=sandbox_result.to_dict(),
                    patches=bundle.changed_patches,
                )
                if confidence.get("action") == "reject":
                    bundle.error = confidence.get("summary") or "Patch confidence too low"
                    continue
                if confidence.get("action") == "review_required":
                    bundle.error = "Patch confidence requires human review before auto-PR"
                    continue
            try:
                await self.create_branch_with_fixes(bundle, run_id)
                ready.append(bundle)
            except RuntimeError as exc:
                bundle.error = str(exc)

        results = await asyncio.gather(*[self.create_pr(b) for b in ready], return_exceptions=True)
        for bundle, res in zip(ready, results, strict=True):
            if isinstance(res, BaseException):
                bundle.error = f"PR creation failed: {res}"
        return bundles

    # ---- Phase 6: registry ---------------------------------------------------------------

    @staticmethod
    def build_registry(bundles: list[IssueBundle]) -> dict[str, Any]:
        return {
            "branches": [
                {
                    "branch_name": b.branch_name,
                    "pr_number": b.pr_number,
                    "pr_url": b.pr_url,
                    "category": b.category,
                    "issues_count": len(b.issues),
                    "files": [p["file_path"] for p in b.changed_patches],
                    "merged": False,
                    "deleted": False,
                    "error": b.error,
                }
                for b in bundles
            ]
        }

    async def save_pr_registry(
        self, db: AsyncSession, pipeline_run_id: UUID, bundles: list[IssueBundle]
    ) -> PipelineArtifact:
        art = PipelineArtifact(
            pipeline_run_id=pipeline_run_id,
            artifact_type="auto_pr_registry",
            content=self.build_registry(bundles),
            agent_model=settings.anthropic_model,
        )
        db.add(art)
        await db.commit()
        return art

    # ---- Feature 3 hook: Dockerfile remediation -----------------------------------------

    async def open_dockerfile_remediation_pr(
        self,
        dockerfile_path: str,
        optimized_dockerfile: str,
        issues: list[dict[str, Any]],
        run_id: UUID | str | None = None,
    ) -> IssueBundle:
        self.run_id = str(run_id or "manual")
        patch = {
            "file_path": dockerfile_path,
            "original_content": "",
            "fixed_content": optimized_dockerfile,
            "explanation": "Applied Dockerfile hardening and optimizations from ORION Dockerfile agent",
            "changes_made": [i.get("description", "") for i in issues if i.get("description")][:20],
            "issues": issues,
        }
        bundle = IssueBundle(
            category="dockerfile",
            issues=issues,
            file_patches=[patch],
            branch_name=f"orion/fix-dockerfile-{self.run_id[:8]}",
            pr_title=f"[ORION] {CATEGORY_TITLES['dockerfile']} ({len(issues)} issues)",
            pr_body="",
        )
        await self.create_branch_with_fixes(bundle, self.run_id)
        await self.create_pr(bundle)
        return bundle

    async def verify_permissions(self) -> bool:
        r = await self.client.get("/")
        if r.status_code not in (200, 304):
            return False
        scopes = [s.strip() for s in (r.headers.get("X-OAuth-Scopes") or "").split(",") if s.strip()]
        return "repo" in scopes or "public_repo" in scopes
