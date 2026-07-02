# 06_DATABASE_SPEC - PostgreSQL Schema Final

## 1. Mục tiêu

Database là contract lõi của hệ thống. Schema phải đủ rõ để viết Alembic migration, seed data, Admin Console query và worker logic mà không phải đoán.

Schema MVP phải hỗ trợ:

- TradingView bar webhook làm data feed chính.
- Lưu candle đã đóng cho `XAUUSD`, `EURUSD`, `GBPUSD` trên `M15`, `H1`.
- Strategy engine tạo signal có audit trail.
- Router tạo Telegram outbox idempotent.
- Telegram worker retry an toàn, không tạo duplicate row.
- Admin Console thấy feed freshness, health, latest signals, failed deliveries.
- Admin action được audit bằng before/after.
- Mở rộng future cho MT5, MT4, AI filter, backtest, auto-trade mà không phá bảng MVP.

## 2. Naming and Storage Rules

- Table/column dùng `snake_case`.
- API/Admin Console response map sang `camelCase` ở service layer, không đổi DB naming.
- Mọi timestamp dùng `TIMESTAMPTZ` và lưu UTC.
- Decimal price dùng `NUMERIC`, không dùng float.
- Boolean column dùng prefix `is_`, `has_`, `can_`.
- Enum values dùng `UPPER_SNAKE_CASE`.
- ID chính dùng `BIGINT GENERATED ALWAYS AS IDENTITY`.
- Text column dùng `TEXT` + `CHECK` khi cần giới hạn, không dùng `VARCHAR(n)` trong migration đầu.
- Không lưu raw secret/token trong DB. TradingView token/body secret lưu dạng hash hoặc `secret_ref` trỏ tới env/secret manager.
- `raw_payload` chỉ chứa payload đã sanitize; không lưu HMAC signature, token, Authorization header.

## 3. Enum Contracts

MVP dùng `TEXT + CHECK` thay vì PostgreSQL enum để migration future dễ hơn. App code vẫn expose enum constants rõ ràng.

### Core values

```text
data_source_type:
  TRADINGVIEW_BAR_WEBHOOK
  TRADINGVIEW_SIGNAL_WEBHOOK
  MT5_CONNECTOR
  MT4_BRIDGE
  OANDA

component_status:
  UNKNOWN
  OK
  DEGRADED
  DOWN
  PAUSED

feed_status:
  UNKNOWN
  WARMUP
  OK
  STALE
  ERROR
  PAUSED

timeframe:
  M5
  M15
  H1
  H4

group_type:
  FREE
  VIP
  SMC
  INTERNAL

group_mode:
  DEMO
  INTERNAL
  LIVE

send_mode:
  BASIC
  FULL
  SUMMARY

risk_level:
  LOW
  MEDIUM
  HIGH

signal_action:
  BUY
  SELL

signal_status:
  CREATED
  REJECTED
  APPROVED
  ROUTED
  QUEUED
  SENT
  PARTIAL_SENT
  PARTIAL_FAILED
  FAILED
  SKIPPED_DUPLICATE

outbox_status:
  PENDING
  SENDING
  SENT
  FAILED_RETRYABLE
  FAILED_PERMANENT
  SKIPPED

delivery_attempt_status:
  SENDING
  SENT
  FAILED_RETRYABLE
  FAILED_PERMANENT
```

## 4. Migration Order

Create tables in this order:

1. `data_sources`
2. `symbol_settings`
3. `broker_symbol_mappings`
4. `data_source_feeds`
5. `telegram_groups`
6. `strategies`
7. `group_strategy_settings`
8. `group_strategy_symbols`
9. `group_strategy_timeframes`
10. `market_candles`
11. `signals`
12. `signal_events`
13. `telegram_outbox`
14. `signal_deliveries`
15. `component_health`
16. `admin_activity_logs`

Indexes are created after all tables exist.

## 5. Tables

### 5.1 data_sources

Represents one logical data source or connector. MVP has one source: `tradingview_bars`.

