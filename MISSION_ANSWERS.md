# Day 14 Lab — Mission Answers

> **Học viên:** Nguyễn Thành Tâm  
> **MSSV:** 2A202603933  
> **Lớp:** K5-L3B

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found in `01-localhost-vs-production/develop/app.py`

1. **Hardcode Secrets trực tiếp trong mã nguồn (Dòng 17–18):**
   - `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`.
   - **Nguy cơ:** Lộ thông tin nhạy cảm ngay khi push code lên Git repository. Bản `production/app.py` sửa bằng cách tách ra `config.py` đọc từ biến môi trường (`os.getenv`).
2. **Dùng `print()` thay vì Structured Logging và in cả API Key ra log (Dòng 33–38):**
   - `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")`.
   - **Nguy cơ:** Lộ secret trong hệ thống thu thập log; log dạng chuỗi tự do không có timestamp, log level và khó truy vấn tự động. Bản `production/app.py` sửa bằng `logging` với định dạng JSON (`json.dumps`), không ghi secret.
3. **Bật cứng `DEBUG = True` và `reload=True` (Dòng 21, 53):**
   - **Nguy cơ:** Tốn tài nguyên theo dõi file trên server, không chạy được multi-worker và có thể lộ stack trace khi gặp lỗi. Bản `production/app.py` sửa bằng `reload=settings.debug`.
4. **Không có Health Check (`/health`) và Readiness (`/ready`) endpoints (Dòng 42–43):**
   - **Nguy cơ:** Cloud platform và Load Balancer không biết container còn sống hay đã sẵn sàng nhận traffic. Bản `production/app.py` bổ sung `GET /health` và `GET /ready`.
5. **Bind cứng vào `host="localhost"` và `port=8000` (Dòng 51–52):**
   - **Nguy cơ:** Bind vào `localhost` bên trong container khiến traffic từ ngoài container không kết nối vào được; các nền tảng PaaS (Render/Railway/Cloud Run) cấp port động qua biến môi trường `PORT`. Bản `production/app.py` bind vào `0.0.0.0` và đọc `PORT` từ env.
6. **Không xử lý Graceful Shutdown (`SIGTERM`):**
   - **Nguy cơ:** Khi redeploy hoặc scale down, tiến trình bị tắt đột ngột làm đứt các request đang xử lý dở. Bản `production/app.py` dùng `lifespan` và bắt tín hiệu `signal.SIGTERM`.

### Exercise 1.2: Kết quả chạy bản `develop`

```http
$ curl -i -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 09:05:12 GMT
server: uvicorn
content-length: 84
content-type: application/json

{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

### Exercise 1.3: Bảng so sánh `Develop` vs `Production`

| Feature | Develop (`develop/app.py`) | Production (`production/app.py`) | Tại sao quan trọng? |
| :--- | :--- | :--- | :--- |
| **Config** | Hardcode trong code (`OPENAI_API_KEY`, `PORT=8000`, `DEBUG=True`) | Đọc từ biến môi trường qua `config.py` (12-Factor App) | Tách biệt cấu hình khỏi code; không lộ secret trong Git; dùng chung 1 Docker image cho nhiều môi trường (dev/staging/prod). |
| **Network Binding** | `host="localhost"`, `port=8000` cố định | `host="0.0.0.0"`, `port` đọc từ biến `PORT` | Cho phép nhận kết nối từ bên ngoài container và tương thích với cơ chế cấp phát `PORT` động của cloud platform. |
| **Health check** | ❌ Không có | ✅ Có `GET /health` (liveness) và `GET /ready` (readiness) | Giúp nền tảng tự động restart container khi treo (`/health`) và chỉ điều hướng traffic vào khi instance đã sẵn sàng (`/ready`). |
| **Logging** | Dùng `print()`, in cả secret | Structured JSON logging (`logging` + `json.dumps`), ẩn secret | Dễ dàng thu thập, parse, lọc và tạo cảnh báo tự động trên các hệ thống quản lý log tập trung (Loki, Datadog, ELK). |
| **Shutdown** | Tắt đột ngột khi dừng process | Graceful shutdown (`lifespan` + `SIGTERM`) | Ngừng nhận request mới nhưng hoàn tất nốt các request đang xử lý dở (in-flight), tránh lỗi 502/mất dữ liệu khi rolling deploy. |

---

## Part 2: Docker

### Exercise 2.1: Câu hỏi về `Dockerfile`

1. **Base image là gì?**
   - Trong `02-docker/develop/Dockerfile`: dùng `python:3.11` (bản đầy đủ dựa trên Debian, chứa kèm nhiều build tools và thư viện hệ thống nên rất nặng).
   - Trong `02-docker/production/Dockerfile`: dùng `python:3.11-slim` (bản tối giản chỉ chứa các gói cần thiết để chạy Python).
2. **Working directory là gì?**
   - Là `/app` (được thiết lập bởi `WORKDIR /app`). Mọi lệnh `COPY`, `RUN`, `CMD` sau đó đều chạy tại thư mục này trong container.
3. **Tại sao `COPY requirements.txt` trước khi `COPY` mã nguồn?**
   - Để tận dụng **Docker Layer Caching**. Vì source code thay đổi thường xuyên hơn `requirements.txt`, việc copy và cài đặt dependencies ở layer trước giúp Docker tái sử dụng cache của bước `pip install` khi chỉ sửa code, rút ngắn thời gian build từ vài phút xuống vài giây.
4. **`CMD` vs `ENTRYPOINT` khác nhau thế nào?**
   - `CMD` khai báo lệnh hoặc tham số mặc định khi chạy container và sẽ bị ghi đè hoàn toàn nếu truyền lệnh khác ở cuối `docker run <image> <command>`.
   - `ENTRYPOINT` cố định chương trình thực thi chính của container; các tham số truyền thêm khi `docker run` sẽ được nối vào làm đối số cho `ENTRYPOINT` (trừ khi dùng `--entrypoint`).

### Exercise 2.2 & 2.3: Kết quả chạy container và so sánh kích thước Image

**Kết quả gọi container:**
```http
$ curl -i -X POST "http://localhost:8000/ask?question=What+is+Docker"
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json

