# SPEC v1.1 - Forex Signal Bot Telegram Multi-Group

## 1. Mục tiêu

Xây dựng hệ thống bot tự động lấy dữ liệu thị trường Forex, phát hiện tín hiệu theo strategy có cấu hình, lọc rủi ro, chống spam, rồi gửi tín hiệu tới đúng nhóm Telegram.

MVP tập trung vào tín hiệu thật, gửi đúng nhóm và log đầy đủ. Hệ thống phải mở rộng được về sau cho nhiều nguồn dữ liệu, nhiều strategy, AI filter, backtest và auto-trade, nhưng không trộn các phần đó vào core MVP.

## 2. Bộ tài liệu spec

Đọc theo thứ tự:

1. `00_MASTER_SPEC.md` - mục tiêu, scope, kiến trúc, phase, quyết định kỹ thuật chính.
2. `01_RUNTIME_DEPLOY_SPEC.md` - runtime Linux/macOS-first cho TradingView webhook, process, env, deploy, backup.
3. `02_DATA_SOURCE_SPEC.md` - TradingView bar webhook, candle chuẩn, symbol mapping, closed-candle rule.
4. `03_STRATEGY_ENGINE_SPEC.md` - plugin strategy, context, signal contract, Liquidity Sweep v1.
5. `04_SIGNAL_RISK_SPEC.md` - lifecycle, risk manager, duplicate guard, cooldown.
6. `05_TELEGRAM_ROUTER_SPEC.md` - group config, routing, formatter, retry, idempotency.
7. `06_DATABASE_SPEC.md` - PostgreSQL schema, indexes, constraints, seed data.
8. `07_API_ADMIN_SPEC.md` - FastAPI `/api/v1`, admin API, webhook API, error contract.
9. `08_SECURITY_SPEC.md` - secret, TradingView webhook auth, future HMAC bridge auth, rate limit, log redaction.
10. `09_MONITORING_TEST_SPEC.md` - logs, metrics, health check, tests, acceptance.
11. `10_FUTURE_PHASES_SPEC.md` - AI, MT4, TradingView, backtest, auto-trade boundary.
12. `11_PRODUCT_OPS_SPEC.md` - problem statement, personas, KPI, release criteria, ops playbook.
13. `12_ADMIN_CONSOLE_SPEC.md` - visual admin console, operator cockpit, workflows, UI states, usability acceptance.

## 3. Problem statement

Bot giải quyết nhu cầu gửi tín hiệu giao dịch vào nhiều nhóm Telegram cho user. Hệ thống cần phân biệt nhóm free và VIP, gửi đúng mức thông tin theo từng nhóm, tránh spam tín hiệu trùng và giúp admin/operator kiểm tra được tín hiệu đã tạo, đã route và đã gửi thành công hay chưa.

Primary users:

- Admin tín hiệu: cấu hình group, strategy, symbol, timeframe và kiểm tra log.
- Trader/user trong nhóm free: nhận tín hiệu cơ bản.
- Trader/user trong nhóm VIP: nhận tín hiệu đầy đủ hơn gồm entry, SL, TP, RR, lý do và invalid condition.
- Operator vận hành: theo dõi health, xử lý lỗi webhook/data feed/Telegram/DB/Redis.

## 4. MVP scope

### In scope

- Data source chính: TradingView bar webhook.
- Backend tự phân tích bằng Python từ candle đã lưu; Pine Script chỉ broadcast bar data, không quyết định strategy.
- Symbols: `XAUUSD`, `EURUSD`, `GBPUSD`.
- Timeframes: `M15`, `H1`.
- Strategy đầu tiên: `liquidity_sweep`.
- Telegram: 3 nhóm demo gồm free, vip, smc.
- Admin Console v1: trực quan, dễ vận hành, nhìn 5 phút hiểu bot đang OK hay lỗi ở đâu.
- Storage: PostgreSQL.
- Queue: RQ + Redis.
- Chỉ chạy strategy trên nến đã đóng.
- Log đầy đủ signal, route, delivery và lỗi.

### Out of scope MVP

- Auto-trade.
- MT5 connector production.
- MT4 bridge production.
- TradingView strategy/confirmation production; MVP chỉ dùng TradingView bar webhook làm data feed.
- AI filter bắt buộc.
- News filter production.
- Dashboard analytics nâng cao.
- Backtest/report tự động.

## 5. Non-goals

- Không cam kết lợi nhuận.
- Không phải lời khuyên tài chính.
- Không auto-trade trong MVP.
- Không đặt lệnh thật hoặc quản lý position.
- Không đảm bảo mọi broker có giá giống TradingView.

## 6. Quyết định kỹ thuật khóa