```sql
CREATE TABLE data_sources (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    type TEXT NOT NULL,
    display_name TEXT NOT NULL,
    broker TEXT NOT NULL DEFAULT 'TRADINGVIEW',
    account_id TEXT,
    secret_ref TEXT,
    webhook_token_hash TEXT UNIQUE,
    body_secret_hash TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    status TEXT NOT NULL DEFAULT 'UNKNOWN',
    stale_grace_minutes INT NOT NULL DEFAULT 20,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_ok_at TIMESTAMPTZ,
    last_payload_received_at TIMESTAMPTZ,
    last_error_code TEXT,
    last_error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (type IN (
        'TRADINGVIEW_BAR_WEBHOOK',
        'TRADINGVIEW_SIGNAL_WEBHOOK',
        'MT5_CONNECTOR',
        'MT4_BRIDGE',
        'OANDA'
    )),
    CHECK (status IN ('UNKNOWN', 'OK', 'DEGRADED', 'DOWN', 'PAUSED')),
    CHECK (stale_grace_minutes > 0)
);
```

Notes:

- `secret_ref` stores an env/secret-manager key name, not the secret value.
- `webhook_token_hash` and `body_secret_hash` store one-way hashes, not raw TradingView secrets.
- `stale_grace_minutes` is added to timeframe length to compute feed-level `stale_after_minutes`.
- `status` is cached health for Admin Console; live health can still be computed at request time.

### 5.2 symbol_settings

Canonical symbol settings used by strategy, risk manager and display formatting.

```sql
CREATE TABLE symbol_settings (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    price_digits INT NOT NULL DEFAULT 2,
    point_size NUMERIC NOT NULL,
    pip_size NUMERIC,
    sl_buffer_points NUMERIC NOT NULL DEFAULT 0,
    entry_zone_points NUMERIC NOT NULL DEFAULT 0,
    max_spread NUMERIC,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (price_digits BETWEEN 0 AND 8),
    CHECK (point_size > 0),
    CHECK (pip_size IS NULL OR pip_size > 0),
    CHECK (sl_buffer_points >= 0),
    CHECK (entry_zone_points >= 0),
    CHECK (max_spread IS NULL OR max_spread >= 0)
);
```

TradingView bar webhook usually does not provide spread. For MVP, `max_spread` may be null or skipped per `04_SIGNAL_RISK_SPEC.md`.

### 5.3 broker_symbol_mappings

Maps source/broker symbols to canonical symbols.

```sql
CREATE TABLE broker_symbol_mappings (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id BIGINT NOT NULL REFERENCES data_sources(id),
    broker TEXT NOT NULL DEFAULT 'TRADINGVIEW',
    canonical_symbol TEXT NOT NULL REFERENCES symbol_settings(symbol),
    broker_symbol TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_id, canonical_symbol),
    UNIQUE (source_id, broker_symbol)
);
```

MVP examples:

```text
TRADINGVIEW / XAUUSD -> OANDA:XAUUSD
TRADINGVIEW / EURUSD -> OANDA:EURUSD
TRADINGVIEW / GBPUSD -> OANDA:GBPUSD
```

### 5.4 data_source_feeds

One row per active source + symbol + timeframe. This powers Admin Console feed matrix.

```sql
CREATE TABLE data_source_feeds (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id BIGINT NOT NULL REFERENCES data_sources(id),
    canonical_symbol TEXT NOT NULL REFERENCES symbol_settings(symbol),
    source_symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    status TEXT NOT NULL DEFAULT 'UNKNOWN',
    stale_after_minutes INT NOT NULL,
    last_candle_time TIMESTAMPTZ,
    last_payload_received_at TIMESTAMPTZ,
    last_error_code TEXT,
    last_error_message TEXT,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_id, canonical_symbol, timeframe),
    CHECK (timeframe IN ('M5', 'M15', 'H1', 'H4')),
    CHECK (status IN ('UNKNOWN', 'WARMUP', 'OK', 'STALE', 'ERROR', 'PAUSED')),
    CHECK (stale_after_minutes > 0)
);
```

Feed status rules:

- `UNKNOWN`: seed/new feed before first payload.
- `WARMUP`: fresh candles are arriving but strategy lookback is not complete yet.
- `OK`: latest closed candle is within stale threshold and minimum lookback is available.
- `STALE`: no candle newer than threshold.
- `ERROR`: last ingest attempt failed validation or storage.
- `PAUSED`: feed is intentionally disabled or paused.

### 5.5 telegram_groups

Telegram destination groups.

