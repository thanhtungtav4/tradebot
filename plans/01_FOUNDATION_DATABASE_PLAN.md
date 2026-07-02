# 01_FOUNDATION_DATABASE_PLAN - Foundation and Database

## 1. Mục tiêu

Tạo nền project và database trước mọi phần khác. Sau plan này, repo có thể chạy app skeleton, migrate DB từ zero, seed MVP data và cung cấp repository/service layer cơ bản.

## 2. Spec nguồn

- `specs/00_MASTER_SPEC.md`
- `specs/01_RUNTIME_DEPLOY_SPEC.md`
- `specs/06_DATABASE_SPEC.md`
- `specs/09_MONITORING_TEST_SPEC.md`

## 3. Artifacts cần tạo khi implement

- Project files: `pyproject.toml`, `.env.example`, `README.md`.
- Local dev files: `docker-compose.yml`, `Makefile` or documented equivalent command runner.
- App packages: `app/config`, `app/db`, `app/models`, `app/repositories`, `app/services`, `app/api`.
- Alembic: `alembic.ini`, `migrations/env.py`, initial migration.
- Seed: idempotent seed command/script.
- Tests: migration smoke, seed repeat-safe, DB constraints.

## 4. Work breakdown

### 4.1 Project scaffold

- Create FastAPI application factory.
- Add settings loader with env validation.
- Add structured logging.
- Add request/correlation id middleware.
- Add standard API error response helper.
- Add DB session dependency.
- Add command entrypoints for migrate, seed, test, run API, run workers.

### 4.2 Database models and migration

Implement schema from `06_DATABASE_SPEC.md`:

- `data_sources`
- `symbol_settings`
- `broker_symbol_mappings`
- `data_source_feeds`
- `telegram_groups`
- `strategies`
- `group_strategy_settings`
- `group_strategy_symbols`
- `group_strategy_timeframes`
- `market_candles`
- `signals`
- `signal_events`
- `telegram_outbox`
- `signal_deliveries`
- `component_health`
- `admin_activity_logs`

Migration must include:

- CHECK constraints for enum-like values.
- Unique constraints for idempotency.
- Indexes required by Admin Console and worker queries.
- FK indexes for normalized routing tables and worker hot paths.
- `TIMESTAMPTZ` for all timestamps.
- `BIGINT GENERATED ALWAYS AS IDENTITY` for primary IDs.
- `TEXT + CHECK` for evolving enum-like values.

### 4.3 Seed data

Seed must be repeat-safe and create:

- One data source: `tradingview_bars`.
- Three symbols: `XAUUSD`, `EURUSD`, `GBPUSD`.
- Broker mappings for TradingView symbols.
- Six feeds: 3 symbols x 2 timeframes.
- Strategy: `liquidity_sweep`.
- Three demo groups inactive: free, VIP, SMC.
- One group strategy setting per demo group.
- Child symbol/timeframe rows for each group strategy setting.
- Component health rows for `api`, `db`, `redis`, `data_feed`, `market_worker`, `signal_worker`, `telegram_worker`, `scheduler`, `telegram_api`.

### 4.4 Repository/service boundary

Create repositories for:

- Data sources and feeds.
- Candles.
- Signals and events.
- Telegram groups/settings.
- Outbox/deliveries.
- Component health.
- Admin activity logs.

Rules:

- Route handlers do not contain DB business logic.
- Services compose repositories.
- Repositories return typed domain objects or ORM models consistently.

## 5. Acceptance criteria

- Fresh DB migrates from zero.
- Seed can run twice without duplicate rows.
- Candle unique key prevents duplicate candle.
- Signal unique key prevents duplicate signal.
- Outbox delivery UID prevents duplicate outbox.
- Feed matrix can query all active feeds without scanning candle history.
- M15/H1 stale thresholds seed as 35/80 minutes when `STALE_GRACE_MINUTES=20`.
- Group routing can query symbols/timeframes through normalized child tables.
- No table stores Telegram bot token, admin password, raw TradingView token/body secret, raw HMAC secret or Authorization header.
- Local PostgreSQL integration test path is documented and runnable.

## 6. Risks and notes

- PostgreSQL is target DB and required for migration/integration tests.
- Unit tests may mock repositories; do not rely on SQLite for schema correctness because JSONB, partial indexes and Postgres constraints are part of the contract.
- Avoid PostgreSQL native enum for MVP to keep future migrations easier.
