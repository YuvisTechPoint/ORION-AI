"""Multi-cloud deployment target registry and resolution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import settings

CLOUD_TARGETS: list[dict[str, Any]] = [
    {
        "id": "docker_local",
        "provider": "local",
        "runtime": "docker",
        "description": "Local Docker daemon build/run (current ORION default).",
    },
    {
        "id": "docker_compose",
        "provider": "local",
        "runtime": "compose",
        "description": "Docker Compose stack on a single host.",
    },
    {
        "id": "kubernetes",
        "provider": "kubernetes",
        "runtime": "k8s",
        "description": "Kubernetes cluster deploy via manifests or Helm.",
    },
    {
        "id": "aws_ecs",
        "provider": "aws",
        "runtime": "ecs",
        "description": "Amazon ECS/Fargate task deployment.",
    },
    {
        "id": "aws_eks",
        "provider": "aws",
        "runtime": "eks",
        "description": "Amazon EKS cluster target.",
    },
    {
        "id": "azure_aks",
        "provider": "azure",
        "runtime": "aks",
        "description": "Azure Kubernetes Service.",
    },
    {
        "id": "gcp_gke",
        "provider": "gcp",
        "runtime": "gke",
        "description": "Google Kubernetes Engine.",
    },
    {
        "id": "gcp_cloud_run",
        "provider": "gcp",
        "runtime": "cloud_run",
        "description": "Google Cloud Run serverless containers.",
    },
    {
        "id": "simulate",
        "provider": "orion",
        "runtime": "simulate",
        "description": "ORION simulated deploy (no cloud API calls).",
    },
]


def _parse_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text or text == "{}":
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _repo_signals(repo_path: str | None) -> dict[str, bool]:
    if not repo_path:
        return {}
    root = Path(repo_path)
    if not root.is_dir():
        return {}
    has_dockerfile = (root / "Dockerfile").is_file()
    has_compose = any((root / name).is_file() for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml"))
    has_k8s = any(
        p.is_file() and ("k8s" in p.as_posix().lower() or "kubernetes" in p.as_posix().lower() or p.name in ("deployment.yaml", "service.yaml"))
        for p in list(root.glob("**/*.yaml"))[:200]
    )
    has_helm = any(root.glob("**/Chart.yaml"))
    has_tf_aws = any(root.glob("**/*.tf")) and any(
        "aws_" in p.read_text(encoding="utf-8", errors="replace")[:5000]
        for p in list(root.glob("**/*.tf"))[:20]
        if p.is_file()
    )
    has_tf_azure = any("azurerm_" in p.read_text(encoding="utf-8", errors="replace")[:5000] for p in list(root.glob("**/*.tf"))[:20] if p.is_file())
    has_tf_gcp = any("google_" in p.read_text(encoding="utf-8", errors="replace")[:5000] for p in list(root.glob("**/*.tf"))[:20] if p.is_file())
    return {
        "dockerfile": has_dockerfile,
        "compose": has_compose,
        "kubernetes": has_k8s or has_helm,
        "helm": has_helm,
        "terraform_aws": has_tf_aws,
        "terraform_azure": has_tf_azure,
        "terraform_gcp": has_tf_gcp,
    }


def resolve_cloud_target(
    *,
    repo_path: str | None = None,
    repo: str = "",
    environment: str | None = None,
    deploy_mode: str | None = None,
    signals: dict[str, bool] | None = None,
) -> dict[str, Any]:
    env = environment or settings.deploy_environment
    mode = (deploy_mode or settings.deploy_mode or "auto").lower()
    sig = signals or _repo_signals(repo_path)
    org = repo.split("/", 1)[0] if "/" in repo else repo

    overrides = _parse_json(settings.cloud_target_json)
    repo_block = overrides.get(repo) if isinstance(overrides.get(repo), dict) else {}
    org_block = overrides.get(org) if isinstance(overrides.get(org), dict) else {}
    preferred = (
        (settings.cloud_deploy_target or "").strip()
        or str(repo_block.get("target") or "")
        or str(org_block.get("target") or "")
    )

    scores: dict[str, int] = {}
    if sig.get("kubernetes") or sig.get("helm"):
        scores["kubernetes"] = scores.get("kubernetes", 0) + 40
        if sig.get("helm"):
            scores["kubernetes"] = scores.get("kubernetes", 0) + 10
    if sig.get("compose"):
        scores["docker_compose"] = scores.get("docker_compose", 0) + 25
    if sig.get("dockerfile"):
        scores["docker_local"] = scores.get("docker_local", 0) + 20
    if sig.get("terraform_aws"):
        scores["aws_eks"] = scores.get("aws_eks", 0) + 15
        scores["aws_ecs"] = scores.get("aws_ecs", 0) + 20
    if sig.get("terraform_azure"):
        scores["azure_aks"] = scores.get("azure_aks", 0) + 25
    if sig.get("terraform_gcp"):
        scores["gcp_gke"] = scores.get("gcp_gke", 0) + 20
        scores["gcp_cloud_run"] = scores.get("gcp_cloud_run", 0) + 15

    if mode in {"simulate", "skip"}:
        scores["simulate"] = 100
    elif mode == "docker" and not scores:
        scores["docker_local"] = 30

    if preferred:
        scores[preferred] = scores.get(preferred, 0) + 100

    if env == "production" and "kubernetes" in scores:
        scores["kubernetes"] = scores.get("kubernetes", 0) + 10

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    primary = ranked[0][0] if ranked else ("simulate" if mode in {"simulate", "skip"} else "docker_local")
    catalog = {t["id"]: t for t in CLOUD_TARGETS}
    primary_meta = catalog.get(primary, catalog["docker_local"])

    return {
        "primary_target": primary,
        "primary_provider": primary_meta.get("provider"),
        "primary_runtime": primary_meta.get("runtime"),
        "recommended_targets": [tid for tid, _ in ranked[:4]] or [primary],
        "scores": [{"target": tid, "score": score} for tid, score in ranked[:6]],
        "repo_signals": sig,
        "environment": env,
        "deploy_mode": mode,
        "configured_target": preferred or None,
        "summary": f"Recommended cloud target: {primary} ({primary_meta.get('provider')}/{primary_meta.get('runtime')}).",
    }


def build_cloud_target_catalog() -> dict[str, Any]:
    return {
        "targets": CLOUD_TARGETS,
        "count": len(CLOUD_TARGETS),
        "default_hint": settings.cloud_deploy_target or "auto",
        "summary": f"{len(CLOUD_TARGETS)} cloud deployment target(s) registered.",
    }
