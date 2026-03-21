from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import os
from uuid import uuid4
from typing import Any

import httpx
from anthropic import Anthropic

from core.logging_config import get_logger
from services.git_service import GitService
from utils.auth_utils import (
    get_effective_github_token,
    get_token_scopes,
    validate_github_token,
)

logger = get_logger("auto_pr_service")


@dataclasses.dataclass
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
        self.created_branches: list[str] = []

        self.client = httpx.AsyncClient(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"token {self.github_token}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        self.git_service = GitService(clone_url)
        self.anthropic_client: Anthropic | None = None

    async def verify_permissions(self) -> None:
        await validate_github_token(self.github_token)
        scopes = get_token_scopes(self.github_token)
        if "repo" not in scopes:
            raise PermissionError(
                "GitHub token missing 'repo' scope — re-login at /api/v1/auth/github to grant repository access"
            )

    @staticmethod
    def _issue_file_path(issue: dict[str, Any]) -> str:
        return str(issue.get("file_path") or issue.get("path") or issue.get("file") or "")

    async def close(self) -> None:
        await self.client.aclose()

    def build_commit_message(self, category: str, issue_type: str, file_path: str) -> str:
        return f"fix({category}): resolve {issue_type} in {file_path}"

    async def noop_healthcheck(self) -> dict[str, Any]:
        """Foundation probe for service wiring during staged rollout."""

        await asyncio.sleep(0)
        return {
            "repo_full_name": self.repo_full_name,
            "base_branch": self.base_branch,
            "created_branches": self.created_branches,
            "github_headers_ready": bool(self.github_token),
            "sample_content_encoding": base64.b64encode(b"ok").decode("utf-8"),
            "json_ready": json.loads('{"ready": true}'),
        }

    async def generate_fix_patches(
        self,
        issues: list[dict[str, Any]],
        repo_path: str,
        category: str,
        anthropic_client: Any,
    ) -> list[dict[str, Any]]:
        file_to_issues: dict[str, list[dict[str, Any]]] = {}
        for issue in issues:
            file_path = self._issue_file_path(issue)
            if not file_path:
                continue
            file_to_issues.setdefault(file_path, []).append(issue)

        patches: list[dict[str, Any]] = []
        for file_path, file_issues in file_to_issues.items():
            absolute_path = os.path.join(repo_path, file_path)
            try:
                with open(absolute_path, encoding="utf-8") as source_file:
                    original_content = source_file.read()
            except OSError as exc:
                logger.error("Failed reading %s for %s fixes: %s", file_path, category, exc)
                continue

            prompt_payload = {
                "file_path": file_path,
                "category": category,
                "issues": file_issues,
                "original_content": original_content,
            }
            try:
                response = anthropic_client.messages.create(
                    model="claude-3-7-sonnet-latest",
                    max_tokens=4000,
                    system=(
                        "You are an expert software engineer. You will receive a source file and a list of issues found in it. "
                        "Your job is to return a corrected version of the entire file that resolves all listed issues. "
                        "Do not add placeholder comments or TODOs — make real, working fixes. "
                        "Return ONLY valid JSON in this exact schema: {\"file_path\": string, \"fixed_content\": string (the complete corrected file), "
                        "\"explanation\": string (what was changed and why), \"changes_made\": [string]}. "
                        "The fixed_content must be the complete file, not a diff or snippet. Return ONLY valid JSON."
                    ),
                    messages=[{"role": "user", "content": json.dumps(prompt_payload)}],
                )
                content_text = ""
                if getattr(response, "content", None):
                    first_block = response.content[0]
                    content_text = getattr(first_block, "text", "") if first_block else ""

                parsed = json.loads(content_text)
                fixed_content = parsed.get("fixed_content") if isinstance(parsed, dict) else ""
                if not isinstance(fixed_content, str) or not fixed_content.strip():
                    raise ValueError("Claude returned empty fixed_content")

                patches.append(
                    {
                        "file_path": file_path,
                        "original_content": original_content,
                        "fixed_content": fixed_content,
                        "explanation": parsed.get("explanation", "Automated fix generated"),
                        "changes_made": parsed.get("changes_made", []),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("AI fix generation failed for %s: %s", file_path, exc)
                patches.append(
                    {
                        "file_path": file_path,
                        "original_content": original_content,
                        "fixed_content": original_content,
                        "explanation": "AI fix generation failed, manual review required",
                        "changes_made": [],
                    }
                )

        return patches

    async def create_branch_with_fixes(self, bundle: IssueBundle, run_id: str) -> str:
        try:
            head_response = await self.client.get(f"/repos/{self.repo_full_name}/git/ref/heads/{self.base_branch}")
            head_response.raise_for_status()
            head_sha = head_response.json()["object"]["sha"]

            branch_name = bundle.branch_name
            create_payload = {"ref": f"refs/heads/{branch_name}", "sha": head_sha}
            create_response = await self.client.post(f"/repos/{self.repo_full_name}/git/refs", json=create_payload)
            if create_response.status_code == 409:
                branch_name = f"{bundle.branch_name}-{run_id[:6]}"
                bundle.branch_name = branch_name
                create_payload["ref"] = f"refs/heads/{branch_name}"
                create_response = await self.client.post(f"/repos/{self.repo_full_name}/git/refs", json=create_payload)
            create_response.raise_for_status()

            for patch in bundle.file_patches:
                file_path = patch["file_path"]
                issue_type = "issue"
                if bundle.issues:
                    issue_type = str(bundle.issues[0].get("type", "issue"))

                file_response = await self.client.get(
                    f"/repos/{self.repo_full_name}/contents/{file_path}",
                    params={"ref": bundle.branch_name},
                )
                file_sha = None
                if file_response.status_code == 200:
                    file_sha = file_response.json().get("sha")
                elif file_response.status_code != 404:
                    file_response.raise_for_status()

                commit_payload = {
                    "message": self.build_commit_message(bundle.category, issue_type, file_path),
                    "content": base64.b64encode(patch["fixed_content"].encode("utf-8")).decode("utf-8"),
                    "branch": bundle.branch_name,
                }
                if file_sha:
                    commit_payload["sha"] = file_sha
                update_response = await self.client.put(
                    f"/repos/{self.repo_full_name}/contents/{file_path}",
                    json=commit_payload,
                )
                update_response.raise_for_status()

            self.created_branches.append(bundle.branch_name)
            return bundle.branch_name
        except httpx.HTTPStatusError as exc:
            response_body = exc.response.text if exc.response is not None else ""
            logger.error("GitHub API error while creating branch/fixes: %s", response_body)
            raise RuntimeError(f"Failed creating branch or committing fixes for {bundle.category}: {response_body}") from exc

    def _build_pr_body(self, bundle: IssueBundle, run_id: str) -> str:
        rows: list[str] = ["| File | Line | Issue Type | Fix Applied |", "|---|---:|---|---|"]
        for issue in bundle.issues:
            file_path = self._issue_file_path(issue) or "n/a"
            line = str(issue.get("line", "n/a"))
            issue_type = str(issue.get("type", "unknown"))
            fix = str(issue.get("fix", "Updated file to resolve finding"))
            rows.append(f"| {file_path} | {line} | {issue_type} | {fix} |")

        changes_made = "\n".join(f"- `{patch.get('file_path', 'unknown')}`" for patch in bundle.file_patches) or "- No file modifications captured"

        return (
            "## Summary of Fixes\n\n"
            + "\n".join(rows)
            + "\n\n## Changes Made\n"
            + changes_made
            + "\n\n## How to Review\n"
            + "1. Review each commit in this PR by file.\n"
            + "2. Validate tests and static checks for modified files.\n"
            + "3. Merge if behavior and security posture are improved.\n\n"
            + f"🤖 Auto-generated by ORION Pipeline — Run ID: {run_id}"
        )

    async def create_pr(self, bundle: IssueBundle) -> int:
        payload = {
            "title": bundle.pr_title,
            "body": bundle.pr_body,
            "head": bundle.branch_name,
            "base": self.base_branch,
            "maintainer_can_modify": True,
        }
        response = await self.client.post(f"/repos/{self.repo_full_name}/pulls", json=payload)
        response.raise_for_status()
        pr_number = int(response.json()["number"])
        bundle.pr_number = pr_number
        return pr_number

    def _build_issue_bundle(self, category: str, issues: list[dict[str, Any]]) -> IssueBundle:
        sanitized = category.replace("_", "-")
        return IssueBundle(
            category=sanitized,
            issues=issues,
            file_patches=[],
            branch_name=f"orion/{sanitized}-fixes",
            pr_title=f"fix({sanitized}): automated ORION remediation",
            pr_body="",
        )

    def _group_issues_by_category(self, combined_issues: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {
            "security": [],
            "code-quality": [],
            "test-failures": [],
        }

        security = combined_issues.get("security_issues", {})
        code = combined_issues.get("code_issues", {})
        qa = combined_issues.get("qa_issues", {})

        if isinstance(security, dict):
            grouped["security"].extend(security.get("issues", []))
        if isinstance(code, dict):
            grouped["code-quality"].extend(code.get("issues", []))
        if isinstance(qa, dict):
            grouped["test-failures"].extend(qa.get("issues", []))

        return grouped

    def _fallback_report_patch(self, category: str, issues: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
        lines = [
            "# ORION Auto-PR Report",
            "",
            f"Category: {category}",
            f"Run ID: {run_id}",
            "",
            "No direct file-specific patch could be generated for the detected issues.",
            "This report PR was created so the repository owner can review and address findings.",
            "",
            "## Findings",
        ]
        if not issues:
            lines.append("- No structured issues were provided.")
        for item in issues:
            if not isinstance(item, dict):
                continue
            issue_type = str(item.get("type", "unknown"))
            severity = str(item.get("severity", "unknown"))
            file_path = str(item.get("file_path", "n/a"))
            fix = str(item.get("fix", "manual review required"))
            lines.append(f"- type={issue_type}, severity={severity}, file={file_path}, fix={fix}")

        content = "\n".join(lines).strip() + "\n"
        return {
            "file_path": f"orion_reports/{category}_run_{run_id[:8]}.md",
            "original_content": "",
            "fixed_content": content,
            "explanation": "Fallback report generated because no direct file patch was available.",
            "changes_made": ["Added ORION report with actionable findings summary"],
        }

    async def open_all_prs(
        self,
        combined_issues: dict[str, Any],
        repo_path: str,
        run_id: str,
        anthropic_client: Any,
    ) -> list[IssueBundle]:
        await self.verify_permissions()
        grouped = self._group_issues_by_category(combined_issues)
        bundles: list[IssueBundle] = []

        categories = [cat for cat, issues in grouped.items() if issues]
        if not categories:
            return bundles

        patch_tasks = [self.generate_fix_patches(grouped[cat], repo_path, cat, anthropic_client) for cat in categories]
        patch_sets = await asyncio.gather(*patch_tasks)

        for category, patches in zip(categories, patch_sets):
            bundle = self._build_issue_bundle(category, grouped[category])
            bundle.file_patches = [patch for patch in patches if isinstance(patch, dict) and patch.get("file_path")]
            if not bundle.file_patches:
                logger.warning("No file patches generated for %s; using fallback report patch", category)
                bundle.file_patches = [self._fallback_report_patch(category=category, issues=grouped[category], run_id=run_id)]
            bundle.pr_body = self._build_pr_body(bundle, run_id)
            bundles.append(bundle)

        if not bundles:
            return []

        created_bundles: list[IssueBundle] = []
        for bundle in bundles:
            try:
                await self.create_branch_with_fixes(bundle, run_id)
                created_bundles.append(bundle)
            except Exception as exc:  # noqa: BLE001
                logger.error("Skipping PR creation for %s bundle due to branch/commit failure: %s", bundle.category, exc)

        if not created_bundles:
            return []

        await asyncio.gather(*(self.create_pr(bundle) for bundle in created_bundles))
        return created_bundles

    async def open_dockerfile_remediation_pr(
        self,
        analysis_result: dict[str, Any],
        target_file_path: str = "Dockerfile",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        active_run_id = run_id or str(uuid4())
        issues = [
            item
            for item in analysis_result.get("dockerfile_issues", [])
            if isinstance(item, dict) and str(item.get("severity", "")).lower() in {"high", "critical"}
        ]
        if not issues:
            return {"queued": False, "reason": "no-high-severity-dockerfile-issues"}

        optimized = analysis_result.get("optimized_dockerfile")
        if not isinstance(optimized, str) or not optimized.strip():
            return {"queued": False, "reason": "missing-optimized-dockerfile"}

        bundle = IssueBundle(
            category="dockerfile-remediation",
            issues=[
                {
                    "type": item.get("issue_type", "dockerfile_issue"),
                    "severity": item.get("severity", "high"),
                    "line": str(item.get("line", "n/a")),
                    "fix": item.get("description", "Apply optimized Dockerfile remediation"),
                    "file_path": target_file_path,
                }
                for item in issues
            ],
            file_patches=[
                {
                    "file_path": target_file_path,
                    "original_content": "",
                    "fixed_content": optimized,
                    "explanation": analysis_result.get("summary", "Automated Dockerfile remediation"),
                    "changes_made": [issue.get("description", "Remediation applied") for issue in issues],
                }
            ],
            branch_name=f"orion/dockerfile-fixes-{active_run_id[:6]}",
            pr_title="fix(dockerfile): automated ORION docker remediation",
            pr_body="",
        )
        bundle.pr_body = self._build_pr_body(bundle, active_run_id)

        await self.create_branch_with_fixes(bundle, active_run_id)
        await self.create_pr(bundle)

        return {
            "queued": True,
            "branch_name": bundle.branch_name,
            "pr_number": bundle.pr_number,
            "repo_full_name": self.repo_full_name,
        }
