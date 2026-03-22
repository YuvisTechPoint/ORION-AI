from __future__ import annotations

from core.config import Settings, get_settings

# Shared settings instance for app.* modules
settings: Settings = get_settings()

__all__ = ["Settings", "settings", "get_settings"]
