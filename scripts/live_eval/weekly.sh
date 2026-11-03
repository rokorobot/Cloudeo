#!/usr/bin/env bash
# The weekly EVAL-01 live check (owner decision 2026-11-02: USD 10 per week).
#
# live-corpus-v1, one repetition, the current baseline against the comparison candidate.
# It is observational monitoring, not a release verdict: one repetition is below
# thresholds-v1's minimum of five. The per-run cap equals the weekly cap because each
# scheduled run starts in a fresh sandbox with an empty spend ledger.
set -euo pipefail
cd "$(dirname "$0")/../.."
export CLOUDEO_EVAL_SUITE=live-corpus-v1 CLOUDEO_EVAL_RUN_CAP=10 CLOUDEO_EVAL_WEEK_CAP=10
exec scripts/live_eval/run_local.sh 1 "${1:-opus-5-5}" "${2:-gpt-5-6}"
