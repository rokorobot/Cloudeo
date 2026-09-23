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


---

## 2026-09-23 — UHP Workspace Bridge foundation

Branch `feat/uhp-workspace-bridge-foundation`, from `main` at `a4030b7`. It adds
`src/cloudeo/bridge/` and standard UHP file operations on `UHPClient`, and
ADR-017. `Controller.run()`, the Workspace Broker, the execution contracts,
the dispatcher, the LongHorizon adapter (still `supports_workspace_sync =
False`), the API, and the database are unchanged. No LongHorizon role binding,
routing, verification, automatic checkpoint, or automatic promotion was added.

Protocol facts were verified in UHP `2026-09-12` and HarnessRouter
`809392d602e34e36f0468943035c54d3350af885` before implementation (ADR-017).
Key finding: HarnessRouter's session listing and archive hide dotfiles and
several directories, so they are not authoritative project state.

Implemented:

- `UHPClient.upload_file()` (multipart `POST /v1/files`),
  `list_session_files()`, and `download_container_file()` (streams raw bytes
  with an optional size cap and never decodes a successful body). New
  `UHPFile`, `UHPFileList`, and `UHPFileContent` types keep extra fields. The
  existing request path now shares header, error, and transport helpers, with
  unchanged behavior.
- `cloudeo.bridge`:
  - `remote_helper.py`: the uploaded stdlib helper (`unpack`, `pack-delta`).
  - `bundle.py`: Git-based selection, the deterministic input bundle,
    whole-bundle validation into staging, and planned delta application with
    rollback.
  - `bridge.py`: `UHPWorkspaceBridge.run(candidate, WorkspaceBridgeTask)`, one
    task through `ExecutionDispatcher`.
  - `models.py`: manifests, `BridgeLimits`, `WorkspaceBridgeResult`.

Validation (all offline):

- With the `longhorizon` extra: **355 passed** (228 existing unchanged, 105 in
  `tests/test_uhp_workspace_bridge.py`, 22 in `tests/test_uhp_files.py`).
  Without the extra: 319 passed, 2 skipped (the LongHorizon adapter module and
  one bridge test that needs it).
- The end-to-end tests use the real `GitWorkspaceBroker`,
  `CandidateWorkspace`, `ExecutionDispatcher`, `UHPHarnessTaskBackend`,
  `UHPClient`, and bridge helper (run as a subprocess). The fake HarnessRouter
  behind `httpx.MockTransport` writes input files into the session working
  directory and applies HarnessRouter's listing filter.
- Architectural acceptance test: accepted A → candidate → bridge round trip
  (modified text and binary, a new nested file, a deletion, a tracked dotfile,
  executable bits) → candidate dirty, accepted still A. Then
  `checkpoint_candidate()`, and accepted is still A. Only `promote()` advances
  it. The bridge's only broker call is `inspect_candidate`.
- The upload contains no `.git` entry and none of the ignored local files
  (`.env`, `*.log`). The helper upload is byte-identical to the packaged
  helper. Exactly one task request is sent: a fresh session with the explicit
  harness and model.
- Candidate unchanged, verified by a snapshot of every file and mode, the
  worktree `.git` file, HEADs, the canonical branch, and `refs/cloudeo`, for:
  `unknown`, `in_progress`, `failed`, `cancelled`, and `incomplete` without an
  artifact; a missing session ID; a listing failure; a missing, duplicate, or
  other-run artifact; a remote symlink; an oversized bundle; and 32 hostile
  bundles. Each hostile bundle is refused as `invalid_bundle` for its specific
  reason; the 32 include a mismatched `input_manifest_sha256` and a bare `.git`
  path. Staging is cleaned up.
- Direct validator tests cover file-count, per-file, total-size, and
  decompression-bomb limits.
- A disk failure mid-apply rolls back to the exact pre-application state. A
  failed rollback raises the original error with the rollback failure
  attached.

Bridge invariants added before merge (same branch):

- Candidate drift: seven local-change scenarios made while the remote episode
  runs each fail with `candidate_changed_during_execution`, and the candidate
  is exactly as the local change left it. The scenarios are: a modified,
  added, or deleted file; an executable-bit change; a local edit of a file the
  remote deleted; a newer local edit of a file the remote changed; and a local
  file created where the remote added one. Editing an ignored `.env` is not
  drift. Removing the drift check makes all seven fail.
