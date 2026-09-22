# Cloudeo Progress and Evidence

## v0.1.0 — Initial control loop

Implemented:

- FastAPI application
- local WSL execution
- SQLite run persistence
- mock Jev adapter
- mock Treg adapter
- OpenRouter Jev adapter
- local Treg CLI adapter
- route threshold
- verification threshold
- bounded retries
- escalation status

Initial mock test:

```text
status: passed
selected_tool: hunter
route_confidence: 0.94
verification_probability: 0.93
```

Audit history was persisted successfully through `GET /v1/runs`.

---

## First real Jev test

Configuration:

```text
Jev: real OpenRouter
Treg: mock
```

Observed:

```text
hunter:   0.95
tomba:    0.04
escalate: 0.01
```

Jev correctly rejected mock provider output:

```text
verification_probability: 0.02
```

Result:

```text
status: escalate
```

This proved real Jev routing and verification worked.

---

## Treg local integration

Local repository:

```text
/home/robert/treg
```

Treg CLI authenticated successfully against:

```text
https://treg.to
```

Observed account:

```text
logged_in: true
active_org: rokoroko
```

Initial Treg promotional balance:

```text
$1.00
```

---

## Real provider metadata

TryKitt:

```text
endpoint: trykitt.people.email.find
method: POST
price: $0.005/success
observed works: 100%
observed hit rate: 38%
observed latency: ~3.8 s
```

Required JSON body:

```json
{
  "fullName": "...",
  "domain": "...",
  "realtime": true
}
```

Tomba:

```text
endpoint: tomba.people.email.find
method: GET
price: $0.0089/success
observed works: 100%
observed hit rate: 29%
observed latency: ~6.3 s
```

Required query fields include:

```text
domain
full_name
```

---

## v0.1 adapter upgrade

Added Treg request support for:

- HTTP method
- query parameters
- JSON body

Tests remained green.

---

## First real dry run

Jev routing:

```text
trykitt:   0.97
tomba:     0.02
escalate:  0.01
route confidence: 0.96
```

Generated TryKitt command:

```text
uv run --project /home/robert/treg treg call
trykitt.people.email.find
--method POST
--data '{"fullName":"Erol Toker","domain":"trykitt.ai","realtime":true}'
```

Generated Tomba command:

```text
uv run --project /home/robert/treg treg call
tomba.people.email.find
--query domain=trykitt.ai
--query 'full_name=Erol Toker'
```

Dry-run output was intentionally rejected by Jev.

---

## First real paid provider execution

Jev selected:

```text
TryKitt = 0.97
```

TryKitt returned:

```json
{
  "fullName": "Erol Toker",
  "domain": "trykitt.ai",
  "email": "erol@trykitt.ai",
  "validIdentity": true,
  "validSMTP": true,
  "validity": "valid"
}
```

Initial Jev verification:

```text
0.81
```

Configured threshold:

```text
0.85
```

Result therefore retried Tomba.

Tomba returned:

```text
provider_capacity_unavailable
```

Final v0.1 result:

```text
status: escalate
```

Treg ledger confirmed:

```text
TryKitt charged: $0.005
Tomba charged: $0.000
remaining promotional balance: $0.995
```

---

## v0.1.1 — Deterministic validator layer

Added deterministic validation for verified work email.

Checks:

```text
email exists
domain matches
identity signal
name match
SMTP validation
validity / verification status
```

Added outputs:

```text
deterministic_status
deterministic_evidence
verification_source
```

Test suite:

```text
4 passed
```

---

## First successful v0.1.1 real run

Jev routing:

```text
trykitt:   0.97
tomba:     0.02
escalate:  0.01
route confidence: 0.96
```

TryKitt output:

```text
email: erol@trykitt.ai
validIdentity: true
validSMTP: true
validity: valid
```

Deterministic evidence:

```text
Email returned: erol@trykitt.ai
Email domain matches expected domain trykitt.ai.
Provider reported validIdentity=true.
Returned person matches Erol Toker.
Provider reported validSMTP=true.
Provider reported valid email status.
```

Outcome:

```text
status: passed
selected_tool: trykitt
deterministic_status: pass
verification_source: deterministic
verification_probability: 1.0
```

No Jev verification call was required after execution.

No Tomba fallback was required.

This is the first fully successful real Cloudeo run.


---

## v0.1.2.1 — Automatic discovery correction