{"question":"What is Docker","answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

**Đo kích thước image bằng `docker images | grep my-agent`:**
```text
my-agent:advanced   9819cdd93b9f   240MB    57.4MB
my-agent:develop    7ff43fd0cf4c   1.67GB   426MB
```

- **Develop (`my-agent:develop`):** `1.67 GB` (~`1670 MB`, compressed `426 MB`)
- **Production (`my-agent:advanced`):** `240 MB` (compressed `57.4 MB`)
- **Chênh lệch (Difference):** Giảm **`1430 MB`**, tương đương giảm **`85.63%`** dung lượng (hoặc giảm **`86.53%`** nếu tính theo compressed size).
- **Lý do Multi-stage build giảm mạnh dung lượng:** Stage 1 (`builder`) cài `gcc`, `libpq-dev` và biên dịch các thư viện Python; Stage 2 (`runtime`) dùng `python:3.11-slim` sạch và chỉ copy thư mục thư viện đã cài đặt từ `builder` sang, loại bỏ toàn bộ trình biên dịch C, header files và apt cache.

### Exercise 2.4: Sơ đồ kiến trúc Docker Compose Stack (`02-docker/production/docker-compose.yml`)

```text
                     ┌─────────────────────── Docker network: internal ───────────────────────┐
                     │                                                                        │
Client ──(Port 80)──▶│  [ nginx ] ──(http://agent:8000)──▶ [ agent (FastAPI) ]                │
                     │                                        │           │                   │
                     │               redis://redis:6379/0 ────┘           └─── http://qdrant:6333
                     │                        ▼                                       ▼       │
                     │             [ redis (7-alpine) ]                    [ qdrant (v1.9.0) ]│
                     └────────────────────────────────────────────────────────────────────────┘
```

**Kết quả test qua Nginx (cổng 80):**
```http
$ curl -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json

{"status":"ok","environment":"staging"}

$ curl -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json

{"question":"Explain microservices","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Triển khai Agent Part 6 lên Render
- **Nền tảng sử dụng:** Render (Blueprint `render.yaml`: Web Service Docker + Render Key Value / Redis).
- **Public URL:** https://k5-day14-ai-agent-ybza.onrender.com (chi tiết trong [DEPLOYMENT.md](DEPLOYMENT.md)).
- **Screenshots:** `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`.

### So sánh `railway.toml` với `render.yaml`

| Tiêu chí | `railway.toml` (Railway) | `render.yaml` (Render Blueprint) |
| :--- | :--- | :--- |
| **Định dạng & Triết lý** | TOML; cấu hình cho **1 service đơn lẻ** trong thư mục hiện tại. | YAML; Infrastructure-as-Code (Blueprint) khai báo **toàn bộ multi-service stack** (Web Service, Redis/KeyValue, Database) trong cùng 1 file. |
| **Khai báo Build & Runtime** | `[build] builder = "DOCKERFILE"` hoặc `"NIXPACKS"`; tự động đọc `Dockerfile`. | `type: web`, `runtime: docker` (hoặc `python`), hỗ trợ chỉ định `rootDir` và `dockerfilePath`. |
| **Quản lý Biến môi trường & Secrets** | Không khai báo env vars trong `railway.toml`; phải đặt qua Railway Dashboard hoặc CLI (`railway variables set`). | Khai báo trực tiếp danh sách `envVars` trong `render.yaml`; hỗ trợ tự sinh secret (`generateValue: true`), nhập thủ công (`sync: false`), hoặc liên kết tự động chuỗi kết nối từ service khác (`fromService`). |
| **Khai báo Redis đi kèm** | Phải thêm plugin Redis trên Dashboard/CLI của Railway. | Khai báo luôn block `- type: keyvalue` trong `render.yaml` và tự động nối `connectionString` vào biến `REDIS_URL` của Web Service. |

### Exercise 3.3: Mô tả CI/CD Pipeline lên GCP Cloud Run (`cloudbuild.yaml` & `service.yaml`)
Pipeline trong `03-cloud-deployment/production-cloud-run/cloudbuild.yaml` tự động hóa 4 bước tuần tự khi có commit mới:
1. **`test` (`python:3.11-slim`):** Cài đặt dependencies từ `requirements.txt` cùng `pytest` và chạy toàn bộ unit tests trong `tests/`; nếu test lỗi thì dừng pipeline ngay.
2. **`build` (`gcr.io/cloud-builders/docker`):** Build Docker image gắn 2 tag (`$COMMIT_SHA` và `latest`), tận dụng `--cache-from` image `latest` trước đó để tăng tốc build.
3. **`push` (`gcr.io/cloud-builders/docker`):** Đẩy Docker image vừa build lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **`deploy` (`gcr.io/cloud-builders/gcloud`):** Deploy image đúng mã `$COMMIT_SHA` lên Cloud Run tại region `asia-southeast1` với cấu hình production (tương ứng với `service.yaml`): `min-instances=1` (tránh cold start), `max-instances=10`, `512Mi` RAM, `1` CPU, inject secret `OPENAI_API_KEY` từ Secret Manager và cấu hình `livenessProbe` (`/health`), `startupProbe` (`/ready`).

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/app.py`)
- **API key được kiểm tra ở đâu?** Tại hàm dependency `verify_api_key` dùng `APIKeyHeader(name="X-API-Key", auto_error=False)` và gắn vào `POST /ask` qua `Depends(verify_api_key)`.
- **Điều gì xảy ra nếu thiếu hoặc sai key?** Thiếu key trả về `401 Unauthorized`; sai key trả về `403 Forbidden` (hoặc `401` trong chuẩn hợp đồng Part 6).
- **Làm sao để rotate key không gây downtime?** Đọc danh sách các key hợp lệ từ biến môi trường hoặc Redis (ví dụ `ACTIVE_API_KEYS=new_key,old_key`), cho phép cả key cũ và key mới cùng hoạt động trong thời gian chuyển giao, cập nhật phía client sang key mới rồi mới xóa key cũ.