- One UHP deployment: a dispatcher whose UHP backend uses a different
  `UHPClient`, a non-UHP harness backend, or no harness backend is refused at
  construction, before any request.
- Output cap: HarnessRouter's produced-file cap (`HARNESS_RESP_MAX_FILE_BYTES`,
  25 MiB) was verified in the pinned source, and input and output limits are
  20 MiB each. The helper enforces the output file-count, total-byte,
  per-file, and bundle limits carried in the input manifest, checking sizes
  with `lstat` before reading; a test shows an over-limit file is never
  opened. Each of `output_too_large`, `output_file_too_large`,
  `output_file_count_exceeded`, and `output_total_bytes_exceeded` makes the
  helper write an error artifact and exit 3. The sync fails with that code and
  nothing is applied, which each has an end-to-end test for. An oversized
  artifact produced without the helper fails as `invalid_bundle`.
- Remote unpack: a symlinked parent (at the root or nested) or a non-directory
  parent is refused before writing, and no file appears outside the
  workspace. Nested directories are still created normally.
- `apply_delta` handles only `Exception`, so `KeyboardInterrupt`,
  `SystemExit`, and cancellation are never turned into `apply_failed`.
- Determinism counterpart: toggling a file's executable bit (0600 to 0700)
  changes the manifest, the archive, and the manifest hash.
- Apply path safety runs before any Git ignore query; a test fails if
  `check-ignore` is reached for an unsafe path. The symlinked-`src` drift test
  asserts the exact, deterministic error message.
- HarnessRouter bootstrap docs: pinned `runner/server.py::_write_agent_doc()`
  writes `AGENTS.md`, `CLAUDE.md`, `QWEN.md`, or `GEMINI.md` (marked
  `<!-- harness-skills:begin -->`) after the input files and before the
  harness starts. `unpack` now reconciles those four root docs before writing
  the snapshot; they are not excluded project paths (ADR-017). The fake
  HarnessRouter reproduces that order, with a Claude-style `CLAUDE.md` by
  default, so every end-to-end test runs under real bootstrap conditions.
  - A: a bootstrap `CLAUDE.md` is removed at unpack and never imported.
  - B, C: a tracked `CLAUDE.md` or `AGENTS.md` (including an executable one)
    replaces the bootstrap copy with exact bytes and mode, and an unchanged
    doc produces no delta.
  - D: an agent edit to a tracked `AGENTS.md` syncs as changed.
  - E: a new `AGENTS.md` created by the agent after the bootstrap copy was
    removed syncs as added, without the marker.
  - F: an unmarked, unknown `AGENTS.md` fails the unpack closed and is left in
    place.
  - G: a symlinked `CLAUDE.md` fails the unpack, and its target is untouched.
  - Helper-level tests cover remove, replace (with executable bit),
    identical, unknown, different, and directory cases for all four names, and
    confirm the names are neither excluded nor refused by output validation.
  - With reconciliation disabled, 15 tests fail. They include the main
    round-trip test, which shows the generated `CLAUDE.md` leaking into the
    candidate, and B/C/D, which show a tracked doc refused at unpack.
- Determinism: after changing file mtimes and permission bits (0600 and 0700),
  a rebuilt input bundle is byte-identical with the same manifest hash. Member
  order, uid/gid, user and group names, mtimes, 0644/0755 modes, and the gzip
  header (no filename, mtime 0) are asserted.
- Identity: the delta must echo `input_manifest_sha256`. Removing that check
  makes its test fail.
- Local path safety: a symlinked `src` directory swapped in during the run is
  caught as drift, and the outside target is untouched. With the drift check
  bypassed, apply still refuses a path through a local symlink as
  `unsafe_local_path` before any mutation. `.git`, `.git/...`, and `.GIT/...`
  are refused.
- Runtime gating: `incomplete` with a valid delta syncs and stays
  `incomplete`. `failed` and `cancelled` are skipped without reading the
  remote workspace, even when an artifact exists.
