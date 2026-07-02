# 03_TRADINGVIEW_INGESTION_PLAN - TradingView Bar Ingestion

## 1. Mục tiêu

Nhận TradingView bar webhook, validate payload, normalize về canonical candle, upsert DB, cập nhật feed freshness và enqueue strategy job khi có candle đóng mới.

## 2. Spec nguồn

- `specs/02_DATA_SOURCE_SPEC.md`
- `specs/06_DATABASE_SPEC.md`
- `specs/07_API_ADMIN_SPEC.md`
- `specs/08_SECURITY_SPEC.md`

## 3. Artifacts cần tạo khi implement

- Endpoint `POST /api/v1/webhooks/tradingview/bars/{webhookToken}`.
- Local/staging admin import endpoint `POST /api/v1/admin/candles/import`.
- Pydantic schema for bar payload.
- Candle normalizer.
- Candle service/repository.
- Feed freshness update service.
- Queue enqueue adapter.
- Tests for payload validation and idempotent upsert.

## 4. Work breakdown

### 4.1 Payload contract

Accept fields:

- source.
- symbol/source symbol.
- timeframe.
- time/candle time.
- open, high, low, close.
- volume optional.
- isClosed.
- `webhookToken` in path plus `secret` in body for MVP auth.

Exact MVP JSON payload:

```json
{
  "secret": "{{tradingview_body_secret}}",
  "source": "TRADINGVIEW",
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

Accepted aliases:

- `symbol` may be TradingView ticker like `OANDA:XAUUSD`; normalize through `broker_symbol_mappings`.
- `timeframe` accepts `15`, `15m`, `M15`, `60`, `1h`, `H1`; normalize to `M15` or `H1`.
- `time` must be UTC or parseable as UTC. If timezone is missing, treat as UTC and log `time_assumed_utc`.
- Numeric fields may arrive as strings and must be parsed into Decimal.

Validation:

- Source must map to `tradingview_bars`.
- Timeframe allowed: `M15`, `H1` in MVP.
- OHLC numeric and internally consistent.
- `isClosed=true`.
- Candle timestamp parseable as UTC.
- Symbol maps via `broker_symbol_mappings`.

### 4.2 Normalize and upsert

Normalize:

- Source symbol to canonical symbol.
- Timeframe to canonical timeframe.
- Decimal values to `Decimal`.
- Timestamp to UTC.

Upsert:

- Unique key: `source_id + symbol + timeframe + candle_time`.
- Duplicate identical candle is no-op.
- Changed candle payload updates row and logs changed summary.

### 4.3 Feed freshness

Update `data_source_feeds`:

- `last_candle_time`.
- `last_payload_received_at`.
- `status=OK`.
- clear last error.

If validation fails:

- update source/feed last error when source/feed can be identified.
- log structured event.
- return standard error shape.

### 4.4 Queue handoff

When a new closed candle is inserted or materially changed:

- enqueue strategy job only if the candle timeframe is a trigger timeframe for at least one active strategy.
- Liquidity Sweep v1 trigger timeframe is `M15`; `H1` updates context/freshness but does not enqueue strategy by itself.
- include correlation id.
- do not enqueue for duplicate no-op.

### 4.5 Local/staging import

Implement `POST /api/v1/admin/candles/import` for warmup data:

- enabled only in `local` and `staging`.
- requires admin auth.
- accepts CSV or JSON closed candles.
- uses the same normalizer/upsert path as TradingView ingest.
- never enabled in production.

## 5. Acceptance criteria

- Valid fake TradingView payload creates candle.
- Duplicate payload does not create duplicate row.
- Invalid OHLC rejected.
- Unknown symbol rejected with clear error.
- Feed matrix shows latest candle after ingest.
- Strategy job is enqueued once for new trigger-timeframe candle.
- H1 candle ingest updates feed freshness without enqueueing Liquidity Sweep.
- Local/staging import can warm up M15/H1 history without bypassing validation.
- Payload sample can be copied into TradingView alert message without code changes except secret value.

## 6. Risks and notes

- TradingView webhook is push-only; no automatic historical backfill.
- Cold-start needs enough M15/H1 bars before strategy can produce signals.
- Spread is usually unavailable from TradingView bars, so spread filter is skipped when spread is null.
