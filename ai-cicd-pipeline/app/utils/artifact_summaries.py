"""Human-readable summaries and verdicts for pipeline artifacts (dashboard + WebSocket)."""

from __future__ import annotations

import json
from typing import Any


def _clip(text: str, limit: int = 500) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _string_field(content: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _sbom_stats(content: dict[str, Any]) -> dict[str, Any]:
    stats = content.get("stats")
    if isinstance(stats, dict):
        return stats
    legacy = content.get("summary")
    if isinstance(legacy, dict):
        return legacy
    return {}


def summarize_artifact(artifact_type: str, content: Any) -> str:
    """Return a one-line summary for an artifact payload."""
    if not isinstance(content, dict):
        return ""

    direct = _string_field(content, "summary", "reason", "error", "reasoning", "root_cause")
    if direct:
        return _clip(direct)

    if artifact_type == "metadata":
        files = len(content.get("changed_files") or [])
        msg = str(content.get("commit_message") or "").split("\n")[0]
        return _clip(f"“{msg}” · {files} changed file(s)" if msg else f"{files} changed file(s)")

    if artifact_type == "diff":
        diff = str(content.get("diff") or "")
        adds = len([ln for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++")])
        dels = len([ln for ln in diff.splitlines() if ln.startswith("-") and not ln.startswith("---")])
        truncated = " (truncated)" if content.get("truncated") else ""
        return f"+{adds} / −{dels} lines{truncated}"

    if artifact_type == "full_scan_combined":
        parts: list[str] = []
        for label, key in (("code", "code_issues"), ("security", "security_issues"), ("qa", "qa_issues")):
            block = content.get(key) or content.get(label)
            if isinstance(block, dict):
                if label == "code":
                    parts.append(f"code: {block.get('severity', '?')}")
                elif label == "security":
                    parts.append(f"security: {block.get('highest_severity', '?')}")
                else:
                    parts.append(f"qa: {block.get('verdict', '?')}")
        return " · ".join(parts) if parts else "Combined scan results"

    if artifact_type == "service_graph":
        nodes = int(content.get("node_count") or len(content.get("nodes") or {}))
        edges = int(content.get("edge_count") or len(content.get("edges") or []))
        root = content.get("root_service") or "app"
        changed = content.get("changed_services") or []
        changed_part = f"; touched {', '.join(changed[:4])}" if changed else ""
        if len(changed) > 4:
            changed_part += f" +{len(changed) - 4} more"
        return f"{nodes} service(s), {edges} link(s) from {root}{changed_part}."

    if artifact_type == "sbom":
        stats = _sbom_stats(content)
        count = int(stats.get("component_count") or len(content.get("components") or []))
        sources = stats.get("sources") or []
        src = ", ".join(sources) if sources else "dependency manifests"
        return f"CycloneDX SBOM: {count} component(s) from {src}."

    if artifact_type == "supply_chain_report":
        posture = content.get("posture") or "unknown"
        locks = len(content.get("lockfiles") or [])
        cves = len(content.get("cve_references") or [])
        return _clip(f"Supply chain {posture}: {locks} lockfile(s), {cves} CVE reference(s).")

    if artifact_type == "performance_intelligence":
        gate = content.get("gate_verdict")
        current = content.get("current") or {}
        baseline = content.get("baseline_comparison") or {}
        profile = (content.get("stress_profile") or {}).get("name") or "standard"
        return _clip(
            f"Performance {gate or '?'}: profile={profile}, p95={current.get('p95_ms')}ms, "
            f"baseline Δ={baseline.get('p95_delta_percent')}%."
        )

    if artifact_type == "deployment_intelligence":
        gate = content.get("gate_verdict")
        strategy = (content.get("strategy") or {}).get("selected") or "canary"
        env = (content.get("deployment") or {}).get("environment") or "staging"
        slo = (content.get("slo_rollback") or {}).get("verdict") or "?"
        return _clip(f"Deploy {gate or '?'}: env={env}, strategy={strategy}, slo={slo}.")

    if artifact_type == "observability_intelligence":
        gate = content.get("gate_verdict")
        corr = (content.get("deploy_correlation") or {}).get("correlation_confidence")
        anomalies = (content.get("metric_anomalies") or {}).get("anomaly_count", 0)
        monitoring = (content.get("deploy_correlation") or {}).get("monitoring_status") or "?"
        return _clip(f"Observability {gate or '?'}: corr={corr}, anomalies={anomalies}, monitoring={monitoring}.")

    if artifact_type == "incident_intelligence":
        gate = content.get("gate_verdict")
        lifecycle = content.get("lifecycle") or {}
        sev = content.get("severity") or "?"
        status = lifecycle.get("status") or "?"
        iid = content.get("incident_id") or "?"
        return _clip(f"Incident {iid} {status} ({sev}); gate={gate or '?'}.")

    if artifact_type == "remediation_intelligence":
        gate = content.get("gate_verdict")
        autonomy = (content.get("autonomy") or {}).get("achieved_level") or "?"
        action = ((content.get("patch") or {}).get("aggregate_confidence") or {}).get("action") or "?"
        return _clip(f"Remediation {gate or '?'}: level {autonomy}, action={action}.")

    if artifact_type == "code_review_intelligence":
        gate = content.get("gate_verdict") or (content.get("gates") or {}).get("gate_verdict")
        score = content.get("overall_score")
        bug = (content.get("bug_prediction") or {}).get("probability_percent")
        layers = content.get("layers") or {}
        failed = [k for k, v in layers.items() if isinstance(v, dict) and v.get("verdict") == "fail"]
        parts = [f"score {score}/100"]
        if bug is not None:
            parts.append(f"bug risk {bug}%")
        if gate:
            parts.append(f"gate {gate}")
        if failed:
            parts.append(f"failed: {', '.join(failed[:3])}")
        return _clip("; ".join(parts))

    if artifact_type == "test_intelligence":
        mode = content.get("mode") or "full_suite"
        gate = content.get("gate_verdict") or (content.get("gates") or {}).get("gate_verdict")
        flaky = (content.get("flaky_analysis") or {}).get("flaky_count", 0)
        selected = len(content.get("selected_tests") or [])
        cov = (content.get("coverage_regression") or {}).get("current_percent")
        if gate:
            base = f"Gate {gate}: mode={mode}"
        elif mode == "selected" and selected:
            base = f"Targeted run: {selected} test file(s) for changed modules."
        else:
            base = f"Test mode: {mode}."
        if cov is not None:
            base += f" Coverage {cov}%."
        if flaky:
            base += f" {flaky} flaky indicator(s)."
        return _clip(base)

    if artifact_type == "repository_intelligence":
        stack = content.get("stack") or {}
        langs = ", ".join(l["name"] for l in stack.get("languages") or []) or "unknown"
        mono = "monorepo" if (content.get("monorepo") or {}).get("detected") else "single-package"
        lic = (content.get("licenses") or {}).get("primary") or "unknown license"
        fp = (content.get("fingerprint") or {}).get("sha256", "")[:12]
        base = _string_field(content, "summary")
        if base:
            return _clip(base)
        return f"{mono}; {langs}; license {lic}; fingerprint {fp}."

    if artifact_type == "change_risk_report":
        risk = content.get("final_risk", "—")
        level = content.get("risk_level", "unknown")
        files = (content.get("change_summary") or {}).get("files_changed")
        file_part = f", {files} file(s)" if files is not None else ""
        recs = content.get("recommendations") or []
        tail = f" — {recs[0]}" if recs else ""
        return _clip(f"Change risk {risk}/100 ({level}){file_part}{tail}")

    if artifact_type == "developer_ux_intelligence":
        readiness = content.get("readiness") or {}
        score = readiness.get("readiness_score", "—")
        return _clip(content.get("summary") or f"Developer UX readiness {score}%.")

    if artifact_type == "release_intelligence":
        passport = content.get("release_passport") or {}
        prediction = content.get("release_prediction") or {}
        gate = content.get("gate_verdict") or "?"
        prob = prediction.get("failure_probability_percent", "—")
        status = "PASS" if passport.get("all_checks_passed") else "WARN"
        return _clip(
            content.get("summary")
            or f"Release intel {gate}: passport {status}, failure prob {prob}%."
        )

    if artifact_type == "release_passport":
        status = "PASS" if content.get("all_checks_passed") else "WARN"
        evidence = content.get("evidence_artifact_count", 0)
        risk = (content.get("risk") or {}).get("final_score", "—")
        level = (content.get("risk") or {}).get("level", "unknown")
        tests = content.get("tests") or {}
        tests_line = f"{tests.get('passed', 0)}/{tests.get('total', 0)} tests"
        return (
            f"Release passport {status}: {evidence} evidence artifact(s), "
            f"risk {risk}/100 ({level}), {tests_line}."
        )

    if artifact_type == "audit_trail":
        events = content.get("events") or []
        if not events:
            return "No audit events recorded."
        last = events[-1]
        return _clip(
            f"{len(events)} event(s); latest: {last.get('action', 'action')} "
            f"by {last.get('actor', 'system')} ({last.get('outcome', 'ok')})."
        )

    if artifact_type == "deployment_info":
        if content.get("simulated"):
            return _string_field(content, "summary") or f"Simulated deploy of {content.get('image_tag', 'image')}."
        if content.get("success") is False:
            return _string_field(content, "summary", "error") or "Deployment failed."
        image = content.get("image_tag") or content.get("image")
        env = content.get("environment") or "staging"
        health = "healthy" if content.get("health_check_passed") else "unhealthy"
        return _clip(f"Deployed {image or 'image'} to {env} ({health}).")

    if artifact_type == "last_known_good_image":
        image = content.get("image") or content.get("image_tag") or "unknown"
        sim = " (simulated)" if content.get("simulated") else ""
        return f"Rollback target: {image}{sim}."

    if artifact_type == "monitoring_summary":
        checks = content.get("checks_performed", 0)
        alerts = content.get("alerts", 0)
        final = content.get("final_status") or "unknown"
        sim = " (simulated)" if content.get("simulated") else ""
        base = _string_field(content, "summary")
        if base:
            return _clip(base)
        return f"{checks} check(s), {alerts} alert(s), final status {final}{sim}."

    if artifact_type == "monitoring_alert":
        sev = content.get("severity") or "alert"
        metric = content.get("metric") or content.get("check") or "metric"
        return _clip(f"{sev}: {metric} — {_string_field(content, 'message', 'detail') or 'threshold breached'}")

    if artifact_type == "approval":
        decision = content.get("decision") or "pending"
        conf = content.get("confidence")
        conf_part = f", confidence {int(float(conf) * 100)}%" if conf is not None else ""
        reason = _string_field(content, "reasoning", "reason")
        return _clip(f"Decision: {decision}{conf_part}. {reason}".strip())

    if artifact_type == "enterprise_approval":
        status = content.get("status") or "pending"
        received = content.get("received_approvals", 0)
        required = content.get("required_approvals", 1)
        return _clip(content.get("summary") or f"Enterprise approval {status}: {received}/{required} sign-off(s).")

    if artifact_type == "approval_intelligence":
        gate = content.get("gate_verdict") or "?"
        auto = (content.get("automated_approval") or {}).get("decision")
        ent = (content.get("enterprise_approval") or {}).get("status")
        return _clip(
            f"Approval intel {gate}: auto={auto}, enterprise={ent}."
        )

    if artifact_type == "multimodal_intelligence":
        gate = content.get("gate_verdict") or "?"
        count = content.get("agents_present", 0)
        return _clip(content.get("summary") or f"Multimodal intel {gate}: {count} agent artifact(s).")

    if artifact_type == "ci_build_log_analysis":
        platform = content.get("ci_platform") or "ci"
        failed = len(content.get("failed_stages") or [])
        return _clip(content.get("summary") or f"{platform}: {failed} failed stage(s).")

    if artifact_type == "metrics_snapshot_analysis":
        anomalies = len(content.get("anomalies") or [])
        fmt = content.get("format") or "metrics"
        return _clip(content.get("summary") or f"{fmt}: {anomalies} anomaly/anomalies.")

    if artifact_type == "kubernetes_manifest_scan":
        return _clip(
            content.get("summary")
            or f"K8s scan: {content.get('finding_count', 0)} finding(s), {content.get('critical_count', 0)} critical."
        )

    if artifact_type == "cloud_intelligence":
        target = (content.get("cloud_target") or {}).get("primary_target")
        gate = content.get("gate_verdict") or "?"
        return _clip(content.get("summary") or f"Cloud intel {gate}; target={target}.")

    if artifact_type == "service_catalog":
        count = content.get("service_count", 0)
        pct = content.get("catalog_completeness_percent", 0)
        return _clip(content.get("summary") or f"Service catalog: {count} service(s), {pct}% complete.")

    if artifact_type == "rag_intelligence":
        count = content.get("chunk_count", 0)
        gate = "grounded" if content.get("grounded") else "ungrounded"
        return _clip(content.get("summary") or f"RAG intel: {count} chunk(s), {gate}.")

    if artifact_type == "agent_memory_snapshot":
        agents = content.get("agents_with_context", 0)
        return _clip(content.get("summary") or f"Agent memory: {agents} agent(s) with context.")

    if artifact_type == "service_catalog_intelligence":
        gate = content.get("gate_verdict") or "?"
        catalog = content.get("catalog") or {}
        count = catalog.get("service_count", 0)
        return _clip(content.get("summary") or f"Catalog intel {gate}: {count} service(s).")

    if artifact_type == "qa_report":
        verdict = content.get("verdict") or "unknown"
        ts = content.get("test_summary") or {}
        if ts.get("total"):
            return f"QA {verdict}: {ts.get('passed', 0)}/{ts.get('total')} tests passed."
        return _string_field(content, "summary") or f"QA verdict: {verdict}."

    if artifact_type == "pr_intelligence":
        posted = content.get("posted") or content.get("comment_posted")
        rec = content.get("recommendation") or content.get("verdict")
        pr = content.get("pr_number") or content.get("pull_number")
        parts = []
        if pr:
            parts.append(f"PR #{pr}")
        if rec:
            parts.append(str(rec))
        if posted is not None:
            parts.append("comment posted" if posted else "comment skipped")
        return _clip(" · ".join(parts) if parts else "PR intelligence report")

    if artifact_type == "fix_loop_report":
        attempts = content.get("attempts") or content.get("iteration_count")
        fixed = content.get("fixed") or content.get("resolved")
        base = _string_field(content, "summary")
        if base:
            return _clip(base)
        if attempts is not None:
            return f"Fix loop: {attempts} attempt(s), resolved={bool(fixed)}."
        return "Fix loop report"

    if artifact_type == "policy_evaluation":
        if content.get("passed") is False:
            return f"Policy blocked ({content.get('violation_count', 0)} violation(s))"
        return f"Policy passed ({len(content.get('policies_evaluated') or [])} policy/policies)"

    if artifact_type == "policy_intelligence":
        gate = content.get("gate_verdict")
        pe = content.get("policy_evaluation") or {}
        ai = content.get("ai_autonomy_policy") or {}
        return _clip(
            f"Policy intel {gate or '?'}: {pe.get('violation_count', 0)} policy + "
            f"{ai.get('violation_count', 0)} AI autonomy violation(s)."
        )

    if artifact_type == "compliance_report":
        score = content.get("overall_score_percent")
        if score is not None:
            return f"Compliance {score}% ({content.get('controls_passed')}/{content.get('controls_total')} controls)"

    if artifact_type == "finops_intelligence":
        cost = (content.get("cost_report") or {}).get("total_usd_estimate", 0)
        gate = content.get("gate_verdict") or "?"
        return _clip(content.get("summary") or f"FinOps {gate}: run ${cost}.")

    if artifact_type == "iam_intelligence":
        gate = content.get("gate_verdict") or "?"
        score = content.get("readiness_score")
        return _clip(content.get("summary") or f"IAM {gate}: readiness {score}%.")

    if artifact_type == "reliability_intelligence":
        gate = content.get("gate_verdict") or "?"
        score = content.get("resilience_score")
        return _clip(content.get("summary") or f"Reliability {gate}: resilience {score}%.")

    if artifact_type == "dr_intelligence":
        gate = content.get("gate_verdict") or "?"
        score = content.get("readiness_score")
        return _clip(content.get("summary") or f"DR {gate}: readiness {score}%.")

    if artifact_type == "knowledge_graph_intelligence":
        gate = content.get("gate_verdict") or "?"
        graph = content.get("graph") or {}
        cov = (content.get("coverage") or {}).get("coverage_percent")
        return _clip(
            content.get("summary")
            or f"Knowledge graph {gate}: {graph.get('node_count', 0)} nodes, coverage {cov}%."
        )

    if artifact_type == "autopilot_intelligence":
        gate = content.get("gate_verdict") or "?"
        primary = (content.get("primary_action") or {}).get("id") or "—"
        return _clip(content.get("summary") or f"Autopilot {gate}: primary action {primary}.")

    if artifact_type == "unified_risk_intelligence":
        gate = content.get("gate_verdict") or "?"
        score = content.get("unified_score")
        level = content.get("risk_level") or "?"
        driver = content.get("primary_driver") or "—"
        return _clip(
            content.get("summary") or f"Unified risk {score}/100 ({level}); driver {driver}. Gate {gate}."
        )

    if artifact_type == "cost_report":
        total = content.get("total_usd_estimate")
        if total is not None:
            return f"Est. cost ${total} ({content.get('llm_tokens', 0)} LLM tokens)"

    if artifact_type == "prompt_injection_scan":
        if content.get("blocked"):
            first = (content.get("findings") or [{}])[0]
            rule = first.get("rule_id") or "pattern"
            src = first.get("source") or "content"
            return f"blocked — {rule} in {src} ({content.get('finding_count', 0)} finding(s))"
        return "clean" if not content.get("findings") else f"{content.get('finding_count', 0)} finding(s)"

    if artifact_type == "agent_eval_report":
        score = content.get("aggregate_score")
        if score is not None:
            return f"AgentEval {score} — {'review' if content.get('human_review_required') else 'ok'}"

    if artifact_type == "decision_ledger":
        return f"{content.get('decision_count', 0)} decision(s) recorded"

    if artifact_type == "model_routing_plan":
        return f"complexity={content.get('complexity', '?')}, {len(content.get('routes') or [])} route(s)"

    if artifact_type == "agent_registry_snapshot":
        return f"{content.get('total', 0)} agent(s) registered"

    if artifact_type == "agent_mesh_snapshot":
        reg = content.get("registry") or {}
        return _clip(content.get("summary") or f"Mesh snapshot: {reg.get('total', 0)} agent(s).")

    if artifact_type == "ai_governance_intelligence":
        gate = content.get("gate_verdict") or "?"
        score = content.get("governance_score", 0)
        esc = content.get("escalation_count", 0)
        return _clip(content.get("summary") or f"AI governance {gate}: score {score}, {esc} escalation(s).")

    if artifact_type == "agent_mesh_intelligence":
        health = content.get("health") or {}
        gate = content.get("gate_verdict") or health.get("gate_verdict") or "?"
        pct = health.get("coverage_percent", 0)
        return _clip(content.get("summary") or f"Agent mesh {gate}: {pct}% coverage.")

    return ""


def artifact_verdict(artifact_type: str, content: Any) -> str | None:
    """Return a short badge label for an artifact, if applicable."""
    if not isinstance(content, dict):
        return None

    for key in (
        "severity",
        "verdict",
        "performance_verdict",
        "decision",
        "highest_severity",
        "final_status",
        "risk_level",
        "recommended_action",
    ):
        value = content.get(key)
        if value is not None and str(value).strip():
            return str(value)

    if artifact_type == "secrets_scan":
        if content.get("passed") is False:
            return "fail"
        return "pass" if content.get("passed") is True else None

    if artifact_type in {"container_security_scan", "iac_security_scan", "contract_test_report"}:
        if content.get("passed") is False:
            return "fail"
        if content.get("passed") is True:
            return "pass"
        critical = content.get("critical_count", 0)
        if critical:
            return "critical"

    if artifact_type == "release_passport":
        return "pass" if content.get("all_checks_passed") else "warn"

    if artifact_type == "release_intelligence":
        return str(content.get("gate_verdict") or "warn")

    if artifact_type == "developer_ux_intelligence":
        readiness = content.get("readiness") or {}
        score = int(readiness.get("readiness_score") or 0)
        if score >= 80:
            return "pass"
        if score >= 60:
            return "warn"
        return "fail"

    if artifact_type == "deployment_info":
        if content.get("success") is False:
            return "failed"
        if content.get("simulated"):
            return "simulated"
        if content.get("success") is True:
            return "deployed"

    if artifact_type == "monitoring_summary" and content.get("simulated"):
        return "simulated"

    if artifact_type == "patch_confidence_report":
        action = content.get("action") or content.get("recommendation")
        if action:
            return str(action)

    if artifact_type == "change_risk_report":
        return str(content.get("risk_level") or "")

    return None
