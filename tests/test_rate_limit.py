"""S1: login/API brute-force rate limiting (fixed window in Redis)."""

import fakeredis
import pytest

from app.security import rate_limit


@pytest.fixture
def redis():
    return fakeredis.FakeStrictRedis()


def test_allows_up_to_limit(redis):
    for _ in range(5):
        assert rate_limit.check(redis, "login:1.2.3.4", limit=5, window_seconds=60) is True


def test_blocks_over_limit(redis):
    for _ in range(5):
        rate_limit.check(redis, "login:1.2.3.4", limit=5, window_seconds=60)
    # 6th attempt in the same window is blocked
    assert rate_limit.check(redis, "login:1.2.3.4", limit=5, window_seconds=60) is False


def test_isolated_per_key(redis):
    for _ in range(5):
        rate_limit.check(redis, "login:1.1.1.1", limit=5, window_seconds=60)
    # different IP still allowed
    assert rate_limit.check(redis, "login:2.2.2.2", limit=5, window_seconds=60) is True


def test_fails_open_when_redis_down():
    class BrokenRedis:
        def incr(self, *a, **k):
            raise ConnectionError("redis down")

    # Redis outage must not lock admins out.
    assert rate_limit.check(BrokenRedis(), "login:x", limit=5, window_seconds=60) is True
