from __future__ import annotations

# Thin adapter so app.api.routes.* can import require_auth
# while reusing the existing authentication implementation.

from api.auth import require_auth  # noqa: F401

__all__ = ["require_auth"]
