"""
Rate limiting (tiêu chí 7).

Yêu cầu:
  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây (sliding window)
  • Vượt giới hạn → HTTP 429, nên kèm header Retry-After
  • State lưu trong Redis để mọi worker / instance dùng chung và vẫn còn sau khi
    restart agent (script chấm sẽ restart agent để kiểm tra)
"""
import time
import uuid
from collections import defaultdict, deque

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

_WINDOW_SECONDS = 60
_fallback_windows: dict[str, deque] = defaultdict(deque)


def check_rate_limit(key: str) -> None:
    """Sliding window rate limit trên Redis Sorted Set."""
    now = time.time()
    limit = settings.rate_limit_per_minute
    redis_key = f"rate_limit:{key}"

    try:
        r.zremrangebyscore(redis_key, 0, now - _WINDOW_SECONDS)
        current_count = r.zcard(redis_key)
        if current_count >= limit:
            oldest = r.zrange(redis_key, 0, 0, withscores=True)
            retry_after = (
                max(1, int(oldest[0][1] + _WINDOW_SECONDS - now) + 1)
                if oldest
                else _WINDOW_SECONDS
            )
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )
        member = f"{now}:{uuid.uuid4().hex[:8]}"
        r.zadd(redis_key, {member: now})
        r.expire(redis_key, _WINDOW_SECONDS)
    except redis.RedisError:
        window = _fallback_windows[key]
        while window and window[0] < now - _WINDOW_SECONDS:
            window.popleft()
        if len(window) >= limit:
            retry_after = max(1, int(window[0] + _WINDOW_SECONDS - now) + 1)
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )
        window.append(now)
