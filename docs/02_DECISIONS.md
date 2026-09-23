# Cloudeo Decision Log

This file records important architectural decisions so they do not have to be reconstructed from chat history.

---

## ADR-001 — Local-first MVP

**Decision:** Build and validate Cloudeo locally in WSL2 before deploying to a server.

**Reason:**

- fastest development loop
- no deployment complexity before architecture validation
- no need for local GPU
- Jev and frontier models can remain API-hosted

**Status:** Accepted.

---

## ADR-002 — Jev is a decision engine, not the whole agent

**Decision:** Use Jev for classification, routing, scoring, and probabilistic verification rather than for reasoning or generation.

**Reason:**

Jev returns structured probabilities and does not generate prose/code. This makes it suitable as a high-frequency decision layer.

**Status:** Accepted.

---

## ADR-003 — Treg is the tool/data plane

**Decision:** Use Treg to discover/call external providers and tools rather than rebuilding provider integrations inside Cloudeo.

**Reason:**

Treg already provides provider access, credential injection, OAuth, CLI, MCP, audit, provider catalog, and metering.

**Status:** Accepted.

**Constraint:** Treg remains behind a Cloudeo adapter boundary because of coupling and licensing considerations.

---

## ADR-004 — Real Jev before real Treg

**Decision:** Introduce real integrations one at a time.

Sequence:

```text
mock Jev + mock Treg
real Jev + mock Treg
real Jev + real Treg dry run
real Jev + real Treg
```

**Reason:** Easier debugging and safer cost control.

**Status:** Completed.

---

## ADR-005 — Deterministic validation before Jev verification

**Decision:** Structured facts should be validated in code first.

Pipeline:

```text
provider output
    ↓
deterministic validation
    ├── pass
    ├── fail
    └── inconclusive → Jev
```

**Reason:** A real TryKitt result contained explicit strong evidence but Jev initially gave only 0.81 probability against a 0.85 threshold. The result could be proven deterministically.

**Status:** Implemented in v0.1.1.

---

## ADR-006 — Do not simply lower confidence thresholds

**Decision:** Avoid fixing false negatives by globally lowering thresholds without understanding evidence structure.

**Reason:** Threshold reduction can increase false positives across unrelated workflows. Explicit facts should instead be extracted and validated deterministically.

**Status:** Accepted.

---

## ADR-007 — Provider failures are deterministic failures

**Decision:** Provider/transport failures such as `TREG_ERROR` should not consume a Jev verification call.

**Reason:** A failed external call is already known to be unusable.

**Status:** Implemented in v0.1.1.

---

## ADR-008 — Automatic tool discovery is the next major milestone

**Decision:** v0.1.2 should remove manually supplied provider candidate arrays.

Target:

```text
objective
  ↓
Treg capability discovery
  ↓
provider metadata
  ↓
compatibility filtering
  ↓
Jev routing
```

**Reason:** Manual candidate construction is the largest remaining non-autonomous part of the current pipeline.

**Status:** Planned.

---

## ADR-009 — LLM escalation comes after automatic discovery

**Decision:** Do not add Claude/GPT reasoning escalation until the tool discovery and validator architecture is stable.

**Reason:** Avoid hiding control-plane weaknesses behind a frontier model.

**Status:** Planned.

---

## ADR-010 — Self-improvement comes later

**Decision:** First collect structured evidence of runs before implementing self-improvement.

Log first:

- decisions
- probabilities
- provider
- costs
- latency
- success/failure
- retries
- validation evidence
- human corrections

Then optimize based on observed data.

**Status:** Planned.


---

## ADR-011 — Extract execution without changing orchestration

**Decision:** Add one internal async `ExecutionBackend` protocol with an
`ExecutionResult` carrying output and economics. Adapt the existing Treg client
through `TregExecutionBackend`; retain it as the controller's default and allow
an optional injected backend. Discovery, routing, verification, and persistence
stay in their current locations.

**Reason:** Establish the execution seam for a future UHP backend while preserving
the v0.1.2.2 path and existing construction sites. No UHP fields or other v2
interfaces are needed for this slice.

