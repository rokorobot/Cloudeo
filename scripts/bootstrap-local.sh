#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv is required. Install uv first, then rerun this script." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

uv sync --extra dev
uv run pytest -q

echo
echo "Cloudeo v0.1 is ready. Start it with:"
echo "  uv run cloudeo"
echo "Then open: http://127.0.0.1:18800/docs"
