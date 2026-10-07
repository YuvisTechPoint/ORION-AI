import asyncio
import json
import re
import subprocess
import time
from typing import Any
from uuid import UUID

import httpx
from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import LLM_ERROR_KEY, BaseAgent
from app.agents.deployment_agent import DeploymentAgent, container_name
from app.config import settings
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.services.journald_service import journald_service
from app.services.phase3_enrichment import run_phase3_incident_response
from app.services.slack_service import SlackService
from app.utils.rollback_intelligence import assess_rollback

SYSTEM_PROMPT = """You are a site reliability engineer monitoring a production deployment.
Analyze log metrics and decide if action is needed. Return ONLY valid JSON:
{
  "status": "healthy"|"degraded"|"critical",
  "anomalies": [{"type": string, "description": string, "severity": "low"|"medium"|"high"}],
  "recommended_action": "monitor"|"alert"|"rollback",
  "error_spike": bool,
  "performance_degraded": bool,
  "summary": string
}
recommended_action: "rollback" only if status=="critical" and error spike or health check failing.
Return ONLY valid JSON."""

_ERROR_RE = re.compile(r"\bERROR\b", re.IGNORECASE)
_WARNING_RE = re.compile(r"\bWARN(ING)?\b", re.IGNORECASE)
_EXCEPTION_RE = re.compile(r"Traceback|Exception:")


def needs_analysis(metrics: dict[str, Any]) -> bool:
    return (
        metrics["error_count"] > 5
        or metrics["exception_count"] > 0
        or metrics["health_status_code"] != 200
    )


def heuristic_assessment(metrics: dict[str, Any]) -> dict[str, Any]:
    health_failing = metrics["health_status_code"] != 200
    error_spike = metrics["error_count"] > 20 or metrics["exception_count"] > 5
    if health_failing:
        status, action = "critical", "rollback"
    elif error_spike or needs_analysis(metrics):
        status, action = "degraded", "alert"
    else:
        status, action = "healthy", "monitor"
    anomalies = []
    if health_failing:
        anomalies.append(
            {"type": "health_check", "description": f"health returned {metrics['health_status_code']}", "severity": "high"}
        )
    if metrics["error_count"]:
        anomalies.append(
            {"type": "errors", "description": f"{metrics['error_count']} error log lines", "severity": "medium"}
        )
    if metrics["exception_count"]:
        anomalies.append(
            {"type": "exceptions", "description": f"{metrics['exception_count']} exceptions", "severity": "high"}
        )
    return {
        "status": status,
        "anomalies": anomalies,
        "recommended_action": action,
        "error_spike": error_spike,
        "performance_degraded": metrics["response_time_ms"] > 2000,
        "summary": f"Heuristic assessment: {status}",
        "analysis_mode": "heuristic",
    }


