import httpx

from app.config import settings


def get_effective_github_token(session_token: str | None = None) -> str:
    if session_token and session_token.strip():
        return session_token.strip()
    if settings.github_token and settings.github_token.strip():
        return settings.github_token.strip()
    raise ValueError(
        "No GitHub token configured — login at /api/v1/auth/github or set GITHUB_TOKEN in .env"
    )


async def validate_github_token(token: str) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    if r.status_code != 200:
        raise ValueError("GitHub token invalid or expired")
    return r.json()


def get_token_scopes(token: str) -> list[str]:
    with httpx.Client(timeout=30.0) as client:
        r = client.get(
            "https://api.github.com/",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    raw = r.headers.get("X-OAuth-Scopes") or ""
    return [s.strip() for s in raw.split(",") if s.strip()]
