# 09_MONITORING_TEST_SPEC - Monitoring and Test Plan

## 1. Mục tiêu

Hệ thống phải cho biết đang sống hay chết ở đâu: TradingView data feed, DB, Redis, strategy, router, Telegram. Test phải chứng minh MVP hoạt động bằng fake data trước khi dùng group thật.

## 2. Structured logging

Log JSON khuyến nghị:

```json
{
  "timestamp": "2026-06-30T10:00:00Z",
  "level": "INFO",
  "event": "signal_approved",
  "requestId": "req_123",
  "signalUid": "liquidity_sweep:XAUUSD:M15:BUY:...",
  "symbol": "XAUUSD",
  "timeframe": "M15",
  "strategyCode": "liquidity_sweep",
  "message": "Signal approved"
}
```

### Correlation id

`requestId` truyền xuyên 3 worker để trace một signal end-to-end:

- API middleware sinh `requestId` mỗi inbound request (đọc header `X-Request-Id` nếu client gửi, không thì tạo `req_<uuid4hex>`). Trả lại trong response header `X-Request-Id`.
- Webhook ingest đưa `requestId` vào job payload khi enqueue strategy job. Strategy job đưa tiếp vào telegram outbox job. Mỗi worker log kèm `requestId` nhận từ job, không sinh mới.
- Nếu một bước thiếu `requestId` (vd job cũ), worker sinh mới và log `requestId_generated` để vẫn trace được.
- `signal_events.details` nên chứa `requestId` để Admin Console nối log với signal timeline.

Required events:

- `data_feed_health_ok`
- `data_feed_stale`
- `tradingview_bar_received`
- `candles_fetched`
- `candle_upserted`
- `strategy_started`
- `strategy_rejected`
- `signal_approved`
- `signal_duplicate_skipped`
- `signal_routed`
- `telegram_send_started`
- `telegram_send_succeeded`
- `telegram_send_failed`

## 3. Metrics

MVP có thể log counters trước, Prometheus sau.

Counters:

- `candles_ingested_total`
- `signals_created_total`
- `signals_rejected_total`
- `signals_approved_total`
- `signals_duplicate_total`
- `telegram_sent_total`
- `telegram_failed_total`

Gauges:

- `last_data_feed_candle_timestamp`
- `pending_telegram_outbox_count`
- `redis_queue_depth_market`
- `redis_queue_depth_signal`
- `redis_queue_depth_telegram`

Latency (đo KPI "<30s từ bar close webhook đến enqueue Telegram", `00 §10` / `11 §4`):

- `signal_pipeline_latency_seconds` — đo từ `tradingview_bar_received` (webhook nhận) đến lúc enqueue telegram outbox cho signal đó. MVP có thể log per-signal latency value; Prometheus histogram sau.
- Mỗi `signal_routed` event log thêm field `pipelineLatencySeconds` để verify KPI từ log mà không cần metrics backend.

## 4. Health check

`GET /api/v1/health` phải kiểm tra:

- DB simple query.
- Redis ping.
- Data feed freshness from latest TradingView candle per active symbol/timeframe.
- Telegram check: cache kết quả `getMe` trong Redis với TTL `TELEGRAM_HEALTH_CACHE_SECONDS` (default 300s). Health full chỉ gọi Telegram thật khi cache miss/expired, tránh spam API và rate limit. Cache hit trả status cached.
- Last successful candle fetch age.

Nếu last candle quá cũ so với timeframe, component data feed phải `DEGRADED`.

## 5. Unit tests

Required:

- Settings validation.
- Candle normalizer.
- Symbol mapping.
- Closed-candle detection.
- Liquidity Sweep BUY.
- Liquidity Sweep SELL.
- Liquidity Sweep reject insufficient data.
- Liquidity Sweep reject INSUFFICIENT_HISTORY khi thiếu lookback (warmup).
- Warmup creates a `signals` row with `status=REJECTED`, `reject_code=INSUFFICIENT_HISTORY`, and `WARMUP_SKIPPED` event.
- H1 candle ingest updates feed freshness but does not enqueue Liquidity Sweep strategy.
- Confidence scoring deterministic: cùng input ra cùng confidence, base + bonus đúng.
- Risk manager RR BUY/SELL.
- Spread rejection khi spread có giá trị.
- Spread filter skip khi spread null (TradingView bar webhook).
- Duplicate UID generation.
- Router group matching.
- Telegram formatter BASIC/FULL.
- Error response formatter.
- Admin overview status aggregation.
- Admin feed matrix stale/healthy status.
- Admin feed matrix warmup status.
- Admin action audit log creation.
- Admin Console login/session/CSRF behavior.
- Admin Console five-minute status data rendering.

## 6. Integration tests

Use fake TradingView bar webhook payloads and mocked Telegram API.

Scenarios:

1. Receive fake TradingView bar payload, upsert DB, enqueue strategy.
2. Detect Liquidity Sweep, approve risk, save signal.
3. Route one signal to correct VIP group only.
4. Create outbox row, mock Telegram success, mark SENT.
5. Repeat same signal, confirm duplicate skip and no new outbox.
6. Mock Telegram 429, confirm retry schedule.
7. Load admin overview data and confirm status cards match DB/Redis/data feed/Telegram fixtures.
8. Login to Admin Console, load Overview, and confirm no secrets are rendered in HTML or JSON payloads.
9. Send H1-only payload and confirm no Liquidity Sweep strategy job is enqueued.
10. Import local/staging warmup candles through admin import and confirm validation/upsert path is reused.

## 7. Manual smoke test

Before production:

1. Start API, Redis, DB, workers.
2. Run seed data.
3. Verify `/api/v1/health`.
4. Call `POST /api/v1/admin/telegram/test-message` for each demo group.
5. Run fake strategy job and confirm one signal delivery.
6. Confirm no secrets in logs.
7. Open Admin Console and verify operator can identify system status, stale feeds and failed deliveries without reading logs.

## 8. MVP acceptance checklist

- API starts cleanly.
- DB migrations apply from zero.
- Seed data creates 3 groups and one strategy.
- Fake data integration test passes.
- Data feed freshness health passes after webhook ingest.
- M15 stale threshold is 35 minutes and H1 stale threshold is 80 minutes when `STALE_GRACE_MINUTES=20`.
- Telegram smoke test sends one message per demo group.
- Duplicate signal test does not send second message.
- Logs show enough context to debug failed delivery.
- `signal_routed` log/metric chứa `pipelineLatencySeconds` để verify KPI <30s.
- Admin Console five-minute usability checklist passes.
