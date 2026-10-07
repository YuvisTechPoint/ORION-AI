from typing import Any

from app.agents.multimodal.base_multimodal_agent import BaseMultimodalAgent, as_text
from app.config import settings
from app.utils.kubernetes_manifest import _analyze_doc, _doc_meta, _split_yaml_docs

K8S_SCHEMA = (
    'Return ONLY valid JSON: {"manifests_reviewed": int, "findings": [{"rule": string, "severity": string, '
    '"resource": string, "description": string, "recommendation": string}], "rollout_risks": [string], '
    '"security_score": int, "severity": string, "summary": string}'
)


class KubernetesManifestAgent(BaseMultimodalAgent):
    artifact_type = "kubernetes_manifest_scan"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.agent_model = settings.multimodal_git_model

    def _heuristic(self) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        resources = 0
        for art in self.text_artifacts():
            text = as_text(art.get("content", ""))
            fname = str(art.get("filename") or "manifest.yaml")
            for doc in _split_yaml_docs(text):
                if "apiVersion:" not in doc:
                    continue
                resources += 1
                meta = _doc_meta(doc)
                resource = f"{meta['kind']}/{meta['name']}"
                for item in _analyze_doc(doc, file=fname):
                    item["resource"] = resource
                    findings.append(item)

        critical = sum(1 for f in findings if f.get("severity") == "critical")
        high = sum(1 for f in findings if f.get("severity") == "high")
        score = max(0, 100 - critical * 25 - high * 10 - len(findings))
        severity = "critical" if critical else ("high" if high else ("medium" if findings else "low"))
        rollout_risks = sorted({f["rule"] for f in findings if f["rule"].startswith(("missing_", "single_replica"))})[:5]
        return {
            "manifests_reviewed": resources,
            "findings": findings[:40],
            "finding_count": len(findings),
            "critical_count": critical,
            "high_count": high,
            "passed": critical == 0,
            "rollout_risks": rollout_risks,
            "security_score": score,
            "severity": severity,
            "summary": f"Reviewed {resources} K8s resource(s); {len(findings)} finding(s) ({critical} critical).",
            "analysis_mode": "heuristic",
        }

    async def execute(self) -> dict[str, Any]:
        result = await self._analyze_json(
            f"You are a Kubernetes platform engineer reviewing manifests for production readiness. {K8S_SCHEMA}",
            "Review probes, securityContext, RBAC, ingress TLS, and rollout safety.",
            self._heuristic(),
            required_key="findings",
            max_tokens=4000,
        )
        return await self._persist(result)
