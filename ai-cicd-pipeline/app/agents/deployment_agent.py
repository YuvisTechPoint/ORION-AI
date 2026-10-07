import asyncio
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.config import settings
from app.models.pipeline_artifact import PipelineArtifact
from app.models.pipeline_run import PipelineRun
from app.services.slack_service import SlackService
from app.utils.progressive_delivery import run_progressive_delivery

MINIMAL_DOCKERFILE = """FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi
ENV PYTHONUNBUFFERED=1
EXPOSE {port}
CMD ["python", "-m", "http.server", "{port}"]
"""


_DOCKER_CACHE_SECONDS = 60.0
_docker_state: dict[str, Any] = {"ok": False, "checked": None}


def container_name() -> str:
    return f"{settings.app_name}-staging"


def docker_available() -> bool:
    checked = _docker_state["checked"]
    if checked is not None and time.monotonic() - checked < _DOCKER_CACHE_SECONDS:
        return bool(_docker_state["ok"])
    try:
        p = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            encoding="utf-8", errors="replace",
            timeout=15,
            check=False,
        )
        ok = p.returncode == 0 and bool(p.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    _docker_state.update(ok=ok, checked=time.monotonic())
    return ok


def resolved_deploy_mode() -> str:
    """docker | simulate | skip.

    auto: use Docker when a daemon is reachable, otherwise simulate deployment so the
    pipeline still reaches deployed + monitoring without a local Docker install.
    """
    mode = settings.deploy_mode.strip().lower()
    if mode in ("docker", "skip", "simulate"):
        return mode
    return "docker" if docker_available() else "simulate"


async def docker(args: list[str], timeout: int = 600) -> tuple[int, str]:
    def _run() -> tuple[int, str]:
        try:
            p = subprocess.run(
                ["docker", *args], capture_output=True, encoding="utf-8", errors="replace", check=False, timeout=timeout
            )
            return p.returncode, (p.stdout or "") + (p.stderr or "")
        except subprocess.TimeoutExpired as exc:
            return 124, f"docker {args[0]} timed out: {exc}"
        except (FileNotFoundError, OSError) as exc:
            return 127, f"docker CLI unavailable: {exc}"

    return await asyncio.to_thread(_run)


async def run_container(image: str) -> tuple[int, str]:
    name = container_name()
    await docker(["stop", name], timeout=60)
    await docker(["rm", name], timeout=60)
    return await docker(
        [
            "run",
            "-d",
            "--name",
            name,
            "-p",
            f"{settings.staging_host_port}:{settings.staging_container_port}",
            image,
        ],
        timeout=60,
    )


class DeploymentAgent(BaseAgent):
    def __init__(
        self,
        pipeline_run_id: UUID,
        db: AsyncSession,
        anthropic_client: AsyncAnthropic | None,
        repo_path: str,
        commit_id: str,
    ) -> None:
        super().__init__(pipeline_run_id, db, anthropic_client)
        self.repo_path = repo_path
        self.commit_id = commit_id
        self.agent_model = settings.deployment_model
        self.slack = SlackService()

    # Backwards-compatible alias used by older callers.
    _docker = staticmethod(docker)

    def image_tag(self) -> str:
        tag = f"{settings.app_name}:{self.commit_id[:8]}"
        return f"{settings.container_registry.rstrip('/')}/{tag}" if settings.registry_enabled else tag

    async def _last_known_good_image(self) -> str | None:
        """Most recent healthy image for the same repository from a previous run."""
        if self.db is None:
            return None
        async with self._db_lock():
            run = (
                await self.db.execute(select(PipelineRun).where(PipelineRun.id == self.pipeline_run_id))
            ).scalar_one_or_none()
            if run is None:
                return None
            rows = (
                await self.db.execute(
                    select(PipelineArtifact)
                    .join(PipelineRun, PipelineRun.id == PipelineArtifact.pipeline_run_id)
                    .where(
                        PipelineRun.repo_full_name == run.repo_full_name,
                        PipelineArtifact.artifact_type == "last_known_good_image",
                        PipelineArtifact.pipeline_run_id != self.pipeline_run_id,
                    )
                    .order_by(PipelineArtifact.created_at.desc())
                    .limit(1)
                )
            ).scalars().all()
        return (rows[0].content or {}).get("image") if rows else None

    async def _current_container_image(self) -> str | None:
        code, out = await docker(["inspect", "-f", "{{.Config.Image}}", container_name()], timeout=30)
        if code != 0:
            return None
        return out.strip() or None

    def _ensure_dockerfile(self) -> bool:
        dockerfile = Path(self.repo_path) / "Dockerfile"
        if dockerfile.is_file():
            return False
        dockerfile.write_text(
            MINIMAL_DOCKERFILE.format(port=settings.staging_container_port), encoding="utf-8"
        )
        self.logger.info("no Dockerfile in repo; generated a minimal one")
        return True

    async def _poll_health(self, url: str, timeout_s: int) -> bool:
        deadline = time.monotonic() + timeout_s
        async with httpx.AsyncClient(timeout=5.0) as client:
            while time.monotonic() < deadline:
                try:
                    r = await client.get(url)
                    if r.status_code == 200:
                        return True
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(5)
        return False

    async def _rollback(self, reason: str, previous_image: str | None = None) -> dict[str, Any]:
        image = previous_image or await self._last_known_good_image()
        if not image:
            self.logger.error("rollback requested (%s) but no last known good image exists", reason)
            result = {"rolled_back": False, "reason": reason, "detail": "no last known good image"}
        else:
            code, log = await run_container(image)
            result = {"rolled_back": code == 0, "reason": reason, "image": image, "log": log[-4000:]}
        await self._update_run_status("rolled_back", error_message=f"Rolled back: {reason}")
        await self.slack.send_monitoring_alert(
            self.pipeline_run_id, [reason], f"rollback to {image or 'n/a'}"
        )
        return result

    async def execute(self) -> dict[str, Any]:
        image = self.image_tag()
        previous_image = await self._last_known_good_image() or await self._current_container_image()
        generated_dockerfile = self._ensure_dockerfile()

        code, build_log = await docker(["build", "-t", image, self.repo_path])
        if code != 0:
            info = {
                "success": False,
                "image_tag": image,
                "environment": settings.deploy_environment,
                "error": "docker build failed",
                "health_check_passed": False,
            }
            await self._save_artifact("deployment_info", info, raw_output=build_log[-50000:])
            return info

        if settings.registry_enabled:
            code, push_log = await docker(["push", image])
            if code != 0:
                info = {
                    "success": False,
                    "image_tag": image,
                    "environment": settings.deploy_environment,
                    "error": "docker push failed",
                    "health_check_passed": False,
                }
                await self._save_artifact("deployment_info", info, raw_output=push_log[-50000:])
                return info

        run_code, run_log = await run_container(image)
        healthy = run_code == 0 and await self._poll_health(
            settings.staging_url.rstrip("/") + "/health", settings.health_check_timeout_seconds
        )

        info: dict[str, Any] = {
            "success": healthy,
            "image_tag": image,
            "environment": settings.deploy_environment,
            "deployed_at": datetime.now(timezone.utc).isoformat(),
            "health_check_passed": healthy,
            "generated_dockerfile": generated_dockerfile,
            "previous_image": previous_image,
        }
        if not healthy:
            info["rollback"] = await self._rollback(
                "health check failed after deployment", previous_image=previous_image
            )
        else:
            await self._save_artifact("last_known_good_image", {"image": image})
            if settings.progressive_delivery_enabled:
                progressive = await run_progressive_delivery(
                    health_url=settings.staging_url.rstrip("/") + "/health",
                    simulated=False,
                )
                info["progressive_delivery"] = progressive
                await self._save_artifact("progressive_delivery", progressive)
                if not progressive.get("passed"):
                    info["success"] = False
                    info["rollback"] = await self._rollback(
                        progressive.get("summary") or "canary aborted", previous_image=previous_image
                    )

        await self._save_artifact(
            "deployment_info",
            info,
            raw_output=(build_log[-40000:] + "\n" + run_log[-10000:]),
            duration_seconds=self.elapsed_seconds,
        )
        return info

    async def execute_simulated(self) -> dict[str, Any]:
        """Record a successful deployment without touching Docker (local dev / CI without daemon)."""
        image = self.image_tag()
        info: dict[str, Any] = {
            "success": True,
            "simulated": True,
            "skipped": False,
            "image_tag": image,
            "environment": settings.deploy_environment,
            "deployed_at": datetime.now(timezone.utc).isoformat(),
            "health_check_passed": True,
            "summary": "Simulated deployment succeeded (Docker daemon unavailable on pipeline host).",
        }
        if settings.progressive_delivery_enabled:
            progressive = await run_progressive_delivery(
                health_url=settings.staging_url.rstrip("/") + "/health",
                simulated=True,
            )
            info["progressive_delivery"] = progressive
            await self._save_artifact("progressive_delivery", progressive)
            info["success"] = bool(progressive.get("passed", True))
        await self._save_artifact("last_known_good_image", {"image": image, "simulated": True})
        await self._save_artifact("deployment_info", info, duration_seconds=self.elapsed_seconds)
        return info
