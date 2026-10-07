from app.utils.artifact_summaries import artifact_verdict, summarize_artifact


def test_sbom_legacy_object_summary():
    content = {
        "components": [{"name": "flask"}],
        "summary": {"component_count": 3, "sources": ["requirements.txt"]},
    }
    assert "3 component(s)" in summarize_artifact("sbom", content)
    assert "requirements.txt" in summarize_artifact("sbom", content)


def test_sbom_string_summary():
    content = {"summary": "CycloneDX SBOM: 2 component(s) from package.json.", "stats": {"component_count": 2}}
    assert summarize_artifact("sbom", content).startswith("CycloneDX")


def test_service_graph_summary():
    content = {
        "root_service": "api",
        "node_count": 4,
        "edge_count": 2,
        "changed_services": ["api", "redis"],
    }
    text = summarize_artifact("service_graph", content)
    assert "4 service(s)" in text
    assert "api" in text


def test_audit_trail_summary():
    content = {
        "events": [
            {"action": "pipeline.trigger", "actor": "e", "outcome": "queued"},
            {"action": "pipeline.complete", "actor": "system", "outcome": "approved"},
        ]
    }
    assert "2 event(s)" in summarize_artifact("audit_trail", content)
    assert "pipeline.complete" in summarize_artifact("audit_trail", content)


def test_change_risk_verdict():
    content = {"final_risk": 22, "risk_level": "low", "summary": "Change risk 22/100 (low); 2 file(s) changed."}
    assert artifact_verdict("change_risk_report", content) == "low"


def test_release_passport_verdict():
    content = {"all_checks_passed": True, "evidence_artifact_count": 12, "risk": {"final_score": 10, "level": "low"}}
    assert artifact_verdict("release_passport", content) == "pass"
