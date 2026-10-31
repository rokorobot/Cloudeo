# EVAL-01 live trials (PR 5)

Plan: [EVAL-01_PLAN.md](EVAL-01_PLAN.md) §5 PR 5 and §8.

## Owner decisions (2026-10-31)

| Decision | Value |
| --- | --- |
| First comparison | Claude Opus 5.5 (`claude-opus-5.5`, Claude Code) vs GPT 5.6 Sol (`gpt-5.6-sol`, Codex; the top GPT 5.6 tier), as the executor |
| Spending caps | USD 7 per comparison run; USD 20 per rolling 7 days |
| Where it runs | Here, in the Cloudroom cloud sandbox, started from chat |
| Credentials | Entered once through Cloudroom's secret form into the git-ignored `.env.live` |
| Comparison thresholds | Not approved: every comparison is **observational** and cannot authorize promotion |

Model ids were confirmed against the running HarnessRouter's catalog
(`/v1/models`), not assumed.

## Running (in Cloudroom)

```bash
scripts/live_eval/run_local.sh [REPETITIONS] [BASELINE] [CANDIDATE]   # default: 3 opus-5-5 gpt-5-6
```

Checks, in order, before any spend: the budget (per-run cap and what is left of
the weekly cap, from `~/.cloudeo-eval/ledger.jsonl`), HarnessRouter up, console
sign-in, both configured models offered. Then `compare --require-clean` and
`verify`. Evidence and reports go to `~/.cloudeo-eval/live/`.

### HarnessRouter without containers

Cloudroom sandboxes cannot run containers (no `CAP_SYS_ADMIN`: no mount
namespaces, `chroot` or device nodes). `scripts/live_eval/hr_native.sh` installs
the image's contents natively: HarnessRouter CE v0.23.7 source at
`809392d602e34e36f0468943035c54d3350af885`, Claude Code 2.1.280, Codex
0.154.0, and starts the same three processes with the entrypoint's
environment (runner as root, gateway and console as the `agent` user it
creates). Deviations from the image, deliberate: the machine's `/tmp`,
`/var/tmp` and `/dev/shm` permissions are not changed (they are shared with the
rest of the sandbox); only the `claude` and `codex` backends are installed;
Node.js is the sandbox's. The console password is random per start; the
session cookie is never printed.

Limits: background processes stop when the sandbox sleeps, so `run_local.sh`
restarts HarnessRouter when needed. The spend ledger lives in this sandbox; a
new cloud thread starts with an empty ledger.

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

- That a full task (not just the catalog) runs on both harnesses with these keys.
- Whether HarnessRouter reports a currency cost: if not, all cost is counted
  at the reserve.