Observed: full objective with person/domain literals produced 0 Treg matches; `work email` produced 55 matches and exposed `people.email.find`. v0.1.2.1 separates capability discovery text from runtime execution state and uses routed rows as capability anchors.

---

## v0.1.2.2 — Hardening

Added clean capability-query generation, terminal dry-run semantics, structured discovery evidence, and per-attempt execution economics. See `docs/08_V0122_HARDENING.md`.


---

## 2026-09-22 — v2 execution foundation

Implemented an internal asynchronous `ExecutionBackend` contract and
`TregExecutionBackend`. The controller accepts an optional backend and uses it
for normal execution and dry-run preparation. Existing callers default to the
Treg wrapper; discovery remains on the existing Treg client.

`UHPExecutionBackend` is not implemented yet. No HarnessRouter, LongHorizon,
Performance Memory, new dependency, configuration, API schema, or database
schema was introduced. Routing and verification remain unchanged.

Validation:

- `UV_NO_SYNC=1 UV_OFFLINE=1 uv run pytest -q`: **33 passed** (15 existing tests
  unchanged, 18 new execution-boundary regression cases).
- Ruff checks pass for the new execution package and test files.
- Compared the baseline controller at `c4db48d` with the refactor through an
  in-memory SQLite/mock HTTP harness: success, dry run, no candidates, provider
  failure, and dry-run failure. HTTP responses, history, persisted request/result
  JSON, and SQLite schema matched after normalizing UUIDs/timestamps. Dry-run
  failure still returns HTTP 502. No external service was called.
- External behavior remains unchanged for the tested paths; existing public
  models, API wiring, adapters, validators, configuration, and database code
  are unchanged.

Known legacy limitations deliberately preserved: shared/stale execution economics,
duplicate candidate ranking, and unknown Jev choice lookup in dry-run. These
remain separately scoped work, not fixes bundled into the extraction.


---

## 2026-09-22 — UHP client foundation (standalone)

Added an internal `cloudeo.uhp` package (`client.py`, `models.py`) built on the
existing `httpx`/`pydantic` dependencies. It is not wired into the controller:
`Controller.run()`, `TregExecutionBackend`, `ToolCandidate`, Jev routing,
verification, `RunRequest`/`RunResponse`, configuration, and the database schema
are unchanged. The v0.1 path remains Objective → Jev → Treg → verification →
SQLite.

Protocol source: UHP `2026-09-12`, checked against the machine-readable
`protocol/schema/uhp-2026-09-12.schema.json` and OpenAPI file in
HarnessRouter/harnessrouter at `v0.23.7` (`809392d602e34e36f0468943035c54d3350af885`).
Every request sends `UHP-Version: 2026-09-12`; a successful response whose
`UHP-Version` header is missing or different is rejected as a protocol error.

Validation:

- `uv run pytest -q`: **67 passed** (33 existing unchanged, 34 new mock-transport
  UHP cases in `tests/test_uhp_client.py`). No Docker or network required.
- Ruff checks pass for the new package, tests, and `dev/uhp_smoke.py`.

HarnessRouter CE local development instance (`dev/harnessrouter.compose.yaml`):

- Image `harnessrouter/harnessrouter@sha256:d8794a4cbaaac8920548b2e1474e84d9c54e754119f700d2817765ec89837ced`
  (Docker Hub tag `0.23.7`; source tag `v0.23.7` = commit `809392d`).
- Bound to `127.0.0.1:18810` only; named volume `cloudeo-harnessrouter-dev-data`
  at `/data`; `restart: "no"`; backends `codex,claude` with Codex `0.154.0` and
  Claude Code `2.1.280` pinned. Runs under Docker Desktop on the Windows host and
  is reachable from WSL at the same loopback address.

Live discovery through `UHPClient` (`GET /v1/uhp`, unauthenticated):

- Implementation: HarnessRouter Community Edition `0.23.7`.
- Versions `2026-09-12`, `2026-08-11`; default `2026-09-12`; conformance class
  `full`; response header `UHP-Version: 2026-09-12`.
- Capabilities all `true`: streaming, sessions, cancellation, files_input,
  files_output, session_listing, harness_management, session_sharing,
  idempotency, plugins.

Not yet proven: `GET /v1/harnesses` returns HTTP 401 without a HarnessRouter API
key. The CE body is `{"detail":"sign in to continue"}` with no UHP error
envelope and no `UHP-Version` header (the client preserved it as `http_error`
with `protocol_version=None`). Harness/model discovery, a live task, and the
two-harness proof are blocked on a Console-created API key and provider
credentials for Codex and Claude Code. No live task has been run.