```sql
CREATE TABLE telegram_groups (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    telegram_chat_id TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'FREE',
    mode TEXT NOT NULL DEFAULT 'DEMO',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_paused BOOLEAN NOT NULL DEFAULT FALSE,
    last_test_message_at TIMESTAMPTZ,
    last_sent_at TIMESTAMPTZ,
    last_delivery_status TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (telegram_chat_id),
    CHECK (type IN ('FREE', 'VIP', 'SMC', 'INTERNAL')),
    CHECK (mode IN ('DEMO', 'INTERNAL', 'LIVE')),
    CHECK (last_delivery_status IS NULL OR last_delivery_status IN (
        'PENDING',
        'SENDING',
        'SENT',
        'FAILED_RETRYABLE',
        'FAILED_PERMANENT',
        'SKIPPED'
    ))
);
```

Operational rules:

- `is_active=false`: group is not considered by router.
- `is_paused=true`: group remains configured but router skips delivery and Admin Console shows `PAUSED`.
- `mode=LIVE` requires explicit confirmation in Admin Console.

### 5.6 strategies

Registered strategy plugins.

```sql
CREATE TABLE strategies (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT 'v1',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    default_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

`default_config` controls global detection defaults. Group-specific config must not change detection logic unless explicitly documented in strategy spec.

### 5.7 group_strategy_settings

Per-group routing and eligibility settings.

```sql
CREATE TABLE group_strategy_settings (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    setting_code TEXT NOT NULL,
    display_name TEXT NOT NULL,
    group_id BIGINT NOT NULL REFERENCES telegram_groups(id),
    strategy_id BIGINT NOT NULL REFERENCES strategies(id),
    min_confidence INT NOT NULL DEFAULT 70,
    risk_level TEXT NOT NULL DEFAULT 'MEDIUM',
    send_mode TEXT NOT NULL DEFAULT 'FULL',
    cooldown_minutes INT NOT NULL DEFAULT 30,
    duplicate_window_minutes INT NOT NULL DEFAULT 30,
    entry_tolerance_points NUMERIC NOT NULL DEFAULT 20,
    min_rr NUMERIC NOT NULL DEFAULT 1.5,
    max_spread NUMERIC,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (group_id, setting_code),
    CHECK (min_confidence BETWEEN 0 AND 100),
    CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH')),
    CHECK (send_mode IN ('BASIC', 'FULL', 'SUMMARY')),
    CHECK (cooldown_minutes >= 0),
    CHECK (duplicate_window_minutes >= 0),
    CHECK (entry_tolerance_points >= 0),
    CHECK (min_rr > 0),
    CHECK (max_spread IS NULL OR max_spread >= 0)
);
```

Important:

- Do not use `UNIQUE (group_id, strategy_id)`. A group may run the same strategy with separate settings for different symbol bundles.
- Symbols and timeframes live in child tables so router queries can use indexed joins instead of JSON scans.
- App-level validation must reject overlapping active settings that would route the same signal twice to the same group.

### 5.7a group_strategy_symbols

Symbols enabled for one group strategy setting.

```sql
CREATE TABLE group_strategy_symbols (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    setting_id BIGINT NOT NULL REFERENCES group_strategy_settings(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL REFERENCES symbol_settings(symbol),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (setting_id, symbol)
);
```

### 5.7b group_strategy_timeframes

Timeframes enabled for one group strategy setting.

```sql
CREATE TABLE group_strategy_timeframes (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    setting_id BIGINT NOT NULL REFERENCES group_strategy_settings(id) ON DELETE CASCADE,
    timeframe TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (setting_id, timeframe),
    CHECK (timeframe IN ('M5', 'M15', 'H1', 'H4'))
);
```

Admin/API request can still accept arrays. Service layer expands `symbols[]` and `timeframes[]` into these child tables in one transaction.

### 5.8 market_candles

Canonical closed candles.

```sql
CREATE TABLE market_candles (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id BIGINT NOT NULL REFERENCES data_sources(id),
    source_code TEXT NOT NULL,
    broker TEXT NOT NULL DEFAULT 'TRADINGVIEW',
    account_id TEXT,
    symbol TEXT NOT NULL REFERENCES symbol_settings(symbol),
    source_symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    candle_time TIMESTAMPTZ NOT NULL,
    open NUMERIC NOT NULL,
    high NUMERIC NOT NULL,
    low NUMERIC NOT NULL,
    close NUMERIC NOT NULL,
    volume NUMERIC,
    spread NUMERIC,
    is_closed BOOLEAN NOT NULL DEFAULT TRUE,
    payload_hash TEXT,
    raw_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_id, symbol, timeframe, candle_time),
    CHECK (timeframe IN ('M5', 'M15', 'H1', 'H4')),
    CHECK (high >= low),
    CHECK (high >= open),
    CHECK (high >= close),
    CHECK (low <= open),
    CHECK (low <= close),
    CHECK (volume IS NULL OR volume >= 0),
    CHECK (spread IS NULL OR spread >= 0)
);
```

Notes:

- MVP stores only closed candles.
- `payload_hash` is optional but useful for ingest debug.
- `raw_payload` must be sanitized.

### 5.9 signals

Strategy output and aggregate signal lifecycle.

```sql
CREATE TABLE signals (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    signal_uid TEXT UNIQUE NOT NULL,
    source_id BIGINT REFERENCES data_sources(id),
    source TEXT NOT NULL,
    strategy_code TEXT NOT NULL REFERENCES strategies(code),
    symbol TEXT NOT NULL REFERENCES symbol_settings(symbol),
    timeframe TEXT NOT NULL,
    action TEXT NOT NULL,
    entry NUMERIC,
    entry_zone_low NUMERIC,
    entry_zone_high NUMERIC,
    sl NUMERIC,
    tp JSONB,
    risk_reward NUMERIC,
    confidence INT,
    reason JSONB,
    invalid_if TEXT,
    source_candle_time TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'CREATED',
    reject_code TEXT,
    reject_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (timeframe IN ('M5', 'M15', 'H1', 'H4')),
    CHECK (action IN ('BUY', 'SELL')),
    CHECK (status IN (
        'CREATED',
        'REJECTED',
        'APPROVED',
        'ROUTED',
        'QUEUED',
        'SENT',
        'PARTIAL_SENT',
        'PARTIAL_FAILED',
        'FAILED',
        'SKIPPED_DUPLICATE'
    )),
    CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 100),
    CHECK (risk_reward IS NULL OR risk_reward > 0),
    CHECK (tp IS NULL OR jsonb_typeof(tp) = 'array'),
    CHECK (reason IS NULL OR jsonb_typeof(reason) = 'array'),
    CHECK (
        status NOT IN ('APPROVED', 'ROUTED', 'QUEUED', 'SENT', 'PARTIAL_SENT', 'PARTIAL_FAILED', 'FAILED')
        OR (
            entry IS NOT NULL
            AND sl IS NOT NULL
            AND tp IS NOT NULL
            AND risk_reward IS NOT NULL
            AND confidence IS NOT NULL
            AND invalid_if IS NOT NULL
        )
    )
);
```

Signal status is aggregate:

- Per-group delivery state lives in `telegram_outbox`.
- Per-attempt history lives in `signal_deliveries`.
- `SENT` means all routed deliveries succeeded.
- `PARTIAL_SENT` means at least one delivery succeeded and at least one delivery is still pending/retryable.
- `PARTIAL_FAILED` means at least one delivery succeeded and at least one delivery failed permanently.
- `FAILED` means all routed deliveries failed permanently.

### 5.10 signal_events

Append-only timeline for a signal.

```sql
CREATE TABLE signal_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    signal_id BIGINT NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    message TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Required event types:

