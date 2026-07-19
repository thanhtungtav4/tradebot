# tradebot

Forex Signal Bot MVP. TradingView bar webhook -> strategy -> risk -> router -> Telegram, with an Admin Console.

Specs in `specs/`, plans in `plans/`. Read `plans/00_MASTER_PLAN.md` first.

Full local run guide: [docs/RUNNING_PROJECT.md](/Volumes/Manager%20Data/Tool/tradebot/docs/RUNNING_PROJECT.md).

## Stack

- Python 3.12 + FastAPI
- SQLAlchemy 2.x + Alembic (PostgreSQL 16, no SQLite for integration)
- Redis 7 + RQ (workers, scheduler)
- Admin Console: Jinja2 + HTMX + Tailwind CSS + DaisyUI (Tailwind standalone CLI, no Node), TradingView Advanced Chart widget
- uv for dependency management

## Docker

Postgres + Redis run in Docker. App and workers run in the host venv (fast reload, easy debug). If Docker is unavailable, install Postgres 16 / Redis 7 locally (`brew install postgresql@16 redis`) and point `DATABASE_URL` / `REDIS_URL` at them.

## Quick start

```bash
cp .env.example .env         # fill CHANGE_ME values
make install                 # uv sync
make dev-services-up         # docker compose: postgres + redis
make migrate                 # alembic upgrade head
make seed                    # deterministic MVP config (repeat-safe)
make css                     # build admin CSS (downloads Tailwind CLI + DaisyUI on first run)
make api                     # uvicorn on :8000
# open http://localhost:8000/api/v1/health
```

Health endpoints:

```bash
curl http://localhost:8000/api/v1/health/live
curl http://localhost:8000/api/v1/health/ready
curl http://localhost:8000/api/v1/health
```

Workers/scheduler (separate terminals):

```bash
make worker-market
make worker-signal
make worker-telegram
make worker-maintenance
make schedule-jobs       # repeat-safe registration for maintenance jobs
make scheduler
```

## Tests

```bash
make test              # unit (no integration)
make test-integration  # needs Postgres up
make smoke
make release-check     # strict automated gates before real Telegram groups
```

`make smoke` seeds the DB, checks live/ready, posts one fake TradingView bar, verifies candle/feed storage, then prints full health. Full health may be `DEGRADED` in local until workers and real Telegram health are available.

Release readiness:

- Use [docs/ops/release_checklist.md](/Volumes/Manager%20Data/Tool/tradebot/docs/ops/release_checklist.md) before moving demo groups to real/live groups.
- `make release-check` is strict and should pass before release.
- For local rehearsal only, run `uv run python scripts/release_check.py --warn-only`.