---

## 2026-09-23 — UHP live execution evidence

Operator-run smoke with `dev/uhp_smoke.py` against the local HarnessRouter CE
`0.23.7` instance (`http://127.0.0.1:18810/api/harness`), UHP `2026-09-12`,
using a Console-created HarnessRouter API key held only in the operator's shell.
No key or provider credential is recorded here or in Git. This supersedes the
"Not yet proven" note in the previous entry.

| Check | Result |
| --- | --- |
| Authenticated discovery (`/v1/harnesses`, harness models) | **PASS** |
| Claude Code live task | **PASS** (runtime `completed`) |
| Codex live task | **BLOCKED_EXTERNAL** (OpenAI provider quota) |

Claude Code live task (`Reply with exactly: CLOUDEO_UHP_OK`, new session):

- Harness `chrn_56a17d779ea643e9b2924aaa1e86e175` (`Cloudeo-claude`, base
  `claude-code`); model `claude-opus-5`.
- Status `completed`; output `CLOUDEO_UHP_OK`.
- Response `resp_c44edf543ff64daeb0d119c8c6f64ca8`; session
  `hsess9f7d54617d284c8d89a64886e1371b92`.
- Response `UHP-Version: 2026-09-12`; client-measured duration 5.21 s.
- `actual_harness: null` — HarnessRouter did not echo `metadata.harness_id` on
  the response. This is observed server metadata behavior; Cloudeo must record
  the requested harness and must not infer an actual one.

`completed` is runtime completion only. It is execution evidence, not Cloudeo
verified success, and nothing was written to Performance Memory (which does not
exist yet).

Codex live task:

- Harness `chrn_bdbb7e0349a14734a2bdc7d57ba81f22` (`Cloudeo - OpenAI`, base
  `codex`); model `gpt-5.5`.
- The UHP task created a real Codex session and rollout, then failed with
  `Reconnecting... 1/5`.
- A direct OpenAI Responses API request with the same OpenAI account returned
  `type: insufficient_quota`, `code: credit_balance_exhausted`,
  `message: You have no credits remaining.`
- Classification: **BLOCKED_EXTERNAL / provider quota**. This is not a Cloudeo,
  UHP client, HarnessRouter, or Codex implementation failure. Paid OpenAI
  requests are not retried until credit is restored.

Two-harness proof status: one harness (Claude Code) proven end to end; the
Codex path reaches the runtime but is blocked by the provider account.


---

## 2026-09-23 — Execution contracts (types, mappings, dispatch)

Branch `feat/execution-contracts`, from `main` at `e938442`. Scope is limited to
types, mappers, and dispatch. `Controller.run()` does not use them, and it still
calls the legacy `ExecutionBackend`/`TregExecutionBackend`, which are unchanged
apart from naming the existing `TREG_ERROR:` marker as a constant.

Implemented (`src/cloudeo/execution/`):

- `contracts.py`: `ExecutionRequest` =
  `DirectToolExecution` (`candidate: ToolCandidate`, `dry_run`) |
  `HarnessTaskExecution` (`task: UHPTaskRequest`, must name `harness_id`),
  discriminated on `kind`. `ExecutionOutcome` carries status, `output_text`,
  `raw_output`, `ExecutionCost`, `duration_ms`, `ExecutionError`, `artifacts`,
  `RuntimeIdentity`, and `native_result`.
- `treg_backend.py`: `outcome_from_treg` and `TregDirectToolBackend`.
- `uhp_backend.py`: `outcome_from_uhp`, `outcome_from_uhp_error`, and
  `UHPHarnessTaskBackend`.
- `dispatch.py`: `ExecutionDispatcher`, which matches on request type only.

Semantics preserved:

- Execution status covers runtime state only: `in_progress`, `completed`,
  `failed`, `incomplete`, `cancelled`, `dry_run`, `unknown`. There are no
  verification states.
- Treg: `TREG_ERROR:` output is kept verbatim as `output_text`, so existing
  validators still fail it. A normal-run error maps to `failed`. A dry run maps
  to `dry_run`, and dry-run preparation errors still propagate. Legacy economics
  are passed through unchanged, including values a failed attempt retains from
  an earlier call.