```text
SIGNAL_CREATED
SIGNAL_REJECTED
SIGNAL_APPROVED
DUPLICATE_SKIPPED
WARMUP_SKIPPED
ROUTER_MATCHED_GROUP
ROUTER_SKIPPED_GROUP
OUTBOX_CREATED
DELIVERY_SENT
DELIVERY_FAILED
SIGNAL_STATUS_UPDATED
```

### 5.11 telegram_outbox

Current state for one signal delivery to one group. This is the source of truth for retry.

```sql
CREATE TABLE telegram_outbox (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    delivery_uid TEXT UNIQUE NOT NULL,
    signal_id BIGINT NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
    group_id BIGINT NOT NULL REFERENCES telegram_groups(id),
    group_strategy_setting_id BIGINT REFERENCES group_strategy_settings(id),
    status TEXT NOT NULL DEFAULT 'PENDING',
    send_mode TEXT NOT NULL DEFAULT 'FULL',
    message_text TEXT NOT NULL,
    parse_mode TEXT,
    attempt_count INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 3,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_attempt_at TIMESTAMPTZ,
    last_error_code TEXT,
    last_error_message TEXT,
    telegram_message_id TEXT,
    locked_by TEXT,
    lock_token TEXT,
    locked_until TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (status IN (
        'PENDING',
        'SENDING',
        'SENT',
        'FAILED_RETRYABLE',
        'FAILED_PERMANENT',
        'SKIPPED'
    )),
    CHECK (send_mode IN ('BASIC', 'FULL', 'SUMMARY')),
    CHECK (attempt_count >= 0),
    CHECK (max_attempts > 0),
    CHECK (attempt_count <= max_attempts)
);
```

