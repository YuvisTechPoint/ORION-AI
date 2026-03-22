import json
from dataclasses import dataclass

from fastapi import HTTPException

from core.config import Settings
from core.db import SessionLocal
from models.db_models import User as UserModel


@dataclass
class UserContext:
    user_id: str
    roles: list[str]
    api_key: str


class AuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._key_map = self._parse_key_map(settings.auth_api_keys_json)

    def authenticate(self, api_key: str | None) -> UserContext:
        # If auth is disabled, return system/admin context
        if not self.settings.auth_enabled:
            return UserContext(user_id="system", roles=["admin"], api_key="disabled")

        if not api_key:
            raise HTTPException(status_code=401, detail="Missing X-API-Key header")

        # Prefer database-backed users when available
        try:
            db = SessionLocal()
            user = db.query(UserModel).filter(UserModel.api_key == api_key).first()
        except Exception:
            user = None
        finally:
            try:
                db.close()
            except Exception:
                pass

        if user:
            # roles stored as JSON string
            try:
                roles = json.loads(user.roles) if user.roles else []
            except Exception:
                roles = []
            return UserContext(user_id=user.username or "unknown", roles=roles, api_key=api_key)

        # Fallback to static API keys from settings
        data = self._key_map.get(api_key)
        if data is None:
            raise HTTPException(status_code=401, detail="Invalid API key")

        roles = data.get("roles", [])
        user_id = data.get("user_id", "unknown")
        return UserContext(user_id=user_id, roles=roles, api_key=api_key)

    def require_role(self, user: UserContext, allowed_roles: set[str]) -> None:
        if not allowed_roles.intersection(set(user.roles)):
            raise HTTPException(status_code=403, detail="Insufficient role for this action")

    def _parse_key_map(self, raw: str) -> dict[str, dict[str, object]]:
        try:
            parsed = json.loads(raw) if raw else {}
            if isinstance(parsed, dict):
                return {str(k): v for k, v in parsed.items() if isinstance(v, dict)}
            return {}
        except json.JSONDecodeError:
            return {}
