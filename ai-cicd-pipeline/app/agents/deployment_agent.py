import asyncio
import json
import subprocess
from typing import Any
from uuid import UUID

import httpx
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.config import settings


class DeploymentAgent(BaseAgent):
    def __init__(
        self,
        pipeline_run_id: UUID,
        db: AsyncSession,
        anthropic_client: AsyncAnthropic,
        repo_path: str,
        commit_id: str,
    ) -> None:
        super().__init__(pipeline_run_id, db, anthropic_client)
        self.repo_path = repo_path
        self.commit_id = commit_id

    @staticmethod
    async def _docker(args: list[str]) -> tuple[int, str]:
        def _run() -> tuple[int, str]:
            p = subprocess.run(
                ["docker", *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=600,
            )
            return p.returncode, (p.stdout or "") + (p.stderr or "")

        return await asyncio.to_thread(_run)

    @classmethod
    async def rollback(cls, previous_image: str | None, container_name: str) -> dict[str, Any]:
        if not previous_image:
            return {"rolled_back": False, "reason": "no previous image"}
        await cls._docker(["stop", container_name])
        await cls._docker(["rm", container_name])
        code, log = await cls._docker(
            [
                "run",
                "-d",
                "--name",
                container_name,
                "-p",
                "8080:8080",
                previous_image,
            ]
        )
        return {"rolled_back": code == 0, "log": log}

    async def _current_container_image(self, container_name: str) -> str | None:
        code, out = await self._docker(
            ["inspect", "-f", "{{.Config.Image}}", container_name]
        )
        if code != 0:
            return None
        img = out.strip()
        return img or None

    async def execute(self) -> dict[str, Any]:
        tag = f"{self.commit_id[:8]}"
        registry = settings.container_registry.strip()
        image_name = (
            f"{registry}/{settings.app_name}:{tag}"
            if registry and not registry.startswith("your-")
            else f"{settings.app_name}:{tag}"
        )

        container = f"{settings.app_name}-staging"
        previous_image = await self._current_container_image(container)

        code, build_log = await self._docker(
            ["build", "-t", image_name, self.repo_path]
        )
        if code != 0:
            info = {
                "success": False,
                "image": image_name,
                "error": "docker build failed",
                "log": build_log[:20000],
            }
            await self._save_artifact(
                "deployment_info", info, raw_output=build_log[:50000]
            )
            return info

        if registry and not registry.startswith("your-"):
            await self._docker(["push", image_name])

        await self._docker(["stop", container])
        await self._docker(["rm", container])
        run_code, run_log = await self._docker(
            ["run", "-d", "--name", container, "-p", "8080:8080", image_name]
        )

        health_url = settings.staging_url.rstrip("/") + "/health"
        ok = False
        for _ in range(max(1, settings.health_check_timeout_seconds // 5)):
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.get(health_url)
                    if r.status_code < 500:
                        ok = True
                        break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(5)

        if not ok:
            rb = await self.rollback(previous_image, container)
            info = {
                "success": False,
                "rolled_back": bool(rb.get("rolled_back")),
                "image": image_name,
                "health_check": "failed",
                "container_log": run_log[:10000],
                "rollback": rb,
            }
            await self._save_artifact(
                "deployment_info", info, raw_output=json.dumps(info)
            )
            return info

        await self._save_artifact(
            "last_known_good_image",
            {"image": image_name},
            raw_output=None,
        )

        info = {
            "success": True,
            "image": image_name,
            "container": container,
            "health_check": "passed",
            "log": run_log[:10000],
        }
        await self._save_artifact(
            "deployment_info",
            info,
            raw_output=build_log[:50000],
            duration_seconds=self.elapsed_seconds,
        )
        return info
