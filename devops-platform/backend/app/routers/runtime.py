from typing import Any

from fastapi import APIRouter

from app.services.navigation import stack_catalog

router = APIRouter(prefix="/runtime", tags=["Runtime"])


@router.get("/navigation")
async def navigation() -> dict[str, Any]:
    return stack_catalog()
