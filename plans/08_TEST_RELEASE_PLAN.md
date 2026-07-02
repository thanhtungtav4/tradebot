# 08_TEST_RELEASE_PLAN - Tests and Release Readiness

## 1. Mục tiêu

Đảm bảo MVP không chỉ chạy được mà còn chứng minh được các đường quan trọng: webhook -> candle -> signal -> outbox -> Telegram attempt -> Admin Console.

## 2. Spec nguồn

- `specs/09_MONITORING_TEST_SPEC.md`
- all module specs.

## 3. Test layers

### 3.1 Unit tests

Required:

- settings validation.
- auth/session/API key/CSRF.
- TradingView payload validation.
- candle normalizer.
- candle upsert idempotency.
- feed freshness status.
- feed warmup status.
- Liquidity Sweep BUY/SELL/reject.
- Liquidity Sweep trigger timeframe gating.
- EMA trend filter.
- RR math.
- duplicate UID generation.
- group eligibility.
- Telegram formatter BASIC/FULL/SUMMARY.
- outbox retry/backoff decision.
- secret redaction.

### 3.2 Integration tests

Scenarios:

1. Run migration and seed from zero.
2. Fake TradingView payload creates candle and updates feed.
3. H1-only payload updates context/feed but does not enqueue Liquidity Sweep.
4. Insufficient history creates `REJECTED/INSUFFICIENT_HISTORY` warmup signal.
5. Local/staging candle import warms up history through the same normalizer.
6. Enough fake candles trigger strategy and approved signal.
7. Approved signal routes to eligible demo group.
8. Mocked Telegram success marks outbox `SENT` and writes attempt row.
9. Mocked Telegram 429 schedules retry.
10. Stale `SENDING` outbox can be reclaimed safely.
11. Duplicate webhook/signal does not create duplicate outbox.
12. Admin Overview data matches DB fixtures.

### 3.3 Admin tests

Required:

- login success/failure.
- CSRF blocks mutation.
- Overview loads component tiles/feed matrix.
- Overview/feed matrix renders `WARMUP`.
- Groups wizard creates demo group.
- Test message action logs admin activity.
- Signals detail shows events.
- Deliveries retry creates audit log.
- No secrets appear in rendered HTML.
- keyboard-only navigation reaches all main Admin Console actions.
- status is not conveyed by color only.
- core screens remain usable at 200% zoom.
- table empty/error/loading states render clearly.

### 3.4 Smoke test

Manual or scripted:

1. Start DB, Redis, API, workers.
2. Run migrations and seed.
3. Login Admin Console.
4. Verify Overview.
5. Send fake TradingView bar payload.
6. Confirm candle/feed update.
7. Send enough fake payloads for strategy context.
8. Confirm signal/outbox.
9. Mock or send Telegram test message.
10. Confirm delivery status and Admin Console visibility.

## 4. Release criteria

MVP can move from demo to real group only when:

- 48h demo run completed.
- no duplicate messages in cooldown window.
- DB/Redis health stable.
- data feed stale states understood and visible.
- Telegram test and delivery logs are clear.
- Admin Console five-minute checklist passes.
- all critical tests pass.
- `APP_ENV=production` refuses default secrets/placeholders.
- demo placeholder Telegram chat IDs cannot be enabled as live groups.
- secure-cookie/HTTPS warnings are visible or enforced for production.

## 5. Acceptance criteria

- CI/local test command runs unit tests.
- Integration test runs on PostgreSQL and can run without live TradingView or Telegram.
- Smoke checklist documented and repeatable.
- Failed tests identify module clearly.

## 6. Risks and notes

- Live Telegram tests should be opt-in using env token/chat id.
- Do not rely on live TradingView for automated tests.
- Use fake candles for deterministic strategy tests.
