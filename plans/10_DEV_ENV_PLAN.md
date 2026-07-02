# 10_DEV_ENV_PLAN - Developer Environment and Commands

## 1. Mục tiêu

Đảm bảo người implement có thể dựng môi trường local nhất quán trước khi viết module: PostgreSQL, Redis, API, workers, scheduler, migrations, seed và test commands.

## 2. Spec nguồn

- `specs/01_RUNTIME_DEPLOY_SPEC.md`
- `specs/06_DATABASE_SPEC.md`
- `specs/09_MONITORING_TEST_SPEC.md`
- `plans/00_MASTER_PLAN.md`

## 3. Artifacts cần tạo khi implement

- `docker-compose.yml` for PostgreSQL and Redis.
- `.env.example`.
- `Makefile` or `justfile` with common commands.
- README local quick start.
- Optional scripts under `scripts/`.

## 4. Required services

Local services:

- PostgreSQL 16+.
- Redis 7+.
- FastAPI app.
- RQ workers.
- RQ scheduler or scheduler command.

No SQLite as the primary integration path.

## 5. Required commands

Provide commands equivalent to:

```text
make install
make dev-services-up
make dev-services-down
make migrate
make seed
make api
make worker-market
make worker-signal
make worker-telegram
make worker-maintenance
make scheduler
make test
make test-integration
make smoke
```

If not using Make, document exact shell commands with the same names/intent.

## 6. Environment defaults

`.env.example` must include:

- `APP_ENV=local`
- `DATABASE_URL`
- `REDIS_URL`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD_HASH`
- `ADMIN_SESSION_SECRET`
- `ADMIN_API_KEY`
- `TRADINGVIEW_WEBHOOK_TOKEN`
- `TRADINGVIEW_BODY_SECRET`
- `TELEGRAM_BOT_TOKEN`
- `STALE_GRACE_MINUTES`
- `OUTBOX_LOCK_TIMEOUT_SECONDS`
- `RETRY_SCAN_INTERVAL_SECONDS`

Placeholders must be obvious and unsafe defaults must be rejected in production.

## 7. Local quick start acceptance

A fresh developer can run:

1. install dependencies.
2. start Postgres/Redis.
3. migrate DB.
4. seed DB.
5. start API.
6. open Admin Console login.
7. run tests.

No manual DB table creation.

## 8. Risks and notes

- Python version should be pinned in `pyproject.toml` to a version supported by dependencies.
- If local machine cannot run Docker, document manual Postgres/Redis env alternatives.
- Do not require live Telegram token for normal tests.
