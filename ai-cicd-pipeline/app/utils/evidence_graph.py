"""ORION evidence graph — relational chain across pipeline artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def build_evidence_graph(
    *,
    run_id: str,
    repo: str,
    commit: str,
    branch: str,
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    incident_id = f"INC-{run_id[:8]}"
    nodes: list[dict[str, Any]] = [
        {"id": run_id, "type": "pipeline_run", "label": run_id[:8]},
        {"id": commit, "type": "commit", "label": commit[:8]},
        {"id": incident_id, "type": "incident", "label": incident_id},
    ]
    edges: list[dict[str, str]] = [
        {"from": run_id, "to": commit, "relation": "deployed"},
    ]

    chain_map = {
        "code_analysis": "code_analysis",
        "security_scan": "security_finding",
        "qa_report": "test_result",
        "change_risk_report": "risk_assessment",
        "deployment_info": "deployment",
        "progressive_delivery": "canary_stage",
        "monitoring_alert": "alert",
        "rollback_intelligence": "rollback_decision",
        "release_passport": "release",
    }

    for artifact_type, node_type in chain_map.items():
        content = artifacts.get(artifact_type)
        if not content:
            continue
        node_id = f"{artifact_type}:{run_id[:8]}"
        nodes.append({"id": node_id, "type": node_type, "label": artifact_type})
        edges.append({"from": commit, "to": node_id, "relation": "produced"})
        if artifact_type in {"monitoring_alert", "rollback_intelligence"}:
            edges.append({"from": node_id, "to": incident_id, "relation": "triggered"})

    diff = artifacts.get("diff") or {}
    for path in (diff.get("files") or [])[:8]:
        fid = f"file:{path}"
        nodes.append({"id": fid, "type": "file", "label": path})
        edges.append({"from": commit, "to": fid, "relation": "modified"})

    return {
        "incident_id": incident_id,
        "run_id": run_id,
        "repository": repo,
        "branch": branch,
        "commit": commit,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes[:100],
        "edges": edges[:150],
    }
