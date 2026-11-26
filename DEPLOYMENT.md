# Deployment Information

## Public URL
https://k5-day14-ai-agent-ybza.onrender.com

## Platform
Render (Docker Web Service + Render Key Value / Redis, cấu hình qua `render.yaml`)

## Test Commands

### 1. Health & Readiness Check
```bash
export BASE="https://k5-day14-ai-agent-ybza.onrender.com"

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
# Expected: 200

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
# Expected: 200
```

### 2. API Test (without & with Authentication)
```bash
# Không có API Key -> Expected: 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Hello"}'

# Có API Key hợp lệ -> Expected: 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'
```

## Environment Variables Set
- `PORT` (Render tự động cấp phát)
- `ENVIRONMENT=production`
- `REDIS_URL` (Tự động liên kết từ service `k5-day14-agent-redis`)
- `AGENT_API_KEY` (Sinh tự động trên Render qua `generateValue: true`)
- `RATE_LIMIT_PER_MINUTE=10`
- `DAILY_BUDGET_USD=1.0`

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
