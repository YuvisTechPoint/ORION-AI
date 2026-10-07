"""ORION knowledge graph — unified repo + service + artifact + incident graph."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.utils.evidence_graph import build_evidence_graph


def _add_node(
    nodes: dict[str, dict[str, Any]],
    node_id: str,
    *,
    node_type: str,
    label: str,
    source: str = "",
    meta: dict[str, Any] | None = None,
) -> None:
    if node_id in nodes:
        return
    nodes[node_id] = {
        "id": node_id,
        "type": node_type,
        "label": label,
        "source": source,
        **(meta or {}),
    }


def _add_edge(edges: list[dict[str, str]], from_id: str, to_id: str, relation: str) -> None:
    edges.append({"from": from_id, "to": to_id, "relation": relation})


def build_knowledge_graph(
    *,
    run_id: str = "",
    repo: str = "",
    commit: str = "",
    branch: str = "",
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []

    if run_id:
        _add_node(nodes, f"run:{run_id}", node_type="pipeline_run", label=run_id[:8], source="pipeline")
    if commit:
        _add_node(nodes, f"commit:{commit}", node_type="commit", label=commit[:8], source="git")
        if run_id:
            _add_edge(edges, f"run:{run_id}", f"commit:{commit}", "produced")
    if repo:
        _add_node(nodes, f"repo:{repo}", node_type="service", label=repo, source="repository")

    # Service graph overlay
    service_graph = artifacts.get("service_graph") or {}
    for name, meta in (service_graph.get("nodes") or {}).items():
        nid = f"svc:{name}"
        _add_node(
            nodes,
            nid,
            node_type=str(meta.get("type") or "service"),
            label=name,
            source=str(meta.get("source") or "service_graph"),
        )
        if repo:
            _add_edge(edges, f"repo:{repo}", nid, "contains")
    for edge in service_graph.get("edges") or []:
        frm = edge.get("from")
        to = edge.get("to")
        if frm and to:
            _add_edge(edges, f"svc:{frm}" if not str(frm).startswith("svc:") else str(frm), f"svc:{to}" if not str(to).startswith("svc:") else str(to), str(edge.get("kind") or "depends_on"))

    # Repository intelligence — frameworks, languages, packages
    repo_intel = artifacts.get("repository_intelligence") or {}
    for lang in repo_intel.get("languages") or []:
        if isinstance(lang, dict):
            lid = f"lang:{lang.get('name', 'unknown')}"
            _add_node(nodes, lid, node_type="framework", label=str(lang.get("name")), source="repository_intelligence")
    for fw in repo_intel.get("frameworks") or []:
        if isinstance(fw, dict):
            fid = f"fw:{fw.get('name', 'unknown')}"
            _add_node(nodes, fid, node_type="framework", label=str(fw.get("name")), source="repository_intelligence")
    for owner in repo_intel.get("owners") or []:
        if isinstance(owner, str) and owner.strip():
            oid = f"owner:{owner}"
            _add_node(nodes, oid, node_type="owner", label=owner, source="codeowners")

    # SBOM dependencies
    sbom = artifacts.get("sbom") or {}
    for comp in (sbom.get("components") or sbom.get("dependencies") or [])[:40]:
        if not isinstance(comp, dict):
            continue
        name = comp.get("name") or comp.get("purl") or "unknown"
        did = f"dep:{name}"
        _add_node(nodes, did, node_type="dependency", label=str(name)[:80], source="sbom", meta={"version": comp.get("version")})
        if repo:
            _add_edge(edges, f"repo:{repo}", did, "depends_on")

    # Changed files
    metadata = artifacts.get("metadata") or {}
    changed = metadata.get("changed_files") or []
    diff = artifacts.get("diff") or {}
    for path in changed[:30] or (diff.get("files") or [])[:30]:
        fid = f"file:{path}"
        _add_node(nodes, fid, node_type="file", label=str(path).split("/")[-1], source="diff", meta={"path": path})
        if commit:
            _add_edge(edges, f"commit:{commit}", fid, "modified")

    # Test intelligence
    test_intel = artifacts.get("test_intelligence") or {}
    for test in (test_intel.get("selected_tests") or test_intel.get("tests") or [])[:20]:
        if isinstance(test, str):
            tid = f"test:{test}"
            _add_node(nodes, tid, node_type="test", label=test.split("/")[-1], source="test_intelligence", meta={"path": test})

    # Key pipeline artifacts as evidence nodes
    for artifact_type in (
        "code_analysis",
        "security_scan",
        "qa_report",
        "change_risk_report",
        "deployment_info",
        "release_passport",
        "incident_commander_report",
    ):
        content = artifacts.get(artifact_type)
        if not content:
            continue
        aid = f"artifact:{artifact_type}"
        _add_node(nodes, aid, node_type="artifact", label=artifact_type, source="pipeline")
        if commit:
            _add_edge(edges, f"commit:{commit}", aid, "produced")

    deployment = artifacts.get("deployment_info") or {}
    if deployment.get("image_tag"):
        dep_id = f"deploy:{deployment['image_tag']}"
        _add_node(nodes, dep_id, node_type="deployment", label=str(deployment["image_tag"]), source="deployment")
        if run_id:
            _add_edge(edges, f"run:{run_id}", dep_id, "deployed")

    # Evidence graph merge (incident chain)
    if run_id and commit and any(artifacts.get(k) for k in ("monitoring_alert", "incident_commander_report")):
        evidence = build_evidence_graph(
            run_id=run_id,
            repo=repo,
            commit=commit,
            branch=branch,
            artifacts=artifacts,
        )
        for node in evidence.get("nodes") or []:
            nid = f"ev:{node.get('id', '')}"
            _add_node(nodes, nid, node_type=str(node.get("type") or "incident"), label=str(node.get("label")), source="evidence_graph")
        for edge in evidence.get("edges") or []:
            _add_edge(edges, f"ev:{edge.get('from')}", f"ev:{edge.get('to')}", str(edge.get("relation") or "links"))

    node_list = list(nodes.values())[:200]
    edge_list = edges[:300]
    return {
        "run_id": run_id or None,
        "repository": repo or None,
        "commit": commit or None,
        "branch": branch or None,
        "node_count": len(node_list),
        "edge_count": len(edge_list),
        "nodes": node_list,
        "edges": edge_list,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": f"Knowledge graph: {len(node_list)} nodes, {len(edge_list)} edges for {repo or 'repository'}.",
    }


def query_knowledge_graph(graph: dict[str, Any], query: str, *, limit: int = 12) -> dict[str, Any]:
    q = (query or "").strip().lower()
    if not q:
        return {"query": query, "matches": [], "paths": [], "summary": "Empty query."}

    tokens = [t for t in q.split() if len(t) > 2]
    matches: list[dict[str, Any]] = []
    for node in graph.get("nodes") or []:
        label = str(node.get("label", "")).lower()
        ntype = str(node.get("type", "")).lower()
        path = str(node.get("path") or (node.get("meta") or {}).get("path", "")).lower()
        source = str(node.get("source", "")).lower()
        score = sum(1 for tok in tokens if tok in label or tok in path or tok in ntype or tok in source)
        if score or q in label or q in path:
            matches.append({**node, "score": score or 1})
    matches.sort(key=lambda n: n.get("score", 0), reverse=True)
    matches = matches[:limit]

    node_ids = {m["id"] for m in matches}
    paths: list[dict[str, Any]] = []
    for edge in graph.get("edges") or []:
        if edge.get("from") in node_ids or edge.get("to") in node_ids:
            paths.append(edge)
    paths = paths[:limit]

    return {
        "query": query,
        "match_count": len(matches),
        "matches": matches,
        "paths": paths,
        "summary": f"Knowledge graph query '{query}': {len(matches)} node(s), {len(paths)} related edge(s).",
    }
