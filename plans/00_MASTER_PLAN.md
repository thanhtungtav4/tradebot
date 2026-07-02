# 00_MASTER_PLAN - Forex Signal Bot MVP

## 1. Mục tiêu

Biến spec pack trong `specs/` thành lộ trình triển khai có thứ tự, có dependency rõ, chưa viết code. Plan này là bản đồ tổng; các plan con trong thư mục `plans/` mô tả từng phần đủ chi tiết để implement sau.

MVP cần đạt:

- TradingView bar webhook gửi candle về backend.
- Backend lưu candle, tự phân tích bằng Python strategy.
- Signal đi qua risk, duplicate guard, router.
- Telegram gửi đúng nhóm free/VIP/SMC.
- Admin Console trực quan, operator mới nhìn 5 phút hiểu hệ thống đang OK hay lỗi ở đâu.
- DB/migration/seed đủ chắc để không phải sửa ngược nhiều.

## 2. Plan con

Đọc theo thứ tự:

1. `01_FOUNDATION_DATABASE_PLAN.md` - project skeleton, config, logging, DB schema, Alembic, seed.
2. `02_SECURITY_ADMIN_AUTH_PLAN.md` - admin session, API key, CSRF, webhook auth, secret redaction.
3. `03_TRADINGVIEW_INGESTION_PLAN.md` - TradingView bar webhook, candle normalize/upsert, feed freshness.
4. `04_STRATEGY_RISK_PLAN.md` - Liquidity Sweep, context loader, risk manager, duplicate guard.
5. `05_ROUTER_TELEGRAM_PLAN.md` - group eligibility, outbox, formatter, Telegram worker, retry.
6. `06_ADMIN_CONSOLE_PLAN.md` - Overview, Feeds, Groups, Strategies, Signals, Deliveries, Settings.
7. `07_HEALTH_MONITORING_OPS_PLAN.md` - health endpoints, component health, stale feed checks, ops jobs.
8. `08_TEST_RELEASE_PLAN.md` - unit/integration/admin/smoke tests and release readiness.
9. `09_FUTURE_PHASES_PLAN.md` - MT5, MT4, AI filter, backtest, auto-trade boundaries.
10. `10_DEV_ENV_PLAN.md` - local dev environment, Docker Compose, commands, worker processes.
11. `11_AI_FILTER_PLAN.md` - Phase Future D khuyến nghị: AI filter, schema, latency, fail-safe, roll-out.

## 3. Implementation order

### Milestone A - Runnable foundation

Includes:

- Project skeleton.
- Settings validation.
- DB models and migrations.
- Seed data.
- Basic `/live` and DB ping health endpoint.
- Local dev commands and service bootstrap.

Depends on:

- `01_FOUNDATION_DATABASE_PLAN.md`
- `10_DEV_ENV_PLAN.md`
- relevant parts of `07_HEALTH_MONITORING_OPS_PLAN.md`

Exit criteria:

- Fresh DB migrates from zero.
- Seed creates TradingView source, 6 feeds, 3 symbols, 3 demo groups, Liquidity Sweep strategy.
- Seed creates normalized group strategy symbol/timeframe rows.
- Seed sets M15/H1 stale thresholds from timeframe length + grace minutes.
- App starts and health/live works.
- `docker compose up` or equivalent local service command starts PostgreSQL and Redis.

### Milestone B - Secure ingress and core pipeline

Includes:

- Admin/API auth.
- Admin Console skeleton: login, layout, protected Overview placeholder.
- TradingView bar webhook.
- Candle validation/upsert.
- Feed matrix data.
- Strategy job enqueue placeholder.

Depends on:

- `02_SECURITY_ADMIN_AUTH_PLAN.md`
- `03_TRADINGVIEW_INGESTION_PLAN.md`
- first slice of `06_ADMIN_CONSOLE_PLAN.md`

Exit criteria:

- Fake TradingView payload creates one candle.
- Duplicate candle does not duplicate row.
- Invalid secret/payload rejected.
- Feed freshness updates.
- Admin login works and Overview can show current feed matrix placeholder.

### Milestone C - Signal generation

Includes:

