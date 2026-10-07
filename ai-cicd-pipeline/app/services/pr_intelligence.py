"""GitHub PR review comment generation and posting."""

from __future__ import annotations

from typing import Any

from app.services.github_service import GitHubService


def build_pr_review_comment(artifacts: dict[str, dict[str, Any]]) -> str:
    change_risk = artifacts.get("change_risk_report") or {}
    security = artifacts.get("security_scan") or {}
    qa = artifacts.get("qa_report") or {}
    contract = artifacts.get("contract_test_report") or {}
    passport = artifacts.get("release_passport") or {}
    test_intel = artifacts.get("test_intelligence") or {}

    risk = change_risk.get("final_risk", "—")
    risk_level = str(change_risk.get("risk_level", "unknown")).upper()
    qa_summary = qa.get("test_summary") or {}
    tests_line = f"{qa_summary.get('passed', 0)}/{qa_summary.get('total', 0)}"
    flaky = (test_intel.get("flaky_analysis") or {}).get("flaky_count", 0)

    sec_high = security.get("highest_severity", "none")
    breaking = contract.get("breaking_count", 0)

    recommendation = "APPROVE"
    if risk_level == "HIGH" or str(qa.get("verdict", "")).lower() == "fail":
        recommendation = "REQUEST CHANGES"
    elif risk_level == "MEDIUM" or breaking:
        recommendation = "COMMENT"

    lines = [
        "## ORION REVIEW",
        "",
        f"**Risk:** {risk}/100 — {risk_level}",
        "",
        "**Security:**",
        f"- Highest severity: {sec_high}",
        "",
        "**Tests:**",
        f"- {tests_line} passed",
        f"- Flaky indicators: {flaky}",
        "",
        "**API / Contract:**",
        f"- Breaking changes detected: {breaking}",
        "",
        "**Deployment:**",
        f"- Release passport: {'PASS' if passport.get('all_checks_passed') else 'pending/incomplete'}",
        "",
        f"**Recommendation:** {recommendation}",
        "",
        "---",
        "🤖 ORION autonomous DevSecOps review",
    ]
    return "\n".join(lines)


def _recommendation_from_artifacts(artifacts: dict[str, dict[str, Any]]) -> str:
    change_risk = artifacts.get("change_risk_report") or {}
    qa = artifacts.get("qa_report") or {}
    contract = artifacts.get("contract_test_report") or {}
    risk_level = str(change_risk.get("risk_level", "unknown")).upper()
    if risk_level == "HIGH" or str(qa.get("verdict", "")).lower() == "fail":
        return "REQUEST CHANGES"
    if risk_level == "MEDIUM" or contract.get("breaking_count"):
        return "COMMENT"
    return "APPROVE"


async def post_pr_intelligence(
    gh: GitHubService,
    *,
    repo_full_name: str,
    commit_sha: str,
    artifacts: dict[str, dict[str, Any]],
    pr_number: int | None = None,
) -> dict[str, Any]:
    if not gh.enabled:
        return {
            "posted": False,
            "summary": "PR intelligence skipped: GitHub token not configured.",
            "reason": "github_disabled",
        }
    recommendation = _recommendation_from_artifacts(artifacts)
    body = build_pr_review_comment(artifacts)
    if pr_number is not None:
        comment = await gh.create_issue_comment(repo_full_name, pr_number, body)
        return {
            "posted": True,
            "target": "pull_request",
            "pr_number": pr_number,
            "comment_id": comment.get("id"),
            "recommendation": recommendation,
            "summary": f"ORION review posted on PR #{pr_number} ({recommendation}).",
        }

    prs = await gh.find_pull_requests_for_commit(repo_full_name, commit_sha)
    if prs:
        number = int(prs[0]["number"])
        comment = await gh.create_issue_comment(repo_full_name, number, body)
        return {
            "posted": True,
            "target": "pull_request",
            "pr_number": number,
            "comment_id": comment.get("id"),
            "recommendation": recommendation,
            "summary": f"ORION review posted on PR #{number} ({recommendation}).",
        }

    comment = await gh.create_commit_comment(repo_full_name, commit_sha, body)
    return {
        "posted": True,
        "target": "commit",
        "comment_id": comment.get("id"),
        "body_preview": body[:200],
        "recommendation": recommendation,
        "summary": f"ORION review posted on commit {commit_sha[:8]} ({recommendation}).",
    }
