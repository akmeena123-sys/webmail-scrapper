#!/bin/bash
set -e
# Runner for the webmail scraper Flask app. launchd will call this script.
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BASE_DIR"
# load .env if present
if [ -f "$BASE_DIR/.env" ]; then
  set -o allexport
  source "$BASE_DIR/.env"
  set +o allexport
fi
# activate venv if exists
if [ -f "$BASE_DIR/venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$BASE_DIR/venv/bin/activate"
fi
mkdir -p "$BASE_DIR/logs"
exec python "$BASE_DIR/app.py" >> "$BASE_DIR/logs/out.log" 2>> "$BASE_DIR/logs/err.log"
