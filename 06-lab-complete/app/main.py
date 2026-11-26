"""
Production AI Agent — Part 6 Final Project
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import time

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Định dạng mỗi dòng log của app thành 1 JSON object hợp lệ (tiêu chí 10)."""

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        try:
            parsed = json.loads(msg)
            if isinstance(parsed, dict):
                return json.dumps(parsed, ensure_ascii=False)
        except (ValueError, TypeError):
            pass

        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": msg,
        }
        return json.dumps(payload, ensure_ascii=False)


logger = logging.getLogger("agent")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(JsonFormatter())
    logger.addHandler(_handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Quản lý vòng đời ứng dụng và xử lý SIGTERM graceful shutdown (tiêu chí 11)."""
    logger.info(
        json.dumps(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "lvl": "INFO",
                "event": "startup",
                "environment": settings.environment,
                "port": settings.port,
            }
        )
    )
    yield
    logger.info(
        json.dumps(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "lvl": "INFO",
                "event": "shutdown",
                "msg": "Graceful shutdown on SIGTERM completed",
            }
        )
    )


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = None


@app.get("/health")
def health():
    """Tiêu chí 4 — Liveness probe: luôn trả 200 khi process còn chạy."""
    return {
        "status": "ok",
        "environment": settings.environment,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready")
def ready():
    """Tiêu chí 5 — Readiness probe: 200 khi sẵn sàng, 503 khi Redis mất kết nối."""
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis is not available")
    return {"status": "ready", "redis": "connected"}


@app.post("/ask")
def ask(
    body: AskRequest,
    request: Request,
    api_key: str = Depends(verify_api_key),
):
    """Tiêu chí 6, 7, 8, 10 — Endpoint chính có Auth, Rate Limit, Cost Guard và JSON log."""
    start = time.perf_counter()

    check_rate_limit(api_key)
    check_budget()

    answer = llm_ask(body.question)

    input_tokens = max(1, len(body.question.split()) * 2)
    output_tokens = max(1, len(answer.split()) * 2)
    cost_usd = record_cost(input_tokens, output_tokens)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)

    logger.info(
        json.dumps(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "lvl": "INFO",
                "event": "request",
                "path": request.url.path,
                "status": 200,
                "ms": duration_ms,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": round(cost_usd, 6),
            }
        )
    )

    return {
        "question": body.question,
        "answer": answer,
        "user_id": body.user_id,
        "cost_usd": round(cost_usd, 6),
    }
