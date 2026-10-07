"""Service catalog intelligence — fleet risk overlay + IDP readiness."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.utils.fleet_view import build_fleet_view
from app.utils.service_catalog import build_service_catalog, merge_fleet_catalogs
from app.utils.service_catalog_registry import build_idp_portal_catalog


def evaluate_catalog_gates(catalog: dict[str, Any]) -> dict[str, Any]:
    violations: list[str] = []
    completeness = int(catalog.get("catalog_completeness_percent") or 0)
    min_complete = int(settings.service_catalog_min_completeness_percent)

    if completeness < min_complete:
        violations.append(f"catalog completeness {completeness}% below {min_complete}%")
    for issue in catalog.get("completeness_issues") or []:
        if "missing owner" in issue:
            violations.append(issue)
            break

    unowned_paths = (catalog.get("ownership") or {}).get("unowned_changed_paths") or []
    if unowned_paths:
        violations.append(f"{len(unowned_paths)} changed path(s) without CODEOWNERS")

    if violations and settings.service_catalog_gate_enabled:
        gate = "fail"
    elif violations:
        gate = "warn"
    else:
        gate = "pass"
    return {"gate_verdict": gate, "violations": violations}


def build_service_catalog_intelligence_report(
    *,
    repo: str = "",
    repo_path: str | None = None,
    artifacts: dict[str, dict[str, Any]] | None = None,
    fleet_runs: list[Any] | None = None,
    fleet_artifacts: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    artifacts = artifacts or {}
    catalog = build_service_catalog(
        repo=repo,
        repo_path=repo_path,
        service_graph=artifacts.get("service_graph"),
        repository_intelligence=artifacts.get("repository_intelligence"),
        cloud_intelligence=artifacts.get("cloud_intelligence"),
    )

    fleet = None
    fleet_catalog = None
    if fleet_runs and fleet_artifacts is not None:
        fleet = build_fleet_view(fleet_runs, fleet_artifacts)
        repo_catalogs: list[dict[str, Any]] = []
        seen_repos: set[str] = set()
        for run in fleet_runs:
            repo_name = str(getattr(run, "repo_full_name", "") or "")
            if not repo_name or repo_name in seen_repos:
                continue
            seen_repos.add(repo_name)
            run_id = str(getattr(run, "id", ""))
            arts = fleet_artifacts.get(run_id) or {}
            repo_catalogs.append(
                build_service_catalog(
                    repo=repo_name,
                    service_graph=arts.get("service_graph"),
                    repository_intelligence=arts.get("repository_intelligence"),
                    cloud_intelligence=arts.get("cloud_intelligence"),
                )
            )
        fleet_catalog = merge_fleet_catalogs(repo_catalogs)
        for svc in fleet_catalog.get("services") or []:
            repo_name = svc.get("repository")
            repo_fleet = next((r for r in fleet.get("repositories") or [] if r.get("repository") == repo_name), None)
            if repo_fleet:
                svc["fleet_risk_score"] = repo_fleet.get("max_risk", 0)
                svc["fleet_status"] = repo_fleet.get("latest_status")

    idp = build_idp_portal_catalog()
    gates = evaluate_catalog_gates(catalog)

    report: dict[str, Any] = {
        "catalog": catalog,
        "fleet": fleet,
        "fleet_catalog": fleet_catalog,
        "idp_portal": idp,
        "gates": gates,
        "gate_verdict": gates["gate_verdict"],
        "analysis_mode": "heuristic",
    }
    report["summary"] = (
        f"Service catalog intel {gates['gate_verdict']}: {catalog.get('service_count', 0)} service(s), "
        f"completeness {catalog.get('catalog_completeness_percent', 0)}%."
    )
    if fleet:
        report["summary"] += f" Fleet highest risk: {fleet.get('highest_risk_repo')} ({fleet.get('highest_risk_score')})."
    return report
