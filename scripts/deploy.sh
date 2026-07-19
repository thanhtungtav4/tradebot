#!/bin/bash
# Manual deploy: test locally, push, then pull+migrate+restart on the VPS.
# Fallback for when GitHub Actions is unavailable. Same steps as deploy.yml.
set -euo pipefail

HOST="${DEPLOY_HOST:-180.93.115.225}"
USER="${DEPLOY_USER:-tradebot}"
KEY="${DEPLOY_KEY:-/tmp/tbdeploy/deploy_key}"
APP_DIR="/home/tradebot/app"

echo ">> Running tests locally (gate)..." >&2
uv run ruff check app tests scripts
uv run pytest -q

echo ">> Pushing to origin/main..." >&2
git push origin main

echo ">> Deploying on $USER@$HOST ..." >&2
ssh -i "$KEY" -o StrictHostKeyChecking=no "$USER@$HOST" bash -s <<'REMOTE'
set -e
export PATH=$HOME/.local/bin:$PATH
cd /home/tradebot/app
git fetch origin main
git reset --hard origin/main
uv sync --frozen
uv run alembic upgrade head
uv run python -m app.seed
sudo systemctl restart tradebot-api tradebot-worker-market tradebot-worker-signal tradebot-worker-telegram tradebot-worker-maintenance tradebot-scheduler
sleep 3
curl -fsS http://127.0.0.1:8000/api/v1/health/ready && echo " <- deploy OK"
REMOTE

echo ">> Done." >&2
