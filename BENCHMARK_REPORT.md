# Benchmark & Observability Report — Day 14

> **Họ tên:** Nguyễn Thành Tâm — **MSSV:** 2A202603933  
> **Ngày chạy:** 2026-11-26  
> **Môi trường:** Linux Ubuntu x86_64, Python 3.12 (`.venv`), Docker Engine 29.8.0 & Docker Compose

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | `< 500 ms` | Với ứng dụng hội thoại AI, độ trễ dưới 500ms cho 95% người dùng đảm bảo phản hồi tức thì, không gây cảm giác chờ đợi (mock LLM bình thường mất ~180–220ms). |
| Error rate `/ask` | `< 2.0 %` | Cho phép error budget 2% để hấp thụ các lỗi thoáng qua từ LLM provider (timeout, rate limit 429/503 từ upstream ~1%) mà không gây báo động giả liên tục. |
| Accuracy trên golden dataset | `≥ 80 %` (`100 %` sau khi sửa KB) | Ngưỡng quality gate tối thiểu trước khi deploy lên production để chặn các bản cập nhật prompt/RAG bị regression làm giảm chất lượng câu trả lời. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

*(Số liệu trích xuất trực tiếp từ `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json` với `300` requests mỗi mức)*

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO (`p95 ≤ 500ms`, `err ≤ 2%`) |
|---:|---:|---:|---:|---:|---:|---|
| 1 | 4.36 | 190.5 | 222.7 | 1682.2 | 1.33% | ✅ PASS |
| 10 | 35.22 | 196.4 | 228.9 | 1701.5 | 0.33% | ✅ PASS |
| 50 | 81.81 | 255.5 | 854.3 | 1725.7 | 0.67% | ❌ FAIL (vi phạm p95) |
| 100 | 56.20 | 466.8 | 3432.9 | 3855.6 | 1.33% | ❌ FAIL (vi phạm p95) |

**Nhận xét:** RPS có tăng tuyến tính theo concurrency không? Vì sao?

- **Không tăng tuyến tính ở mức concurrency cao:**
  - Từ `concurrency = 1` lên `10`, RPS tăng gần tuyến tính từ `4.36 req/s` lên `35.22 req/s` (~8.1 lần) và `p95` giữ ổn định quanh `~223–229 ms` vì async event loop của Uvicorn tận dụng được thời gian chờ I/O (`asyncio.sleep` mô phỏng gọi mạng tới Vector DB và LLM API).
  - Tuy nhiên khi tăng lên `concurrency = 50` (tăng 5 lần so với 10), RPS chỉ đạt `81.81 req/s` (chỉ tăng ~2.3 lần), trong khi `p95` vọt lên `854.3 ms` (vượt SLO `500 ms`).
  - Ở `concurrency = 100`, hệ thống rơi vào trạng thái bão hòa (saturation/queuing contention trên 1 worker đơn lẻ + giới hạn connection pool), khiến RPS tụt xuống còn `56.20 req/s` và `p95` tăng vọt lên `3432.9 ms` (`max = 4891.3 ms`).

### 2.2 Tail latency

*(Số liệu trích xuất trực tiếp từ `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json` ở `concurrency = 20`, `300` requests)*

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---:|---:|---:|
| 0 | 198.9 | 232.0 | 261.2 |
| 0.03 (mặc định) | 239.7 | 228.8 | 1685.1 |
| 0.1 | 317.9 | 1692.2 | 1721.3 |

**Nhận xét:** Chỉ số nào nhạy nhất với request chậm? Vì sao SLO không nên đặt theo average?

- **Chỉ số nhạy nhất:** `p99` (và tiếp theo là `p95` khi tỉ lệ request chậm vượt quá 5%).
  - Khi `MOCK_SLOW_RATE` tăng từ `0` lên `0.03` (3% request bị chậm ~1.5s), latency trung bình (`avg`) chỉ tăng nhẹ từ `198.9 ms` lên `239.7 ms` (+40.8 ms, vẫn trông rất nhanh), `p95` vẫn ở mức `228.8 ms`, nhưng **`p99` nhảy vọt từ `261.2 ms` lên `1685.1 ms` (gấp ~6.5 lần)**.
  - Khi `MOCK_SLOW_RATE = 0.1` (10% request chậm > 5%), cả **`p95` cũng nhảy vọt lên `1692.2 ms`** và `p99` lên `1721.3 ms`, trong khi **`avg` chỉ mới ở mức `317.9 ms`** (vẫn thấp hơn nhiều so với ngưỡng 500ms!).
