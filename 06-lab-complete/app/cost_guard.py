"""
Cost guard (tiêu chí 8).

Yêu cầu:
  • Cộng dồn chi phí LLM (tính theo token) vào Redis
  • Tổng chi phí vượt DAILY_BUDGET_USD (hoặc MONTHLY_BUDGET_USD) → HTTP 402
"""
import time

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

_fallback_cost: dict[str, float] = {}


def _cost_key() -> str:
    return f"cost:daily:{time.strftime('%Y-%m-%d')}"


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    key = _cost_key()
    try:
        current = float(r.get(key) or 0.0)
    except redis.RedisError:
        current = _fallback_cost.get(key, 0.0)

    if current >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Budget exceeded",
                "used_usd": round(current, 6),
                "budget_usd": settings.daily_budget_usd,
            },
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (input_tokens / 1000.0) * PRICE_INPUT_PER_1K + (
        output_tokens / 1000.0
    ) * PRICE_OUTPUT_PER_1K
    key = _cost_key()
    try:
        r.incrbyfloat(key, cost)
        r.expire(key, 86400)
    except redis.RedisError:
        _fallback_cost[key] = _fallback_cost.get(key, 0.0) + cost
    return cost
