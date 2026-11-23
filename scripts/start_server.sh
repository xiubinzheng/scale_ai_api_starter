#!/usr/bin/env bash
# Start the API server.
# Usage: ./scripts/start_server.sh
# Optional env vars: OLLAMA_URL, OLLAMA_MODEL, PORT
set -euo pipefail

cd "$(dirname "$0")/.."
exec .venv/bin/uvicorn main:app --port "${PORT:-8000}"