**Constraint:** Preserve normal `TREG_ERROR:` normalization, dry-run exception
propagation, and legacy economics behavior. Existing ranking and unknown-choice
behavior are unchanged. UHP remains unimplemented.

**Status:** Implemented; 33 tests pass. See the execution-foundation evidence in
`03_PROGRESS_AND_EVIDENCE.md`.


---

## ADR-012 — Standalone UHP client before execution integration

**Decision:** Add a UHP-native client (`cloudeo.uhp`) with its own request,
result, harness, model, and error types, pinned to UHP `2026-09-12`. Do not
route it through `ExecutionBackend`, `ToolCandidate`, or the controller yet.

**Reason:** A harness task (input, harness, model, step/time budgets, session
continuation, output items) is a different execution class from a Treg endpoint
call. Proving the UHP boundary independently lets the shared execution request
be designed from two concrete shapes instead of one.

**Constraint:** `completed` is runtime completion, never Cloudeo verified
success. Terminal output (including partial output of `incomplete`, `failed`,
and `cancelled`) and unknown output item types are preserved unchanged.
Structured errors keep HTTP status, UHP code, type, message, param, detail,
body, and the response `UHP-Version`. No retries or recovery policy are built
on them yet. Transport timeouts do not claim cancellation.

**Status:** Client implemented; 34 mock-transport tests. Live discovery proven
against HarnessRouter CE 0.23.7; harness listing and live tasks await an API key
and provider credentials. See `03_PROGRESS_AND_EVIDENCE.md`.


---

## ADR-013 — Discriminated execution request and outcome (proposed)

**Decision (proposed):** Replace the Treg-shaped `ExecutionBackend.execute(
ToolCandidate)` with a discriminated `ExecutionRequest`
(`DirectToolExecution` | `HarnessTaskExecution`) and a common
`ExecutionOutcome` that carries a backend-native result, rather than a generic
`ExecutionBackend[T]` or a flattened universal task model.

**Reason:** The concrete Treg and UHP shapes share little beyond attempt
identity, execution status, evidence, cost, duration, and error. Harness
selection, model fallback, step/time budgets, sessions, `incomplete`, and
partial output have no Treg equivalent; endpoint, method, query/body, and ledger
economics have no UHP equivalent. A discriminated union keeps each class typed
and lets the controller consume one outcome shape.

**Constraint:** Execution status never means verified success. Native results
are retained, not reduced to text. The live `actual_harness: null` observation
means runtime identity records what was requested and what the server actually
echoed as separate fields.

**Status:** Proposed only; not implemented or wired into `Controller.run()`.
See `12_EXECUTION_REQUEST_AND_OUTCOME_PROPOSAL.md`.

**Amendment (2026-09-23, `feat/execution-contracts`):** Implemented as types,
mappers, and dispatch only (`src/cloudeo/execution/contracts.py`,
`treg_backend.py`, `uhp_backend.py`, `dispatch.py`). Still not used by
`Controller.run()`. Deviations from the proposal:

1. `HarnessTaskExecution` composes the existing `UHPTaskRequest` as `task`
   instead of copying its fields, so there is one UHP request definition. It
   rejects a task without `harness_id`, so the server default never hides which
   harness was selected.
2. Neither request carries `attempt_id` or `profile_id` yet. No caller exists
   to supply them; they arrive with controller integration.
3. `ExecutionStatus` adds `unknown`, used when Cloudeo could not observe the
   final task state. Such a task may have been accepted or still be running,
   so it is neither `failed` nor `cancelled`. For request-level UHP failures,
   only an HTTP 4xx rejection other than 408 maps to `failed`. HTTP 408, 5xx,
   any other HTTP status, transport failures, and protocol failures map to
   `unknown`. An explicit `UHPTaskResult` status is always kept as returned.
   Structured error fields are kept in every case, and nothing is retried.
