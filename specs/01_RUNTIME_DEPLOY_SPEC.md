# 01_RUNTIME_DEPLOY_SPEC - Runtime, Deploy, Process

## 1. Mục tiêu

Spec này khóa môi trường chạy MVP theo hướng không phụ thuộc Windows. MVP dùng TradingView bar webhook làm data feed, backend chạy được trên macOS/Linux/VPS Linux. MT5 connector chuyển sang phase sau khi có Windows VPS.

## 2. Runtime decision

MVP chạy theo mô hình:

```text
Linux VPS/macOS dev machine
  - Python 3.12 virtualenv
  - FastAPI API process
  - RQ workers
  - RQ scheduler

PostgreSQL
  - local service, Docker, hoặc managed DB

Redis
  - local service, Docker, hoặc managed Redis
```

MT5 future phase chạy theo mô hình:

```text
Windows VPS
  - MetaTrader 5 Terminal
  - MT5 Python Connector Agent
  - Push candles/ticks to backend API
```

## 3. Processes

| Process | Command mẫu | Nhiệm vụ |
| --- | --- | --- |
| API | `uvicorn app.main:app --host 0.0.0.0 --port 8000` | Admin API, webhooks, health |
| Scheduler | `rq-scheduler --url $REDIS_URL` | Maintenance, data feed stale checks, outbox retry scan mỗi `RETRY_SCAN_INTERVAL_SECONDS` |
| Worker market | `rq worker market --url $REDIS_URL` | Normalize/store webhook candles, enqueue strategy |
| Worker signal | `rq worker signal --url $REDIS_URL` | Strategy, risk, router |
| Worker telegram | `rq worker telegram --url $REDIS_URL` | Send Telegram, retry |

Production nên chạy bằng systemd, Docker Compose, Supervisor hoặc process manager tương đương. MVP local có thể chạy bằng terminal riêng.

## 4. Environment variables

| Name | Required | Example | Ghi chú |
| --- | --- | --- | --- |
| `APP_ENV` | yes | `production` | `local`, `staging`, `production` |
| `APP_SECRET_KEY` | yes | random 32+ chars | Ký token nội bộ |
| `DATABASE_URL` | yes | `postgresql+psycopg://...` | Không log full URL |
| `REDIS_URL` | yes | `redis://localhost:6379/0` | Queue/cache |
| `ADMIN_AUTH_MODE` | yes | `api_key` | MVP dùng API key |
| `ADMIN_API_KEY` | yes | random 32+ chars | Header `Authorization: Bearer ...` |
| `ADMIN_CONSOLE_ENABLED` | no | `true` | Bật/tắt browser Admin Console |
| `ADMIN_USERNAME` | yes | `admin` | Username cho Admin Console MVP |
| `ADMIN_PASSWORD_HASH` | yes | bcrypt/argon2 hash | Không lưu plain password |
| `ADMIN_SESSION_SECRET` | yes | random 32+ chars | Ký session cookie |
| `ADMIN_SESSION_TTL_HOURS` | no | `8` | Session timeout |
| `TELEGRAM_BOT_TOKEN` | yes | `123:abc` | Không log |
| `TELEGRAM_SEND_TIMEOUT_SECONDS` | no | `10` | Default 10 |
| `TELEGRAM_HEALTH_CACHE_SECONDS` | no | `300` | TTL cache getMe trong health check |
| `OUTBOX_LOCK_TIMEOUT_SECONDS` | no | `120` | Reclaim outbox row nếu lock stale |
| `RETRY_SCAN_INTERVAL_SECONDS` | no | `20` | Scheduler scan outbox để retry |
| `DUPLICATE_LOCK_TTL_SECONDS` | no | `60` | TTL Redis lock duplicate guard |
| `TRADINGVIEW_WEBHOOK_TOKEN` | yes | random 32+ chars | Token trong URL path, seed vào data_sources |
| `TRADINGVIEW_BODY_SECRET` | yes | random 32+ chars | Shared secret trong body, seed vào data_sources |
| `TRADINGVIEW_ALLOWED_IPS` | no | `52.89.214.238,...` | IP allowlist TradingView; rỗng = tắt allowlist |
| `MTX_WEBHOOK_SECRET` | no | random 32+ chars | HMAC secret cho MT4/MT5/signal webhook future |
| `WEBHOOK_FUTURE_ALLOWED_SKEW_SECONDS` | no | `300` | Reject replay HMAC webhook future |
| `STALE_GRACE_MINUTES` | no | `20` | Cộng thêm trên độ dài bar để tính stale theo timeframe (M15→35m, H1→80m). Thay cho ngưỡng cố định cũ |
| `FUTURE_CANDLE_BUFFER_SECONDS` | no | `120` | Reject candle có candle_time tương lai quá buffer |
| `CANDLE_RETENTION_DAYS` | no | `365` | Purge market_candles cũ hơn (xem 06 §10) |
| `AUDIT_RETENTION_DAYS` | no | `365` | Purge admin_activity_logs cũ hơn |
| `DEFAULT_TIMEZONE` | yes | `UTC` | Storage dùng UTC |
| `LOG_LEVEL` | no | `INFO` | `DEBUG` chỉ local |

## 5. Directory layout

Runtime không được ghi file vào source tree ngoài logs/caches có chủ đích.

```text
tradebot/
  app/
  migrations/
  specs/
  tests/
  .env.example
  pyproject.toml
```

Runtime data:

```text
/var/lib/tradebot/
  logs/
  backups/
  exports/
```

## 6. Health check contract

Endpoint:

```http
GET /api/v1/health
```

Response success:

```json
{
  "status": "OK",
  "components": {
    "api": {"status": "OK"},
    "db": {"status": "OK", "latencyMs": 12},
    "redis": {"status": "OK", "latencyMs": 3},
    "dataFeed": {"status": "OK", "lastCandleAt": "2026-06-30T15:00:00Z"},
    "telegram": {"status": "OK"}
  }
}
```

Nếu component lỗi, HTTP status là `503`, body vẫn giữ cùng shape với `status: "DEGRADED"` hoặc `status: "DOWN"`.

## 7. Backup

- PostgreSQL backup tối thiểu 1 lần/ngày.
- Giữ 7 daily backups gần nhất.
- Backup phải bao gồm config, signals, deliveries, candles tối thiểu 30 ngày gần nhất.
- Không backup `.env` chung vào nơi public.

## 8. Acceptance criteria

- Cài được Python dependencies trên macOS/Linux host.
- API, scheduler và 3 worker chạy độc lập.
- `/api/v1/health` phát hiện được DB/Redis/data feed/Telegram lỗi.
- Có `.env.example` đủ biến bắt buộc khi scaffold code.
- Restart worker không gửi lại Telegram message đã `SENT`.