- UHP: all five response statuses map one-to-one. Partial output and unknown
  output item types are kept. `actual_harness` stays None unless echoed.
  Requested and actual model stay separate. Token usage is never converted to
  money. For request-level failures, only an HTTP 4xx rejection other than 408
  maps to `failed`. HTTP 408, 5xx, other HTTP statuses, transport failures, and
  protocol failures map to `unknown`, never `cancelled`, because the task may
  have been accepted. There are no retries.
- `native_result` is the backend's own `ExecutionResult` or `UHPTaskResult`
  object.
- The dispatcher never selects a harness, a model, or a backend class. A missing
  backend raises `ExecutionBackendUnavailable` and is never substituted.

Validation:

- `UV_NO_SYNC=1 UV_OFFLINE=1 uv run pytest -q`: **116 passed** (67 existing
  unchanged, 49 new in `tests/test_execution_contracts.py`, including one case
  per HTTP status for 400, 401, 404, 409, 422, 429, 408, 500, 502, 503, 504, and
  307). No network calls; UHP paths use `httpx.MockTransport`.
- Review hardening before merge: every `UHPHTTPError` had mapped to `failed`,
  which overstated what Cloudeo knows after a 5xx or 408. The rule above
  replaced it.
- A test found that Pydantic's smart-mode union coerced a legacy economics dict
  into `ExecutionEconomics`, dropping unknown keys. The field now uses
  left-to-right union mode, and tests assert the dict is kept.
- Ruff checks pass for the new and changed files.

No live provider verification was performed in this milestone.


---

## 2026-09-23 — Execution dispatch adoption (Treg path only)

Branch `feat/execution-dispatch-adoption`, from `main` at `10d4b71`. This is a
plumbing migration. External behavior is intended to be unchanged, and the
golden characterization below checks that. No provider or live verification
was performed; every test is offline.

Execution flow before:

```text
Controller.run()
  -> self.execution_backend.execute(candidate, dry_run)   # TregExecutionBackend
  -> ExecutionResult(output, economics)
  -> validate_tool_output(output) -> Jev fallback -> AttemptResult / RunResponse
```

Execution flow after (both the dry-run and attempt-loop call sites):

```text
Controller.run()
  -> Controller._execute_direct_tool(candidate, dry_run)
  -> ExecutionDispatcher.execute(DirectToolExecution(candidate, dry_run))
  -> TregDirectToolBackend -> TregExecutionBackend -> TregClient
  -> ExecutionOutcome
  -> (outcome.output_text, outcome.cost.direct_tool_economics)
  -> validate_tool_output(output) -> Jev fallback -> AttemptResult / RunResponse
```

Constructor: `Controller(settings, jev, treg, database)` is unchanged and builds
a Treg-only dispatcher with no harness-task backend. `execution_backend=` still
accepts a legacy Treg-shaped backend; it is adapted through
`LegacyDirectToolBackend`, not bypassed. New optional `execution_dispatcher=`
injects a dispatcher; passing both raises `ValueError`. The internal
`Controller.execution_backend` attribute is replaced by `execution_dispatcher`;
no caller read it. `api/app.py` is unchanged.

Semantics deliberately preserved:

- Validators receive exactly the text the legacy path produced. `outcome.status`
  is not consulted by the controller, so the validators' `TREG_ERROR:` prefix
  check remains the only interpretation rule.
- Dry-run preparation errors propagate as the same exception object, and the API
  still maps them to HTTP 502.
- Candidate order, attempt limit, and the legacy duplicate ranking are unchanged.
- Legacy economics pass through as-is, including values a failed attempt retains
  from an earlier call (not fixed).
- The unknown-choice dry-run `KeyError` is unchanged.
- Verification, the RunResponse/AttemptResult shapes, persistence, and the API are
  unchanged. `ExecutionOutcome` is internal and not exposed.

Validation:

- Golden characterization: `tests/fixtures/controller_golden_v0122.json` was
  captured from the unmodified controller at `10d4b71` (10 controller scenarios
  and 4 `POST /v1/runs` cases). It records normalized responses, persisted
  rows, Treg call order with dry-run flags, exact validator inputs, and Jev
  verification inputs. The migrated controller reproduces it exactly.
- `UV_NO_SYNC=1 UV_OFFLINE=1 uv run pytest -q`: **142 passed** (116 existing
  unchanged, 15 in `tests/test_controller_characterization.py`, 11 in
  `tests/test_dispatch_adoption.py`). The latter prove the controller sends
  `DirectToolExecution` requests in legacy order with the same candidate
  objects, that the default dispatcher refuses harness tasks, and that a Treg
  run makes no network call and never constructs a UHP client.