4. Proposed `evidence` became `raw_output`: Treg stdout verbatim, or UHP output
   items verbatim, with no synthetic wrapper. Proposed `cost` became
   `ExecutionCost` with `direct_tool_economics` (kept exactly as the Treg path
   produced it, dict or model) and `harness_usage` (UHP usage, or None).
5. Runtime identity fields are `requested_*` / `actual_*`. `actual_harness`
   is set only when the server echoes `metadata.harness_id`. Treg identity is
   `requested_tool` only; the Treg call ID stays in economics.
6. `artifacts` is an empty list of dicts; no artifact type is defined until a
   backend reports artifacts.
7. Backends use two explicit protocols (`DirectToolExecutionBackend`,
   `HarnessTaskExecutionBackend`) instead of a generic `ExecutionBackend[R]`.
   The legacy `ExecutionBackend`/`TregExecutionBackend` are unchanged, and the
   new `TregDirectToolBackend` wraps them.


---

## ADR-014 — Controller executes through the dispatcher (Treg only)

**Decision:** `Controller.run()` executes every tool attempt, including the dry
run, as a `DirectToolExecution` through an `ExecutionDispatcher` and reads the
resulting `ExecutionOutcome`. By default the controller builds a dispatcher with
only a direct-tool backend (`TregDirectToolBackend`). The legacy
`execution_backend=` argument is kept and adapted through
`LegacyDirectToolBackend`. An optional `execution_dispatcher=` may be injected
instead, but not together with it.

**Reason:** Move the controller onto the execution contracts without changing
behavior, so a later milestone can add harness execution by configuring the
dispatcher rather than rewriting the attempt loop.

**Constraint:** The controller does not interpret `outcome.status`; the
validators remain the only `TREG_ERROR:` rule, and runtime status is never
verification. Legacy economics, ranking, and dry-run exception behavior are
preserved. No harness-task backend is configured, and `HarnessTaskExecution`
is not built by the controller.

**Status:** Implemented on `feat/execution-dispatch-adoption`; equivalence is
checked against a golden captured at `10d4b71`. See
`03_PROGRESS_AND_EVIDENCE.md`.


---

## ADR-015 — Workspace Broker owns canonical accepted state

**Decision:** Add a Workspace Broker (`src/cloudeo/workspace/`) that owns the
canonical accepted state of a workspace. An executor may only produce a
candidate state. Only a separate, explicit `promote` call can change the
accepted state. The first implementation, `GitWorkspaceBroker`, uses a Git
commit SHA as the checkpoint type.

**Canonical vs candidate state:** `CanonicalWorkspaceState` is an explicit
`(workspace_id, accepted_commit)`, stored in the ref
`refs/cloudeo/workspaces/<id>/accepted`. It is never a branch or `HEAD`, and
the broker never checks out, resets, or moves a branch in the canonical
repository. A `CandidateWorkspace` is a detached Git worktree created at the
exact accepted commit, outside the repository's working tree. A
`WorkspaceCheckpoint` is an immutable commit that descends from the candidate's
base and was recorded by the broker.

**Why executor completion cannot change canonical state:** An executor exiting,
`ExecutionOutcome.status == "completed"`, changed files, locally passing tests,
and a harness saying it is done are all claims made by, or about, the party
being checked. Acceptance criteria V2-D03 and V2-D04 require that a failed audit
cannot advance the accepted checkpoint, and that an auditor can inspect the
candidate independently. The broker therefore has no automatic promotion path;
a future verifier-driven caller decides.

**Optimistic concurrency:** A candidate records the accepted commit it began
from. Promotion requires the accepted commit to still equal that base. If
accepted moved from A to B after candidate C began from A, promoting C fails as
stale and B is kept. There is no auto-rebase, force-reset, or history rewrite;
every promotion is a fast-forward. Only commits the broker recorded as
checkpoints for that candidate and workspace can be promoted.

