export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

.PHONY: install dev-services-up dev-services-down migrate seed api \
	worker-market worker-signal worker-telegram worker-maintenance \
	schedule-jobs scheduler test test-integration smoke release-check lint \
	css css-watch

install:
	uv sync

css:
	bash scripts/tailwind.sh build

css-watch:
	bash scripts/tailwind.sh watch

dev-services-up:
	docker compose up -d

dev-services-down:
	docker compose down

migrate:
	uv run alembic upgrade head

seed:
	uv run python -m app.seed

api:
	uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

worker-market:
	uv run rq worker market --url $${REDIS_URL:-redis://localhost:6379/0} --worker-ttl 86400

worker-signal:
	uv run rq worker signal --url $${REDIS_URL:-redis://localhost:6379/0} --worker-ttl 86400

worker-telegram:
	uv run rq worker telegram --url $${REDIS_URL:-redis://localhost:6379/0} --worker-ttl 86400

worker-maintenance:
	uv run rq worker maintenance --url $${REDIS_URL:-redis://localhost:6379/0} --worker-ttl 86400

schedule-jobs:
	uv run python scripts/schedule_jobs.py

scheduler:
	uv run python scripts/schedule_jobs.py
	uv run rqscheduler --url $${REDIS_URL:-redis://localhost:6379/0}

test:
	uv run pytest -m "not integration"

test-integration:
	uv run pytest -m integration

smoke:
	uv run python scripts/smoke.py

release-check:
	uv run python scripts/release_check.py

lint:
	uv run ruff check app tests scripts