- UHP file operations: the multipart upload carries `UHP-Version`,
  authorization, filename, content type, and `purpose`; typed parsing keeps
  extra fields; downloads return exact bytes, including JSON-looking and
  non-UTF-8 content; a missing or wrong `UHP-Version` is rejected; structured
  413 and 404 errors are kept; size caps are enforced while streaming; there
  are no retries.
- The helper is checked to parse as Python 3.8 and to import only the
  standard library.

No live provider, harness, or HarnessRouter calls were made.


---

## 2026-09-23 — LongHorizon workspace executor

Branch `feat/longhorizon-workspace-executor`, from `main` at `d78f1b5`. It adds
`UHPWorkspaceExecutorAdapter`, the fail-closed role-eligibility layer, and
ADR-018. These are unchanged: `Controller.run()`, the Workspace Broker, the
bridge, the UHP client, the dispatcher, the execution contracts, the API, the
database, and `UHPHarnessAgentAdapter` (still `supports_workspace_sync =
False`). LongHorizon itself is not patched, and its manager loop is not run
from Cloudeo. No auditor, checkpoint, promotion, or rejection step was added.

Implemented:

- `src/cloudeo/longhorizon/workspace_executor.py`:
  `UHPWorkspaceExecutorAdapter(profile, bridge, candidate, *, clock)`.
  - It checks the candidate before each episode.
  - It runs one bridge task per episode in a fresh session.
  - Result mapping and metadata follow ADR-018: `completed` without a synced
    workspace is `error` with `workspace_sync_failed`.
  - `supports_workspace_sync = True`. Construction with a non-syncing bridge is
    refused.
- `src/cloudeo/longhorizon/roles.py`: `LONGHORIZON_ROLES`,
  `MANAGER_ROLE_KEYWORDS`, the exact-type `ROLE_ELIGIBILITY` table,
  `eligible_roles()`, `require_role_eligible()`, and
  `bind_longhorizon_roles()`.
- The test fake HarnessRouter (`tests/test_uhp_workspace_bridge.py`) gained
  `response_overrides`, a new session and workspace for each task after the
  first, and an `input_manifest()` that reads the latest upload. These changes
  are backward compatible: the 105 bridge tests are unchanged and pass.

Validation (all offline):

- With the `longhorizon` extra: **386 passed** (355 existing unchanged, 31 in
  `tests/test_longhorizon_workspace_executor.py`). Without the extra: 319
  passed and 3 skipped (the two LongHorizon modules and one bridge test).
- Focused suites: LongHorizon adapter 35, bridge 105, UHP client and files 56,
  Workspace Broker 51.
- The tests use the real `GitWorkspaceBroker`, `CandidateWorkspace`,
  `UHPWorkspaceBridge`, `UHPClient`, `ExecutionDispatcher`,
  `UHPHarnessTaskBackend`, and LongHorizon's `AgentAdapter`, `Environment`,
  `EpisodeBudget`, and `EpisodeResult`, with the offline fake HarnessRouter.
- Test names are in `tests/test_longhorizon_workspace_executor.py`; the
  numbers in brackets count parametrized cases.
- `test_a_executor_changes_candidate_but_never_accepted_state` [1]: accepted A
  → one executor episode → the candidate is modified, added, and deleted, and
  is dirty. Afterwards:
  - accepted state and the candidate `HEAD` are both still A;
  - there are no checkpoint refs and no promoted or rejected markers;
  - `independently_verified` is false.
- `test_executor_uses_only_read_only_broker_calls` [1]: a spy broker records
  that the only calls are `inspect_candidate` and `accepted_state`.
- `test_b_completed_without_sync_is_error` [2]: `completed` with
  `output_artifact_missing` or `missing_session_id` gives `error` with
  `workspace_sync_failed: <code>`, and the candidate is unchanged.
- `test_c_unknown_runtime` [1]: a transport timeout gives `unknown` → `error`
  with `runtime_state_unobserved`. The sync is skipped and the candidate is
  unchanged.
- `test_d_e_f_non_completed_runtime` [3]: `failed` → `error`, `cancelled` →
  `cancelled`, `in_progress` → `error` with `runtime_state_unobserved`. The
  sync is skipped and the candidate is unchanged.
