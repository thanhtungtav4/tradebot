# 04_STRATEGY_RISK_PLAN - Strategy, Risk, Duplicate Guard

## 1. Mục tiêu

Chạy Liquidity Sweep v1 trên candles đã đóng, tạo signal candidate, kiểm tra risk, chống duplicate và lưu signal/event đầy đủ.

## 2. Spec nguồn

- `specs/03_STRATEGY_ENGINE_SPEC.md`
- `specs/04_SIGNAL_RISK_SPEC.md`
- `specs/06_DATABASE_SPEC.md`

## 3. Artifacts cần tạo khi implement

- Strategy base interface and registry.
- Liquidity Sweep strategy.
- Context loader.
- EMA/calculation helpers.
- Risk manager.
- Duplicate guard.
- Signal service/repository.
- Unit tests for strategy/risk/duplicate.

## 4. Work breakdown

### 4.1 Context loader

For a strategy job:

- Run only for strategy trigger timeframe. Liquidity Sweep v1 trigger is `M15`.
- Load latest closed M15 candles.
- Load H1 context candles.
- Enforce lookback and cold-start rules.
- Build strategy context with symbol config and strategy default config.
- Reject early if required context is missing.
- If lookback is missing, persist a `signals` row with `status=REJECTED`, `reject_code=INSUFFICIENT_HISTORY`, and event `WARMUP_SKIPPED`.

### 4.2 Liquidity Sweep v1

Implement:

- BUY sweep low rules.
- SELL sweep high rules.
- Confirmation candle.
- H1 EMA50/EMA200 trend filter.
- Entry, SL, TP1, TP2.
- RR calculation.
- Confidence scoring.
- Reason list and invalid condition.

### 4.3 Global risk manager

Reject if:

- Missing entry/SL/TP/invalid condition.
- RR below threshold.
- Spread exceeds max spread when spread exists.
- Data stale/missing.
- Signal duplicate.

Skip spread filter when spread is null from TradingView.

### 4.4 Duplicate guard

Implement deterministic `signal_uid`:

```text
{strategyCode}:{symbol}:{timeframe}:{action}:{sourceCandleTime}:{entryBucket}
```

Rules:

- DB unique `signal_uid` is final guard.
- Redis lock may be added to reduce race.
- Duplicate conflict writes/returns `SKIPPED_DUPLICATE` behavior without outbox.

### 4.5 Signal persistence

Persist:

- `signals`.
- `signal_events`.
- reject code/message where relevant.
- metadata for debug.

## 5. Acceptance criteria

- Unit test creates valid BUY signal from fake candles.
- Unit test creates valid SELL signal from fake candles.
- Insufficient H1 context creates a warmup/reject signal row and event.
- RR below threshold rejects.
- Duplicate signal does not create second signal/outbox.
- Signal events explain created/approved/rejected/duplicate states.

## 6. Risks and notes

- TradingView H1/M15 feeds may arrive at different times; strategy should only run when required context is available.
- Do not let group settings change strategy detection logic. Group settings are for router eligibility.
