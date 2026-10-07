"""Multi-key RBAC for ORION API operations."""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass

from fastapi import HTTPException, status

from app.config import settings


@dataclass
class OrionUserContext:
    user_id: str
    roles: list[str]
    api_key: str | None = None


class OrionAuthService:
    @staticmethod
    def _parse_keys(raw: str) -> dict[str, dict[str, object]]:
        try:
            parsed = json.loads(raw or "{}")
            if isinstance(parsed, dict):
                return {str(k): v for k, v in parsed.items() if isinstance(v, dict)}
        except json.JSONDecodeError:
            pass
        return {}

    def resolve_api_key(self, provided: str | None) -> OrionUserContext | None:
        if not provided:
            return None
        provided = provided.strip()
        legacy = (settings.orion_api_key or "").strip()
        if legacy and hmac.compare_digest(legacy, provided):
            return OrionUserContext(user_id="legacy-orion-key", roles=["admin", "operator"], api_key=provided)
        entry = self._parse_keys(settings.auth_api_keys_json).get(provided)
        if entry is None:
            return None
        roles = entry.get("roles") or ["operator"]
        if isinstance(roles, str):
            roles = [roles]
        return OrionUserContext(
            user_id=str(entry.get("user_id") or "api-user"),
            roles=[str(r) for r in roles],
            api_key=provided,
        )

    def require_roles(self, user: OrionUserContext, allowed: set[str]) -> None:
        if not allowed.intersection(set(user.roles)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(sorted(allowed))}",
            )


auth_service = OrionAuthService()