- Backend dùng Python + FastAPI.
- Worker dùng RQ + Redis.
- Database dùng PostgreSQL.
- MVP chạy tốt trên macOS/Linux/VPS Linux vì không phụ thuộc MT5 terminal.
- MT5 connector là phase sau, cần Windows host/VPS có MT5 terminal local.
- API public/internal đều dùng contract rõ ràng, Pydantic validation ở boundary, error format thống nhất.
- Data source, strategy, router, Telegram sender tách module. Không hardcode logic theo từng group.
- Auto-trade nếu có sau này phải là `Execution Engine` riêng, không sửa `Signal Engine` thành engine đặt lệnh.

## 7. Kiến trúc tổng thể

```text
TradingView Bar Alert
  -> Webhook Receiver
  -> Candle Normalizer
  -> PostgreSQL market_candles
  -> Strategy Worker
  -> Risk Manager + Duplicate Guard
  -> Signal Router
  -> Telegram Outbox
  -> Telegram Worker
  -> Telegram Groups
```

Extension sau MVP:

```text
MT5 Terminal       -> MT5 Python Connector -> Candle Adapter
MT4 EA Bridge       -> MT4 Bridge API  -> Candle Buffer
AI Filter           -> Post-rule signal scoring
Execution Engine    -> Auto-trade boundary
```

## 8. Luồng MVP chuẩn

1. TradingView alert chạy `once per bar close` cho từng symbol/timeframe active.
2. TradingView gửi OHLCV bar qua webhook `POST /api/v1/webhooks/tradingview/bars/{webhookToken}`.
3. Webhook receiver verify path token + body secret, validate payload, normalize symbol/timeframe/timestamp UTC.
4. Candle được upsert vào `market_candles`.
5. Khi có nến đóng mới thuộc trigger timeframe của strategy active, enqueue job `run_strategy`.
6. Strategy engine load context `M15 + H1`, chạy `liquidity_sweep`.
7. Signal candidate đi qua risk manager.
8. Duplicate guard kiểm tra signal trùng; cooldown được xử lý theo từng group ở router.
9. Signal hợp lệ lưu vào `signals`, route tới các group đủ điều kiện.
10. Telegram outbox tạo delivery idempotent.
11. Telegram worker gửi tin nhắn, update `telegram_outbox` current state và append `signal_deliveries` attempt log.

## 9. Phase triển khai

### Phase 1 - Core MVP

- Scaffold FastAPI, settings, logging, database, migrations.
- TradingView bar webhook + fake webhook data cho test.
- Candle model và webhook-triggered strategy enqueue.
- Liquidity Sweep v1.
- Risk manager, duplicate guard.
- Telegram sender + formatter.
- Admin Console v1 overview, groups, feeds, signals, deliveries, settings.
- Seed 3 nhóm demo.
- Health check và integration test.

### Phase 2 - Multi-group Config

- Admin API CRUD groups, strategies, group settings.
- Route theo symbol, timeframe, strategy, confidence, cooldown.
- Message format free/vip/smc.

### Phase 3 - TradingView Webhook

- Mở rộng từ bar webhook sang confirmation hoặc external signal source theo config.
- Payload signal validation.
- Không để Pine Script thay thế backend strategy nếu mode là backend-analysis.

### Phase 4 - MT5 Connector

- Thuê/chạy Windows VPS có MT5 terminal.
- MT5 Python connector lấy candles/ticks.
- Mapping broker/account/symbol.
- So sánh data feed TradingView vs MT5 nếu cần.

### Phase 5 - MT4 Bridge

- EA MQL4 gửi candle/tick về API.
- Secret riêng theo terminal/account.
- Mapping broker/account/symbol.

### Phase 6 - AI Filter

- Rule engine vẫn quyết định setup.
- AI chỉ trả valid/invalid, confidence adjustment, risk note.
- Structured JSON output, reject khi data thiếu.

### Phase 7 - Backtest/Report

- Lưu kết quả signal.
- Manual outcome trước, auto TP/SL tracking sau.
- Report winrate theo group/strategy/symbol/timeframe.

## 10. MVP acceptance

MVP đạt khi chứng minh được:

- Nhận được TradingView bar webhook cho 3 symbols và 2 timeframes.
- Strategy chỉ chạy trên nến đã đóng.
- Phát hiện được ít nhất một Liquidity Sweep từ fake data test.
- Reject signal thiếu SL/TP, RR thấp, spread cao hoặc duplicate.
- Route signal đúng group theo config.
- Gửi Telegram thành công bằng bot token thật ở smoke test.
- Log được signal, routing decision, Telegram delivery result.
- `/api/v1/health` trả trạng thái DB, Redis, data feed và Telegram.
- Delivery latency từ lúc nhận bar close webhook đến lúc enqueue Telegram dưới 30 giây trong điều kiện bình thường.
- Không gửi duplicate trong cooldown window.
- Operator mới nhìn Admin Console trong 5 phút trả lời được: bot đang chạy không, data feed nào stale, nhóm nào lỗi delivery, cần làm gì tiếp theo.