### Exercise 4.2 & 4.3: Kết quả kiểm tra JWT Auth & Rate Limiting (`401`, `200`, `429`)

- **Thuật toán Rate Limiting trong `rate_limiter.py`:** Sliding Window Counter (lưu các mốc timestamp của từng user trong cửa sổ trượt 60 giây; loại bỏ các timestamp cũ hơn `now - 60s` rồi kiểm tra số lượng).
- **Giới hạn:** Role `user` (`student`): **10 requests/phút**; Role `admin` (`teacher`): **100 requests/phút**.
- **Cách nâng/bypass limit cho admin:** Đọc trường `role` từ payload của JWT token (`user["role"]`), nếu `role == "admin"` thì chuyển sang dùng `rate_limiter_admin` (100 req/phút) hoặc bỏ qua bước check limit.

**1. Trường hợp không có token → `HTTP 401 Unauthorized`:**
```http
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 401 Unauthorized
date: Thu, 26 Nov 2026 10:12:05 GMT
content-length: 84
content-type: application/json
www-authenticate: Bearer
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}
```

**2. Trường hợp có JWT token hợp lệ (`student` / `demo123` tại `POST /auth/token`) → `HTTP 200 OK`:**
```http
$ curl -i -X POST http://localhost:8000/ask \
  -H "Authorization: Bearer <REDACTED_JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"question": "Explain JWT"}'
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 10:12:18 GMT
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"question":"Explain JWT","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","usage":{"requests_remaining":9,"budget_remaining_usd":0.000018}}
```

**3. Trường hợp gọi liên tiếp vượt 10 requests/phút → `HTTP 429 Too Many Requests`:**
```http
$ for i in {1..12}; do curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer <REDACTED_JWT_TOKEN>" -H "Content-Type: application/json" -d "{\"question\": \"Test $i\"}"; done
HTTP/1.1 429 Too Many Requests
date: Thu, 26 Nov 2026 10:12:30 GMT
content-type: application/json
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795687998
retry-after: 48
x-content-type-options: nosniff
x-frame-options: DENY

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":48}}
```

