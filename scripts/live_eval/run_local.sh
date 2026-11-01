#!/usr/bin/env bash
# One live EVAL-01 comparison, entirely inside a Cloudroom cloud sandbox.
#
#   scripts/live_eval/run_local.sh [REPETITIONS] [BASELINE] [CANDIDATE]
#
# Keys come from the git-ignored .env.live (entered once through Cloudroom's secret form);
# nothing secret is printed. Order of checks, all before any spend: budget (USD 7 per run,
# USD 20 per rolling week), HarnessRouter up, console sign-in, configured models offered.
set -euo pipefail
cd "$(dirname "$0")/../.."
REPS=${1:-3}
SUITE=${CLOUDEO_EVAL_SUITE:-live-smoke-v2}
BASE=src/cloudeo/evaluation/configurations/${2:-opus-5-5}.json
CAND=src/cloudeo/evaluation/configurations/${3:-gpt-5-6}.json
OUT=${CLOUDEO_EVAL_OUT:-$HOME/.cloudeo-eval/live}
LEDGER=${CLOUDEO_EVAL_LEDGER:-$HOME/.cloudeo-eval/ledger.jsonl}
HR=scripts/live_eval/hr_native.sh
RUN=/opt/harnessrouter/run
[ -f .env.live ] || { echo "no .env.live: enter the keys once via Cloudroom's secret form"; exit 1; }
mkdir -p "$OUT" "$(dirname "$LEDGER")"
eval_cli() { uv run --no-sync python -m cloudeo.evaluation "$@"; }

eval_cli compare --suite "$SUITE" --baseline "$BASE" --candidate "$CAND" \
  --repetitions "$REPS" --out "$OUT" --ledger "$LEDGER" --estimate-only

if ! curl -fsS -m 3 http://127.0.0.1:18810/api/harness/v1/uhp >/dev/null 2>&1; then
  [ -f /opt/harnessrouter/app/ui/server.js ] || "$HR" install
  "$HR" start .env.live
fi
pw=$(cat "$RUN/console-password")
curl -fsS -m 30 -c "$RUN/cookies" -o /dev/null http://127.0.0.1:18810/api/selfhost/login \
  -H 'content-type: application/json' -d "{\"username\":\"cloudeo\",\"password\":\"$pw\"}"
unset pw
chmod 600 "$RUN/cookies"
# curl writes HttpOnly cookies (the session cookie is one) as "#HttpOnly_<domain>" lines.
CLOUDEO_EVAL_UHP_COOKIE=$(awk '{sub(/^#HttpOnly_/, "")} !/^#/ && NF >= 7 {printf "%s%s=%s", sep, $6, $7; sep="; "}' "$RUN/cookies")
[ -n "$CLOUDEO_EVAL_UHP_COOKIE" ] || { echo "sign-in returned no session cookie"; exit 1; }
export CLOUDEO_EVAL_UHP_COOKIE CLOUDEO_EVAL_UHP_URL=http://127.0.0.1:18810/api/harness

uv run --no-sync python scripts/live_eval/preflight.py "$BASE" "$CAND"
eval_cli compare --suite "$SUITE" --baseline "$BASE" --candidate "$CAND" \
  --repetitions "$REPS" --out "$OUT" --ledger "$LEDGER" --require-clean
eval_cli verify --out "$OUT"
