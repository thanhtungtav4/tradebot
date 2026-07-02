# 05_ROUTER_TELEGRAM_PLAN - Router and Telegram Delivery

## 1. Mục tiêu

Route approved signals to eligible Telegram groups, create idempotent outbox rows, format messages by group mode and deliver with safe retry/attempt logging.

## 2. Spec nguồn

- `specs/05_TELEGRAM_ROUTER_SPEC.md`
- `specs/06_DATABASE_SPEC.md`
- `specs/07_API_ADMIN_SPEC.md`

## 3. Artifacts cần tạo khi implement

- Router service.
- Group eligibility service.
- Telegram formatter.
- Telegram API client.
- Outbox worker.
- Retry scheduler job.
- Delivery attempt logger.
- Tests for routing, formatting, locking, retry.

## 4. Work breakdown

### 4.1 Group eligibility

For each approved signal, evaluate active group settings:

- group active and not paused.
- setting active.
- symbol included through `group_strategy_symbols`.
- timeframe included through `group_strategy_timeframes`.
- strategy matches.
- confidence >= min confidence.
- cooldown not active.
- no existing outbox delivery UID.

Cooldown source:

- Query latest non-skipped `telegram_outbox` joined to `signals` for the same `group_id`, `symbol`, `strategy_code`, `action`, `timeframe`.
- Use `sent_at` if available, otherwise `created_at` for queued/retryable rows.
- Active cooldown skips only that group; it does not reject the global signal.

### 4.2 Outbox creation

Create one `telegram_outbox` row per eligible group.

Delivery UID:

```text
{signal_uid}:{group_id}
```

Rules:

- conflict means skip, not error.
- write `OUTBOX_CREATED` signal event.
- update signal aggregate status to `QUEUED` when rows created.
- if no groups are eligible, keep signal `APPROVED` and write router skipped events with reasons.

### 4.3 Message formatting

Implement modes:

- BASIC for free groups.
- FULL for VIP/SMC groups.
- SUMMARY reserved but available.

Rules:

- MVP sends plain text to avoid Markdown escaping issues.
- Free message can show zone, action, timeframe, reason.
- VIP message shows entry, SL, TP, RR, strategy, confidence, reasons, invalid condition.

### 4.4 Telegram worker

Worker flow:

1. Claim due `PENDING`/`FAILED_RETRYABLE` outbox row or stale `SENDING` row using `FOR UPDATE SKIP LOCKED`, `locked_until`, `lock_token`.
2. Append `signal_deliveries` attempt row.
3. Call Telegram `sendMessage`.
4. Update outbox current state.
5. Finish attempt row.
6. Update group last delivery fields.
7. Update signal aggregate status where needed.

Retry rules:

- Retry max 3 attempts.
- Backoff 30s, 2m, 5m.
- Telegram 429 uses `retry_after` if available.
- Permanent 400/403 failures become `FAILED_PERMANENT`.
- `SENT` rows never retry.
- Reclaimed stale `SENDING` rows must inspect latest attempt before resending; if a Telegram message id already exists, mark `SENT` instead of sending again.
- Signal aggregate status supports `SENT`, `PARTIAL_SENT`, `PARTIAL_FAILED`, and `FAILED`.

## 5. Acceptance criteria

- Eligible group receives outbox row.
- Inactive/paused group does not receive outbox row.
- Duplicate delivery UID does not create second outbox.
- Retry creates new `signal_deliveries` attempt row.
- Failed permanent appears in Admin Console delivery list.
- Telegram token never appears in logs.

## 6. Risks and notes

- Telegram can receive duplicate message if worker crashes after sending but before DB update. Spec accepts rare risk and requires audit log event.
- Do not delete failed outbox rows; Admin Console needs them for operator action.