- **Vì sao SLO không đặt theo average:** Số trung bình (`avg`) cộng dồn và san phẳng các giá trị ngoại lai (outliers), che giấu hoàn toàn trải nghiệm tệ hại của nhóm 1%–10% người dùng gặp tail latency (phải chờ gần 1.7 giây). Đặt SLO theo percentile (`p95`, `p99`) buộc hệ thống phải đảm bảo chất lượng phục vụ cho đại đa số (95%–99%) tập khách hàng thực tế.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

*(Số liệu trích xuất trực tiếp từ `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json` trên bộ 23 câu hỏi `golden_dataset.jsonl`)*

| Chỉ số | Agent v1 (`eval_v1.json`) | Agent v2 (`eval_v2.json`) | Agent v2 (sau khi sửa KB — `eval_v2_fixed.json`) |
|---|---:|---:|---:|
| Accuracy | 4.35% (1/23) | 91.30% (21/23) | 100.00% (23/23) |
| Avg tokens / câu | 57.9 | 109.0 | 111.7 |
| Tổng cost (USD) | $0.000415 | $0.000760 | $0.000774 |
| Cost / câu đúng (USD) | $0.00041535 | $0.00003619 | $0.00003364 |
| Quality gate | FAIL | PASS (vs v1, min 80%) | PASS (vs v2, min 100%, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry mới vào `KNOWLEDGE_BASE` trong `utils/mock_llm.py` với từ khóa kích hoạt `["jwt", "api key", "xác thực"]` và nội dung giải thích JWT là token tự chứa thông tin có chữ ký số và thời gian hết hạn. |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry mới vào `KNOWLEDGE_BASE` trong `utils/mock_llm.py` với từ khóa kích hoạt `["hpa", "kubernetes", "scale dựa trên"]` và nội dung giải thích Kubernetes HPA tự động scale pod dựa trên cpu, memory và custom metrics. |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- **Latency & Chi phí trên mỗi request:** Agent `v2` có thêm bước retrieval (`retrieve_context` ~20ms) và ghép tài liệu tìm được vào prompt nên số token trung bình mỗi câu tăng почти gấp đôi (`111.7 tokens` so với `57.9 tokens` của `v1`), làm tổng chi phí cho 23 câu tăng từ `$0.000415` lên `$0.000774` và latency `p50` tăng nhẹ từ `165.4 ms` lên `190.4 ms`.
- **Hiệu quả kinh tế thực sự (`Cost / câu đúng`):** `v1` không có context RAG nên trả lời chung chung, chỉ đúng `1/23` câu (`4.35%`), dẫn tới chi phí để có 1 câu trả lời đúng lên tới **`$0.00041535`**. Ngược lại, `v2` (sau khi sửa KB) đạt `23/23` (`100%`), giúp **`Cost / câu đúng` giảm xuống chỉ còn `$0.00003364` — rẻ hơn gấp ~12.3 lần so với `v1`**! Đánh đổi thêm ~25ms latency và ~1.8x token/request để tăng accuracy từ 4.35% lên 100% là hoàn toàn xứng đáng.
- **Cách dùng exit code của `run_eval.py` làm Quality Gate trong CI (Exercise 7.3):**
  - Script `eval/run_eval.py` trả về **`exit code 0`** khi đạt ngưỡng `--min-accuracy` và không có câu nào bị regression so với `--baseline`, ngược lại trả về **`exit code 1`** khi vi phạm. Trong GitHub Actions, bất kỳ step nào có exit code khác 0 sẽ tự động đánh trượt (fail) job CI và chặn merge Pull Request:
    ```yaml
    - name: Run Golden Dataset Quality Gate
      run: |
        python eval/run_eval.py \
          --url http://localhost:8002 \
          --min-accuracy 0.95 \
          --baseline reports/eval_v2_fixed.json \
          --out reports/eval_ci.json
    ```

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (`screenshots/grafana-dashboard.png`)
- [x] Một trace chậm trong Jaeger (`screenshots/jaeger-slow-trace.png`)
- [x] Một trace lỗi trong Jaeger (`screenshots/jaeger-error-trace.png`)
- [x] Trang Alerts của Prometheus với ít nhất 2 alert đang **firing** (`screenshots/prometheus-alert-firing.png`)

**Trả lời câu hỏi phân tích Dashboard (Exercise 7.4):**
1. **Khoảng cách giữa `avg` và `p95` / `p99` trên panel Latency:** Đường `avg` nằm thấp (~220–245ms) và rất phẳng, trong khi đường `p99` (và `p95` khi tăng `MOCK_SLOW_RATE`) vọt lên ~1.7 giây do 3% request rơi vào nhánh tail latency (`+1500ms`).
2. **Vì sao Input tokens/s luôn cao hơn Output tokens/s trên panel LLM:** Ở Agent `v2`, mỗi prompt gửi lên LLM bao gồm `SYSTEM_PROMPT` + đoạn tài liệu `context` lấy từ `KNOWLEDGE_BASE` + câu hỏi của user (~70–85 input tokens), trong khi câu trả lời ngắn gọn chỉ khoảng ~35–46 output tokens.
3. **Vì sao Nginx chặn `/metrics` (trả về `404`) từ bên ngoài:** Endpoint `/metrics` phơi bày chi tiết cấu trúc nội bộ của hệ thống (tên các route, lưu lượng truy cập, tỉ lệ lỗi, tên model LLM, chi phí USD tích lũy, phiên bản phần mềm). Vì vậy Nginx chặn `/metrics` ở cổng public `8080`, chỉ cho phép Prometheus truy cập trực tiếp qua mạng Docker nội bộ `obs_net` (`agent:8000/metrics`).

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (`for: 1m`, ngưỡng `> 5%`) | ~75 giây (~15s cửa sổ rate tăng + 60s `for: 1m`) | Panel **Error Rate** (Golden Signals) chuyển đỏ (~20%) & **HTTP Requests by Status** (cột `503` tăng vọt). |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (`for: 2m`, ngưỡng `p95 > 0.8s`) | ~140 giây (~20s bucket dịch chuyển + 120s `for: 2m`) | Panel **HTTP Latency (p50 / p95 / p99 / avg)** và **p95 Latency** (nhảy lên ~1.7s). |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`for: 1m`, ngưỡng `> $0.50/h`) và `AgentHighLatencyP95` | ~70 giây (với `LLMCostBurnRateHigh`) | Panel **Cost Burn Rate (USD/h)** (tăng ~16.7 lần) và **LLM Call Latency**. |
| D | `docker pause` 1 instance | `AgentInstanceDown` (`for: 30s`, điều kiện `up{job="agent"} == 0`) | ~35–40 giây (1 chu kỳ scrape 5s timeout + 30s `for: 30s`) | Panel **Instances Up** (giảm đi 1) và **Requests/s by Instance** (1 đường rơi về 0). |
| E | `AGENT_VERSION=v1` | **Không có alert nào firing** | Không bao giờ firing | Panel **Retrieval Hit Ratio** rơi về 0, **Tokens/s** giảm ~45%, bảng **Running Instances** đổi nhãn sang `v1`. |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

