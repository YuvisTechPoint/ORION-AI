"""Tests for Phase 15 Kubernetes / cloud intelligence."""

from __future__ import annotations

import json
from pathlib import Path

from app.utils.cloud_intelligence import build_cloud_intelligence_report, evaluate_cloud_gates
from app.utils.cloud_target_registry import build_cloud_target_catalog, resolve_cloud_target
from app.utils.kubernetes_manifest import scan_kubernetes_manifests


SAMPLE_DEPLOYMENT = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: api
        image: myapp:latest
        ports:
        - containerPort: 8000
"""


def test_scan_kubernetes_manifest_finds_probe_gaps(tmp_path: Path):
    manifest = tmp_path / "k8s" / "deployment.yaml"
    manifest.parent.mkdir()
    manifest.write_text(SAMPLE_DEPLOYMENT, encoding="utf-8")
    report = scan_kubernetes_manifests(str(tmp_path))
    assert report["manifests_scanned"] == 1
    rules = {f["rule"] for f in report["findings"]}
    assert "missing_liveness_probe" in rules
    assert "missing_readiness_probe" in rules
    assert "latest_tag" in rules


def test_privileged_pod_is_critical(tmp_path: Path):
    manifest = tmp_path / "deploy.yaml"
    manifest.write_text(
        "apiVersion: v1\nkind: Pod\nmetadata:\n  name: bad\nspec:\n  containers:\n  - name: c\n    image: x:1\n    securityContext:\n      privileged: true\n",
        encoding="utf-8",
    )
    report = scan_kubernetes_manifests(str(tmp_path))
    assert report["critical_count"] >= 1
    assert report["passed"] is False


def test_resolve_cloud_target_kubernetes_signals(tmp_path: Path):
    (tmp_path / "k8s").mkdir()
    (tmp_path / "k8s" / "deployment.yaml").write_text(SAMPLE_DEPLOYMENT, encoding="utf-8")
    resolved = resolve_cloud_target(repo_path=str(tmp_path), repo="acme/api")
    assert resolved["primary_target"] == "kubernetes"
    assert "kubernetes" in resolved["recommended_targets"]


def test_cloud_target_json_override(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "app.utils.cloud_target_registry.settings.cloud_target_json",
        json.dumps({"acme/api": {"target": "gcp_cloud_run"}}),
    )
    resolved = resolve_cloud_target(repo_path=str(tmp_path), repo="acme/api")
    assert resolved["primary_target"] == "gcp_cloud_run"


def test_build_cloud_intelligence_report(tmp_path: Path):
    k8s = scan_kubernetes_manifests(str(tmp_path))
    report = build_cloud_intelligence_report(
        repo="acme/api",
        repo_path=str(tmp_path),
        kubernetes_manifest_scan=k8s,
        iac_security_scan={"critical_count": 0, "passed": True},
        container_security_scan={"passed": True},
    )
    assert report["cloud_target"]["primary_target"]
    assert "gate_verdict" in report


def test_cloud_gate_fails_on_critical_k8s(monkeypatch):
    monkeypatch.setattr("app.utils.cloud_intelligence.settings.cloud_intelligence_gate_enabled", True)
    gates = evaluate_cloud_gates(
        kubernetes_manifest_scan={"critical_count": 1, "high_count": 0, "passed": False},
        iac_security_scan={"critical_count": 0, "passed": True},
        container_security_scan={"passed": True},
        dockerfile_analysis={"security_score": 90},
    )
    assert gates["gate_verdict"] == "fail"


def test_cloud_target_catalog():
    catalog = build_cloud_target_catalog()
    assert catalog["count"] >= 8
    ids = {t["id"] for t in catalog["targets"]}
    assert "kubernetes" in ids
    assert "aws_ecs" in ids