class MonitoringAgent(BaseAgent):
    def __init__(
        self,
        pipeline_run_id: UUID,
        db: AsyncSession,
        anthropic_client: AsyncAnthropic | None,
        poll_interval_seconds: int | None = None,
        max_duration_seconds: int | None = None,
    ) -> None:
        super().__init__(pipeline_run_id, db, anthropic_client)
        self.agent_model = settings.monitoring_model
        self.poll_interval = poll_interval_seconds or settings.monitoring_poll_interval_seconds
        self.max_duration = max_duration_seconds or settings.monitoring_window_minutes * 6 * 60
        self.slack = SlackService()

    async def _deployment_was_simulated(self) -> bool:
        async with self._db_lock():
            row = (
                await self.db.execute(
                    select(PipelineArtifact)
                    .where(
                        PipelineArtifact.pipeline_run_id == self.pipeline_run_id,
                        PipelineArtifact.artifact_type == "deployment_info",
                    )
                    .order_by(PipelineArtifact.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        content = (row.content or {}) if row else {}
        return bool(content.get("simulated"))

    def _simulated_metrics(self) -> dict[str, Any]:
        return {
            "error_count": 0,
            "warning_count": 0,
            "exception_count": 0,
            "health_status_code": 200,
            "response_time_ms": 12.0,
            "log_lines": ["[simulated] staging health check OK"],
            "orion_journald": {"enabled": False, "simulated": True},
            "simulated": True,
        }

    def _container_logs(self) -> str:
        try:
            p = subprocess.run(
                [
                    "docker",
                    "logs",
                    "--since",
                    f"{self.poll_interval}s",
                    "--tail",
                    "200",
                    container_name(),
                ],
                capture_output=True,
                encoding="utf-8", errors="replace",
                check=False,
                timeout=60,
            )
            return (p.stdout or "") + (p.stderr or "")
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
            self.logger.debug("docker logs unavailable: %s", exc)
            return ""

    async def _collect_metrics(self) -> dict[str, Any]:
        raw = await asyncio.to_thread(self._container_logs)
        lines = raw.splitlines()

        status_code, response_ms = 0, 0.0
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(settings.staging_url.rstrip("/") + "/health")
                status_code = r.status_code
        except httpx.HTTPError:
            status_code = 0
        response_ms = (time.perf_counter() - started) * 1000

        journald = await journald_service.get_error_summary(
            since_minutes=max(1, self.poll_interval // 60 or 1)
        )
        return {
            "error_count": sum(1 for ln in lines if _ERROR_RE.search(ln)),
            "warning_count": sum(1 for ln in lines if _WARNING_RE.search(ln)),
            "exception_count": sum(1 for ln in lines if _EXCEPTION_RE.search(ln)),
            "health_status_code": status_code,
            "response_time_ms": round(response_ms, 1),
            "log_lines": lines[-50:],
            "orion_journald": journald,
        }

    async def _run_incident_response(
        self,
        metrics: dict[str, Any],
        *,
        log_excerpt: str = "",
    ) -> dict[str, Any] | None:
        async with self._db_lock():
            run = await self.db.get(PipelineRun, self.pipeline_run_id)
            if run is None:
                return None
            rows = (
                await self.db.execute(
                    select(PipelineArtifact).where(
                        PipelineArtifact.pipeline_run_id == self.pipeline_run_id
                    )
                )
            ).scalars().all()
        arts = {a.artifact_type: a.content or {} for a in rows}
        return await run_phase3_incident_response(
            self.db,
            run,
            artifacts=arts,
            metrics=metrics,
            log_excerpt=log_excerpt,
        )

    async def _rollback_assessment(self, metrics: dict[str, Any]) -> dict[str, Any]:
        async with self._db_lock():
            rows = (
                await self.db.execute(
                    select(PipelineArtifact).where(
                        PipelineArtifact.pipeline_run_id == self.pipeline_run_id
                    )
                )
            ).scalars().all()
        arts = {a.artifact_type: a.content or {} for a in rows}
        metrics_with_size = {**metrics, "sample_size": max(100, metrics.get("error_count", 0) * 10)}
        return assess_rollback(
            metrics=metrics_with_size,
            deployment_info=arts.get("deployment_info"),
            change_risk=arts.get("change_risk_report"),
        )

    async def _assess(self, metrics: dict[str, Any]) -> dict[str, Any]:
        fallback = heuristic_assessment(metrics)
        if not needs_analysis(metrics):
            return fallback
        payload = {k: v for k, v in metrics.items() if k != "log_lines"}
        payload["recent_logs"] = metrics["log_lines"]
        result = await self._call_claude_json(SYSTEM_PROMPT, json.dumps(payload, default=str), max_tokens=800)
        if LLM_ERROR_KEY in result or "recommended_action" not in result:
            return fallback
        for key, value in fallback.items():
            result.setdefault(key, value)
        result["analysis_mode"] = "llm"
        return result

    async def execute(self) -> dict[str, Any]:
        await self._update_run_status("monitoring")

        if await self._deployment_was_simulated():
            assessment = heuristic_assessment(self._simulated_metrics())
            summary = {
                "checks_performed": 1,
                "alerts": 0,
                "final_status": "deployed",
                "window_seconds": 0,
                "simulated": True,
                "assessment": assessment,
                "summary": "Simulated monitoring window passed (no Docker runtime).",
            }
            await self._save_artifact("monitoring_summary", summary, duration_seconds=self.elapsed_seconds)
            await self._update_run_status("deployed")
            return summary

        deadline = time.monotonic() + self.max_duration
        consecutive_alerts = 0
        incident_response_done = False
        checks = 0
        alerts: list[dict[str, Any]] = []
        final_status = "deployed"

        while time.monotonic() < deadline:
            await asyncio.sleep(self.poll_interval)
            checks += 1
            metrics = await self._collect_metrics()
            assessment = await self._assess(metrics)
            action = str(assessment.get("recommended_action", "monitor")).lower()
            anomalies = [
                a.get("description", str(a)) if isinstance(a, dict) else str(a)
                for a in assessment.get("anomalies", [])
            ]

            if assessment.get("status") == "healthy":
                consecutive_alerts = 0
                continue

            if action in ("alert", "rollback"):
                consecutive_alerts += 1
                alert = {"check": checks, "metrics": {k: v for k, v in metrics.items() if k != "log_lines"}, "assessment": assessment}
                alerts.append(alert)
                await self._save_artifact("monitoring_alert", alert, raw_output="\n".join(metrics["log_lines"]))
                await self.slack.send_monitoring_alert(self.pipeline_run_id, anomalies, action)
                if not incident_response_done:
                    commander = await self._run_incident_response(
                        metrics,
                        log_excerpt="\n".join(metrics.get("log_lines") or []),
                    )
                    if commander:
                        incident_response_done = True
                        alerts.append({"incident_commander": commander.get("incident_id")})

            if action == "rollback" and consecutive_alerts >= 2:
                rollback_intel = await self._rollback_assessment(metrics)
                await self._save_artifact("rollback_intelligence", rollback_intel)
                if not rollback_intel.get("recommend_rollback", True):
                    consecutive_alerts = 1
                    continue
                deployer = DeploymentAgent(self.pipeline_run_id, self.db, None, "", "")
                rollback = await deployer._rollback(assessment.get("summary") or "monitoring detected critical failure")
                await self._update_run_status(
                    "auto_rolled_back",
                    error_message=f"Auto-rolled back by monitoring: {assessment.get('summary')}",
                )
                final_status = "auto_rolled_back"
                alerts.append({"rollback": rollback})
                break

        summary = {
            "checks_performed": checks,
            "alerts": len([a for a in alerts if "assessment" in a]),
            "final_status": final_status,
            "window_seconds": self.max_duration,
        }
        await self._save_artifact("monitoring_summary", summary, duration_seconds=self.elapsed_seconds)
        if final_status == "deployed":
            await self._update_run_status("deployed")
        return summary