- Sự cố ở thí nghiệm E là **suy giảm chất lượng câu trả lời (Quality / Silent Regression)** chứ không phải lỗi hạ tầng: HTTP status vẫn `200 OK`, latency thậm chí còn nhanh hơn và chi phí thấp hơn nên mọi chỉ số Golden Signals về hạ tầng đều xanh.
- Để phát hiện trong production cần kết hợp 3 lớp:
  1. **Trước khi deploy (CI/CD Quality Gate):** Chạy `eval/run_eval.py` trên golden dataset để chặn ngay từ bước Pull Request (như đã làm ở Phần 3).
  2. **Metric nghiệp vụ / RAG chuyên biệt:** Đặt alert khi chỉ số `agent_retrieval_total{result="hit"}` hoặc tỉ lệ retrieval hit ratio đột ngột rơi xuống dưới ngưỡng (ví dụ `< 50%` trong 5 phút) hoặc khi số `input_tokens` trung bình mỗi request giảm bất thường (dấu hiệu mất context RAG).
  3. **Online Eval / User Feedback:** Thu thập nút Thumbs Up/Down của người dùng thực tế và chạy LLM-as-a-Judge chấm điểm ngẫu nhiên một tỉ lệ nhỏ (ví dụ 1–5%) log hội thoại production theo thời gian thực.