- Ruff passes for the changed execution module and new tests. `controller.py`
  keeps its pre-existing ISC004 finding and was not reformatted, to keep the
  diff to the migration itself.

UHP remains outside `Controller.run()`.


---

## 2026-09-23 — Workspace Broker foundation

Branch `feat/workspace-broker-foundation`, from `main` at `c3e8d93`. It adds
`src/cloudeo/workspace/` (`models.py`, `broker.py`, `git.py`) and ADR-015.
`Controller.run()`, the dispatcher, the execution contracts, the UHP client, the
API, and the database are unchanged. No LongHorizon, verification policy,
Performance Memory, remote Git, or automatic promotion was added.

Central invariant: an executor may produce a candidate state; only a separate
`promote` call changes the canonical accepted state.

Implemented:

- Types: `CanonicalWorkspaceState`, `CandidateWorkspace` (its `local_path` is
  local and internal only), `WorkspaceCheckpoint`, `CandidateInspection`,
  `PromotionResult`, `RejectionRecord`, plus typed errors
  (`StaleCandidateError`, `ForeignCheckpointError`, `NothingToCheckpointError`,
  `CandidateStateError`, `WorkspaceConflictError`).
- `WorkspaceBroker` protocol: `accepted_state`, `create_candidate`,
  `inspect_candidate`, `checkpoint_candidate`, `promote`, `reject`, `cleanup`.
- `GitWorkspaceBroker`: all state is kept in Git refs under
  `refs/cloudeo/workspaces/<id>/`, with no database. Candidates are detached
  worktrees at the accepted commit. A checkpoint commits the candidate's changes
  as the broker identity, or captures descendant commits the executor made.
  Promotion is one atomic `update-ref --stdin` transaction: a compare-and-swap
  fast-forward of the accepted ref, creation of the `promoted` marker, and
  verification that no `rejected` marker exists. Rejection is one transaction
  too, and keeps the rejected commit reachable. Candidate worktree creation and
  broker checkpoint commits run no repository hooks, using command-scoped
  settings only. Checkpoint commits also ignore signing configuration. A failed
  `git worktree add` rolls back the candidate's `base` ref. `cleanup` removes
  only the worktree and refuses to drop uncheckpointed changes unless
  `discard=True`.

Validation:

- `UV_NO_SYNC=1 UV_OFFLINE=1 uv run pytest -q`: **193 passed** (142 existing
  unchanged, 51 in `tests/test_workspace_broker.py`). Tests use temporary
  repositories with isolated Git config and no remote.
- Hook isolation for candidate creation (3 of the 51):
  - a `post-checkout` hook that writes a marker and exits 1 does not run
    during `create_candidate()`. The candidate still starts at the accepted
    commit, with its `base` ref and a detached worktree;
  - the same hook still runs for an ordinary `git worktree add`, proving the
    repository was not reconfigured;
  - a repository-configured `core.hooksPath` is overridden for the broker
    command only and is still set afterwards; the local config is identical;
  - rollback on a failed `worktree add` still works with the hook installed.

  With the `hooks_disabled` flag removed, the two hook-detection tests fail.
- State-integrity hardening (12 of the 48):
  - promotion updates `accepted` and `promoted` together;
  - a stale or failed promotion transaction changes no ref;
  - promote-after-reject and reject-after-promote transactions change nothing,
    even when the pre-checks are bypassed to force a race;
  - a threaded promote-vs-reject race, repeated for 8 rounds, never records
    both decisions;
  - rejection leaves accepted state and the canonical checkout unchanged;
  - `pre-commit`, `prepare-commit-msg`, `commit-msg`, and `post-commit` hooks do
    not run for broker checkpoints but still block an ordinary commit;
  - a local `commit.gpgSign=true` with a failing `gpg.program` does not affect
    broker checkpoints but blocks an ordinary commit;
  - the broker identity wins over the `GIT_AUTHOR_*` and `GIT_COMMITTER_*`
    environment variables;
  - a failed `worktree add` leaves no candidate ref, and leaves the blocking
    directory, other candidates, refs, and worktrees untouched.
