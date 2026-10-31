# EVAL-01 live trials (PR 5)

Plan: [EVAL-01_PLAN.md](EVAL-01_PLAN.md) §5 PR 5 and §8.

## Owner decisions (2026-10-31)

| Decision | Value |
| --- | --- |
| First comparison | Claude Opus 5.5 (Claude Code) vs GPT 5.6 (Codex), as the executor |
| Spending caps | USD 7 per comparison run; USD 20 per rolling 7 days |
| Credentials | Entered once; stored as GitHub `live-eval` environment secrets `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` |
| Comparison thresholds | Not approved: every comparison is **observational** and cannot authorize promotion |

The owner first chose the cloud sandbox for credentials. That sandbox cannot run
containers (mount namespaces are denied), so the pinned HarnessRouter image runs
in GitHub Actions instead, with the keys entered once into the `live-eval`
environment.

## Running

Actions → **live-eval** → *Run workflow* on `main` (inputs: repetitions, baseline
and candidate configuration). The `live-eval` environment requires the owner's
approval and accepts only protected branches. The job:

1. restores the spend ledger from earlier runs' `live-eval-ledger` artifacts;
2. refuses to start if the planned reserves exceed the run cap or what is left
   of the weekly cap;
3. starts the pinned HarnessRouter CE 0.23.7 image on loopback with the provider
   keys as connections, signs in with a per-run random password, and masks the
   session cookie;
4. checks that each configured model is offered (no spend);
5. runs `compare --require-clean`, then `verify`, and uploads the evidence and a
   one-line ledger entry.

Locally, with any reachable HarnessRouter:

```bash
export CLOUDEO_EVAL_UHP_URL=http://127.0.0.1:18810/api/harness CLOUDEO_EVAL_UHP_KEY=...
uv run python -m cloudeo.evaluation compare --suite live-smoke-v1 \
  --baseline src/cloudeo/evaluation/configurations/opus-5-5.json \
  --candidate src/cloudeo/evaluation/configurations/gpt-5-6.json \
  --repetitions 3 --out eval-out --require-clean
```

## Suite `live-smoke-v1` (capability, live)

| Case | Path exercised | Oracle |
| --- | --- | --- |
| `live-exact-reply` | `dispatch_attempt` → HarnessRouter → model | output is exactly `CLOUDEO_LIVE_OK` |
| `live-arithmetic` | same | output is exactly `1610` |
| `live-workspace-edit` | `authorize_executor_attempt` → bridge → HarnessRouter session → delta applied to a real Git candidate | `notes/greeting.txt` read from the candidate equals the expected line; accepted state unchanged |

Reserve: USD 0.35 per trial; 3 cases × 3 repetitions × 2 configurations =
USD 6.30 planned. Tokens are recorded but never converted to money; a trial
whose cost the runtime did not report counts as its full reserve. Executor
profiles declare `metered_api` with a cost limit within the policy cap.

## Comparison report

`comparison-<run>.json` and `.md`: per configuration attempted, completed,
verified (outcome and execution pass), outcome pass, execution-policy
violations, unknown, unsupported, infrastructure-invalid, not run (budget),
reported and counted cost, cost per verified success (only with known cost),
median and p95 duration (p95 only with n ≥ 20), per-case k/n; changed
variables and kind (`single_variable` or `system`; this one is `system`:
harness, model and provider all change); paired verified-rate difference with a
case-clustered bootstrap interval; critical findings. Every attempted trial is
kept. `verify` regrades from the retained files.

## Not yet proven (first live run)

- Headless HarnessRouter bootstrap: provider connections from environment
  variables and console-cookie authentication follow the CE self-hosting
  guide, but have not run in CI. The job fails before any spend if sign-in or
  preflight fails.
- Model ids `claude-opus-5-5` and `gpt-5.6` for the built-in `claude` and
  `codex` harnesses: confirmed by preflight against the harness model lists.
- Whether HarnessRouter reports a currency cost: if not, all cost is counted
  at the reserve.
