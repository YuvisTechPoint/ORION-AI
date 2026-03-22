import asyncio
import json
import re
import subprocess
from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.agents.deployment_agent import DeploymentAgent
from app.config import settings


class MonitoringAgent(BaseAgent):
    async def execute(self) -> dict[str, Any]:
        container = f"{settings.app_name}-staging"
        iterations = max(1, settings.monitoring_window_minutes * 6)
        interval = settings.monitoring_poll_interval_seconds
        consecutive_alerts = 0
        summary: dict[str, Any] = {
            "iterations": iterations,
            "alerts": [],
            "final_status": "monitoring",
        }

        previous_image: str | None = None
        code, out = await DeploymentAgent._docker(
            ["inspect", "-f", "{{.Config.Image}}", container]
        )
        if code == 0:
            previous_image = out.strip() or None

        for i in range(iterations):
            await asyncio.sleep(interval)

            def _logs() -> str:
                p = subprocess.run(
                    [
                        "docker",
                        "logs",
                        f"--since={interval}s",
                        container,
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
                return (p.stdout or "") + (p.stderr or "")

            raw = await asyncio.to_thread(_logs)
            err_lines = [
                ln
                for ln in raw.splitlines()
                if re.search(r"ERROR|Exception|Traceback", ln, re.I)
            ]
            threshold = 5
            if len(err_lines) >= threshold:
                user = json.dumps(
                    {
                        "iteration": i,
                        "error_lines": err_lines[:200],
                        "raw_tail": raw[-20000:],
                    }
                )
                system = (
                    "You are an SRE. Return JSON with recommended_action (rollback|investigate|ignore) "
                    "and anomalies (list of short strings)."
                )
                decision = await self._call_claude_json(system, user, max_tokens=800)
                rec = str(decision.get("recommended_action", "")).lower()
                if rec == "rollback":
                    consecutive_alerts += 1
                else:
                    consecutive_alerts = 0

                await self._save_artifact(
                    "monitoring_alert",
                    {
                        "iteration": i,
                        "error_count": len(err_lines),
                        "decision": decision,
                    },
                    raw_output=raw[:30000],
                )

                if rec == "rollback" and consecutive_alerts >= 2:
                    await DeploymentAgent.rollback(previous_image, container)
                    await self._update_run_status("auto_rolled_back")
                    summary["final_status"] = "auto_rolled_back"
                    return summary

        await self._update_run_status("monitoring")
        return summary
