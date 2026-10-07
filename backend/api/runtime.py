from typing import Any

from fastapi import APIRouter

from core.navigation import stack_catalog

router = APIRouter(prefix="/runtime", tags=["Runtime"])


@router.get("/navigation")
def navigation() -> dict[str, Any]:
    """Cross-stack URLs for the unified navigation bar."""
    return stack_catalog()