- Covered: explicit accepted commit (not branch `HEAD`); idempotent,
  non-replacing initialization; exact candidate content; candidate edits and
  promotion leave the canonical checkout's HEAD, branch, files, and status
  unchanged; isolation between candidates; real descendant checkpoint commits;
  empty and repeated checkpoints refused; executor commits captured; rewritten
  history refused; promotion only on `promote`; stale candidates refused; a
  simulated concurrent move of accepted defeats promotion via compare-and-swap;
  commits made outside the broker, unrelated histories, other workspaces, and
  tampered candidate identities refused; rejection keeps accepted state and the
  rejected commit (also after cleanup); promote and reject decisions are final;
  dirty-state inspection and cleanup; only allowlisted local Git subcommands
  run.
- The test run created no `refs/cloudeo` refs or worktrees in the Cloudeo
  repository itself.

No live execution, harness, or provider verification was performed.


---

## 2026-09-23 — Test hygiene: mock-loop engine disposal

Merged `fix/test-mock-loop-dispose-engine` into `main` (`e552d7a`).
`tests/test_mock_loop.py` now disposes its aiosqlite engine. This removes a
`ResourceWarning` that already existed on main and was attributed to whichever
later test ran garbage collection. On the merged main: 193 passed, zero
`ResourceWarning`s across four runs, and a pass with `-W error::ResourceWarning`.
Test-only change.

---

## 2026-09-23 — LongHorizon AgentAdapter foundation

Branch `feat/longhorizon-adapter-foundation`, from `main` at `e552d7a`. It adds
the optional `cloudeo.longhorizon` package and ADR-016. `Controller.run()`, the
dispatcher, execution contracts, UHP client, Workspace Broker, API, and
database are unchanged. The LongHorizon manager loop is not run from Cloudeo.

Upstream pin:

- LongHorizon-Harness `v0.1.7`, commit
  `ff76d6a4c0a4f6d7dfeb2fc2adcf51ccb87a3b9a`, is installed through the
  `longhorizon` extra as a Git dependency on that commit. `uv.lock` adds only
  `lh-harness 0.1.7` from that commit; no other locked version changed.
- The PyPI `lh-harness==0.1.7` wheel and sdist match their PyPI hashes, and all
  source files are byte-identical to the commit. Both also contain three
  compiled web-UI files that are not in the source. The PyPI package is
  therefore not an exact match, and the Git pin is used instead.

Implemented:

- `HarnessExecutionProfile(harness_id, model, max_step=None)`: explicit and
  frozen.
- `UHPHarnessAgentAdapter(profile, dispatcher)`: implements LongHorizon's
  `AgentAdapter`. `run_episode()` sends one `HarnessTaskExecution` per episode
  (new session, no `previous_response_id`, `timeout_seconds` equal to the
  `EpisodeBudget`) through `ExecutionDispatcher`, and maps the outcome with
  `episode_result_from_outcome()`. `supports_workspace_sync = False`. The
  LongHorizon `Environment` is never called.
- The status mapping and metadata keys are as listed in ADR-016.

Validation:

- `UV_NO_SYNC=1 UV_OFFLINE=1 uv run pytest -q` with the `longhorizon` extra:
  **228 passed**, no skips (193 existing unchanged, 35 in
  `tests/test_longhorizon_adapter.py`).
- In an isolated environment without the extra: 193 passed, and the adapter
  module was skipped. No core module imports `lh_harness`, and importing the
  adapter raises a clear "requires the optional 'longhorizon' extra" error.
- Adapter tests use LongHorizon's real `AgentAdapter`, `Environment`,
  `EpisodeBudget`, and `EpisodeResult`, plus the real dispatcher,
  `UHPHarnessTaskBackend`, and `UHPClient` over a mocked HTTP transport. The
  real network transport is blocked, and the test Environment fails on any
  call.
- Covered: protocol conformance and matching signature; the
  `supports_workspace_sync` flag; exact profile and fresh-session request
  payloads; exactly one dispatched request per episode; every status mapping,
  including budget and non-budget `incomplete`, `unknown` after a transport
  timeout and after a 503, and `in_progress` within and after the episode
  budget; `unknown` and `in_progress` never `cancelled`; complete metadata for
  every runtime state; `actual_harness=None` kept; echoed harness and model
  fallback kept separate; usage, protocol, and response and session IDs;
  diagnostic-only marking when there is no text output; rejection of dry-run
  and direct-tool outcomes; explicit profile validation.
- Ruff passes for the new package and tests.

No live harness, provider, or HarnessRouter calls were made.
