# 07_HEALTH_MONITORING_OPS_PLAN - Health, Monitoring, Ops

## 1. Mục tiêu

Đảm bảo app cho biết đang sống/chết ở đâu: DB, Redis, data feed, workers, Telegram. Health state phải phục vụ API, Admin Console và operator playbook.

## 2. Spec nguồn

- `specs/01_RUNTIME_DEPLOY_SPEC.md`
- `specs/09_MONITORING_TEST_SPEC.md`
- `specs/11_PRODUCT_OPS_SPEC.md`
- `specs/12_ADMIN_CONSOLE_SPEC.md`

## 3. Artifacts cần tạo khi implement

- `/api/v1/health`
- `/api/v1/health/live`
- `/api/v1/health/ready`
- component health service.
- stale feed scheduler job.
- outbox retry scan job.
- queue depth helpers.
- structured log events.
- ops smoke script/checklist.

## 4. Work breakdown

### 4.1 Health endpoints

Implement:

- `live`: process alive.
- `ready`: DB/Redis ready.
- full health: DB, Redis, data feed, Telegram API, workers and scheduler.

Milestone split:

- Milestone A implements only `/live` and DB ping readiness.
- Milestone F implements full component health, feed freshness, queue depth and Telegram checks.

Response:

- standard component shape.
- 200 when OK.
- 503 when degraded/down critical component.

### 4.2 Component health

Maintain `component_health` rows:

- `api`
- `db`
- `redis`
- `data_feed`
- `market_worker`
- `signal_worker`
- `telegram_worker`
- `scheduler`
- `telegram_api`

Admin Console Overview reads these rows.

### 4.3 Stale feed scheduler

Scheduled job:

- scan `data_source_feeds`.
- compare `last_candle_time` to stale threshold.
- set `UNKNOWN`, `WARMUP`, `OK`, `STALE`, `ERROR`, `PAUSED`.
- update `component_health.data_feed`.

### 4.4 Outbox retry scheduler

Scheduled job:

- scan `telegram_outbox` with `PENDING`, `FAILED_RETRYABLE`, or stale `SENDING`.
- only enqueue due rows or stale locks.
- ignore `SENT`, `FAILED_PERMANENT`, `SKIPPED`.
- reclaim stale locks using `locked_until`.

### 4.4a Worker process map

Required worker processes:

- `market`: optional async ingest jobs and feed maintenance.
- `signal`: strategy and routing jobs.
- `telegram`: send Telegram jobs.
- `maintenance`: stale feed scan and outbox retry scan.

Local dev may run one worker listening to all queues; production should split queues.

Health component mapping:

- `market_worker`: ingest/feed maintenance queue is being consumed.
- `signal_worker`: strategy/routing queue is being consumed.
- `telegram_worker`: Telegram send queue is being consumed.
- `scheduler`: stale feed and outbox retry jobs are being scheduled.
- `telegram_api`: cached Telegram `getMe`/bot permission check.

### 4.5 Structured logging and metrics

Log events:

- `tradingview_bar_received`
- `candles_ingested`
- `data_feed_stale`
- `strategy_started`
- `signal_approved`
- `signal_rejected`
- `signal_routed`
- `telegram_send_succeeded`
- `telegram_send_failed`
- `admin_action_logged`

Metrics/log counters:

- candles ingested.
- signals created/rejected/approved/duplicate.
- telegram sent/failed.
- pending outbox count.
- queue depth.
- signal pipeline latency.

## 5. Acceptance criteria

- Health reports DB/Redis down.
- Health reports stale feed.
- Admin Overview matches component health state.
- Outbox retry scheduler does not retry `SENT`.
- Operator runbooks are reachable from degraded states.

## 6. Risks and notes

- Health should be cheap; avoid scanning candle history in request path.
- `data_source_feeds` and `component_health` are cache/current-state tables for fast Admin Console.
