"""Phase 4 enterprise unit tests."""

from app.utils.audit_explorer import explore_audit_events
from app.utils.compliance_packs import evaluate_compliance
from app.utils.enterprise_sso import assess_sso_readiness
from app.utils.finops import compute_pipeline_cost
from app.utils.fleet_view import build_fleet_view
from app.utils.policy_engine import evaluate_policies
from app.utils.signed_builds import verify_signed_build
from app.utils.tenant_rbac import resolve_tenant_context, tenant_allows_action


def _sample_artifacts(**overrides) -> dict:
    base = {
        "security_scan": {"passed": True, "vulnerabilities": []},
        "secrets_scan": {"critical_count": 0, "passed": True},
        "qa_report": {"verdict": "pass", "skipped": True},
        "sbom": {"components": [{"name": "flask"}]},
        "code_analysis": {"severity": "pass"},
        "iac_security_scan": {"passed": True},
    }
    base.update(overrides)
    return base


def test_policy_blocks_critical_secrets() -> None:
    arts = _sample_artifacts(secrets_scan={"critical_count": 1, "passed": False})
    report = evaluate_policies(arts, unsigned_image=False)
    assert report["passed"] is False
    assert any(v["rule"] == "secrets_detected" for v in report["violations"])


def test_policy_passes_clean_run() -> None:
    report = evaluate_policies(_sample_artifacts(), unsigned_image=False)
    assert report["passed"] is True


def test_compliance_pack_scoring() -> None:
    arts = _sample_artifacts()
    arts["tenant_rbac_context"] = resolve_tenant_context("acme/payments")
    report = evaluate_compliance(arts, pack_ids=["soc2", "owasp"])
    assert report["controls_total"] >= 4
    assert report["overall_score_percent"] >= 80


def test_signed_build_simulated() -> None:
    report = verify_signed_build(commit="abc123", repo="org/app", simulated=True)
    assert report["verified"] is True


def test_signed_build_cosign_verify(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.utils.signed_builds.run_cosign_verify",
        lambda image_ref, **_: {"tool": "cosign", "status": "ok", "verified": True, "image_ref": image_ref},
    )
    report = verify_signed_build(
        commit="abc123def456",
        repo="org/app",
        deployment_info={"image_tag": "registry.example.com/org/app:abc123de"},
        require_signature=True,
        simulated=False,
        cosign_verify_enabled=True,
    )
    assert report["verified"] is True
    assert report["signer"] == "cosign"


def test_tenant_rbac_permissions() -> None:
    tenant = resolve_tenant_context("acme/api", user_roles=["viewer"])
    tenant["rbac_enforced"] = True
    assert tenant["tenant_id"] == "acme"
    assert tenant_allows_action(tenant, "read") is True
    assert tenant_allows_action(tenant, "deploy") is False


def test_finops_cost_breakdown() -> None:
    report = compute_pipeline_cost(
        run_id="run-1",
        repo="org/app",
        duration_seconds=120,
        artifacts={"code_analysis": {"tokens_used": 5000}},
    )
    assert report["total_usd_estimate"] > 0
    assert report["breakdown"]["llm_usd"] > 0


def test_fleet_view_ranks_by_risk() -> None:
    class Run:
        def __init__(self, rid: str, repo: str, status: str) -> None:
            self.id = rid
            self.repo_full_name = repo
            self.status = status

    runs = [Run("a", "org/high", "blocked_code"), Run("b", "org/low", "deployed")]
    arts = {
        "a": {"change_risk_report": {"final_risk": 90}},
        "b": {"change_risk_report": {"final_risk": 10}},
    }
    fleet = build_fleet_view(runs, arts)
    assert fleet["highest_risk_repo"] == "org/high"


def test_audit_explorer_filters() -> None:
    class Run:
        def __init__(self, rid: str, repo: str) -> None:
            self.id = rid
            self.repo_full_name = repo
            self.status = "deployed"

    runs = [Run("1", "org/a")]
    audit = {
        "1": [
            {"ts": "2026-01-01T00:00:00Z", "action": "pipeline.retry", "actor": "ci-bot", "outcome": "queued"}
        ]
    }
    report = explore_audit_events(runs, audit, action_filter="pipeline.retry")
    assert report["total"] == 1


def test_sso_readiness_report() -> None:
    report = assess_sso_readiness()
    assert "providers" in report
    assert "summary" in report
