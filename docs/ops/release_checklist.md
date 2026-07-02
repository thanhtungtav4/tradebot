# MVP Release Checklist - Demo to Real Telegram Groups

Use this checklist before changing any Telegram group from demo/inactive to real/live.

## 1. Required Commands

Run these commands from the project root:

```bash
make lint
make test-integration
make smoke
make schedule-jobs
uv run python scripts/release_check.py
```

For local rehearsal where workers or live Telegram are intentionally missing:

```bash
uv run python scripts/release_check.py --warn-only
```

Strict release must use the command without `--warn-only`.

## 2. 48h Demo Evidence

Record evidence before release:

| Item | Required Evidence | Result |
| --- | --- | --- |
| Demo start time | ISO timestamp | |
| Demo end time | ISO timestamp, at least 48h after start | |
| Active symbols/timeframes | XAUUSD/EURUSD/GBPUSD M15+H1 or approved subset | |
| Duplicate delivery check | No duplicate Telegram message within cooldown window | |
| Feed health | No unexplained `STALE`/`ERROR`; any stale state has known cause | |
| DB/Redis health | No unresolved DB/Redis errors | |
| Telegram delivery | Test message and real delivery attempt visible in Admin Console | |
| Admin five-minute check | Operator can identify feed health, latest signal, delivery state and next action without logs | |

## 3. Automated Gates

`scripts/release_check.py` blocks release when:

- required `component_health` rows are missing or not `OK`.
- any active feed is not `OK`.
- active data sources are missing or in an error/down state.
- a placeholder Telegram chat id is active or live.
- an active `LIVE` group has no successful test message.
- Telegram outbox has unresolved `FAILED_RETRYABLE`, `FAILED_PERMANENT`, or `SENDING` rows.
- `APP_ENV=production` contains placeholder/short secrets. This is enforced by settings startup validation.

## 4. Manual Go/No-Go

Go only when all are true:

- The automated release check passes in strict mode.
- One operator has completed the 48h demo evidence table.
- Real Telegram groups have been tested with the real bot token and chat ids.
- Admin Overview shows `OK` or every non-OK state has a documented, accepted reason.
- A rollback path is known: pause groups, disable live mode, stop workers if needed.

No-go when any are true:

- Admin Console cannot explain the next operator action in under five minutes.
- Any placeholder group is active/live.
- Telegram bot was kicked, rate-limited, or cannot send to the target group.
- Data feed is stale and the cause is unknown.
- There are unresolved DB/Redis errors.