**Atomic terminal decisions:** Promotion is one `git update-ref --stdin`
transaction (`start` … `prepare` / `commit`). It verifies the `rejected`
marker is absent, compare-and-swaps `accepted` from the base to the checkpoint
commit, and creates the `promoted` marker, which fails if it already exists.
Rejection is likewise one transaction: it verifies `promoted` is absent and
creates `rejected`. Either every ref in a transaction changes or none does. A
promote and a reject racing for the same candidate can never both succeed, and
a failed promotion leaves `accepted` and both markers unchanged. A changed
`accepted` is reported as `StaleCandidateError`; an existing decision as
`CandidateStateError`. There are no retries.

**Rejection:** leaves accepted state unchanged and keeps the rejected commit
reachable through a `rejected` ref, so the evidence is not lost. The returned
`RejectionRecord` carries the reason; storing reasons and richer evidence
durably is future work.

**Hook-isolated broker operations:** Broker operations manage state; they are
not project validation. Two broker-controlled Git operations run with
`core.hooksPath` set to the null device for that command only, so no repository
hook runs:

1. candidate creation (`git worktree add` in `create_candidate()`), which would
   otherwise run the repository's `post-checkout` hook;
2. checkpoint commits created by `checkpoint_candidate()`, which would
   otherwise run `pre-commit`, `prepare-commit-msg`, `commit-msg`, and
   `post-commit`.

Checkpoint commits additionally use the fixed broker identity (also set through
the `GIT_AUTHOR_*` and `GIT_COMMITTER_*` environment variables, which would
otherwise take precedence) and `commit.gpgSign=false`, so signing configuration
cannot block them. The command-scoped setting also overrides a `core.hooksPath`
configured in the repository. The repository's hook files and persistent
config are never modified.

Outside this guarantee: anything an executor runs inside a candidate, including
commits it makes itself and other Git commands. The broker does not disable
hooks for those.

**Candidate creation rollback:** The candidate's `base` ref is created before
`git worktree add`. If the worktree cannot be created, only that ref is deleted
(compare-and-delete against the expected commit), and the original error is
raised. A failed creation never leaves a registered candidate, and no other ref
or worktree is touched.

**Relationship to HarnessRouter sessions:** A UHP session keeps a conversation
and a server-side working directory. It can expire, deleting it removes its
files, and UHP 2026-09-12 defines no checkpoint, snapshot, or restore semantics.
Harness sessions are therefore execution mechanisms, never canonical state.
Switching harness starts from the accepted checkpoint, not from another
harness's native session (V2-D05). Moving files between a candidate and a
harness session is future work.

**Relationship to LongHorizon roles:** The Manager chooses what to attempt
against the current accepted state. An Executor works only in a candidate. The
Auditor inspects the candidate checkpoint, as a commit, independently of the
Executor's claims. Only after the audit passes does the controlling loop call
`promote`; on failure it calls `reject`. LongHorizon is not integrated yet.

**Constraints:** Only local Git subcommands run (enforced by an allowlist); no
fetch, push, or remote access. Worktrees isolate working files, not trust: they
share refs and objects with the repository, so a hostile local executor could
move Cloudeo refs. Untrusted local executors need a separate clone or container.
The broker is synchronous and not yet used by `Controller.run()` or the
dispatcher.

**Status:** Implemented on `feat/workspace-broker-foundation`. See
`03_PROGRESS_AND_EVIDENCE.md`.


---

## ADR-016 — LongHorizon AgentAdapter backed by UHP execution

**Decision:** Add an optional `cloudeo.longhorizon` package with
`UHPHarnessAgentAdapter`, which implements LongHorizon-Harness's `AgentAdapter`
protocol. Each `run_episode()` call runs one bounded harness task through the
existing `ExecutionDispatcher` and `UHPHarnessTaskBackend`, using an explicit
`HarnessExecutionProfile` (harness ID, model, optional step limit). The result
is mapped onto LongHorizon's real `EpisodeResult`.