### Exercise 4.4: Cách triển khai Cost Guard
- **Tại sao cần cả Rate Limit và Cost Guard:** Rate Limit giới hạn tốc độ gọi (req/phút) để chống spam/DDoS, nhưng không ngăn được việc user gọi đều đặn với prompt/output rất dài làm tốn tiền token. Cost Guard kiểm soát trực tiếp chi phí USD tích lũy.
- **Thiết kế với Redis:**
  1. **Trước khi gọi LLM (`check_budget`):** Đọc key theo ngày `cost:daily:{YYYY-MM-DD}` từ Redis. Nếu tổng chi phí hiện tại `>= DAILY_BUDGET_USD`, chặn ngay bằng `HTTP 402 Payment Required`.
  2. **Sau khi gọi LLM (`record_cost`):** Tính chi phí của request `cost = (input_tokens / 1000) * PRICE_INPUT + (output_tokens / 1000) * PRICE_OUTPUT`, sau đó cộng dồn nguyên tử vào Redis bằng `INCRBYFLOAT` và đặt TTL `EXPIRE 86400` (24 giờ) để tự động reset sang ngày mới.

---

## Part 5: Scaling & Reliability

### Exercise 5.1–5.5: Health/Readiness, Graceful Shutdown & Stateless Scaling

1. **Sự khác nhau giữa `/health` (Liveness) và `/ready` (Readiness):**
   - `/health` kiểm tra tiến trình Python còn sống hay đã bị treo. Nó **luôn trả 200** ngay cả khi Redis mất kết nối để tránh việc platform restart container liên tục một cách vô ích khi lỗi nằm ở Redis.
   - `/ready` kiểm tra instance đã sẵn sàng xử lý request chưa (bằng cách ping Redis). Khi mất kết nối Redis, `/ready` trả **503 Service Unavailable** để Load Balancer tạm ngưng gửi request mới vào instance đó.
2. **Tại sao lưu state trong RAM bị hỏng khi chạy nhiều instance?**
   - Mỗi container instance (hoặc mỗi worker của Uvicorn) có bộ nhớ RAM tách biệt. Khi Nginx Load Balancer phân phối các request của cùng một user sang các instance khác nhau theo Round-Robin, instance mới không có dữ liệu session/rate-limit trong RAM của instance cũ. Đẩy toàn bộ state xuống **Redis** giúp mọi instance đều đọc/ghi chung một nguồn dữ liệu thống nhất.
3. **Kết quả chạy `docker compose -p k5-day14-scaling up -d --build --scale agent=3` và `python test_stateless.py`:**

```text
============================================================
Stateless Scaling Demo
============================================================

Session ID: 8e41c79a-5d12-4a9b-83e1-9f2c4a11b08e

Request 1: [instance-3f9a1c]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...

Request 2: [instance-b82d4e]
  Q: Why do we need containers?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response...

Request 3: [instance-7c109a]
  Q: What is Kubernetes?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response...

Request 4: [instance-3f9a1c]
  Q: How does load balancing work?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response...

Request 5: [instance-b82d4e]
  Q: What is Redis used for?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response...

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-3f9a1c', 'instance-b82d4e', 'instance-7c109a'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: What is Kubernetes?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: How does load balancing work?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: What is Redis used for?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...

✅ Session history preserved across all instances via Redis!
```

---

## Part 6: Final Project — Output `check_production_ready.py` (`PASS 12/12`)

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 42/42 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

---

## Khai báo sử dụng AI (AI Usage Log — theo `RULES.md`)

- **Công cụ AI sử dụng:** Antigravity AI Assistant (DevOps Mentor).
- **Các phần có hỗ trợ từ AI:**
  1. Giải thích khái niệm 12-Factor App, Multi-stage Docker build, Sliding Window Rate Limiting, Cost Guard, Liveness/Readiness probes, Graceful Shutdown (`SIGTERM`) và 3 trụ cột Observability (Metrics, Traces, Logs).
  2. Hỗ trợ hoàn thiện các mục `TODO` trong `06-lab-complete/` (`app/`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `render.yaml`) và kiểm thử với `check_production_ready.py`.
  3. Hỗ trợ chẩn đoán lỗi đường dẫn Python user site-packages trong `06-lab-complete/benchmark-observability/production/Dockerfile`, bổ sung 2 mục vào `KNOWLEDGE_BASE` trong `mock_llm.py` cho bài tập Eval 7.3 và tổng hợp mẫu báo cáo.
- **Kiểm chứng của học viên:** Học viên đã tự chạy lại các lệnh build Docker image, kiểm tra kích thước image, chạy load test, eval, stack Observability (Grafana, Prometheus, Jaeger, Locust), deploy lên Render và đối chiếu toàn bộ số liệu với các file JSON/CSV thực tế.
