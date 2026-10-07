import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from sqlalchemy import select

from app.models.pipeline_artifact import PipelineArtifact
from app.services.auto_pr_service import FIX_FAILED_EXPLANATION, AutoPRService, IssueBundle, group_issues
from tests.conftest import make_claude_response

RUN_ID = "1234abcd-0000-0000-0000-000000000000"

COMBINED = {
    "security_issues": {
        "vulnerabilities": [
            {"file": "app/api/users.py", "line": 31, "type": "sql_injection", "severity": "high", "description": "f-string SQL"},
            {"file": "app/api/users.py", "line": 40, "type": "info_leak", "severity": "low", "description": "minor"},
            {"file": "", "type": "dependency", "severity": "critical"},
        ]
    },
    "code_issues": {
        "issues": [
            {"file": "./app/api/users.py", "line": 3, "type": "warning", "description": "unused import"},
            {"file": "app/api/users.py", "line": 9, "type": "convention", "description": "naming"},
        ]
    },
    "qa_issues": {"skipped": True, "issues": [{"file": "tests/test_x.py"}]},
}


def test_group_issues_filters_by_actionability():
    groups = group_issues(COMBINED)
    assert set(groups) == {"security", "code-quality"}
    assert [i["line"] for i in groups["security"]] == [31]
    assert [i["line"] for i in groups["code-quality"]] == [3]


def test_issue_bundle_tracks_changed_patches():
    bundle = IssueBundle("security", [], [{"file_path": "a", "unchanged": True}, {"file_path": "b"}], "br", "t", "")
    assert [p["file_path"] for p in bundle.changed_patches] == ["b"]


def test_service_requires_token():
    with pytest.raises(ValueError):
        AutoPRService(None, "o/r", "https://github.com/o/r.git")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "app" / "api").mkdir(parents=True)
    (tmp_path / "app" / "api" / "users.py").write_text("import json\nq = f\"SELECT {x}\"\n", encoding="utf-8")
    return tmp_path


class FakeGitHub:
    def __init__(self, existing_branches: set[str] | None = None) -> None:
        self.existing = set(existing_branches or ())
        self.refs: list[str] = []
        self.commits: list[dict] = []
        self.pulls: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and "/git/ref/heads/" in path:
            return httpx.Response(200, json={"object": {"sha": "base-sha"}})
        if request.method == "POST" and path.endswith("/git/refs"):
            ref = json.loads(request.content)["ref"].removeprefix("refs/heads/")
            if ref in self.existing:
                return httpx.Response(422, json={"message": "Reference already exists"})
            self.existing.add(ref)
            self.refs.append(ref)
            return httpx.Response(201, json={"ref": ref})
        if request.method == "GET" and "/contents/" in path:
            return httpx.Response(200, json={"sha": "file-sha"})
        if request.method == "PUT" and "/contents/" in path:
            self.commits.append(json.loads(request.content))
            return httpx.Response(201, json={"content": {}})
        if request.method == "POST" and path.endswith("/pulls"):
            body = json.loads(request.content)
            number = 100 + len(self.pulls)
            self.pulls.append(body)
            return httpx.Response(201, json={"number": number, "html_url": f"https://github.com/o/r/pull/{number}"})
        return httpx.Response(404, json={"message": f"unexpected {request.method} {path}"})


def service_with(fake: FakeGitHub) -> AutoPRService:
    svc = AutoPRService("ghp_realistic_test_token", "testuser/testrepo", "https://github.com/testuser/testrepo.git")
    svc.client = httpx.AsyncClient(base_url="https://api.github.com", transport=httpx.MockTransport(fake.handler))
    return svc


def fixing_client() -> MagicMock:
    client = MagicMock()
    client.messages.create = AsyncMock(
        return_value=make_claude_response(
            {
                "file_path": "app/api/users.py",
                "fixed_content": "q = 'SELECT ?'\n",
                "explanation": "Parameterized the query",
                "changes_made": ["Removed f-string SQL", "Dropped unused import"],
            }
        )
    )
    return client


async def test_open_all_prs_end_to_end(repo):
    fake = FakeGitHub(existing_branches={f"orion/fix-security-{RUN_ID[:8]}"})
    svc = service_with(fake)
    bundles = await svc.open_all_prs(COMBINED, str(repo), RUN_ID, fixing_client())
    await svc.close()

    by_cat = {b.category: b for b in bundles}
    assert set(by_cat) == {"security", "code-quality"}
    assert by_cat["security"].branch_name == f"orion/fix-security-{RUN_ID[:8]}-{RUN_ID[:6]}"
    assert by_cat["code-quality"].branch_name == f"orion/fix-code-quality-{RUN_ID[:8]}"
    assert all(b.pr_number and b.pr_url and b.error is None for b in bundles)

    assert len(fake.commits) == 2
    commit = fake.commits[0]
    assert commit["sha"] == "file-sha"
    assert base64.b64decode(commit["content"]).decode() == "q = 'SELECT ?'\n"
    assert commit["message"].startswith("fix(")

    body = fake.pulls[0]["body"]
    assert "| File | Line | Issue Type | Fix Applied |" in body
    assert "### Changes Made" in body and "### How to Review" in body
    assert f"Run ID: {RUN_ID}" in body
    assert fake.pulls[0]["maintainer_can_modify"] is True


async def test_failed_fix_generation_opens_no_pr(repo):
    fake = FakeGitHub()
    svc = service_with(fake)
    bundles = await svc.open_all_prs(COMBINED, str(repo), RUN_ID, None)
    await svc.close()
    assert all(b.error == "no fixes generated" and b.pr_number is None for b in bundles)
    assert fake.refs == [] and fake.pulls == []
    assert bundles[0].file_patches[0]["explanation"] == FIX_FAILED_EXPLANATION


async def test_patch_generation_refuses_paths_outside_repo(repo, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "secret.py"
    outside.write_text("SECRET = 1\n")
    svc = service_with(FakeGitHub())
    issues = [{"file": "../" + outside.parent.name + "/secret.py"}, {"file": "app/api/users.py"}]
    patches = await svc.generate_fix_patches(issues, str(repo), "security", fixing_client())
    await svc.close()
    assert [p["file_path"] for p in patches] == ["app/api/users.py"]


async def test_registry_persisted_for_branch_cleanup(repo, db_session, pipeline_run):
    svc = service_with(FakeGitHub())
    bundles = await svc.open_all_prs(COMBINED, str(repo), pipeline_run.id, fixing_client())
    await svc.save_pr_registry(db_session, pipeline_run.id, bundles)
    await svc.close()

    art = (
        await db_session.execute(select(PipelineArtifact).where(PipelineArtifact.artifact_type == "auto_pr_registry"))
    ).scalar_one()
    entries = art.content["branches"]
    assert {e["category"] for e in entries} == {"security", "code-quality"}
    assert all(e["merged"] is False and e["deleted"] is False and e["pr_number"] for e in entries)
    assert entries[0]["files"] == ["app/api/users.py"]