**Pinned upstream:** LongHorizon-Harness `v0.1.7`, commit
`ff76d6a4c0a4f6d7dfeb2fc2adcf51ccb87a3b9a` (a lightweight tag;
https://github.com/AMAP-ML/LongHorizon-Harness, MIT). It is installed through
the optional `longhorizon` extra as a Git dependency on that exact commit, and
`uv.lock` records the same commit. The PyPI release `lh-harness==0.1.7` was
checked: its wheel and sdist hashes match PyPI, and every source file is
byte-identical to that commit. It additionally ships three compiled web-UI
files that are not in the source and cannot be verified from it, so the
package does not exactly correspond to the source and is not used. A Git
install omits those files by upstream design; the adapter does not use them.
Installations that only use Treg or UHP do not install LongHorizon, and no core
module imports it.

**AgentAdapter boundary:** The contract is
`run_episode(prompt, env, budget, live_trajectory_path=None) -> EpisodeResult`.
The adapter makes no routing decision; harness and model come only from the
profile. Every episode is a new UHP session, and `previous_response_id` is
never set, so each episode has a fresh executor context (V2-E02). The
LongHorizon `EpisodeBudget` becomes the UHP `timeout_seconds`. No local
cancellation is added. The live trajectory path is not written; the UHP output
items are returned in `actions_log` instead.

**Lossy status mapping, native state preserved:**

| Cloudeo `ExecutionOutcome.status` | `EpisodeResult.status` |
| --- | --- |
| `completed` | `done` |
| `failed` | `error` |
| `cancelled` | `cancelled` |
| `incomplete` with an explicit budget reason (`max_steps`, `max_step`, `timeout`, `timeout_seconds`, `max_output_tokens`) | `timeout` |
| `incomplete` with any other reason or none | `error` |
| `unknown` | `error`, with `runtime_state_unobserved` |
| `in_progress` | `timeout` if the episode budget was exhausted, otherwise `error`; both with `runtime_state_unobserved` |

`unknown` and `in_progress` are never mapped to `cancelled`.
`EpisodeResult.metadata` always carries `cloudeo_runtime_status`,
`requested_harness`, `actual_harness`, `requested_model`, `actual_model`,
`model_fallback`, `response_id`, `session_id`, `protocol_version`, `usage`,
`execution_duration_ms`, `execution_error`, `incomplete_details`, and
`supports_workspace_sync`. Nothing is inferred: `actual_harness` stays `None`
when HarnessRouter does not echo it. Role text is exposed through LongHorizon's
`assistant_visible_output` key; `actions_log` holds the raw UHP output items.

**`done` is not verification:** `EpisodeResult.status == "done"` means only that
the harness task completed. Independent audit and Cloudeo verification decide
success.

**Ownership:** LongHorizon owns the objective and cross-round orchestration
(V2-E01). The Workspace Broker owns accepted code state (ADR-015). A
HarnessRouter session is execution state only. Cloudeo chooses the profile
outside the adapter.

**Workspace limitation:** The harness works in its HarnessRouter session
workspace, not in the LongHorizon `Environment` passed to `run_episode()`,
which the adapter never calls. File changes made by the harness are therefore
invisible to anything inspecting that Environment. The adapter declares
`supports_workspace_sync = False`. It may back manager, final-response, and
other text-only roles. It is not eligible for file-mutating executor roles or
for auditors that inspect the workspace. Any future Cloudeo role-binding layer
must reject binding it to a role that needs shared workspace visibility while
`supports_workspace_sync` is false. A candidate<->UHP file bridge is required
before those roles can use it.

**Status:** Implemented on `feat/longhorizon-adapter-foundation`. The
LongHorizon manager loop is not run from Cloudeo, and `Controller.run()` is
unchanged. See `03_PROGRESS_AND_EVIDENCE.md`.


---

## ADR-017 — UHP Workspace Bridge Foundation

**Decision:** Add `cloudeo.bridge`, which moves a `CandidateWorkspace` into one
fresh UHP session and brings the executor's changes back as a validated delta.
The bridge may change the candidate's working tree and nothing else.

**Canonical ownership:**

- The Workspace Broker's accepted commit is canonical state (ADR-015).
- A `CandidateWorkspace` is mutable executor state.
- A HarnessRouter session workspace is temporary remote execution state.

After a successful sync the candidate is simply dirty and uncheckpointed. The
bridge never calls `checkpoint_candidate()`, `promote()`, or `reject()`; it
calls only the broker's read-only `inspect_candidate()`. It never moves
accepted state, a branch, or `HEAD`.

**Protocol facts verified** in the pinned sources (UHP `2026-09-12`;
HarnessRouter `809392d602e34e36f0468943035c54d3350af885`):

1. Input is `POST /v1/files` (multipart `file`, optional `purpose`, default
   `user_data`), then `{"type": "input_file", "file_id": ...}`.
2. HarnessRouter writes task input files into the session working directory
   under their upload filenames (`_write_input_files`).
3. Artifacts are listed with `GET /v1/sessions/{session_id}/files`.
4. Artifacts are downloaded as raw bytes from
   `GET /v1/containers/{container_id}/files/{file_id}/content`.
5. A session keeps one working directory across turns (Sessions §1).
6. HarnessRouter also has implementation-specific by-path
   `GET/PUT /v1/sessions/{sid}/files/{path:path}`. The bridge does not use
   them.
7. HarnessRouter's session listing and `.../files/archive` both apply
   `_ws_visible`, which hides every path starting with `.`, the names
   `.gitignore`, `AGENTS.md`, and `CLAUDE.md`, and the directories `.git/`,
   `.harness/`, `.claude/`, `.codex/`, `tmp/`, `node_modules/`,
   `__pycache__/`, `.venv/`, `venv/`, `.cache/`, and `.next/` at any depth.
   **Neither is authoritative project state**, so the bridge does not
   reconstruct the project from them. It uses a helper-produced delta instead.
   HarnessRouter's default upload cap is 25 MiB (`HARNESS_UPLOAD_MAX_BYTES`),
   and so is its produced-file cap (`HARNESS_RESP_MAX_FILE_BYTES`).

**Transport:**

1. Select the candidate's files with Git semantics
   (`git ls-files --cached --others --exclude-standard -z`): tracked files plus
   untracked, non-ignored files, NUL-separated. `.git` is never selected, and
   ignored files (for example `.env`) are never sent. Tracked files deleted in
   the working tree are not sent. Symbolic links, paths under a symlinked
   directory, submodules, nested repositories, non-UTF-8 paths, and paths
   colliding with bridge names fail before anything is uploaded.
2. Build a deterministic input bundle
   `.cloudeo-bridge-input-<run>.tar.gz`. It contains `manifest.json` plus
   `files/<path>`, in sorted order, with mtime 0, uid/gid 0, empty user and
   group names, mode 0644 or 0755, and a gzip header with no filename and
   mtime 0. Building the same snapshot twice produces identical bytes and the
   same manifest hash, even after mtimes or non-semantic permission bits change
   (0644 to 0600, or 0755 to 0700). Toggling the executable bit (0600 to 0700)
   does change the manifest, archive, and hash, because executable state is
   part of each entry. Tests check both. The input manifest records the
   format, bridge run ID (`bridge_<32 hex>`), `workspace_id`, `candidate_id`,
   `base_commit`, `head_commit`, the output limits (`max_output_files`,
   `max_output_total_bytes`, `max_output_file_bytes`,
   `max_output_bundle_bytes`), and each file's path, size, SHA-256, and
   executable bit. The SHA-256 of these canonical manifest bytes is kept as
   the run's `input_manifest_sha256`.
3. Upload the stdlib-only helper `.cloudeo-bridge-helper.py`
   (`src/cloudeo/bridge/remote_helper.py`, Python 3.8+) and the bundle through
   `POST /v1/files`. On unpack, the helper walks every parent component of each
   file under the remote workspace. It refuses a symlinked or non-directory
   parent and requires the resolved parent to stay inside the workspace, so
   `workspace/link -> /tmp/outside` plus `link/file.txt` writes nothing
   outside. This protects the remote session; canonical state is protected
   separately.
4. Submit exactly one `HarnessTaskExecution` through `ExecutionDispatcher`,
   with the explicit harness and model, no `previous_response_id`, and input
   made of the transport instructions (fenced, and separated from the user's
   task) plus the two `input_file` references. The harness runs
   `unpack --run-id`, does the task, then runs `pack-delta --run-id`.
5. `pack-delta` compares the final tree with the input manifest and writes
   `cloudeo-bridge-output-<run>.tar.gz`, a delta containing added and changed
   files (with size, SHA-256, and executable bit) and an explicit deleted-path
   list. Unchanged files do not come back. The delta manifest echoes the
   identity fields and the `input_manifest_sha256` of the snapshot it was made
   from. It excludes `.git` and `__pycache__` at any depth, the root runtime
   directories `.claude`, `.codex`, and `.harness`, and bridge-reserved root
   names. It refuses symbolic links and special files, so no output is
   produced. Each file is checked with `lstat` before it is read, so an
   oversized executor workspace is never loaded into memory. If a limit is
   exceeded, the helper writes a small error artifact (`kind: "error"`) instead
   of a delta and exits with status 3. The error is one of `output_too_large`
   (the packed delta exceeds `max_output_bundle_bytes`),
   `output_file_too_large`, `output_file_count_exceeded`, or
   `output_total_bytes_exceeded`, together with the limit, the observed value,
   and the path where relevant. There is no splitting into several artifacts.
6. Using `ExecutionOutcome.runtime.session_id`, list the session's files and
   select exactly one artifact whose filename, and path where the server
   reports one, is this run's exact output name. Download it through the
   configured client by `container_id` and `file_id`; a `download_url` host is
   never followed.
7. Validate the whole bundle. Then check that the candidate has not drifted
   (below). Only then apply the delta to the same candidate.

**Optimistic concurrency (candidate drift):** The snapshot that was sent is the
apply precondition. Immediately before applying any delta, the bridge rebuilds
the candidate's manifest with the same selection and hashing rules and requires
it to equal the manifest that was sent. A locally changed, added, or deleted
file, or a changed executable bit, made while the remote episode ran fails the
sync with `candidate_changed_during_execution`, and zero remote changes are
applied. In particular:

- a remote delete cannot delete a locally modified file;
- a remote change cannot overwrite a newer local change;
- a remote addition cannot overwrite a path created locally during the run.

The two mutations are never merged. Ignored local files, such as `.env`, are
outside the snapshot, so editing them is not drift. A per-file content and
mode check at apply time remains as a second line of defense.

**One UHP deployment:** Uploads, the task, the session listing, and the
download must reach the same UHP server. `UHPWorkspaceBridge` refuses
construction unless the dispatcher's harness-task backend is a
`UHPHarnessTaskBackend` whose `client` is the very `UHPClient` the bridge uses
for file operations.

**Artifact size caps:** HarnessRouter CE's default caps are 25 MiB for uploads
(`HARNESS_UPLOAD_MAX_BYTES`) and 25 MiB per produced file
(`HARNESS_RESP_MAX_FILE_BYTES`, in `_collect_produced`, which also takes only
the first `HARNESS_RESP_MAX_FILES`, 25, per turn). `BridgeLimits` sets
`max_input_bundle_bytes` and `max_output_bundle_bytes` to 20 MiB each. A helper
error artifact fails the sync with its own code (`output_too_large`,
`output_file_too_large`, `output_file_count_exceeded`, or
`output_total_bytes_exceeded`), and nothing is applied. An oversized artifact
produced without the helper fails as `invalid_bundle`.

**Runtime gating and sync are separate:** `WorkspaceBridgeResult` carries the
`ExecutionOutcome` unchanged, plus `workspace_sync_status` (`synced`,
`skipped`, or `failed`), the run and session IDs, the added, changed, deleted,
and ignored paths, and a structured error.

- `completed`: a valid delta may sync.
- `incomplete`: a valid delta may sync. The outcome stays `incomplete`, and
  nothing implies verification.
- `unknown` or `in_progress`: `skipped`; the remote workspace is not read.
- `failed` or `cancelled`: `skipped`. Remote state is not applied even if an
  artifact exists. A later policy layer may deliberately add salvage.
- `completed` or `incomplete` without a valid artifact, or without a
  `session_id`: `failed`.
- In every case other than `synced`, the candidate is unchanged.

`completed` does not mean synced. Synced does not mean verified, and does not
mean checkpointed. Checkpointed does not mean promoted.

**Security:**

- `.git` never crosses the bridge in either direction.
- Ignored local files are not sent.
- The downloaded archive is untrusted. It is decompressed through a bounded
  reader (so a decompression bomb is refused) and validated as a whole, into a
  staging directory outside the candidate, before the first mutation.
- Rejected:
  - absolute paths, `..`, backslashes, drive letters, NULs, and empty
    components;
  - `.git` in any case, excluded paths, and reserved names;
  - symlinks, hardlinks, directories, devices, FIFOs, and sparse members;
  - duplicate or undeclared members;
  - a missing or duplicate-key manifest;
  - a mismatched run ID, `workspace_id`, `candidate_id`, `base_commit`, or
    `input_manifest_sha256`. The hash does not make the executor trusted; it
    prevents applying a delta made for another run or snapshot;
  - size or hash mismatch;
  - a path listed twice in the delta;
  - added paths that were sent, and changed or deleted paths that were not;
  - file-versus-directory conflicts;
  - output compressed-size, total-size, per-file-size, and file-count limits
    (`BridgeLimits` defaults: 20 MiB, 256 MiB, 32 MiB, and 10,000 files).
- Only paths that were sent can be changed or deleted, and only if their
  current content and mode still match what was sent. Otherwise the result is
  `workspace_conflict`. A remote-created path that local `.gitignore` rules
  ignore (checked with `git check-ignore`) is not imported; it is reported in
  `ignored_paths`. Tracked files remain eligible.
- **Local path safety:** In a worktree `.git` is usually a file, so apply
  refuses `.git` itself as well as `.git/...`, in any case. Every path in the
  delta, including ignored additions, is refused with `unsafe_local_path`
  before the first mutation if any existing parent inside the candidate is a
  symlink, or if its real parent resolves outside the candidate or into
  `.git`. So `candidate/some_link/file` cannot escape through an ignored or
  local symlink that was never part of the uploaded snapshot. This check runs
  before Git is queried about ignore rules, because Git refuses paths beyond a
  symlink. The bridge's own Git use is limited to `ls-files` and
  `check-ignore`.

**Failure atomicity:** Validation failures cause zero candidate mutation.
Application is planned in full first. Each changed or deleted file is backed
up, and every write goes to a temporary file followed by `os.replace`. If a
filesystem operation fails midway, changed files are restored, added files
removed, deleted files and pruned directories restored, and created
directories removed; the result is then `apply_failed`. If the rollback itself
fails, the original exception is raised with the rollback failure attached as
a note and as `__context__`. Only ordinary exceptions (`Exception`) are
handled this way. `KeyboardInterrupt`, `SystemExit`, and cancellation-like
control flow propagate unchanged and are never converted into `apply_failed`.
`.git` is never touched.

**Capability flags:** `UHPWorkspaceBridge.supports_workspace_sync = True`. The
base `UHPHarnessAgentAdapter.supports_workspace_sync` stays `False`; only a
future composed role-binding layer may advertise a LongHorizon adapter with
workspace sync.

**Limitations:**

- The harness must cooperate by running the deterministic helper, and needs a
  `python3` (3.8 or later) in its sandbox.
- Symbolic links and submodules are not supported and fail explicitly.
- Tracked files under the root runtime directories (`.claude`, `.codex`,
  `.harness`) are sent but their changes are not returned.
- Only regular-file content and the executable bit are transported.
- No live provider or HarnessRouter proof yet; all validation is offline.
- No LongHorizon role binding yet.

**Status:** Implemented on `feat/uhp-workspace-bridge-foundation`; not merged.
See `03_PROGRESS_AND_EVIDENCE.md`.