- `test_g_incomplete_keeps_budget_mapping_and_records_partial_sync` [2]: a
  valid partial delta syncs, with `max_steps` → `timeout` and `interrupted` →
  `error`.
- `test_h_candidate_drift_is_not_done_and_local_edit_survives` [1]: gives
  `error` with `workspace_sync_failed: candidate_changed_during_execution`.
- `test_i_profile_budget_and_fresh_session_per_episode` [1]: the profile's
  harness, model, step limit, and per-episode budget timeouts are sent. Two
  episodes use two distinct sessions with no `previous_response_id`, and the
  second returns only its own delta.
- `test_j_metadata_keeps_runtime_evidence_and_adds_workspace_evidence` [1].
- `test_k_capability_flags` [1] and `test_executor_conforms_to_agent_adapter`
  [1]: the executor is `True`, and the base adapter is still `False`.
- `test_l_role_eligibility_matrix` [7]: every role against both adapters.
- `test_role_eligibility_fails_closed_for_unknowns` [1]: a subclass, an unknown
  object, the unknown roles `agent` and `auditor`, and a mixed binding set are
  all refused.
- `test_role_keywords_match_pinned_manager` [1]: the role keywords match the
  signature of the pinned manager's `_run_impl`.
- `test_m_n_environment_untouched_and_no_trajectory_fabricated` [1].
- Candidate checks, public broker API only; each returns `error` with no
  HarnessRouter request:
  - `test_stale_candidate_is_an_executor_error_without_remote_calls` [1]:
    another candidate was promoted, and the candidate is byte-for-byte
    unchanged.
  - `test_candidate_whose_base_moved_by_its_own_promotion_is_stale` [1]:
    caught only as staleness, not recognized as promoted.
  - `test_cleaned_up_candidate_is_an_executor_error` [1]: the candidate is not
    recreated.
  - `test_foreign_candidate_is_an_executor_error` [1].
  - `test_unsendable_candidate_is_an_executor_error` [1]: a symlink.
  - `test_executor_requires_a_workspace_capable_bridge` [1].
- The adapter source contains no call to `create_candidate()`,
  `checkpoint_candidate()`, `promote()`, `reject()`, `cleanup()`, private broker
  methods, broker refs, or the Environment.
- Mutation checks:
  - Removing the completed+unsynced → `error` rule fails 3 tests (B ×2, H).
  - Removing the staleness check fails the 2 staleness tests.
- Ruff passes.

Known limitations (ADR-018):

- The public WorkspaceBroker protocol exposes no terminal lifecycle state, so
  the adapter cannot distinguish an open candidate from a promoted or rejected
  one. Lifecycle ownership must be enforced by future orchestration or by a
  public broker lifecycle query.
- The LongHorizon executor prompt may name `config.workspace_path` while
  execution happens in a fresh remote session workspace. Safety inside the full
  `manager.run()` flow is unproven, and is a prerequisite test for the
  role-binding milestone. `manager.run()` compatibility is not claimed.

No live provider, harness, or HarnessRouter calls were made.


---

## 2026-09-23 — Independent LongHorizon workspace auditor

Branch `feat/longhorizon-workspace-auditor`, from `main` at `f3a71cb`. It adds
`cloudeo.bridge.audit` (`WorkspaceAuditSnapshot`,
`UHPWorkspaceAuditTransport`, `WorkspaceAuditResult`, `snapshot_content_sha256`),
`cloudeo.longhorizon.workspace_auditor` (`UHPWorkspaceAuditorAdapter`), the
`cli_auditor` row of the role table, and ADR-019.

`UHPWorkspaceBridge` gained two shared module functions
(`fetch_output_artifact`, `require_single_deployment`). Its behavior, codes,
and messages are unchanged. These are unchanged:

- the Workspace Broker;
- the base adapter (still `supports_workspace_sync = False`);
- the workspace executor;
- the dispatcher and contracts, and `Controller.run()`;
- the API, database, config, and dependencies.

No checkpoint, promotion, rejection, manager-loop, GUI, routing, or
verification-gate code was added.

The source findings for pinned LongHorizon `ff76d6a…` are recorded in ADR-019.
Two of them matter for later milestones:

- **Format repair:** `manager.run()` rebuilds a format-repaired result with the
  primary metadata, so a UHP adapter's `assistant_visible_output` hides the
  repaired text. This fails closed as `blocked`.
- **Run abort:** an auditor `error` is classified as a provider failure and
  aborts the whole pinned manager run.

Validation (all offline):

- With the `longhorizon` extra: **429 passed** (386 existing unchanged, 43 in
  `tests/test_longhorizon_workspace_auditor.py`). Without the extra: 319 passed
  and 4 skipped (the three LongHorizon modules and one bridge test).
- Focused suites: workspace executor 31, LongHorizon adapter 35, bridge 105
  (the fake HarnessRouter gained per-task response overrides; no bridge test
  changed), UHP client and files 56, Workspace Broker 51.
- The tests use the real `GitWorkspaceBroker`, `CandidateWorkspace`,
  `UHPWorkspaceBridge`, `UHPWorkspaceAuditTransport`, `UHPClient`,
  `ExecutionDispatcher`, `UHPHarnessTaskBackend`, and bridge helper (run as a
  subprocess). They also use LongHorizon's real `AgentAdapter`, `Environment`,
  `EpisodeBudget`, `EpisodeResult`, `build_role_auditor_prompt()` (with
  `workspace_path="/workspace"`), `audit_report_from_episode_result()`,
  `auditor_report_text_from_episode_result()`, `parse_audit_report()`, and
  `manager._should_repair_auditor_format()`.

Tests in `tests/test_longhorizon_workspace_auditor.py` (the numbers in
brackets are parametrized cases):

- `test_a_to_i_executor_then_independent_read_only_audit` [1]:
  - The executor makes candidate A′.
  - The auditor gets a fresh session and remote workspace. It sees exactly A′,
    with HarnessRouter's bootstrap `CLAUDE.md` removed, and makes no changes.
    The result is `done`.
  - The candidate is byte-for-byte A′ (files, modes, `.git` file, HEADs,
    canonical branch, `refs/cloudeo`), accepted is still A, and there is no
    checkpoint or promoted/rejected marker.
  - The executor and auditor session IDs, response IDs, and workspaces all
    differ. There is no `previous_response_id`, and the auditor's own harness,
    model, `max_step`, and budget are used.
  - The recorded manifest hash equals the hash of the uploaded manifest bytes.
  - The three-line report is preserved verbatim and parses as `complete /
    clean / aligned` through both LongHorizon parsers. Nothing is promoted.
- `test_auditor_uses_only_read_only_broker_calls` [1]: a spy records exactly
  `inspect_candidate` and `accepted_state`.
- `test_audit_snapshot_content_identity_for_the_next_gate` [1]:
  - Recomputing the content hash with another run ID gives the same content
    hash, but not the same manifest hash.
  - A later edit changes the content hash.
- `test_j_malformed_report_is_left_to_longhorizon` [1]: the result is `done`,
  the text is unchanged, LongHorizon's repair predicate is true, and the report
  parses as `blocked / suspect / unknown`.
- `test_j_source_finding_repaired_text_loses_to_primary_visible_output` [1]:
  documents the upstream repair quirk (fails closed).
- `test_k_to_n_remote_auditor_mutation_is_detected` [4]: an added, modified,
  or deleted file, or an executable-bit change.
  - The result is `error` with `auditor_workspace_mutation_detected`, and the
    exact paths are recorded (a mode-only change is listed under
    `mode_changed`).
  - The native `verifier_workspace_*` keys are set, and the report text is
    moved to `untrusted_auditor_output`.
  - LongHorizon reports `blocked`, noting the auditor write.
  - The candidate is unchanged.
- `test_o_missing_evidence_is_error` [2]: a missing artifact, or no session ID.
- `test_p_invalid_evidence_bundle_is_error` [2]: a garbage bundle, or a bundle
  built from another snapshot (`input_manifest_sha256`). Each gives
  `invalid_bundle`, the candidate is unchanged, and staging is empty.
- `test_q_to_t_local_drift_invalidates_audit` [4]: a local file modified,
  added, deleted, or with its executable bit changed during the audit. Each
  gives `candidate_changed_during_audit`, and the local change is kept (no
  merge).
