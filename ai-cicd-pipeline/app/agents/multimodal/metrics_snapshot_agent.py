import json
import re
from typing import Any

from app.agents.multimodal.base_multimodal_agent import BaseMultimodalAgent, as_text
from app.config import settings

METRICS_SCHEMA = (
    'Return ONLY valid JSON: {"format": string, "anomalies": [{"metric": string, "value": number, '
    '"threshold": number, "severity": string, "detail": string}], "saturated_resources": [string], '
    '"recommended_actions": [string], "severity": string, "summary": string}'
)

_METRIC_LINE = re.compile(
    r"^([a-zA-Z_:][a-zA-Z0-9_:]*)\s+(?:\{[^}]*\}\s+)?(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)\s*$"
)
_HIGH_WATERMARK = 0.85


def _parse_prometheus(text: str) -> list[tuple[str, float]]:
    samples: list[tuple[str, float]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _METRIC_LINE.match(line)
        if not match:
            continue
        try:
            samples.append((match.group(1), float(match.group(2))))
        except ValueError:
            continue
    return samples


def _parse_grafana_json(text: str) -> list[str]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    titles: list[str] = []
    panels = payload.get("panels") if isinstance(payload, dict) else None
    if isinstance(panels, list):
        for panel in panels[:20]:
            if isinstance(panel, dict) and panel.get("title"):
                titles.append(str(panel["title"]))
    return titles


class MetricsSnapshotAgent(BaseMultimodalAgent):
    artifact_type = "metrics_snapshot_analysis"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.agent_model = settings.multimodal_git_model

    def _heuristic(self) -> dict[str, Any]:
        anomalies: list[dict[str, Any]] = []
        saturated: list[str] = []
        fmt = "unknown"
        actions: list[str] = []

        for art in self.text_artifacts():
            text = as_text(art.get("content", ""))
            prom = _parse_prometheus(text)
            if prom:
                fmt = "prometheus"
                for name, value in prom[:200]:
                    lname = name.lower()
                    if "error_rate" in lname or lname.endswith("_errors_total"):
                        if value > 0:
                            anomalies.append(
                                {
                                    "metric": name,
                                    "value": value,
                                    "threshold": 0,
                                    "severity": "high",
                                    "detail": "Non-zero error counter",
                                }
                            )
                    if any(token in lname for token in ("cpu", "memory", "mem", "disk", "utilization")):
                        if 0 <= value <= 1 and value >= _HIGH_WATERMARK:
                            saturated.append(name)
                            anomalies.append(
                                {
                                    "metric": name,
                                    "value": value,
                                    "threshold": _HIGH_WATERMARK,
                                    "severity": "medium",
                                    "detail": "Resource utilization above 85%",
                                }
                            )
                        elif value > 85 and value <= 100:
                            saturated.append(name)
                if saturated:
                    actions.append("Scale affected services or investigate resource limits")
            elif _parse_grafana_json(text):
                fmt = "grafana_json"
                titles = _parse_grafana_json(text)
                if titles:
                    actions.append(f"Review Grafana panels: {', '.join(titles[:5])}")

        severity = "high" if any(a.get("severity") == "high" for a in anomalies) else (
            "medium" if anomalies else "low"
        )
        return {
            "format": fmt,
            "anomalies": anomalies[:20],
            "saturated_resources": saturated[:10],
            "recommended_actions": actions or ["No threshold breaches detected in snapshot"],
            "severity": severity,
            "summary": f"Metrics snapshot ({fmt}): {len(anomalies)} anomaly/anomalies, {len(saturated)} saturated resource(s).",
        }

    async def execute(self) -> dict[str, Any]:
        result = await self._analyze_json(
            f"You are an SRE reviewing Prometheus or Grafana metric exports for production anomalies. {METRICS_SCHEMA}",
            "Highlight threshold breaches, saturated resources, and remediation steps.",
            self._heuristic(),
            required_key="anomalies",
            max_tokens=3000,
        )
        return await self._persist(result)
