from __future__ import annotations

from unittest.mock import MagicMock, patch

from shared.rate_limit_redis import redis_rate_limit_allow, redis_rate_limit_available


def test_redis_rate_limit_allow_blocks_over_limit() -> None:
    import shared.rate_limit_redis as rl

    rl._REDIS_AVAILABLE = None
    rl._REDIS_URL = None
    rl._REDIS_CLIENT = None

    client = MagicMock()
    client.ping.return_value = True
    client.incr.side_effect = [1, 2]
    client.expire.return_value = True

    with patch("redis.from_url", return_value=client):
        assert redis_rate_limit_available("redis://127.0.0.1:6379/0") is True
        allowed = redis_rate_limit_allow(
            "redis://127.0.0.1:6379/0",
            "1.2.3.4",
            max_requests=1,
            window_seconds=60,
        )
        assert allowed is True
        blocked = redis_rate_limit_allow(
            "redis://127.0.0.1:6379/0",
            "1.2.3.4",
            max_requests=1,
            window_seconds=60,
        )
        assert blocked is False


def test_redis_rate_limit_returns_none_without_url() -> None:
    assert redis_rate_limit_allow("", "client", max_requests=5, window_seconds=60) is None
