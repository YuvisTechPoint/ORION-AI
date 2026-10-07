"""Tests for Phase 16 service catalog / IDP intelligence."""

from __future__ import annotations

import json
from pathlib import Path

from app.utils.service_catalog import build_service_catalog, merge_fleet_catalogs
from app.utils.service_catalog_intelligence import (
    build_service_catalog_intelligence_report,
    evaluate_catalog_gates,
)
from app.utils.service_catalog_registry import build_idp_portal_catalog, resolve_catalog_overrides
from app.utils.service_graph import build_service_graph


COMPOSE = """\
version: '3'
services:
  api:
    build: .
    depends_on:
      - redis
  redis:
    image: redis:7
"""


def test_build_service_catalog_from_compose(tmp_path: Path):
    (tmp_path / "docker-compose.yml").write_text(COMPOSE, encoding="utf-8")
    (tmp_path / "CODEOWNERS").write_text("* @platform-team\n", encoding="utf-8")
    graph = build_service_graph(str(tmp_path))
    catalog = build_service_catalog(
        repo="acme/api",
        repo_path=str(tmp_path),
        service_graph=graph,
    )
    names = {s["name"] for s in catalog["services"]}
    assert "api" in names
    assert "redis" in names
    assert catalog["service_count"] >= 2
    assert catalog["catalog_completeness_percent"] >= 60


def test_catalog_json_override(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "app.utils.service_catalog_registry.settings.service_catalog_json",
        json.dumps(
            {
                "acme/api": {
                    "team": "@payments",
                    "services": {
                        "api": {
                            "display_name": "Payments API",
                            "tier": "tier-0",
                            "owners": ["@payments-oncall"],
                            "health_endpoint": "/v1/health",
                        }
                    },
                }
            }
        ),
    )
    (tmp_path / "docker-compose.yml").write_text(COMPOSE, encoding="utf-8")
    graph = build_service_graph(str(tmp_path))
    catalog = build_service_catalog(repo="acme/api", repo_path=str(tmp_path), service_graph=graph)
    api = next(s for s in catalog["services"] if s["id"] == "api")
    assert api["name"] == "Payments API"
    assert api["tier"] == "tier-0"
    assert api["health_endpoint"] == "/v1/health"


def test_merge_fleet_catalogs():
    merged = merge_fleet_catalogs(
        [
            {"repository": "acme/api", "services": [{"id": "api", "name": "api"}]},
            {"repository": "acme/web", "services": [{"id": "web", "name": "web"}]},
        ]
    )
    assert merged["repository_count"] == 2
    assert merged["service_count"] == 2
    assert {s["repository"] for s in merged["services"]} == {"acme/api", "acme/web"}


def test_evaluate_catalog_gates_fail_on_low_completeness(monkeypatch):
    monkeypatch.setattr("app.utils.service_catalog_intelligence.settings.service_catalog_gate_enabled", True)
    monkeypatch.setattr(
        "app.utils.service_catalog_intelligence.settings.service_catalog_min_completeness_percent", 90
    )
    gates = evaluate_catalog_gates({"catalog_completeness_percent": 50, "completeness_issues": []})
    assert gates["gate_verdict"] == "fail"
    assert gates["violations"]


def test_build_service_catalog_intelligence_report(tmp_path: Path):
    (tmp_path / "docker-compose.yml").write_text(COMPOSE, encoding="utf-8")
    report = build_service_catalog_intelligence_report(
        repo="acme/api",
        repo_path=str(tmp_path),
        artifacts={},
    )
    assert report["catalog"]["service_count"] >= 2
    assert report["idp_portal"]["golden_paths"]
    assert report["gate_verdict"] in {"pass", "warn", "fail"}


def test_idp_portal_catalog():
    portal = build_idp_portal_catalog()
    assert len(portal["golden_paths"]) >= 4
    assert portal["self_service_actions"]


def test_resolve_catalog_overrides_org_and_repo(monkeypatch):
    monkeypatch.setattr(
        "app.utils.service_catalog_registry.settings.service_catalog_json",
        json.dumps(
            {
                "acme": {"team": "@acme-platform"},
                "acme/api": {"tier": "tier-0", "links": {"docs": "https://docs.acme/api"}},
            }
        ),
    )
    overrides = resolve_catalog_overrides("acme/api")
    assert overrides["team"] == "@acme-platform"
    assert overrides["tier"] == "tier-0"
    assert overrides["links"]["docs"] == "https://docs.acme/api"
