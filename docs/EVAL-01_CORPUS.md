# EVAL-01 corpus v1

Suite: `src/cloudeo/evaluation/suites/corpus-v1.json`. Plan: [EVAL-01_PLAN.md](EVAL-01_PLAN.md) §6.
Baseline: `46ac370`. All cases are deterministic: only external boundaries are
faked (Treg, Jev, the UHP/HarnessRouter server, and the auditor model's report).

```bash
uv run python -m cloudeo.evaluation run --suite corpus-v1 --out eval-out
uv run python -m cloudeo.evaluation verify --out eval-out
```

## Partitions

| Partition | Cases | Meaning | Run exit code |
| --- | ---: | --- | --- |
| regression | 18 | Supported behavior; must pass | any fail or error → exit 1 |
| capability | 8 | Known gaps; expected to fail today, each names the missing feature | reported, never fails the run |
| holdout | 0 of 4 | Contamination check; authored independently later (below) | aggregate counts only |

A capability case that starts passing is promoted to regression in a new corpus
version. The test suite pins every capability case as failing, like a strict xfail.

Families follow the plan's table of 30. Four slots are reserved for holdout:
the corpus-v1 family counts are 3 discovery, 3 validation, 3 identity,
4 authorization, 3 billing, 3 auditor, 3 checkpoints, 4 recovery. Which
families take the 4 holdout cases is the holdout author's choice.

## Coverage

| Family | Case | Rev | Partition | Severity | Entry point | Needs |
| --- | --- | ---: | --- | --- | --- | --- |
| Discovery and routing | `routing-discovered-typed-match` | 1 | regression | major | `core.controller.run` | — |
| Discovery and routing | `routing-missing-capability-escalates` | 1 | regression | major | `core.controller.run` | — |
| Discovery and routing | `routing-respects-excluded-provider` | 1 | capability | major | `core.controller.run` | — |
| Validation and Jev | `deterministic-fail-then-jev-escalation` | 2 | regression | critical | `core.controller.run` | — |
| Validation and Jev | `direct-tool-verified-success` | 2 | regression | major | `core.controller.run` | — |
| Validation and Jev | `persuasive-invalid-result-escalates` | 1 | regression | critical | `core.controller.run` | — |
| Identity and ambiguous completion | `uhp-unknown-no-unsafe-retry` | 2 | regression | critical | `execution.uhp_dispatch_failure` | orchestration |
| Identity and ambiguous completion | `identity-actual-model-mismatch` | 1 | capability | critical | `execution.uhp_dispatch` | orchestration |
| Identity and ambiguous completion | `identity-reported-model-fallback` | 1 | capability | critical | `execution.uhp_dispatch` | orchestration |
| Authorization, workspace and secrets | `auditor-remote-write-blocks-promotion` | 1 | regression | critical | `longhorizon.audit_then_promotion_gate` | longhorizon |
| Authorization, workspace and secrets | `ignored-secret-never-uploaded` | 1 | regression | critical | `longhorizon.audit_then_promotion_gate` | longhorizon |
| Authorization, workspace and secrets | `secret-in-tool-output-not-persisted` | 1 | capability | major | `core.controller.run` | — |
| Authorization, workspace and secrets | `unapproved-harness-dispatch-refused` | 1 | capability | critical | `execution.uhp_dispatch` | orchestration |
| Billing and budgets | `prohibited-billing-transition` | 2 | regression | critical | `control.billing_approval` | v2_control |
| Billing and budgets | `unknown-billing-mode-never-approved` | 1 | regression | critical | `control.billing_approval` | v2_control |
| Billing and budgets | `tool-cost-over-budget-refused` | 1 | capability | major | `core.controller.run` | — |
| Auditor independence and evidence | `malformed-audit-report-refused` | 1 | regression | critical | `longhorizon.audit_then_promotion_gate` | longhorizon |
| Auditor independence and evidence | `missing-audit-evidence-refused` | 1 | regression | critical | `longhorizon.promotion_gate` | longhorizon |
| Auditor independence and evidence | `post-audit-mutation-refused` | 3 | regression | critical | `longhorizon.audit_then_promotion_gate` | longhorizon |
| Checkpoints and promotion | `head-changed-after-audit-refused` | 1 | regression | critical | `longhorizon.audit_then_promotion_gate` | longhorizon |
| Checkpoints and promotion | `stale-candidate-refused` | 1 | regression | critical | `longhorizon.audit_then_promotion_gate` | longhorizon |
| Checkpoints and promotion | `verified-candidate-promoted` | 1 | regression | critical | `longhorizon.audit_then_promotion_gate` | longhorizon |
| Recovery and refusal | `invalid-request-refused-without-retry` | 1 | regression | major | `execution.uhp_dispatch` | orchestration |
| Recovery and refusal | `tool-failures-escalate` | 1 | regression | major | `core.controller.run` | — |
| Recovery and refusal | `harness-unavailable-uses-approved-fallback` | 1 | capability | major | `execution.uhp_dispatch` | orchestration |
| Recovery and refusal | `rate-limited-retry-within-policy` | 1 | capability | minor | `execution.uhp_dispatch` | orchestration |

`longhorizon` cases need the optional extra; without it they are reported as
`unsupported`, never as passes.

## Capability gaps measured

| Case | Missing today | Related obligation |
| --- | --- | --- |
| `routing-respects-excluded-provider` | Routing has no provider allow-list from approvals | — |
| `identity-actual-model-mismatch` | A completed run with a different actual model is accepted as plain success | — |
| `identity-reported-model-fallback` | A runtime-reported model fallback is accepted as plain success | V2C-12 |
| `unapproved-harness-dispatch-refused` | Dispatch is not bound to an approved WorkOrder | V2C-02 |
| `secret-in-tool-output-not-persisted` | Tool output is stored verbatim in the run record | — |
| `tool-cost-over-budget-refused` | `RunRequest` carries no cost budget | — |
| `harness-unavailable-uses-approved-fallback` | No control-owned fallback execution | V2C-12 |
| `rate-limited-retry-within-policy` | No control-owned retry policy | — |

Passing a capability case never marks a V2C obligation ENFORCED by itself
(plan §9); that needs the production integration and its own tests.

## Oracle review

Each expected state was derived from the documented behavior of the code under
test (validators, `outcome_from_uhp_error`, `assess_execution_failure`,
`normalize_auditor_result`, `evaluate_promotion_gate`, `BillingPolicy`), not
copied from observed output. Two mismatches on the first run were fixture bugs,
not product behavior, and were fixed in the scenarios:

- the fake UHP server omitted the `UHP-Version` header, so identity cases were
  measuring a protocol error (`actual_model` pinned in the case exposed it);
- the stale-candidate case counted the other promotion's checkpoint.

Independent review of the oracles: see the PR for the reviewer's findings.

## Holdout process

1. An author independent of Cloudeo development writes the holdout cases in the
   `EvalCase` format, with `partition: "holdout"`, in restricted storage:
   `<dir>/cases/<case-id>.r<revision>.json`.
2. The author gives the maintainer only each case's ID, revision and digest
   (`python -m cloudeo.evaluation digest FILE`).
3. A new corpus version lists them with `"holdout": true`. The runner refuses
   holdout content inside the repository and a partition/flag mismatch.
4. Runs with `CLOUDEO_EVAL_HOLDOUT_DIR=<dir>` execute them and store their
   trials in `<dir>/results/`; the run output shows only aggregate counts.
   Without the directory they are counted as `unavailable`.
5. Holdout results inform promotion review only (plan §8). A diagnosis that
   needs holdout content retires that case and replaces it in a new version.
