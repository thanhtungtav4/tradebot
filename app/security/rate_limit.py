"""Fixed-window rate limiting in Redis. Fail-open on Redis errors.

ponytail: fixed window, not sliding; a burst at a window boundary can allow up
to 2x. Fine for brute-force defense. Switch to sliding log if precision matters.
"""

import logging

logger = logging.getLogger("rate_limit")


def check(redis, key: str, *, limit: int, window_seconds: int) -> bool:
    """Return True if the request is allowed, False if the limit is exceeded.

    Counts one hit against `key`. On any Redis error, allow the request
    (availability over strictness — never lock the admin out on an outage).
    """
    try:
        count = redis.incr(key)
        if count == 1:
            redis.expire(key, window_seconds)
        return count <= limit
    except Exception as exc:  # noqa: BLE001 - fail open on any backend error
        logger.warning("rate_limit unavailable, failing open: %s", exc)
        return True
