import socket
from urllib.parse import urlparse

import redis

from core.config import Settings

try:
    import psycopg2
except Exception:  # noqa: BLE001
    psycopg2 = None


def _database_backend(database_url: str) -> str:
    lowered = database_url.lower()
    if lowered.startswith("postgresql://") or lowered.startswith("postgres://"):
        return "postgresql"
    if lowered.startswith("sqlite://"):
        return "sqlite"
    return "unknown"


def check_redis(settings: Settings) -> tuple[bool, str]:
    if settings.queue_backend.lower() != "redis":
        return True, "queue backend is not redis"

    try:
        client = redis.Redis.from_url(settings.redis_url)
        pong = client.ping()
        if pong:
            return True, "redis reachable"
        return False, "redis ping failed"
    except Exception as exc:  # noqa: BLE001
        return False, f"redis unreachable: {exc}"


def check_postgres(settings: Settings) -> tuple[bool, str]:
    backend = _database_backend(settings.database_url)
    if backend != "postgresql":
        return True, "database backend is not postgresql"

    if psycopg2 is None:
        return False, "psycopg2 is not installed"

    try:
        conn = psycopg2.connect(settings.database_url)
        conn.close()
        return True, "postgres reachable"
    except Exception as exc:  # noqa: BLE001
        return False, f"postgres unreachable: {exc}"


def preflight_report(settings: Settings) -> dict[str, object]:
    redis_ok, redis_message = check_redis(settings)
    postgres_ok, postgres_message = check_postgres(settings)

    parsed = urlparse(settings.database_url)
    host = parsed.hostname or ""
    db_backend = _database_backend(settings.database_url)

    report = {
        "app_env": settings.app_env,
        "llm_mode": "live" if settings.llm_api_key else "mock",
        "queue_backend": settings.queue_backend,
        "database_backend": db_backend,
        "database_host": host,
        "qa_mode": settings.qa_mode,
        "auth_enabled": settings.auth_enabled,
        "checks": {
            "redis": {"ok": redis_ok, "message": redis_message},
            "postgres": {"ok": postgres_ok, "message": postgres_message},
        },
    }

    healthy = redis_ok and postgres_ok
    report["healthy"] = healthy
    return report


def probe_tcp(host: str, port: int, timeout: float = 1.5) -> bool:
    if not host:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        return result == 0