- Liquidity Sweep strategy.
- Context loader.
- Global risk manager.
- Duplicate guard.
- Signal and signal event persistence.

Depends on:

- `04_STRATEGY_RISK_PLAN.md`

Exit criteria:

- Fake candle set creates BUY/SELL signal in tests.
- Reject cases have reject code/event.
- Duplicate signal does not create outbox.

### Milestone D - Telegram delivery

Includes:

- Router/group eligibility.
- Telegram outbox.
- Message formatter.
- Telegram worker retry/attempt log.

Depends on:

- `05_ROUTER_TELEGRAM_PLAN.md`

Exit criteria:

- Signal routes only to eligible groups.
- Outbox unique by `signal_uid + group_id`.
- Retry appends `signal_deliveries` attempt rows.
- `SENT` never retries.

### Milestone E - Admin Console

Includes:

- Complete Overview cockpit.
- Feed matrix.
- Groups wizard.
- Signals timeline.
- Deliveries retry UI.
- Settings/runbook.

Depends on:

- `06_ADMIN_CONSOLE_PLAN.md`
- data from prior milestones.

Exit criteria:

- Operator can answer five-minute checklist.
- Admin can create demo group and send test message.
- Runtime-changing actions write audit logs.

### Milestone F - Monitoring, tests, release readiness

Includes:

- Component health jobs.
- Stale feed scheduler.
- Outbox retry scheduler.
- Worker job contracts fully wired.
- Full test suite.
- Smoke test script.

Depends on:

- `07_HEALTH_MONITORING_OPS_PLAN.md`
- `08_TEST_RELEASE_PLAN.md`

Exit criteria:

- Health degrades when data feed stale.
- Integration pipeline fake webhook -> signal -> outbox -> mocked Telegram passes.
- Admin Console status matches DB/Redis/data feed/Telegram fixtures.

## 4. MVP scope boundaries

In MVP:

- TradingView bar webhook is the only production data source.
- Backend strategy is the decision maker.
- Admin Console is part of MVP.
- PostgreSQL is production DB target.
- Redis/RQ handle async jobs.
- Local integration tests use PostgreSQL, not SQLite.

Out of MVP:

- MT5 connector.
- MT4 bridge.
- TradingView signal/confirmation mode.
- AI filter.
- News filter.
- Backtest/report production.
- Auto-trade.

## 5. Default implementation decisions

- Backend: Python + FastAPI.
- ORM/migrations: SQLAlchemy 2.x + Alembic.
- Queue: Redis + RQ.
- Admin Console: FastAPI server-rendered Jinja2 + HTMX.
- Password hash: Argon2 preferred, bcrypt acceptable.
- DB enum implementation: `TEXT + CHECK`.
- Primary IDs: `BIGINT GENERATED ALWAYS AS IDENTITY`.
- Current Telegram delivery state: `telegram_outbox`.
- Delivery attempt history: `signal_deliveries`.
- Admin feed matrix source of truth: `data_source_feeds`.

## 5a. Worker job contracts

All jobs include `correlation_id`, `created_at`, and minimal IDs instead of large ORM payloads.

```text
ingest_tradingview_bar
  queue: market
  payload: raw sanitized bar payload, source code

run_strategy
  queue: signal
  payload: symbol, timeframe, candle_time, source_id

route_signal
  queue: signal
  payload: signal_id

send_telegram
  queue: telegram
  payload: outbox_id

scan_stale_feeds
  queue: maintenance
  payload: none

scan_outbox_retry
  queue: maintenance
  payload: none
```

Webhook route may normalize/upsert synchronously for MVP, then enqueue `run_strategy`. If ingest is moved async later, it must keep the same payload contract.

## 6. Cross-cutting acceptance

Before calling MVP complete:

- No hardcoded secrets.
- No raw token/secret in logs.
- All timestamps are UTC `TIMESTAMPTZ`.
- All external inputs validated at boundary.
- Admin list endpoints are paginated.
- Every runtime-changing admin action writes `admin_activity_logs`.
- Operator five-minute checklist passes.
- Fake-data integration test passes without TradingView or Telegram live services.
- Production startup refuses default/placeholder secrets.
- Demo Telegram chat IDs cannot be enabled as `LIVE`.
