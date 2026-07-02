# Hướng Dẫn Chạy Dự Án Tradebot
Admin vẫn ở:
http://localhost:8000/admin
Đăng nhập:
username: admin
password: admin-local-12345 

Tài liệu này hướng dẫn chạy local/dev cho MVP Forex Signal Bot:

TradingView bar webhook -> candle -> strategy -> risk/duplicate -> router -> Telegram -> Admin Console.

## 1. Yêu cầu máy

- macOS hoặc Linux.
- Python 3.12.
- `uv`.
- Docker + Docker Compose.
- Internet nếu muốn test Telegram thật.

Kiểm tra nhanh:

```bash
python3 --version
uv --version
docker --version
docker compose version
```

Nếu chưa có `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 2. Cấu hình `.env`

Tạo file `.env`:

```bash
cp .env.example .env
```

Các biến quan trọng:

```env
APP_ENV=local
DATABASE_URL=postgresql+psycopg://tradebot:tradebot@localhost:5432/tradebot
REDIS_URL=redis://localhost:6379/0

ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=...
ADMIN_API_KEY=...
ADMIN_SESSION_SECRET=...

TRADINGVIEW_WEBHOOK_TOKEN=...
TRADINGVIEW_BODY_SECRET=...

TELEGRAM_BOT_TOKEN=...
```

Tạo password hash cho Admin:

```bash
uv run python -c "from app.security.secrets import hash_password; print(hash_password('your-admin-password'))"
```

Copy output vào `ADMIN_PASSWORD_HASH`.

Với local, `TELEGRAM_BOT_TOKEN` có thể để placeholder nếu chưa gửi Telegram thật. Khi `APP_ENV=production`, app sẽ từ chối chạy nếu secret còn placeholder hoặc quá ngắn.

## 3. Cài dependency

```bash
make install
```

Lệnh này chạy `uv sync` và tạo virtualenv theo `uv.lock`.

## 4. Bật Postgres và Redis

```bash
make dev-services-up
```

Kiểm tra container:

```bash
docker compose ps
```

Tắt khi không dùng:

```bash
make dev-services-down
```

## 5. Migrate và seed database

```bash
make migrate
make seed
```

Seed tạo dữ liệu MVP:

- 1 data source `tradingview_bars`.
- 3 symbols: `XAUUSD`, `EURUSD`, `GBPUSD`.
- 2 timeframes: `M15`, `H1`.
- 6 feeds.
- Strategy `liquidity_sweep`.
- 3 demo Telegram groups inactive.
- Component health rows.

Seed là repeat-safe, có thể chạy lại.

## 6. Chạy API

Terminal 1:

```bash
make api
```

API chạy ở:

```text
http://localhost:8000
```

Health endpoints:

```bash
curl http://localhost:8000/api/v1/health/live
curl http://localhost:8000/api/v1/health/ready
curl http://localhost:8000/api/v1/health
```

Ghi chú: `/api/v1/health` có thể trả `503 DEGRADED` ở local nếu worker chưa chạy hoặc Telegram token còn placeholder. Đây là bình thường trong lúc dev.

## 7. Chạy workers và scheduler

MVP dùng Redis/RQ. Mỗi lệnh nên chạy ở một terminal riêng.

Terminal 2:

```bash
make worker-market
```

Terminal 3:

```bash
make worker-signal
```

Terminal 4:

```bash
make worker-telegram
```

Terminal 5:

```bash
make worker-maintenance
```

Terminal 6:

```bash
make scheduler
```

Nếu chỉ muốn đăng ký lại recurring jobs:

```bash
make schedule-jobs
```

Scheduler jobs hiện có:

- `scan_outbox_retry`: quét outbox retry mỗi 20 giây.
- `scan_stale_feeds`: quét feed stale mỗi 60 giây.
- `scan_component_health`: refresh component health mỗi 60 giây.

## 8. Mở Admin Console

URL:

```text
http://localhost:8000/admin
```

Đăng nhập bằng:

- username: giá trị `ADMIN_USERNAME`.
- password: plain password bạn đã dùng để tạo `ADMIN_PASSWORD_HASH`.

Các màn chính:

- Overview: trạng thái hệ thống, feed freshness, latest signals, delivery queue, runbook xử lý lỗi.
- Feeds: matrix symbol/timeframe.
- Groups: tạo group demo, gửi test message, pause/resume, bật LIVE có guard.
- Strategies: strategy config hiện tại.
- Signals: danh sách tín hiệu.
- Deliveries: trạng thái gửi Telegram, retry/skip.
- Settings: cấu hình vận hành đã được mask secret.

## 9. Gửi thử TradingView webhook bằng curl

Thay `YOUR_WEBHOOK_TOKEN` và `YOUR_BODY_SECRET` theo `.env`.

```bash
curl -X POST "http://localhost:8000/api/v1/webhooks/tradingview/bars/YOUR_WEBHOOK_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "secret": "YOUR_BODY_SECRET",
    "symbol": "OANDA:XAUUSD",
    "timeframe": "M15",
    "time": "2026-01-01T08:00:00Z",
    "open": "2000.0",
    "high": "2010.0",
    "low": "1995.0",
    "close": "2005.0",
    "volume": "100",
    "isClosed": true
  }'
