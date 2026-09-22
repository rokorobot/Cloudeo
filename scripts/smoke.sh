#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${CLOUDEO_BASE_URL:-http://127.0.0.1:18800}"

echo "== health =="
curl -fsS "$BASE_URL/health" | python -m json.tool

echo "== demo run =="
curl -fsS "$BASE_URL/v1/runs" \
  -H 'Content-Type: application/json' \
  --data @"$(dirname "$0")/demo.json" | python -m json.tool