### 4.3 Debug bằng trace

**1. Một trace chậm nhất tìm được trong Jaeger:**
- `trace_id`: `775ca5ef2b455fcd77c5a21602302051`
- Tổng thời gian: `~1702.4 ms`
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (`1680.4 ms`, chiếm **`98.7%`** tổng thời gian request; trong khi bước `agent.retrieve_context` chỉ mất `~20 ms`). Điều này chứng minh nút thắt cổ chai nằm ở bước gọi LLM upstream chứ không phải ở bước tìm kiếm tài liệu RAG hay code xử lý của FastAPI.
- Dòng log tương ứng (grep theo `trace_id` từ `docker compose -p k5-day14-observability logs agent`):

```json
{"ts": "2026-11-26T14:59:58.724468+00:00", "level": "INFO", "service": "observable-agent", "instance": "179f40f82736", "event": "llm_call", "trace_id": "775ca5ef2b455fcd77c5a21602302051", "span_id": "d885410922527193", "request_id": "8fee29b1d04d", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 74, "output_tokens": 37, "cost_usd": 3.3e-05, "llm_ms": 1680.4}
```

**2. Một trace lỗi (`error=true`) tìm được trong Jaeger:**
- `trace_id`: `4836b69735ff920f4b138c68082f060a`
- Span lỗi: `chat mock-llm-small` (có event `exception`: `Upstream LLM error: 503 Service Unavailable (mock)`).
- Dòng log JSON tương ứng:

```json
{"ts": "2026-11-26T14:59:56.145920+00:00", "level": "INFO", "service": "observable-agent", "instance": "179f40f82736", "event": "llm_error", "trace_id": "4836b69735ff920f4b138c68082f060a", "span_id": "8cfd1205586d8935", "request_id": "c22908965015", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

*(Số liệu trích xuất trực tiếp từ `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv`)*

| Số instance | Hàng số liệu | Requests | RPS (`Requests/s`) | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---:|---|---:|---:|---:|---:|---:|---:|
| **1** (`scale_1`) | `POST /ask` | 7072 | 59.31 | 200 | 400 | 1700 | 85 (1.20%) |
| **1** (`scale_1`) | `Aggregated` | 7786 | 65.30 | 190 | 380 | 1700 | 85 (1.09%) |
| **3** (`scale_3`) | `POST /ask` | 7137 | 59.87 | 200 | 280 | 1700 | 63 (0.88%) |
| **3** (`scale_3`) | `Aggregated` | 7794 | 65.39 | 190 | 270 | 1700 | 63 (0.81%) |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

- **Scale từ 1 lên 3 instance giúp giảm đáng kể `p95` và `max latency`:**
  - Ở `POST /ask`, **`p95` giảm từ `400 ms` xuống còn `280 ms` (cải thiện 30%)**, và ở `Aggregated` giảm từ `380 ms` xuống `270 ms`. Độ trễ tối đa (`Max Response Time`) cũng giảm từ `2132.45 ms` xuống `1862.37 ms`, và `p95` của `GET /health` giảm mạnh từ `63 ms` xuống `25 ms`.
  - Lý do: Khi chỉ có 1 instance (giới hạn `0.5 CPU`), 100 concurrent users tạo ra độ trễ xếp hàng (event loop scheduling & CPU contention) trên một process Uvicorn duy nhất. Khi scale lên 3 instance, Nginx chia đều tải (~20 req/s mỗi instance), triệt tiêu hiện tượng nghẽn CPU cục bộ.
- **Tại sao RPS (~65.3 req/s) và `p50` (200 ms), `p99` (1700 ms) gần như không đổi?**
  - **Về RPS:** Trong `locustfile.py`, mỗi trong số 100 virtual users có thời gian nghỉ `wait_time = between(0.5, 2.0)` (trung bình nghỉ `1.25s`) cộng với thời gian xử lý request trung bình `~0.225s` → mỗi user chỉ gửi tối đa `1 / (1.25 + 0.225) ≈ 0.67 req/s`. Với 100 users, tổng lưu lượng đầu vào tối đa mà Locust phát sinh chỉ đạt khoảng **`~65–67 req/s`** (Law of Little: $L = \lambda \times W$). Ngay cả 1 instance async cũng đã đủ sức xử lý thông lượng 65 req/s này.
  - **Về `p50` và `p99`:** Nút thắt nằm ở **thời gian phản hồi của chính dịch vụ LLM bên ngoài (I/O-bound latency)** — mỗi lần gọi `mock_llm` luôn tốn ~180–200ms (`p50`) và 3% số lần gọi bị tail latency +1500ms (`p99 = 1700ms`). Scale thêm nhiều container Agent chỉ giúp xử lý được nhiều người dùng đồng thời hơn mà không làm giảm thời gian chờ mỗi lệnh gọi LLM đơn lẻ (muốn giảm `p50`/`p99` của LLM phải dùng semantic caching, streaming, hoặc model nhỏ hơn/nhanh hơn).

---

## 6. Kết luận

- **3 điều học được về benchmark & observability:**
  1. **Đừng bao giờ tin vào Latency trung bình (`avg`):** Một hệ thống có `avg = 239ms` vẫn có thể bắt người dùng ở nhóm `p99` chờ tới `1.7 giây`. Mọi SLO và Alert về hiệu năng bắt buộc phải thiết lập dựa trên phân vị (`p95`, `p99`).
  2. **Hạ tầng xanh không đồng nghĩa với AI trả lời đúng:** Các công cụ giám sát hạ tầng (Prometheus/Grafana) chỉ bắt được lỗi hệ thống (`5xx`, timeout, sập container, đội chi phí), hoàn toàn "mù" trước lỗi suy giảm chất lượng câu trả lời (như khi tụt từ `v2` về `v1`). Phải luôn kết hợp **Offline Golden Dataset Eval (Quality Gate trong CI)** với **Online Observability**.
  3. **Sức mạnh của sự kết hợp Metrics → Traces → Logs qua `trace_id`:** Metrics trên Grafana báo động *khi nào* hệ thống bất thường; Traces trên Jaeger chỉ đích danh *span nào* gây chậm (`chat mock-llm-small` chiếm 98.7% thời gian); và `trace_id` trong JSON logs cho phép truy xuất chính xác ngữ cảnh lỗi của từng request.
- **Nếu đưa agent này lên production thật, em sẽ thêm các metric và alert sau:**
  - **Metrics bổ sung:**
    - `agent_cache_hits_total` / `agent_cache_misses_total` (hiệu quả của Semantic/Redis Cache).
    - `llm_time_to_first_token_seconds` (TTFT — cực kỳ quan trọng khi dùng streaming response).
    - `agent_guardrail_blocked_total{reason="prompt_injection|pii|budget"}` và `user_feedback_score_total{rating="up|down"}`.
    - Nginx/Ingress access metrics (`nginx_http_requests_total{status="502|504"}`) để bắt những lỗi gateway timeout mà bản thân container agent không nhìn thấy.
  - **Alerts bổ sung:**
    - Alert khi **Retrieval Hit Ratio** tụt xuống `< 40%` trong 10 phút (cảnh báo Vector DB hoặc pipeline RAG có vấn đề).
    - Alert khi **Rate Limit `429` hoặc Budget `402` spike** bất thường (dấu hiệu bị tấn công brute-force/spam hoặc một khách hàng doanh nghiệp vừa chạm trần quota).