Operational rules:

- Router creates one row per `signal_uid + group_id`.
- Worker updates this row on each attempt.
- `SENT` rows must never be retried.
- `FAILED_RETRYABLE` rows are scanned by scheduler when `next_attempt_at <= NOW()`.
- Lock uses `locked_until` and `lock_token`; stale locks can be reclaimed after `OUTBOX_LOCK_TIMEOUT_SECONDS`.

### 5.12 signal_deliveries

Immutable attempt log. Every Telegram send attempt creates one row.

```sql
CREATE TABLE signal_deliveries (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    outbox_id BIGINT NOT NULL REFERENCES telegram_outbox(id) ON DELETE CASCADE,
    delivery_uid TEXT NOT NULL,
    signal_id BIGINT NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
    group_id BIGINT NOT NULL REFERENCES telegram_groups(id),
    attempt_no INT NOT NULL,
    status TEXT NOT NULL,
    http_status_code INT,
    telegram_message_id TEXT,
    error_code TEXT,
    error_message TEXT,
    response_payload JSONB,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (outbox_id, attempt_no),
    CHECK (attempt_no > 0),
    CHECK (status IN (
        'SENDING',
        'SENT',
        'FAILED_RETRYABLE',
        'FAILED_PERMANENT'
    )),
    CHECK (http_status_code IS NULL OR http_status_code BETWEEN 100 AND 599)
);
```

Important:

- `telegram_outbox` is current state.
- `signal_deliveries` is append-only attempt history.
- Do not update old `signal_deliveries` rows except to set `finished_at` and result of the same attempt.

### 5.13 component_health

Cached component health for Admin Console and `/health`.

```sql
CREATE TABLE component_health (
    component_code TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'UNKNOWN',
    summary TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_ok_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (status IN ('UNKNOWN', 'OK', 'DEGRADED', 'DOWN', 'PAUSED'))
);
```

Required component codes:

```text
api
db
redis
data_feed
market_worker
signal_worker
telegram_worker
scheduler
telegram_api
```

### 5.14 admin_activity_logs

Audit log for admin actions that affect runtime behavior.

```sql
CREATE TABLE admin_activity_logs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_type TEXT NOT NULL DEFAULT 'ADMIN',
    actor_id TEXT,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    before_state JSONB,
    after_state JSONB,
    ip_address TEXT,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Must log:

- Create/update/disable/enable Telegram group.
- Create/update/disable group strategy setting.
- Send test Telegram message.
- Retry delivery.
- Mark delivery skipped.
- Pause/resume source, feed, group, strategy, symbol/timeframe.
- Rotate TradingView token/body secret or future HMAC secret.
- Change stale threshold.

## 6. Required Indexes

```sql
CREATE INDEX idx_data_source_feeds_status
ON data_source_feeds (status, is_active, updated_at DESC);

CREATE INDEX idx_data_source_feeds_matrix
ON data_source_feeds (canonical_symbol, timeframe, source_id);

CREATE INDEX idx_broker_symbol_mappings_source_symbol
ON broker_symbol_mappings (source_id, broker_symbol);

CREATE INDEX idx_group_strategy_settings_group_active
ON group_strategy_settings (group_id, is_active);

CREATE INDEX idx_group_strategy_settings_strategy_active
ON group_strategy_settings (strategy_id, is_active);

CREATE INDEX idx_group_strategy_symbols_symbol
ON group_strategy_symbols (symbol, setting_id);

CREATE INDEX idx_group_strategy_symbols_setting
ON group_strategy_symbols (setting_id);

CREATE INDEX idx_group_strategy_timeframes_timeframe
ON group_strategy_timeframes (timeframe, setting_id);

CREATE INDEX idx_group_strategy_timeframes_setting
ON group_strategy_timeframes (setting_id);

CREATE INDEX idx_market_candles_lookup
ON market_candles (symbol, timeframe, candle_time DESC);

CREATE INDEX idx_market_candles_source_lookup
ON market_candles (source_id, symbol, timeframe, candle_time DESC);