```

Kết quả thành công:

```json
{
  "outcome": "created",
  "candleId": 1,
  "enqueued": true
}
```

`M15` có thể enqueue strategy. `H1` chỉ cập nhật context/feed, không enqueue Liquidity Sweep.

## 10. Warmup dữ liệu local/staging

Endpoint import candle chỉ bật khi `APP_ENV=local` hoặc `APP_ENV=staging`.

```bash
curl -X POST "http://localhost:8000/api/v1/admin/candles/import" \
  -H "Authorization: Bearer YOUR_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "candles": [
      {
        "symbol": "OANDA:XAUUSD",
        "timeframe": "H1",
        "time": "2026-01-01T00:00:00Z",
        "open": "2000",
        "high": "2010",
        "low": "1990",
        "close": "2005",
        "volume": "100",
        "isClosed": true
      }
    ]
  }'
```

Production sẽ trả `403 IMPORT_DISABLED`.

## 11. Chạy test

Unit/non-integration:

```bash
make test
```

Integration, cần Postgres đang chạy:

```bash
make test-integration
```

Toàn bộ suite:

```bash
uv run pytest -q
```

Lint:

```bash
make lint
```

Smoke test local:

```bash
make smoke
```

Smoke sẽ:

1. Seed database.
2. Check live/ready.
3. Gửi một fake TradingView bar.
4. Xác nhận candle/feed đã lưu.
5. In trạng thái full health.

## 12. Release check trước khi bật group thật

Local rehearsal:

```bash
uv run python scripts/release_check.py --warn-only
```

Strict gate trước release:

```bash
make release-check
```

Checklist 48h demo nằm ở:

```text
docs/ops/release_checklist.md
```

Không bật group thật nếu:

- Worker/Redis/DB chưa OK.
- Feed còn stale/error mà chưa rõ lý do.
- Telegram bot chưa gửi test message thành công.
- Group còn placeholder chat id.
- Outbox còn failed/retryable/sending chưa xử lý.

## 13. Cấu hình Telegram thật

Luồng khuyến nghị:

1. Tạo Telegram bot bằng BotFather.
2. Copy bot token vào `TELEGRAM_BOT_TOKEN`.
3. Add bot vào group.
4. Lấy `chat_id` thật.
5. Vào Admin Console -> Groups.
6. Tạo group demo với `chat_id`.
7. Bấm `Test message`.
8. Khi test status là `SENT`, mới bấm `Bật LIVE`.

Guard hiện tại:

- Không bật LIVE nếu chat id là `PLACEHOLDER...` hoặc `CHANGE_ME...`.
- Không bật LIVE nếu chưa có test message `SENT`.

## 14. TradingView alert payload

Trong TradingView, alert nên chạy `once per bar close`.

Payload mẫu:

```json
{
  "secret": "YOUR_BODY_SECRET",
  "symbol": "{{ticker}}",
  "timeframe": "{{interval}}",
  "time": "{{time}}",
  "open": "{{open}}",
  "high": "{{high}}",
  "low": "{{low}}",
  "close": "{{close}}",
  "volume": "{{volume}}",
  "isClosed": true
}
```

Webhook URL:

```text
https://YOUR_DOMAIN/api/v1/webhooks/tradingview/bars/YOUR_WEBHOOK_TOKEN
```

Local TradingView không gọi được `localhost` trực tiếp. Khi cần test từ TradingView thật, dùng domain public hoặc tunnel như Cloudflare Tunnel/ngrok.

## 15. Lỗi thường gặp

### `/api/v1/health` trả DEGRADED

Kiểm tra:

```bash
docker compose ps
make schedule-jobs
```

Đảm bảo các worker đang chạy:

```bash
make worker-market
make worker-signal
make worker-telegram
make worker-maintenance
make scheduler
```

Nếu Telegram token còn placeholder, `telegram_api` sẽ là `UNKNOWN`.

### Webhook trả `INVALID_WEBHOOK_TOKEN`

Token trong URL không khớp với hash đã seed từ `TRADINGVIEW_WEBHOOK_TOKEN`.

Cách xử lý:

```bash
make seed
```

Sau đó dùng đúng token trong `.env`.

### Webhook trả `INVALID_BODY_SECRET`

`secret` trong JSON không khớp `TRADINGVIEW_BODY_SECRET`.

### Webhook trả `UNKNOWN_SYMBOL`

Symbol không có trong mapping seed. MVP seed hỗ trợ:

- `OANDA:XAUUSD`
- `OANDA:EURUSD`
- `OANDA:GBPUSD`

### Strategy không tạo signal

Liquidity Sweep cần đủ context:

- 22 nến M15.
- 51 nến H1.
- Setup phải thật sự sweep swing high/low và có confirmation candle.

Nếu thiếu dữ liệu, hệ thống tạo signal `REJECTED` với `INSUFFICIENT_HISTORY`.

### Telegram delivery failed

Vào Admin Console -> Deliveries.

Kiểm tra:

- Bot còn trong group không.
- Chat id có đúng không.
- Bot có quyền gửi tin không.
- Có bị rate limit không.

Sau khi sửa, bấm `Retry now`.

## 16. Reset local database

Nếu cần làm sạch local DB:

```bash
make dev-services-down
docker volume rm tradebot_pgdata
make dev-services-up
make migrate
make seed
```

Chỉ dùng cho local/dev. Không dùng trên production.

## 17. Thứ tự chạy nhanh mỗi ngày

```bash
make dev-services-up
make migrate
make seed
make api
```

Mở thêm các terminal worker/scheduler:

```bash
make worker-signal
make worker-telegram
make worker-maintenance
make scheduler
```

Sau đó mở:

```text
http://localhost:8000/admin
```
