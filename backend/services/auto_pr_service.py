from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
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
    error_label: str | None = None
    issue_id: str | None = None
    severity: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None


class AutoPRService:
    def __init__(
        self,
        github_token: str | None,
        repo_full_name: str,
        clone_url: str,
        base_branch: str = "main",
    ) -> None:
        provided_token = (github_token or "").strip()
        if provided_token:
            self.github_token = provided_token
        else:
            try:
                self.github_token = get_effective_github_token(None)
            except ValueError:
                self.github_token = ""

        self.repo_full_name = repo_full_name
        self.clone_url = clone_url
        self.base_branch = base_branch
        self.created_branches: list[str] = []
        self.gh_executable = self._detect_gh_executable()

        provider = (os.getenv("ORION_AUTO_PR_PROVIDER", "gh_cli") or "gh_cli").strip().lower()
        gh_requested = provider in {"gh", "gh_cli", "github_cli"}
        self.auto_pr_backend = "gh_cli" if gh_requested and bool(self.gh_executable) else "github_api"
        if gh_requested and self.auto_pr_backend != "gh_cli":
            logger.warning("ORION_AUTO_PR_PROVIDER requested gh_cli, but gh is unavailable; falling back to github_api")

        self._gh_workspace: str | None = None
        self._gh_repo_path: str | None = None

        self.client = httpx.AsyncClient(
            base_url="https://api.github.com",
            headers=self._github_api_headers(),
        )
        self.git_service = GitService(clone_url)
        self.anthropic_client: Anthropic | None = None

    @staticmethod
    def _detect_gh_executable() -> str | None:
        for env_key in ("ORION_GH_PATH", "GH_PATH"):
            candidate = (os.getenv(env_key) or "").strip()
            if candidate and Path(candidate).exists():
                return candidate

        which_value = shutil.which("gh")
        if which_value:
            return which_value

        windows_candidates = [
            Path(os.getenv("ProgramFiles", "")) / "GitHub CLI" / "gh.exe",
            Path(os.getenv("ProgramFiles(x86)", "")) / "GitHub CLI" / "gh.exe",
            Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "GitHub CLI" / "gh.exe",
        ]
        for candidate in windows_candidates:
            if str(candidate) and candidate.exists():
                return str(candidate)

        return None

    @staticmethod
    def is_gh_cli_available() -> bool:
        return AutoPRService._detect_gh_executable() is not None

    def _gh_cmd(self, *args: str) -> list[str]:
        exe = self.gh_executable or "gh"
        return [exe, *args]

    def _github_api_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.github_token:
            headers["Authorization"] = f"token {self.github_token}"
        return headers

    async def _run_local_cmd(
        self,
        args: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        context: str = "command failed",
    ) -> subprocess.CompletedProcess[str]:
        def _run() -> subprocess.CompletedProcess[str]:
            base_env = os.environ.copy()
            if env:
                base_env.update(env)
            return subprocess.run(  # noqa: S603
                args,
                cwd=cwd,
                env=base_env,
                text=True,
                capture_output=True,
                check=False,
            )

        result = await asyncio.to_thread(_run)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"{context}: {' '.join(args)} -> {detail}")
        return result

    async def _ensure_gh_cli_access(self) -> None:
        if not self.gh_executable:
            raise PermissionError("GitHub CLI (gh) is not installed on the backend host")

        await self._run_local_cmd(self._gh_cmd("--version"), context="Unable to execute GitHub CLI")
        await self._run_local_cmd(
            self._gh_cmd("auth", "status", "--hostname", "github.com"),
            context="GitHub CLI is not authenticated; run 'gh auth login' on the backend host",
        )
        await self._run_local_cmd(
            self._gh_cmd("repo", "view", self.repo_full_name),
            context=f"GitHub CLI cannot access repository {self.repo_full_name}",
        )

    async def _ensure_gh_repo_checkout(self) -> str:
        if self._gh_repo_path and Path(self._gh_repo_path).exists():
            return self._gh_repo_path

        workspace = tempfile.mkdtemp(prefix="orion_gh_repo_")
        self._gh_workspace = workspace
        repo_dirname = self.repo_full_name.split("/", 1)[-1]

        try:
            await self._run_local_cmd(
                self._gh_cmd(
                    "repo",
                    "clone",
                    self.repo_full_name,
                    repo_dirname,
                    "--",
                    "--branch",
                    self.base_branch,
                    "--single-branch",
                ),
                cwd=workspace,
                context=f"Failed to clone {self.repo_full_name} with gh",
            )
        except RuntimeError:
            await self._run_local_cmd(
                self._gh_cmd("repo", "clone", self.repo_full_name, repo_dirname),
                cwd=workspace,
                context=f"Failed to clone {self.repo_full_name} with gh",
            )

        repo_path = str(Path(workspace) / repo_dirname)
        await self._run_local_cmd(["git", "checkout", self.base_branch], cwd=repo_path, context="Failed to checkout base branch")
        await self._run_local_cmd(["git", "pull", "--ff-only", "origin", self.base_branch], cwd=repo_path, context="Failed to update base branch")
        await self._run_local_cmd(["git", "config", "user.name", "orion-bot"], cwd=repo_path, context="Failed to set git user.name")
        await self._run_local_cmd(
            ["git", "config", "user.email", "orion-bot@users.noreply.github.com"],
            cwd=repo_path,
            context="Failed to set git user.email",
        )

        self._gh_repo_path = repo_path
        return repo_path

    async def _ensure_unique_branch_name(self, repo_path: str, preferred: str, run_id: str) -> str:
        candidate = preferred
        for attempt in range(0, 6):
            result = await self._run_local_cmd(
                ["git", "ls-remote", "--heads", "origin", candidate],
                cwd=repo_path,
                context="Failed checking remote branches",
            )
            if not (result.stdout or "").strip():
                return candidate

            suffix = f"-{run_id[:6]}"
            if attempt > 0:
                suffix = f"-{run_id[:6]}-{attempt}"
            candidate = f"{preferred}{suffix}"

        raise RuntimeError(f"Could not determine unique branch name for {preferred}")

    async def _create_branch_with_fixes_via_gh(self, bundle: IssueBundle, run_id: str) -> str:
        repo_path = await self._ensure_gh_repo_checkout()
        branch_name = await self._ensure_unique_branch_name(repo_path, bundle.branch_name, run_id)
        bundle.branch_name = branch_name

        await self._run_local_cmd(["git", "checkout", self.base_branch], cwd=repo_path, context="Failed to reset to base branch")
        await self._run_local_cmd(["git", "pull", "--ff-only", "origin", self.base_branch], cwd=repo_path, context="Failed refreshing base branch")
        await self._run_local_cmd(["git", "checkout", "-B", branch_name], cwd=repo_path, context="Failed creating working branch")

        for patch in bundle.file_patches:
            file_path = str(patch.get("file_path", "")).strip()
            if not file_path:
                continue
            abs_path = Path(repo_path) / file_path
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(str(patch.get("fixed_content", "")), encoding="utf-8")

        await self._run_local_cmd(["git", "add", "-A"], cwd=repo_path, context="Failed staging remediation changes")
        status = await self._run_local_cmd(["git", "status", "--porcelain"], cwd=repo_path, context="Failed checking staged changes")
        if not (status.stdout or "").strip():
            raise RuntimeError(f"No file changes generated for {bundle.category} ({bundle.issue_id or 'issue'})")

        commit_file = bundle.file_patches[0].get("file_path", "repository") if bundle.file_patches else "repository"
        issue_type = str(bundle.issues[0].get("type", "issue")) if bundle.issues else "issue"
        await self._run_local_cmd(
            ["git", "commit", "-m", self.build_commit_message(bundle.category, issue_type, str(commit_file))],
            cwd=repo_path,
            context="Failed committing remediation changes",
        )
        await self._run_local_cmd(["git", "push", "-u", "origin", branch_name], cwd=repo_path, context="Failed pushing remediation branch")

        self.created_branches.append(branch_name)
        return branch_name

    async def _create_pr_via_gh(self, bundle: IssueBundle) -> int:
        create_args = [
            *self._gh_cmd(
                "pr",
                "create",
                "--repo",
                self.repo_full_name,
                "--base",
                self.base_branch,
                "--head",
                bundle.branch_name,
                "--title",
                bundle.pr_title,
                "--body",
                bundle.pr_body,
            ),
        ]
        try:
            await self._run_local_cmd(create_args, context=f"Failed creating PR for {bundle.branch_name}")
        except RuntimeError as exc:
            if "already exists" not in str(exc).lower():
                raise

        # gh pr view does not support --head on some CLI versions. Passing
        # the branch name positionally is the most compatible way to resolve
        # the PR details for the just-created head branch.
        view_result = await self._run_local_cmd(
            self._gh_cmd(
                "pr",
                "view",
                bundle.branch_name,
                "--repo",
                self.repo_full_name,
                "--json",
                "number,url",
            ),
            context=f"Failed reading PR details for {bundle.branch_name}",
        )
        payload = json.loads(view_result.stdout or "{}")
        pr_number = int(payload.get("number"))
        bundle.pr_number = pr_number
        bundle.pr_url = str(payload.get("url", ""))
        return pr_number

    async def _ensure_success(self, response: httpx.Response, context: str) -> None:
        if 200 <= response.status_code < 300:
            return
        body = response.text or ""
        message = ""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                message = str(payload.get("message") or "")
        except Exception:  # noqa: BLE001
            message = ""
        detail = message or body or "GitHub API request failed"
        raise RuntimeError(f"{context}: HTTP {response.status_code} - {detail}")

    async def _head_branch_exists(self, branch_name: str) -> bool:
        response = await self.client.get(f"/repos/{self.repo_full_name}/git/ref/heads/{branch_name}")
        return response.status_code == 200

    async def _branch_has_diff(self, base_branch: str, head_branch: str) -> bool:
        compare = await self.client.get(f"/repos/{self.repo_full_name}/compare/{base_branch}...{head_branch}")
        await self._ensure_success(compare, "GitHub compare check failed")
        payload = compare.json()
        ahead_by = int(payload.get("ahead_by", 0)) if isinstance(payload, dict) else 0
        return ahead_by > 0

    async def verify_permissions(self) -> None:
        if self.auto_pr_backend == "gh_cli":
            await self._ensure_gh_cli_access()
            return

        if not self.github_token:
            raise PermissionError("No GitHub token available for github_api backend")

        try:
            await validate_github_token(self.github_token)
        except Exception as exc:  # noqa: BLE001
            raise PermissionError(f"GitHub token validation failed: {exc}") from exc

        scopes = get_token_scopes(self.github_token)
        if scopes and "repo" not in scopes:
            raise PermissionError(
                "GitHub token missing 'repo' scope — re-login at /api/v1/auth/github to grant repository access"
            )

        repo_resp = await self.client.get(f"/repos/{self.repo_full_name}")
        await self._ensure_success(repo_resp, f"Failed loading repository {self.repo_full_name}")
        repo_data = repo_resp.json() if repo_resp.headers.get("content-type", "").startswith("application/json") else {}

        # Align base branch with the repository's default branch to avoid
        # branch lookup failures when callers pass a non-existent branch
        # (e.g., "main" vs "master"). This keeps auto-PR creation robust
        # across repositories without requiring callers to know the default.
        if isinstance(repo_data, dict):
            default_branch = repo_data.get("default_branch")
            if isinstance(default_branch, str) and default_branch.strip():
                self.base_branch = default_branch.strip()

            permissions = repo_data.get("permissions", {})
        else:
            permissions = {}
        if permissions and not bool(permissions.get("push", False)):
            raise PermissionError(
                f"Token does not have push access to {self.repo_full_name}; cannot create branches/PRs"
            )

    @staticmethod
    def _issue_file_path(issue: dict[str, Any]) -> str:
        return str(issue.get("file_path") or issue.get("path") or issue.get("file") or "")

    async def close(self) -> None:
        await self.client.aclose()
        if self._gh_workspace and Path(self._gh_workspace).exists():
            shutil.rmtree(self._gh_workspace, ignore_errors=True)
        self._gh_workspace = None
        self._gh_repo_path = None

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
        if anthropic_client is None:
            raise ValueError("Anthropic client is required for generate_fix_patches")

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
                if not isinstance(parsed, dict):
                    raise ValueError("Claude returned non-object JSON payload")

                file_path_value = parsed.get("file_path")
                fixed_content = parsed.get("fixed_content")
                explanation = parsed.get("explanation", "Automated fix generated")
                changes_made = parsed.get("changes_made", [])

                if not isinstance(file_path_value, str) or not file_path_value.strip():
                    raise ValueError("Claude response missing file_path")
                if not isinstance(fixed_content, str) or not fixed_content.strip():
                    raise ValueError("Claude returned empty fixed_content")
                if not isinstance(explanation, str):
                    raise ValueError("Claude explanation must be a string")
                if not isinstance(changes_made, list):
                    changes_made = []
                else:
                    changes_made = [str(item) for item in changes_made]

                patches.append(
                    {
                        "file_path": file_path,
                        "original_content": original_content,
                        "fixed_content": fixed_content,
                        "explanation": explanation,
                        "changes_made": changes_made,
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

    @staticmethod
    def _normalize_error_label(issue: dict[str, Any]) -> str:
        raw = str(
            issue.get("rule_id")
            or issue.get("rule")
            or issue.get("label")
            or issue.get("type")
            or "issue"
        )
        raw = raw.strip().lower().replace(" ", "-").replace("_", "-")
        slug = "".join(ch if (ch.isalnum() or ch == "-") else "-" for ch in raw).strip("-")
        return slug or "issue"

    async def create_branch_with_fixes(self, bundle: IssueBundle, run_id: str) -> str:
        if self.auto_pr_backend == "gh_cli":
            return await self._create_branch_with_fixes_via_gh(bundle, run_id)

        try:
            head_response = await self.client.get(f"/repos/{self.repo_full_name}/git/ref/heads/{self.base_branch}")
            await self._ensure_success(head_response, f"Base branch lookup failed ({self.base_branch})")
            head_sha = head_response.json()["object"]["sha"]

            branch_name = bundle.branch_name
            create_payload = {"ref": f"refs/heads/{branch_name}", "sha": head_sha}
            create_response = await self.client.post(f"/repos/{self.repo_full_name}/git/refs", json=create_payload)
            if create_response.status_code == 409:
                branch_name = f"{bundle.branch_name}-{run_id[:6]}"
                bundle.branch_name = branch_name
                create_payload["ref"] = f"refs/heads/{branch_name}"
                create_response = await self.client.post(f"/repos/{self.repo_full_name}/git/refs", json=create_payload)
            await self._ensure_success(create_response, f"Failed creating branch {branch_name}")

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
                    await self._ensure_success(file_response, f"Failed reading {file_path} on {bundle.branch_name}")

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
                await self._ensure_success(update_response, f"Failed committing {file_path} to {bundle.branch_name}")

            self.created_branches.append(bundle.branch_name)
            return bundle.branch_name
        except Exception as exc:  # noqa: BLE001
            logger.error("GitHub API error while creating branch/fixes: %s", exc)
            raise RuntimeError(f"Failed creating branch or committing fixes for {bundle.category}: {exc}") from exc

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
        if not (bundle.pr_title or "").strip():
            bundle.pr_title = f"fix({bundle.category}): automated remediation"
        if not (bundle.pr_body or "").strip():
            bundle.pr_body = "Automated remediation from ORION pipeline."

        if self.auto_pr_backend == "gh_cli":
            return await self._create_pr_via_gh(bundle)

        head_exists = await self._head_branch_exists(bundle.branch_name)
        if not head_exists:
            raise RuntimeError(f"Cannot create PR: head branch does not exist ({bundle.branch_name})")

        has_diff = await self._branch_has_diff(self.base_branch, bundle.branch_name)
        if not has_diff:
            raise RuntimeError(
                f"Cannot create PR: no commit difference between head {bundle.branch_name} and base {self.base_branch}"
            )

        payload = {
            "title": bundle.pr_title,
            "body": bundle.pr_body,
            "head": bundle.branch_name,
            "base": self.base_branch,
            "maintainer_can_modify": True,
        }
        response = await self.client.post(f"/repos/{self.repo_full_name}/pulls", json=payload)
        await self._ensure_success(response, f"Failed creating PR for {bundle.branch_name}")
        pr_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        pr_number = int(pr_data["number"])
        bundle.pr_number = pr_number
        bundle.pr_url = str(pr_data.get("html_url", ""))
        return pr_number

    def _build_group_bundle(
        self,
        category: str,
        error_label: str,
        issues: list[dict[str, Any]],
        run_id: str,
    ) -> IssueBundle:
        sanitized = category.replace("_", "-")
        slug_label = "".join(ch if (ch.isalnum() or ch == "-") else "-" for ch in error_label.strip().lower()).strip("-")
        slug_label = slug_label or "issue"

        # Derive a representative severity for the bundle (highest severity wins).
        severity_order = {"low": 0, "medium": 1, "high": 2}
        resolved_severity = "unknown"
        best_score = -1
        for issue in issues:
            sev = str(issue.get("severity", "unknown")).lower()
            score = severity_order.get(sev, -1)
            if score > best_score:
                best_score = score
                resolved_severity = sev

        suffix = f"-{run_id[:6]}" if run_id else ""
        branch_name = f"orion/{sanitized}/{slug_label}{suffix}"
        pr_title = f"Fix {sanitized}: {error_label} findings"

        return IssueBundle(
            category=sanitized,
            issues=list(issues),
            file_patches=[],
            branch_name=branch_name,
            pr_title=pr_title,
            pr_body="",
            error_label=error_label,
            issue_id=slug_label,
            severity=resolved_severity,
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

    def _fallback_report_patch(
        self,
        category: str,
        issues: list[dict[str, Any]],
        run_id: str,
        issue_id: str | None = None,
    ) -> dict[str, Any]:
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
            "file_path": f"orion_reports/{category}_{issue_id or 'issue'}_run_{run_id[:8]}.md",
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
        per_group_bundles: list[IssueBundle] = []

        for category, issues in grouped.items():
            if not issues:
                continue

            # Refine grouping: within each category, group by normalized error label/rule-id.
            label_to_issues: dict[str, list[dict[str, Any]]] = {}
            label_display: dict[str, str] = {}
            for issue in issues:
                if not isinstance(issue, dict):
                    continue
                label = self._normalize_error_label(issue)
                label_to_issues.setdefault(label, []).append(issue)
                if label not in label_display:
                    label_display[label] = str(issue.get("type") or issue.get("rule_id") or label)

            for label, grouped_issues in label_to_issues.items():
                if not grouped_issues:
                    continue

                bundle = self._build_group_bundle(category, label_display.get(label, label), grouped_issues, run_id)
                patches = await self.generate_fix_patches(grouped_issues, repo_path, category, anthropic_client)
                bundle.file_patches = [patch for patch in patches if isinstance(patch, dict) and patch.get("file_path")]
                if not bundle.file_patches:
                    logger.warning(
                        "No file patch generated for %s group %s; using fallback report patch",
                        category,
                        bundle.issue_id,
                    )
                    bundle.file_patches = [
                        self._fallback_report_patch(
                            category=category,
                            issues=grouped_issues,
                            run_id=run_id,
                            issue_id=bundle.issue_id,
                        )
                    ]
                bundle.pr_body = self._build_pr_body(bundle, run_id)
                per_group_bundles.append(bundle)

        if not per_group_bundles:
            return []

        created_bundles: list[IssueBundle] = []
        for bundle in per_group_bundles:
            try:
                await self.create_branch_with_fixes(bundle, run_id)
                created_bundles.append(bundle)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Skipping PR creation for %s issue %s due to branch/commit failure: %s",
                    bundle.category,
                    bundle.issue_id,
                    exc,
                )

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