- `test_candidate_head_moving_during_audit_invalidates_it` [1]: a HEAD move
  with identical files.
- `test_u_accepted_state_moving_during_audit_invalidates_it` [1]:
  `candidate_stale_during_audit`.
- `test_stale_candidate_before_audit_makes_no_request` [1].
- `test_unavailable_candidate_makes_no_request` [3]: cleaned up (not
  recreated), forged, or symlink.
- `test_v_unknown_runtime` [1], `test_w_x_non_completed_runtime` [3]
  (`failed`, `cancelled`, `in_progress`), and
  `test_y_incomplete_keeps_runtime_mapping_and_is_no_audit` [2] (`max_steps` →
  `timeout`, `interrupted` → `error`). In each, LongHorizon reports `blocked`.
- `test_z_aa_environment_untouched_and_no_trajectory` [1].
- `test_ab_ac_ad_role_matrix` [7]: every role against all three adapters.
- `test_ae_auditor_subclass_and_unknowns_fail_closed` [1]:
  - a subclass is refused;
  - the unknown role names `auditor`, `agent`, and `auditor_agent` are
    refused;
  - the auditor cannot be bound as `cli_executor`, nor the executor as
    `cli_auditor`;
  - a mixed binding returns only explicit keywords;
  - the pinned manager takes `cli_auditor_agent`.
- `test_capabilities_and_agent_adapter_conformance` [1].
- `test_transport_requires_one_uhp_deployment` [1].
- `test_af_tracked_project_doc_replaces_bootstrap_copy` [1] and
  `test_af_unknown_remote_doc_fails_closed` [1].
- `test_ag_ah_snapshot_excludes_ignored_files_and_git` [1]: no `.env`,
  `debug.log`, or `.git` component, while `.github/` is still sent.

Mutation checks (each change was reverted afterwards):

| Deliberate change | Tests that fail |
| --- | --- |
| Remote mutations ignored | K–N (4) |
| The auditor delta applied to the candidate | K–N (4), on the candidate snapshot |
| No post-audit drift check | Q–T and the HEAD-move test (5) |
| No post-audit accepted-state check | U (1) |
| Problems not blocking `done` | 15 |
| `previous_response_id` set | A–I (1) |

Ruff passes.

No live provider, harness, or HarnessRouter calls were made.


---

## 2026-09-23 — Auditor-result normalization

Branch `feat/longhorizon-promotion-gate`, from `main` at `b91ab83` (commit
`2e5bca8`). It adds `src/cloudeo/longhorizon/audit_result.py` (`normalize_auditor_result`,
`AuditorVerification`, `AuditorFailure`) and the ADR-019 amendment. No
existing module changed, and LongHorizon is not modified.

Validation (all offline):

- With the `longhorizon` extra: **516 passed** (429 existing unchanged, 87 in
  `tests/test_longhorizon_audit_result.py`). Without the extra: 319 passed and
  5 skipped (the four LongHorizon modules and one bridge test).
- Focused suites: normalizer 87, workspace auditor 43, workspace executor 31,
  LongHorizon adapter 35, bridge 105.

Tests in `tests/test_longhorizon_audit_result.py` (the numbers in brackets are
parametrized cases):

- **Normal reports:**
  - `test_valid_report_is_verified` [1];
  - `test_valid_but_incomplete_report_is_not_verified` [1];
  - `test_longhorizon_acceptance_guard_still_applies` [1]: LongHorizon
    downgrades blocking constraints.
- **Mutation:** `test_mutation_detected_is_blocked_and_list_preserved` [1]
  (native keys; `added`, `changed`, `deleted`, and `type_changed` are kept
  exactly).
- **Unusable reports:**
  - `test_missing_report_is_blocked` [3]: empty, whitespace, or a valid
    report present only in `actions_log`;
  - `test_malformed_report_is_blocked` [1];
  - `test_conflicting_visible_outputs_are_ambiguous` [1];
  - `test_identical_visible_outputs_follow_longhorizon_precedence` [1];
  - `test_no_read_only_evidence_is_blocked` [1].
