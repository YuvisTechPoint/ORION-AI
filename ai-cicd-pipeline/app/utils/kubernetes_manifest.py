"""Kubernetes manifest analysis — probes, privileges, rollouts, and RBAC heuristics."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.config import settings

_K8S_PATH_HINTS = ("k8s", "kubernetes", "deploy", "manifest", "helm", "charts")
_K8S_FILENAMES = frozenset(
    {
        "deployment.yaml",
        "deployment.yml",
        "service.yaml",
        "service.yml",
        "ingress.yaml",
        "ingress.yml",
        "hpa.yaml",
        "pdb.yaml",
        "networkpolicy.yaml",
    }
)
_KIND_RE = re.compile(r"^kind:\s*(\w+)\s*$", re.MULTILINE)
_NAME_RE = re.compile(r"^\s*name:\s*(.+)\s*$", re.MULTILINE)
_NAMESPACE_RE = re.compile(r"^\s*namespace:\s*(.+)\s*$", re.MULTILINE)


def _is_k8s_manifest(path: Path, *, root: Path | None = None) -> bool:
    if root is not None:
        try:
            rel = path.relative_to(root).as_posix().lower()
        except ValueError:
            rel = path.name.lower()
    else:
        rel = path.name.lower()
    if any(part in {"test", "tests", "__tests__"} for part in Path(rel).parts):
        return False
    if any(x in rel for x in (".git/", "node_modules/", "vendor/")):
        return False
    if path.name.lower() in _K8S_FILENAMES:
        return True
    if not path.name.endswith((".yaml", ".yml")):
        return False
    if any(hint in rel for hint in _K8S_PATH_HINTS):
        return True
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return False
    return "apiVersion:" in head and _KIND_RE.search(head) is not None


def _split_yaml_docs(text: str) -> list[str]:
    docs: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        if line.strip() == "---":
            if buf:
                docs.append("\n".join(buf))
                buf = []
            continue
        buf.append(line)
    if buf:
        docs.append("\n".join(buf))
    return docs


def _doc_meta(doc: str) -> dict[str, str]:
    kind = (_KIND_RE.search(doc).group(1) if _KIND_RE.search(doc) else "") or "Unknown"
    name = (_NAME_RE.search(doc).group(1).strip() if _NAME_RE.search(doc) else "") or "unnamed"
    namespace = (_NAMESPACE_RE.search(doc).group(1).strip() if _NAMESPACE_RE.search(doc) else "default")
    return {"kind": kind, "name": name, "namespace": namespace}


def _finding(
    *,
    rule: str,
    severity: str,
    file: str,
    resource: str,
    description: str,
    recommendation: str,
) -> dict[str, Any]:
    return {
        "rule": rule,
        "severity": severity,
        "file": file,
        "resource": resource,
        "description": description,
        "recommendation": recommendation,
    }


def _analyze_doc(doc: str, *, file: str) -> list[dict[str, Any]]:
    meta = _doc_meta(doc)
    kind = meta["kind"]
    resource = f"{kind}/{meta['name']}"
    findings: list[dict[str, Any]] = []
    lower = doc.lower()

    if kind == "Deployment":
        if "livenessprobe:" not in lower:
            findings.append(
                _finding(
                    rule="missing_liveness_probe",
                    severity="high",
                    file=file,
                    resource=resource,
                    description="Deployment without livenessProbe",
                    recommendation="Add livenessProbe so kubelet can restart unhealthy pods.",
                )
            )
        if "readinessprobe:" not in lower:
            findings.append(
                _finding(
                    rule="missing_readiness_probe",
                    severity="high",
                    file=file,
                    resource=resource,
                    description="Deployment without readinessProbe",
                    recommendation="Add readinessProbe to keep not-ready pods out of Service endpoints.",
                )
            )
        if "resources:" not in lower:
            findings.append(
                _finding(
                    rule="missing_resource_limits",
                    severity="medium",
                    file=file,
                    resource=resource,
                    description="Deployment containers missing resources requests/limits",
                    recommendation="Set cpu/memory requests and limits for scheduling and noisy-neighbor protection.",
                )
            )
        if re.search(r"replicas:\s*1\b", doc) and settings.deploy_environment == "production":
            findings.append(
                _finding(
                    rule="single_replica_production",
                    severity="medium",
                    file=file,
                    resource=resource,
                    description="Single replica Deployment in production-like environment",
                    recommendation="Run at least 2 replicas with PodDisruptionBudget for HA.",
                )
            )
        if "strategy:" not in lower:
            findings.append(
                _finding(
                    rule="missing_rollout_strategy",
                    severity="low",
                    file=file,
                    resource=resource,
                    description="No explicit Deployment rollout strategy",
                    recommendation="Use rollingUpdate with maxUnavailable/maxSurge for safer rollouts.",
                )
            )

    if kind in {"Deployment", "StatefulSet", "DaemonSet", "Pod"}:
        if re.search(r"privileged:\s*true", doc, re.I):
            findings.append(
                _finding(
                    rule="privileged_container",
                    severity="critical",
                    file=file,
                    resource=resource,
                    description="Privileged container detected",
                    recommendation="Set securityContext.privileged=false and drop unnecessary capabilities.",
                )
            )
        if re.search(r"hostnetwork:\s*true", doc, re.I):
            findings.append(
                _finding(
                    rule="host_network",
                    severity="high",
                    file=file,
                    resource=resource,
                    description="Pod uses hostNetwork",
                    recommendation="Avoid hostNetwork unless required; use ClusterIP Services instead.",
                )
            )
        if "runasnonroot:" in lower and re.search(r"runasnonroot:\s*false", doc, re.I):
            findings.append(
                _finding(
                    rule="runs_as_root",
                    severity="high",
                    file=file,
                    resource=resource,
                    description="Container explicitly runs as root",
                    recommendation="Set securityContext.runAsNonRoot=true and runAsUser >= 1000.",
                )
            )
        elif "securitycontext:" not in lower and kind in {"Deployment", "Pod"}:
            findings.append(
                _finding(
                    rule="missing_security_context",
                    severity="medium",
                    file=file,
                    resource=resource,
                    description="No pod/container securityContext defined",
                    recommendation="Set runAsNonRoot, readOnlyRootFilesystem where possible, and drop ALL capabilities.",
                )
            )
        if re.search(r"image:\s*[^\s:]+:latest\b", doc, re.I):
            findings.append(
                _finding(
                    rule="latest_tag",
                    severity="medium",
                    file=file,
                    resource=resource,
                    description="Container image uses :latest tag",
                    recommendation="Pin images by digest or immutable version tag.",
                )
            )

    if kind == "Secret" and re.search(r"(?i)(password|token|apikey|private_key)\s*:\s*['\"][^'\"]{6,}", doc):
        findings.append(
            _finding(
                rule="literal_secret_data",
                severity="critical",
                file=file,
                resource=resource,
                description="Literal secret value in manifest",
                recommendation="Use ExternalSecrets, SealedSecrets, or cloud secret manager references.",
            )
        )

    if kind == "Service" and re.search(r"type:\s*LoadBalancer", doc, re.I):
        if "0.0.0.0/0" in doc:
            findings.append(
                _finding(
                    rule="open_load_balancer",
                    severity="critical",
                    file=file,
                    resource=resource,
                    description="LoadBalancer allows 0.0.0.0/0",
                    recommendation="Restrict source ranges and use internal load balancers when possible.",
                )
            )

    if kind == "Ingress" and "tls:" not in lower:
        findings.append(
            _finding(
                rule="ingress_without_tls",
                severity="medium",
                file=file,
                resource=resource,
                description="Ingress without TLS section",
                recommendation="Configure TLS hosts and cert-manager or cloud-managed certificates.",
            )
        )

    if kind in {"Role", "ClusterRole"} and re.search(r"- '\*'", doc):
        findings.append(
            _finding(
                rule="wildcard_rbac",
                severity="high",
                file=file,
                resource=resource,
                description="RBAC role grants wildcard permissions",
                recommendation="Scope verbs/resources to least privilege required.",
            )
        )

    return findings


def scan_kubernetes_manifests(repo_path: str, *, changed_files: list[str] | None = None) -> dict[str, Any]:
    root = Path(repo_path)
    paths: list[Path] = []
    if changed_files:
        for rel in changed_files:
            candidate = root / rel.replace("\\", "/")
            if candidate.is_file() and _is_k8s_manifest(candidate, root=root):
                paths.append(candidate)
    else:
        for pattern in ("**/*.yaml", "**/*.yml"):
            for candidate in root.glob(pattern):
                if _is_k8s_manifest(candidate, root=root):
                    paths.append(candidate)

    seen: set[str] = set()
    findings: list[dict[str, Any]] = []
    resources: list[dict[str, Any]] = []
    for path in paths:
        rel = path.relative_to(root).as_posix()
        if rel in seen:
            continue
        seen.add(rel)
        text = path.read_text(encoding="utf-8", errors="replace")[:200_000]
        for doc in _split_yaml_docs(text):
            if "apiVersion:" not in doc:
                continue
            meta = _doc_meta(doc)
            resources.append({"file": rel, **meta})
            findings.extend(_analyze_doc(doc, file=rel))

    critical = sum(1 for f in findings if f.get("severity") == "critical")
    high = sum(1 for f in findings if f.get("severity") == "high")
    kinds = sorted({r["kind"] for r in resources})
    return {
        "manifests_scanned": len(seen),
        "resources_found": len(resources),
        "kinds": kinds,
        "finding_count": len(findings),
        "critical_count": critical,
        "high_count": high,
        "passed": critical == 0,
        "findings": findings[:60],
        "resources": resources[:40],
        "summary": (
            f"Scanned {len(seen)} K8s manifest(s), {len(resources)} resource(s); "
            f"{len(findings)} finding(s) ({critical} critical, {high} high)."
        ),
        "analysis_mode": "heuristic",
    }
