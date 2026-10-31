# EVAL-01 corpus

Current suite: `corpus-v2` (27 cases: 19 regression, 8 capability); see
"Corpus v2" below. `corpus-v1` (26 cases) is kept unchanged as history.

Suite files: `src/cloudeo/evaluation/suites/`. Plan: [EVAL-01_PLAN.md](EVAL-01_PLAN.md) §6.
Baseline: `46ac370`. All cases are deterministic: only external boundaries are
faked (Treg, Jev, the UHP/HarnessRouter server, and the auditor model's report).

```bash
uv run python -m cloudeo.evaluation run --suite corpus-v2 --out eval-out
uv run python -m cloudeo.evaluation verify --out eval-out
```

## Partitions

| Partition | Cases | Meaning | Run exit code |
| --- | ---: | --- | --- |
| regression | 18 | Supported behavior; must pass | any fail or error → exit 1 |
| capability | 8 | Known gaps; fail (6) or unknown (2) today, each names the missing feature | reported, never fails the run |
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
| `identity-actual-model-mismatch` | No identity policy consumer decides on a completed run with a different actual model; graded unknown | — |
| `identity-reported-model-fallback` | No identity policy consumer decides on a reported model fallback; graded unknown | V2C-12 |
| `unapproved-harness-dispatch-refused` | Dispatch is not bound to an approved WorkOrder; a refusal would be an observed, completed outcome | V2C-02 |
| `secret-in-tool-output-not-persisted` | Tool output is stored verbatim in the run record | — |
| `tool-cost-over-budget-refused` | `RunRequest` carries no cost budget | — |
| `harness-unavailable-uses-approved-fallback` | Discovery lists only the fallback before dispatch; no control-owned fallback execution | V2C-12 |
| `rate-limited-retry-within-policy` | No control-owned retry policy | — |

Passing a capability case never marks a V2C obligation ENFORCED by itself
(plan §9); that needs the production integration and its own tests.

## Oracle review

Expected states were derived from the documented behavior of the code under
test, not copied from observed output. Three oracle or fixture errors surfaced
while running them and were fixed in the fixtures: the fake UHP server omitted
the `UHP-Version` header (identity cases measured a protocol error), the
stale-candidate case counted another candidate's checkpoint, and the
remote-write case used Cloudeo's `mode_changed` mutation shape where
`AuditorVerification` carries LongHorizon's `type_changed` shape
(`tests/test_longhorizon_audit_result.py:33`).

An independent reviewer (separate thread, different model family) graded the
first revision: 9 OK, 11 WEAK, 6 WRONG. Resolutions:

| Finding | Cases | Resolution |
| --- | --- | --- |
| Policy input never reaches production, or the fake forces an outcome a correct implementation would avoid | excluded-provider, cost-over-budget | Router fake picks only among offered choices; refusal accepted as a valid outcome; budget passed in the request (ignored today, new revision when the field exists) |
| "Accepted" inferred from runtime status | both identity cases | Proxy removed; the decision is unobserved (unknown) until an identity policy consumer exists |
| A correct refusal would grade unknown or error | unapproved-dispatch | Refusal is recorded as an observed outcome with its own evidence event |
| 503 gives no outage evidence; any other harness counted as fallback | harness-unavailable | Discovery lists only the fallback before dispatch; per-harness counts and an approved-harness rule |
| Any retry satisfied the oracle | rate-limited-retry | Retry must be identical and on the same harness (authorization rule) |
| Promotion judged by the gate's own result | verified-promoted, ignored-secret | Accepted tree read from Git and compared byte-for-byte with the fixture; parent must be the base |
| BLOCKED for any reason passed | auditor-remote-write | Reason, mutated paths and the fake model's write event required |
| Jev check only on exact outputs | persuasive-invalid | No Jev verification at all |
| A deleted run record hid the secret | secret-in-output | Run record must exist |
| Required events without substance | all controller cases | `db:run_records` is emitted only when rows exist |

A targeted re-review of the WRONG cases found the identity and cost-budget
cases OK. For excluded-provider, unapproved-dispatch, harness fallback and
rate-limited retry it found that the policy input cannot reach production: the
control-owned routing, dispatch, fallback and retry entry points do not exist
yet. Each of these cases therefore also requires a control-decision
observation (`routing.allow_list_applied`, `control.dispatch_decision`,
`control.fallback_authorized_by`, `control.retry_authorized_by`) that no current
scenario produces. They fail today on real evidence, and they cannot pass until
a new case revision binds them to the real entry point. The dispatch scenario
no longer treats an exception as a refusal.

### Stated limits (not fixed in corpus v1)

- `routing-discovered-typed-match` and `routing-missing-capability-escalates`
  fake the Treg client's discovery, so catalog matching and input binding are
  not exercised. Follow-up: a catalog-level fake beneath the real adapter.
- `uhp-unknown-no-unsafe-retry` and `invalid-request-refused-without-retry`
  stop at orchestration's attention assessment; the control state transition
  (`route_execution_failure` on a WorkOrder) is not exercised. Follow-up.
- `missing-audit-evidence-refused` is a gate contract test with synthetic
  auditor evidence (trace `partial`), not end-to-end producer coverage.
- Observations such as gate status, audit status and attempt labels are
  Cloudeo's classifications; cases use them to test classification, while
  execution, persistence and promoted content are read independently.
- A policy-denied counterpart to `rate-limited-retry-within-policy` belongs in
  the next corpus version.

## Corpus v2

Closes two stated limits of corpus v1 and adds the policy-denied retry case:

| Case | v1 | v2 |
| --- | --- | --- |
| `routing-discovered-typed-match` r2 | Treg faked at the client | Real `TregCLIClient` over a fake `treg` command (`fake_treg.py`): Cloudeo's discovery queries, catalog search and get, input binding, endpoint rejection and call arguments all run; the exact bound call is part of the oracle |
| `routing-missing-capability-escalates` r2 | Empty candidate list supplied | The catalog offers only an endpoint needing an input the request lacks; the real adapter rejects it during binding |
| `uhp-unknown-no-unsafe-retry` r3 | Stopped at the attention assessment | Routed through `route_execution_failure` on an approved, executing WorkOrder: `USER_ATTENTION_REQUIRED`, `AGENT_UNAVAILABLE`, no new attempt |
| `invalid-request-refused-without-retry` r2 | Same | Same as above |
| `rate-limited-not-retried-without-policy` r1 (new, regression) | — | HTTP 429 with no retry policy: one request, attention raised; counterpart to the retry capability case |

Seeded defects caught: input binding that drops an enum input (call arguments
differ), and a routing step that never raises attention.

Remaining limits: `missing-audit-evidence-refused` is still a synthetic gate
contract test; the four capability cases that need control-owned routing,
dispatch, fallback and retry still wait for those entry points. Treg events in
`run_treg_cli` trials are appended after the run (the fake runs in its own
process), so they keep call order but are not interleaved with Jev events.

## Rollback

EVAL-01 PRs 2–4 only add `src/cloudeo/evaluation/`, `tests/test_evaluation.py`,
docs, and expected-skip entries; PR 3b also moved the fake HarnessRouter out of
two test files. Reverting their merge commits restores the previous state; no
runtime code, schema or stored operational data depends on them. Trial
directories written by the runner are outside the repository and can be
deleted.

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