- **Failures:**
  - `test_runtime_failure_is_auditor_error` [5]: authentication, rate limit,
    generic provider error, timeout, and cancelled, each even with a perfect
    report present;
  - `test_cloudeo_audit_boundary_codes` [5]: drift, staleness, invalid
    evidence, and an unavailable candidate are `BLOCKED`; an upload failure is
    `AUDITOR_ERROR`.
- **Repair:**
  - `test_manager_repair_shape_does_not_use_repaired_actions_log` [1]: the
    pinned manager's corrected-result shape stays `BLOCKED` /
    `report_malformed`, sourced from the primary visible output;
  - `test_repair_is_used_only_when_explicitly_passed` [1];
  - `test_1_malformed_original_with_positive_repair_is_capped_at_not_verified`
    [1]: text, parsed fields, source, and repair metadata are kept, with
    reason `report_repaired_not_verification_authority`;
  - `test_2_repaired_negative_report_is_not_verified` [1];
  - `test_structured_evidence_does_not_make_a_repaired_report_verified` [1];
  - `test_3_unacceptable_repair_is_blocked` [5]: a failed repair, a repair
    that is still malformed, one only in `actions_log`, a mutated repair, or an
    ambiguous one;
  - `test_repair_is_ignored_when_primary_report_is_valid` [1];
  - `test_repair_cannot_rescue_a_mutated_or_failed_primary` [1];
  - `test_4_no_repair_turns_a_failed_audit_into_verified` [36]: 12 failure
    conditions × a malformed, empty, or valid primary, each with a positive
    repair. The conditions are a runtime error, a provider authentication
    error, a timeout, cancellation, a native mutation, a Cloudeo mutation, no
    read-only evidence, a guard without a verdict, drift, staleness, invalid
    evidence, and a transport failure. None is `VERIFIED`, and the repair is
    never considered.
- **Sweep:** `test_extraction_or_execution_failure_is_never_verified` [12].
- **Evidence:** `test_upstream_metadata_is_preserved_unmodified` [1].
- **With the real `UHPWorkspaceAuditorAdapter`:**
  - `test_real_read_only_audit_is_verified`;
  - `test_real_auditor_mutation_is_blocked_with_paths`;
  - `test_real_local_drift_is_blocked`;
  - `test_real_runtime_failure_is_auditor_error`;
  - `test_real_malformed_audit_with_positive_repair_is_not_verified`.

Mutation checks (each change was reverted afterwards):

| Deliberate change | Tests that fail |
| --- | --- |
| LongHorizon's own source precedence, which falls back to `actions_log` | 8 |
| No read-only evidence requirement | 7 (including the `no_read_only_evidence` and `guard_without_verdict` cases with a valid primary) |
| Repair parsed the way the pinned manager does | 3 (the positive-repair cap test, the negative-repair test, and the real-adapter repair test) |
| No repair cap | 3 (the two capped-repair unit tests and the real-adapter repair test) |

Ruff passes.

No live provider, harness, or HarnessRouter calls were made.


---

## 2026-09-23 — Verified checkpoint and promotion gate

Branch `feat/longhorizon-promotion-gate`, from `main` at `b91ab83`, after the
normalizer (`2e5bca8`) and its documentation fix (`6fce086`); the gate is commit
`7a191c0`. It adds `src/cloudeo/longhorizon/promotion_gate.py`, the helper
`current_content_sha256()` in `src/cloudeo/bridge/audit.py`, and ADR-020. The
broker, bridge transport, adapters, normalizer, and LongHorizon are unchanged.

**The race identified:** the audit inspects state A, the workspace becomes B,
and promotion accepts B on A's verification. A recheck of `HEAD` and the
content hash before checkpointing is necessary but not sufficient, because
`checkpoint_candidate()` commits whatever the worktree holds at that instant: a
change between the recheck and the commit would be checkpointed.

**The fix is a post-checkpoint proof from immutable commits.** After
checkpointing, the gate reads the checkpoint commit from Git objects and
requires two things:

- its parent is the audited `HEAD`;
- its content hash equals the audited content hash.

Only then does it call `promote()`, which moves accepted state to that
immutable commit through the broker's own compare-and-swap. The statuses are
listed in ADR-020.

