#!/usr/bin/env bash
# Run the gradebook app locally (no Docker), using uv.
#
#   ./start.sh              scrape once now (default)
#   ./start.sh schedule     run every day on SCHEDULE_CRON until Ctrl+C
#   ./start.sh dashboard    rebuild data/site/index.html from saved CSVs (no login) and open it
#   ./start.sh serve        serve the dashboard with write-off buttons at http://localhost:$DASHBOARD_PORT (default 8787)
#   ./start.sh parse FILE   re-parse a saved gradebook HTML file
#   ./start.sh parse-assignments data/raw/assignments_*.html data/raw/gradebook_*.html
#                           re-parse saved assignment pages (no login)
#   ./start.sh test         run the tests
#
# Handy overrides:  HEADLESS=false ./start.sh   (watch the browser)
#                   MAX_RETRIES=2 ./start.sh    (one-off runs default to no retries)
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is not installed. Install it with:  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi
if [[ ! -f .env ]]; then
  echo "Missing .env. Create it with:  cp .env.example .env   then add your Skyward login." >&2
  exit 1
fi

uv sync --quiet
# Downloads Chromium the first time; does nothing if it is already installed.
uv run --quiet playwright install chromium

# .env sets DATA_DIR=/app/data for Docker; locally write to ./data instead.
# Variables set here win over .env.
export DATA_DIR="${LOCAL_DATA_DIR:-$PWD/data}"
export STATE_DIR="${LOCAL_STATE_DIR:-$PWD/state}"
mkdir -p "$DATA_DIR"

if [[ "${1:-run}" == "test" ]]; then
  shift
  exec uv run pytest -q "$@"
fi
if [[ "${1:-run}" == "serve" ]]; then
  exec uv run python -m gradebook serve "${@:2}"
fi
if [[ "${1:-run}" == "dashboard" ]]; then
  uv run python -m gradebook dashboard
  if command -v open >/dev/null 2>&1; then open "$DATA_DIR/site/index.html"; fi
  exit 0
fi
if [[ "${1:-run}" == "run" ]]; then
  # A one-off local run should fail fast instead of waiting 10 minutes to retry.
  export MAX_RETRIES="${MAX_RETRIES:-0}"
fi
exec uv run python -m gradebook "${@:-run}"