CREATE INDEX idx_signals_lookup
ON signals (symbol, timeframe, strategy_code, action, created_at DESC);

CREATE INDEX idx_signals_status_created
ON signals (status, created_at DESC);

CREATE INDEX idx_signal_events_signal
ON signal_events (signal_id, created_at);

CREATE INDEX idx_telegram_outbox_pending
ON telegram_outbox (status, next_attempt_at)
WHERE status IN ('PENDING', 'FAILED_RETRYABLE');

CREATE INDEX idx_telegram_outbox_stale_lock
ON telegram_outbox (locked_until)
WHERE status = 'SENDING';

CREATE INDEX idx_telegram_outbox_signal
ON telegram_outbox (signal_id);

CREATE INDEX idx_telegram_outbox_group_status
ON telegram_outbox (group_id, status, created_at DESC);

CREATE INDEX idx_signal_deliveries_outbox
ON signal_deliveries (outbox_id, attempt_no);

CREATE INDEX idx_signal_deliveries_status
ON signal_deliveries (status, created_at DESC);

CREATE INDEX idx_admin_activity_logs_lookup
ON admin_activity_logs (resource_type, resource_id, created_at DESC);

CREATE INDEX idx_admin_activity_logs_created
ON admin_activity_logs (created_at DESC);
```

## 7. Seed Data

MVP seed must be deterministic and safe to run repeatedly.

### data_sources

```text
code: tradingview_bars
type: TRADINGVIEW_BAR_WEBHOOK
display_name: TradingView Bar Webhook
broker: TRADINGVIEW
secret_ref: env
config:
  webhookTokenRef: TRADINGVIEW_WEBHOOK_TOKEN
  bodySecretRef: TRADINGVIEW_BODY_SECRET
webhook_token_hash: sha256(env TRADINGVIEW_WEBHOOK_TOKEN)
body_secret_hash: sha256(env TRADINGVIEW_BODY_SECRET)
stale_grace_minutes: 20
status: UNKNOWN
```

### symbol_settings

```text
XAUUSD:
  display_name: Gold / XAUUSD
  price_digits: 2
  point_size: 0.01
  pip_size: 0.1
  sl_buffer_points: 20
  entry_zone_points: 20
  max_spread: null

EURUSD:
  display_name: EUR/USD
  price_digits: 5
  point_size: 0.00001
  pip_size: 0.0001
  sl_buffer_points: 20
  entry_zone_points: 10
  max_spread: null

GBPUSD:
  display_name: GBP/USD
  price_digits: 5
  point_size: 0.00001
  pip_size: 0.0001
  sl_buffer_points: 20
  entry_zone_points: 10
  max_spread: null
```

### broker_symbol_mappings

```text
tradingview_bars / XAUUSD -> OANDA:XAUUSD
tradingview_bars / EURUSD -> OANDA:EURUSD
tradingview_bars / GBPUSD -> OANDA:GBPUSD
```

### data_source_feeds

Create 6 rows:

```text
XAUUSD M15
XAUUSD H1
EURUSD M15
EURUSD H1
GBPUSD M15
GBPUSD H1
```

All use source `tradingview_bars`, status `UNKNOWN` before the first payload.

Feed `stale_after_minutes` is materialized from timeframe length + `STALE_GRACE_MINUTES`:

```text
M15 feeds: 35 minutes
H1 feeds: 80 minutes
```

When candles start arriving but lookback is still insufficient, scheduler/context builder may set status `WARMUP`. Do not use one global stale threshold for all timeframes.

### strategies

```text
code: liquidity_sweep
name: Liquidity Sweep
version: v1
default_config:
  triggerTimeframe: M15
  triggerTimeframes: ["M15"]
  contextTimeframe: H1
  swingLookback: 20
  confirmationCandles: 1
  minRiskReward: 1.5
  tp1R: 1.0
  tp2R: 2.0
```

### telegram_groups

Create 3 demo groups with placeholder chat IDs:

```text
free_demo:
  type: FREE
  mode: DEMO
  is_active: false

vip_demo:
  type: VIP
  mode: DEMO
  is_active: false

smc_demo:
  type: SMC
  mode: DEMO
  is_active: false
```

Placeholders must be replaced before sending real test messages.

### group_strategy_settings

Create one setting per demo group:

```text
setting_code: liquidity_sweep_default
strategy: liquidity_sweep
min_confidence:
  free_demo: 75
  vip_demo: 70
  smc_demo: 80