A failed post-checkpoint check or promotion returns the checkpoint
(`stage="refused_after_checkpoint"`, `checkpoint_created=True`) and keeps it
and its ref, unaccepted, as evidence.

Validation (all offline):

- With the `longhorizon` extra: **545 passed** (516 existing unchanged, 29 in
  `tests/test_longhorizon_promotion_gate.py`). Without the extra: 319 passed
  and 6 skipped (the five LongHorizon modules and one bridge test).
- Focused suites: gate 29, normalizer 87, workspace auditor 43, workspace
  executor 31, LongHorizon adapter 35, bridge 105, Workspace Broker 51.
- The verifications come from the real `UHPWorkspaceAuditorAdapter` (offline
  fake HarnessRouter) and `normalize_auditor_result()`. The broker is the
  real `GitWorkspaceBroker`.

Tests in `tests/test_longhorizon_promotion_gate.py` (the numbers in brackets
are parametrized cases):

- **Allowed:**
  - `test_verified_and_current_is_promoted_exactly` [1]: evaluation is
    read-only. The promoted commit's parent is the audited `HEAD`, and its
    content hash equals the audited one.
  - `test_already_checkpointed_audited_state_is_promoted` [1]: the audited
    checkpoint is reused (`checkpoint_created=False`).
  - `test_ignored_local_files_are_not_workspace_state` [1]: the trust boundary.
  - `test_commit_content_matches_worktree_content_rules` [1].
- **After the audit:**
  - `test_workspace_changed_after_audit_is_denied` [4]: content hash changed,
    a new dirty file, a deletion, or an executable bit. Each is refused before
    any checkpoint.
  - `test_head_changed_with_identical_files_is_denied` [1]: same files,
    different version identity.
  - `test_same_content_on_another_candidate_is_stale` [1].
  - `test_accepted_state_moved_after_audit_is_stale` [1].
- **Races:**
  - `test_audit_then_change_then_gate` [1]: the audit-A → workspace-B
    scenario.
  - `test_race_between_recheck_and_checkpoint_is_denied` [1]: a change
    injected at checkpoint time. It gives `WORKSPACE_CHANGED` /
    `checkpoint_differs_from_audit` and `refused_after_checkpoint`. The
    checkpoint is returned, its ref kept, and the candidate `HEAD` is that
    commit, which holds the raced content. Accepted state is unchanged.
  - `test_race_on_accepted_state_before_promote_is_denied` [1]: gives
    `VERIFICATION_STALE`, and the checkpoint is kept.
  - `test_caller_can_distinguish_how_far_the_gate_got` [1]:
    `refused_before_checkpoint` (no checkpoint), `refused_after_checkpoint`
    (with a checkpoint), and `promoted`.
- **Verification contract:**
  - `test_not_verified_blocked_and_auditor_error_are_denied` [1]: from real
    audits.
  - `test_repaired_prose_can_never_promote` [1]: including forged `VERIFIED`
    results that carry repair provenance.
  - `test_gate_consumes_the_contract_not_the_prose` [1].
  - `test_forged_verified_without_mutation_verdict_is_denied` [1].
- **Evidence:** `test_missing_or_malformed_evidence_is_denied` [8]: no content
  hash, no `HEAD`, no candidate ID, a bad hash, a symbolic `HEAD`, a snapshot
  changed during the audit, no accepted-state check, or no remote check.
- **Other:** `test_nothing_to_promote` [1] and
  `test_gate_uses_only_public_broker_calls` [1] (`inspect_candidate`,
  `accepted_state`, `checkpoint_candidate`, `promote`).

Mutation checks (each change was reverted afterwards):

| Deliberate change | Tests that fail |
| --- | --- |
| No post-checkpoint commit verification | 2: the checkpoint-time race is then promoted (the race test and the stage test) |
| No content comparison before checkpoint | 5 |
| No content comparison anywhere | 7 |
| No `HEAD` comparison | 1 |
| No identity comparison | 1 |
| Repair provenance not checked | 1 |
| After-audit flags not required | 3 |
| The created checkpoint dropped from post-checkpoint refusals | 3 |

Ruff passes.

No live provider, harness, or HarnessRouter calls were made.