send_mode:
  free_demo: BASIC
  vip_demo: FULL
  smc_demo: FULL
cooldown_minutes: 30
duplicate_window_minutes: 30
min_rr: 1.5
max_spread: null
```

For each seeded setting:

```text
group_strategy_symbols: XAUUSD, EURUSD, GBPUSD
group_strategy_timeframes: M15
```

### component_health

Create rows:

```text
api
db
redis
data_feed
market_worker
signal_worker
telegram_worker
scheduler
telegram_api
```

## 8. Idempotency Rules

### Candle ingest

Unique key:

```text
source_id + symbol + timeframe + candle_time
```

Upsert behavior:

- If same candle arrives again with identical values, update `updated_at` and ignore.
- If same unique key arrives with different OHLC values, update row and log event `candle_payload_changed` with old/new summary. This can happen if source revises a just-closed bar.

### Signal creation

Unique key:

```text
signal_uid
```

`signal_uid` format:

```text
{strategyCode}:{symbol}:{timeframe}:{action}:{sourceCandleTime}:{entryBucket}
```

Duplicate insert conflict must not create outbox.

### Telegram delivery

Unique key:

```text
delivery_uid = {signal_uid}:{group_id}
```

Router inserts one `telegram_outbox` row per delivery UID. Retry updates that outbox row and appends `signal_deliveries` attempt rows.

## 9. Admin Console Query Contracts

### Overview status tiles

Read:

- `component_health`
- `data_source_feeds`
- `telegram_outbox`
- latest `signals`

Expected query patterns:

```sql
SELECT * FROM component_health;

SELECT canonical_symbol, timeframe, status, last_candle_time, last_payload_received_at, last_error_message
FROM data_source_feeds
WHERE is_active = TRUE
ORDER BY canonical_symbol, timeframe;

SELECT status, COUNT(*)
FROM telegram_outbox
GROUP BY status;

SELECT *
FROM signals
ORDER BY created_at DESC
LIMIT 10;
```

### Feed matrix

Source of truth is `data_source_feeds`, not raw candle scanning. Workers update feed rows after ingest/stale checks.

Status display must support `UNKNOWN`, `WARMUP`, `OK`, `STALE`, `ERROR`, and `PAUSED`.

### Signal detail

Read:

- `signals`
- `signal_events`
- `telegram_outbox`
- `signal_deliveries`

### Delivery detail

Read:

- `telegram_outbox` current status.
- `signal_deliveries` attempt history.
- linked `signals` and `telegram_groups`.

## 10. Retention Policy

Defaults:

| Data | Retention |
| --- | --- |
| `market_candles` | 365 days |
| `signals` | 730 days |
| `signal_events` | 730 days |
| `telegram_outbox` | 730 days |
| `signal_deliveries` | 730 days |
| `admin_activity_logs` | 365 days |
| `raw_payload` heavy fields | May be pruned after 30 days if storage grows |

Retention jobs must never delete rows needed by pending/retryable outbox.

## 11. Migration Principles

- Use Alembic.
- One migration creates base schema.
- One seed script inserts deterministic MVP config.
- Never edit an applied production migration.
- Add new columns nullable first, backfill, then enforce NOT NULL if needed.
- Prefer additive changes to preserve Admin Console/API compatibility.
- Indexes needed by Admin Console must ship with the migration that introduces the screen.

## 12. Acceptance Criteria

- Fresh DB migrates from zero.
- Seed creates runnable MVP config with one TradingView source, 6 feeds, 3 symbols, 3 groups and one strategy.
- Seed stores TradingView webhook token/body secret as hashes or refs, never raw secret values.
- M15 feed thresholds are 35 minutes and H1 feed thresholds are 80 minutes when `STALE_GRACE_MINUTES=20`.
- Duplicate candle upsert does not create duplicate rows.
- Duplicate signal insert does not create outbox.
- Duplicate delivery UID is blocked by `telegram_outbox.delivery_uid`.
- Retry creates new `signal_deliveries` attempt rows but does not create a second outbox row.
- Group routing uses normalized `group_strategy_symbols` and `group_strategy_timeframes` rows, not JSON scans.
- Admin Console feed matrix can query all active feeds from `data_source_feeds`.
- Admin Console overview can query component health, pending outbox and latest signals without scanning all candle history.
- Admin runtime actions are written to `admin_activity_logs`.
- No table stores Telegram bot token, admin password, HMAC secret or Authorization header.
