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
8. Before the harness starts, and after writing the task's input files, the
   runner's `_write_agent_doc()` always creates or overwrites a
   backend-specific instruction document at the workspace root:
   - `AGENTS.md` for codex, hermes, pi, dsh, opencode, cline, omp, goose,
     kimi, aider, and openhands;
   - `QWEN.md` for qwen;
   - `GEMINI.md` for gemini;
   - `CLAUDE.md` otherwise, for Claude Code.

   Its managed block begins with `<!-- harness-skills:begin -->`, appended
   after any user-authored harness doc. Without handling, a candidate that
   tracks that file would be refused at unpack, and a candidate that does not
   would have HarnessRouter's copy imported as a new project file.

**Bootstrap instruction docs:** The bridge removes or replaces only recognized
HarnessRouter-managed bootstrap documents before establishing the project
snapshot. `unpack` validates every input file first. Then, before writing any
project file, it inspects each of `AGENTS.md`, `CLAUDE.md`, `QWEN.md`, and
`GEMINI.md` that exists at the remote root:

- It must be a regular file; a symlink, directory, or special file fails the
  unpack, and a symlink is never followed.
- It carries the HarnessRouter marker and the snapshot has that path: it is
  replaced by the candidate's copy, and its bytes and executable state then
  equal the snapshot exactly.
- It carries the marker and the snapshot does not have that path: it is
  removed, so it is not in the remote baseline and cannot come back as an
  added file.
- It has no marker: it is accepted only if it already equals the candidate's
  copy. Otherwise the unpack fails closed as unexpected remote state, and the
  file is neither overwritten nor deleted.

These filenames are **not** excluded project paths. After unpack they are
ordinary project files: an agent's edit to a tracked `AGENTS.md` returns as a
change, and an `AGENTS.md` the agent deliberately creates returns as an
addition. The same applies to `CLAUDE.md`, `QWEN.md`, and `GEMINI.md`.
Because HarnessRouter loaded its own document before the helper restored the
project's, the transport instructions tell the harness, right after unpack,
that the snapshot is now authoritative and to read the project's instruction
file, if any, and follow it. The fake HarnessRouter in the tests reproduces
the pinned order: input files, then the bootstrap doc, then the harness
running unpack, the task, and pack-delta.

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

**Status:** Implemented on `feat/uhp-workspace-bridge-foundation`; merged into
`main` (through `d78f1b51c2c57b81c65eeec0829a70a9886c41c0`).
See `03_PROGRESS_AND_EVIDENCE.md`.


---

## ADR-018 — LongHorizon Workspace Executor Composition

**Decision:** Add `UHPWorkspaceExecutorAdapter`
(`cloudeo.longhorizon.workspace_executor`). It implements LongHorizon's
`AgentAdapter` by composing the UHP Workspace Bridge (ADR-017) with one bound
`CandidateWorkspace`. It is bound to a `HarnessExecutionProfile`, a
`UHPWorkspaceBridge`, a candidate, and an optional clock. Each `run_episode()`
builds one `WorkspaceBridgeTask` from the prompt, the profile's harness, model,
and step limit, and the `EpisodeBudget` as `timeout_seconds`, then calls
`bridge.run(candidate, task)`. Every episode is a fresh UHP session with no
`previous_response_id`. Several episodes may run against the same candidate,
and each starts from the candidate as the previous one left it.

**Two adapters, two capabilities:**

| Adapter | `supports_workspace_sync` | Sees files |
| --- | --- | --- |
| `UHPHarnessAgentAdapter` (ADR-016) | `False` (unchanged) | No; its HarnessRouter session is discarded |
| `UHPWorkspaceExecutorAdapter` | `True` | Yes; the bound candidate, through the bridge |

**Role eligibility (`cloudeo.longhorizon.roles`), fail-closed:** The pinned
LongHorizon manager (`_run_impl`) takes one keyword per role and silently falls
back to its default `agent`, or `auditor_agent` for auditors, when a role is
left unbound. Cloudeo therefore binds roles only through
`bind_longhorizon_roles()`. It validates every binding before returning
anything, and returns only explicit role keywords (`manager_agent`,
`cli_executor_agent`, ...), never `agent` or `auditor_agent`. Eligibility is an
explicit table keyed by exact adapter type. It is not inferred from class names
or capability flags. A subclass, an unknown adapter, or an unknown role name is
eligible for nothing.

| Role | `UHPHarnessAgentAdapter` | `UHPWorkspaceExecutorAdapter` |
| --- | --- | --- |
| `manager` | eligible | no: needs no mutation |
| `final_response` | eligible | no: needs no mutation |
| `auditor_format_repair` | eligible | no |
| `cli_executor` | no: cannot see the workspace | **eligible** |
| `gui_executor` | no | no: no GUI or screenshot contract |
| `cli_auditor` | no | no: mutates the candidate; not independent |
| `gui_auditor` | no | no |

No adapter is eligible for an auditor role that inspects the workspace. The
independent workspace auditor is the next missing component.

**State flow (this milestone stops at the last step):**

```
accepted A ──create_candidate──▶ candidate @ A
candidate ──cli_executor episode──▶ bridge ──▶ fresh UHP session ──▶ validated delta
delta ──▶ candidate A′ (dirty, uncheckpointed, UNVERIFIED)      accepted is still A
```

The adapter calls only the broker's read-only `inspect_candidate()` and
`accepted_state()`. It never calls `checkpoint_candidate()`, `promote()`,
`reject()`, `create_candidate()`, or `cleanup()`. It never moves accepted state,
a branch, or `HEAD`.

**Result mapping:** The runtime mapping is exactly ADR-016's
(`episode_result_from_outcome`), with one added rule:

| Runtime | Workspace sync | `EpisodeResult.status` |
| --- | --- | --- |
| `completed` | `synced` | `done` |
| `completed` | `failed` (or anything but `synced`) | **`error`**, with `workspace_sync_failed: <code>: <message>` |
| `incomplete` | `synced` (partial delta) or `failed` | ADR-016 budget mapping (`timeout` or `error`); the sync state is in the metadata |
| `failed` / `cancelled` | `skipped` | `error` / `cancelled` |
| `unknown` / `in_progress` | `skipped` | `error` (or `timeout` for `in_progress` past the budget), with `runtime_state_unobserved` |

A `completed` runtime whose work did not reach the candidate must not look like
`done`. Otherwise LongHorizon would continue as though the candidate had
changed. `done` still means only "the harness completed and the candidate
received its delta". It is not verification.

**Metadata:** All ADR-016 keys are kept (`cloudeo_runtime_status`, requested and
actual harness and model, `model_fallback`, `response_id`, `session_id`,
`usage`, ...). The executor sets `supports_workspace_sync: True` and adds
`workspace_sync_status`, `workspace_sync_error` (`{code, message}` or `None`),
`bridge_run_id`, `workspace_id`, `candidate_id`, `candidate_base_commit`,
`added_paths`, `changed_paths`, `deleted_paths`, `ignored_paths`, and
`independently_verified: False`, which is always false.

**Candidate checks (public broker API only):** The adapter checks the candidate
before any upload, using only the public `WorkspaceBroker` protocol. It never
calls private `GitWorkspaceBroker` methods such as `_require_open()` and never
reads broker-owned refs. `inspect_candidate()` must succeed, which proves the
candidate's identity and worktree. `accepted_state()` must still equal the
candidate's `base_commit`. On failure the adapter returns an `EpisodeResult`
with `status="error"` and `cloudeo_runtime_status=None`, and makes no
HarnessRouter request.

- `candidate_unavailable`: a foreign or forged candidate, a missing or
  cleaned-up worktree, or a candidate the bridge refuses to send, for example
  one containing a symlink. The bridge's own `inspect_candidate()` and
  input-building failures also map here; they happen before anything is
  uploaded.
- `candidate_stale`: the candidate's base no longer equals accepted state.
- `workspace_upload_failed`: a UHP error while uploading, before any task is
  submitted.

The adapter never recreates the candidate, never creates a second one, and
never switches accepted state. The Workspace Broker's semantics are unchanged
by this milestone.

**Lifecycle state is not visible (public protocol limitation):** The current
WorkspaceBroker public protocol does not expose terminal candidate lifecycle
state. UHPWorkspaceExecutorAdapter therefore cannot independently distinguish
an open candidate from one already marked promoted/rejected using only the
public broker interface. Future orchestration must enforce lifecycle
ownership, or the Broker protocol must gain an explicit public lifecycle query.

`inspect_candidate()` deliberately verifies only ownership and worktree state.
A candidate whose own promotion advanced accepted state fails the staleness
check, but only because accepted state moved. It is not recognized as
promoted. A rejected candidate leaves accepted state unchanged, so it passes
both checks. The adapter makes no claim to detect either state.

**Environment:** The executor's filesystem is the bound candidate, not the
LongHorizon `Environment` passed to `run_episode()`. That Environment is
accepted for protocol compatibility and never called. The pinned manager still
uses its Environment itself: it writes round prompts there, and takes
screenshots for GUI steps.

**Workspace path mismatch in manager prompts (unproven):** The pinned
LongHorizon executor prompt may contain `config.workspace_path`, which comes
from the LongHorizon Environment. Execution actually happens in a fresh remote
HarnessRouter session workspace, where the bridge has extracted the candidate
snapshot. The bridge transport instructions (ADR-017) tell the harness to work
in the current extracted project directory. That has **not** been proven safe
inside the full LongHorizon `manager.run()` prompt flow, where the manager's
prompt may name a different path. This branch does not rewrite LongHorizon
prompts and does not claim `manager.run()` compatibility. The later
role-binding and manager-integration milestone must, as a prerequisite, test
the manager's real executor prompt through the bridge. That test must show
that the harness works only in the extracted snapshot and that the delta lands
in the candidate. Otherwise that milestone must reconcile `workspace_path`
explicitly.

**Trajectory:** The bridge does not stream a native LongHorizon trajectory.
`live_trajectory_path` is accepted and never written, and no trajectory is
fabricated. UHP output items stay in `actions_log`, which is marked
diagnostics-only when there is no assistant text.

**Limitations:**

- No terminal lifecycle detection: the public WorkspaceBroker protocol does
  not expose whether a candidate is open, promoted, or rejected, so the adapter
  cannot tell them apart. Future orchestration must enforce lifecycle
  ownership, or the Broker protocol must gain an explicit public lifecycle
  query.
- `workspace_path` prompt mismatch: the LongHorizon executor prompt may name
  `config.workspace_path`, while execution happens in a fresh remote session
  workspace. Safety inside the full `manager.run()` prompt flow is unproven,
  and that is a prerequisite test for the role-binding milestone.
  `manager.run()` compatibility is not claimed.
- `in_progress` and `unknown` runs leave a remote session that may still be
  mutating. Nothing is applied from it.
- No manager-loop integration, auditor, checkpoint, promotion, or rejection.
- All validation is offline; there is no live HarnessRouter proof.

**Status:** Implemented on `feat/longhorizon-workspace-executor`; merged into
`main` with a normal merge commit on top of `d78f1b5`.
See `03_PROGRESS_AND_EVIDENCE.md`.


---

## ADR-019 — Independent LongHorizon Workspace Auditor

**Decision:** Add `UHPWorkspaceAuditTransport` (`cloudeo.bridge.audit`) and
`UHPWorkspaceAuditorAdapter` (`cloudeo.longhorizon.workspace_auditor`). They
freeze the bound `CandidateWorkspace` into an exact snapshot, audit it in one
fresh UHP session, and return the auditor's natural-language report to
LongHorizon's own audit machinery. Nothing the auditor does remotely ever
reaches the candidate.

**Executor vs auditor:**

| | `UHPWorkspaceExecutorAdapter` (ADR-018) | `UHPWorkspaceAuditorAdapter` |
| --- | --- | --- |
| Transport | `UHPWorkspaceBridge.run()` | `UHPWorkspaceAuditTransport.run()` |
| Candidate | Mutated through a validated delta | Never mutated; the delta is evidence only |
| Remote delta | Applied | Must be empty, otherwise `auditor_workspace_mutation_detected` |
| After the run | Drift check before apply | Candidate, candidate `HEAD`, and accepted state all rechecked |
| `supports_workspace_sync` | `True` | `True`: it can inspect a synchronized snapshot |
| `workspace_access` | n/a | `read_only_snapshot`: it cannot change the candidate |
| Role | `cli_executor` only | `cli_auditor` only |

**State flow (this milestone stops at the last step):**

```
candidate A′ (dirty, UNVERIFIED)
   ↓ freeze: deterministic snapshot, content hash H
fresh UHP session (no previous_response_id)
   ↓ unpack → read-only audit → pack-delta (evidence, never imported)
LongHorizon auditor report text
   ↓
candidate still A′ (H unchanged)    accepted still A
AUDITED, BUT NOT YET ACCEPTED
```

**Separate facts and stages.** Each is established by a different component,
and none implies the next:

1. The runtime completed (`cloudeo_runtime_status == "completed"`).
2. The workspace snapshot is authentic: the candidate still equals snapshot H
   and its `HEAD`, and accepted state did not move.
3. The auditor was read-only: its remote delta was empty.
4. The audit report says `complete` (LongHorizon's parser).
5. A verification gate accepts the report (next milestone).
6. A checkpoint is created.
7. Promotion.

This milestone provides 1–3 and passes the text through to 4. It implements
nothing from 5 onward.

**Source findings (LongHorizon `ff76d6a…`, verified before implementation):**

- **`AgentAdapter` contract:** it is
  `run_episode(prompt, env, budget, live_trajectory_path=None) -> EpisodeResult`.
  The manager passes the CLI auditor as `cli_auditor_agent`, falling back to
  `auditor_agent` or `agent` when it is unbound. `_run_role_episode()` converts
  `CancelledError` into `cancelled`.
- **Auditor prompt:** `build_role_auditor_prompt()` inserts
  `workspace_path` under "Independent evidence boundary". The built-in CLI
  auditor instructions are themselves read-only ("Do not create, modify, move,
  or delete task files").
- **Control header:** the first three non-empty lines must match `Status:
  complete|incomplete|blocked`, `Integrity: clean|suspect|violation`, and
  `Contract audit: aligned|unknown|needs_revision|invalid`. English and Chinese
  keywords are accepted, and `**bold**` is tolerated. A missing header
  produces `blocked / suspect / unknown`.
- **Text extraction:** `audit_report_from_episode_result()` and
  `auditor_report_text_from_episode_result()` read the metadata key
  `assistant_visible_output` in preference to `actions_log`.
- **Non-`done` episodes:** if `EpisodeResult.status != "done"`,
  `audit_report_from_episode_result()` returns `blocked` with a synthesized
  runtime-failure report, and the auditor text is not used.
- **Native mutation guard:** LongHorizon has its own read-only guard metadata
  (`verifier_workspace_*`, produced by `adapters/claude_permissions.py`). With
  `verifier_workspace_restored` false, only deletions, and a declared
  integrity violation, LongHorizon accepts remote deletions as confirmed
  artifact deletions.
- **Format repair:** `_should_repair_auditor_format()` runs only for a `done`
  result whose header is invalid. `_should_accept_auditor_format_repair()`
  rejects the repair if the result is not `done`, has hard runtime signals, or
  shows a workspace mutation.
- **Format-repair quirk:** the manager rebuilds the corrected result with the
  repaired text in `actions_log` but the **primary** metadata. Its
  `assistant_visible_output` therefore wins, and with any adapter that sets
  that key (ADR-016) the repaired text is ignored and the report stays
  `blocked`. This fails closed and is an upstream integration issue, not
  patched here.
- **Error aborts the run:** in `manager.run()`, an auditor `EpisodeResult` with
  status `error` is classified by `classify_agent_runtime_failure()` as a
  provider failure, and the whole run aborts (`provider_*`). Only `timeout` is
  treated as recoverable. Every invalid audit from this adapter (a mutation,
  drift, staleness, or missing evidence) is `error`, so under the pinned manager
  it would end the run rather than fail a single round.

**Transport:**

1. Before anything is uploaded, only public broker calls are made:
   `inspect_candidate()` for identity and worktree, then `accepted_state()`,
   which must still equal the candidate's `base_commit`. A failure returns
   `candidate_unavailable` or `candidate_stale`, and no request is sent.
2. Freeze a `WorkspaceAuditSnapshot` with `build_input_bundle()`. It uses the
   same Git selection, deterministic archive, manifest, and limits as the
   bridge, never includes `.git` or ignored files, and has the same
   symlink/submodule restrictions. It holds `workspace_id`, `candidate_id`,
   `base_commit`, `head_commit`, the manifest, `manifest_sha256`, and the
   archive bytes.
3. Upload the helper and the snapshot, and run exactly one
   `HarnessTaskExecution` through the `ExecutionDispatcher`. It uses the
   auditor's own harness, model, step limit, and budget, with no
   `previous_response_id`. Construction requires the same `UHPClient` identity
   as the bridge (`require_single_deployment`).
4. The audit instructions say:
   - run `unpack` first;
   - the snapshot is authoritative;
   - read `AGENTS.md`, `CLAUDE.md`, `QWEN.md`, or `GEMINI.md` if present;
   - a local workspace path in the prompt means the current extracted
     directory;
   - inspect only: no repair, and no created, modified, moved, or deleted
     files;
   - send tool caches and outputs outside the project;
   - run `pack-delta` before the final answer.
5. For `completed` or `incomplete` runs, download exactly this run's output
   artifact through the shared `fetch_output_artifact()` (the same selection
   rules as the bridge). Validate it with the existing hostile-bundle
   validator (`validate_output_bundle()`), including identity and
   `input_manifest_sha256`. Then **discard** it. It is never passed to
   `apply_delta()`. For `unknown`, `in_progress`, `failed`, or `cancelled`
   runs the remote workspace is not read.
6. After the run, recheck:
   - the candidate `HEAD` must equal the snapshot's `HEAD`;
   - the candidate manifest must equal the snapshot, using the same selection
     and hashing (content, additions, deletions, and executable bits);
   - accepted state must still equal `base_commit`.

**Result mapping:** The runtime mapping is exactly ADR-016's. A `completed` run
becomes `error` when any of the following holds, in this order:

1. `candidate_stale_during_audit`: accepted state moved.
2. `candidate_changed_during_audit`: a local file changed, was added or
   deleted, changed executable bit, or the candidate `HEAD` moved.
3. `auditor_workspace_mutation_detected`: the remote delta is not empty. All
   changed paths are recorded, and executable-bit-only changes are listed
   separately as `mode_changed`.
4. `audit_evidence_invalid: <code>`: the artifact is missing or ambiguous, the
   session ID is missing, or the bundle is invalid.

In every such case the auditor's text is moved from `assistant_visible_output`
to `untrusted_auditor_output`, so LongHorizon never reads it as the role's
report. A `completed` run with none of these conditions is `done`. `failed`,
`cancelled`, `unknown`, and `in_progress` keep their ADR-016 status, and no
audit is accepted: LongHorizon reports `blocked`. `incomplete` keeps its
`timeout` or `error` mapping, and even a well-formed `complete` report from it
parses as `blocked`.

`done` means only that the runtime completed, the bound snapshot was
inspected, the auditor's remote copy was unchanged, and the candidate and
accepted state were unchanged. It is not `Status: complete`: LongHorizon's
parser decides that from the text. The adapter never repairs, rewrites, or
reinterprets the report. Format checking, format repair,
`parse_audit_report()`, the acceptance-constraint guard, and the
integrity/contract interpretation stay with LongHorizon. An empty remote delta
proves only that the auditor did not change its copy. It does not prove that
the audit conclusion is correct.

**Metadata:** All ADR-016 keys are kept, plus:

- `supports_workspace_sync: True` and `workspace_access: "read_only_snapshot"`;
- `workspace_id`, `candidate_id`, and `candidate_base_commit`;
- `audit_transport_run_id`, `audit_snapshot_head`, and `audit_snapshot_file_count`;
- `audit_snapshot_manifest_sha256`: the exact bundle sent, which includes the run
  ID;
- `audit_snapshot_content_sha256`: the audited file state, meaning every path,
  size, SHA-256, and executable bit;
- `audit_snapshot_unchanged` and `accepted_state_unchanged`;
- `auditor_remote_evidence` (`unchanged`, `mutated`, `failed`, or `skipped`)
  and `auditor_remote_workspace_unchanged`;
- `auditor_workspace_mutations` (`added`, `changed`, `deleted`,
  `mode_changed`);
- `audit_evidence_error` and `audit_invalid_reasons`;
- `independently_verified: False`, always.

When remote evidence was obtained, the adapter also emits LongHorizon's native
guard keys in the pinned shape: `verifier_workspace_guard`,
`verifier_workspace_mutation_detected`, `verifier_workspace_mutations`,
`verifier_workspace_mutation_counts`, and
`verifier_workspace_restore_on_mutation`. `verifier_workspace_restored` is set
to `True`. That is accurate: the task workspace is the candidate, which never
receives auditor writes. It also means LongHorizon never treats a remote
deletion as a confirmed artifact deletion.

**Evidence for the next gate:** The future verification gate **must not
promote merely from an auditor text report.** Before it checkpoints, it must
establish that the candidate is still exactly the audited state. It should
recompute `snapshot_content_sha256()` from the candidate with the same
selection rules, require it to equal `audit_snapshot_content_sha256`, and
require the candidate `HEAD` to equal `audit_snapshot_head`. The candidate
identity (`workspace_id`, `candidate_id`, `candidate_base_commit`) is retained
for that check. No such gate is implemented here.

**Independence:** "Independent" here means an independent execution, session,
and workspace boundary. Every audit is a new HarnessRouter session with no
`previous_response_id`. It shares no executor session, response, or remote
workspace; the only shared state is Cloudeo's deterministic snapshot. It does
**not** mean independent provider or model identity, which is not required
here. A future policy may require model or provider diversity for high-risk
audits.

**Role eligibility (exact type, fail-closed):**

| Role | `UHPHarnessAgentAdapter` | `UHPWorkspaceExecutorAdapter` | `UHPWorkspaceAuditorAdapter` |
| --- | --- | --- | --- |
| `manager` | ✅ | ❌ | ❌ |
| `final_response` | ✅ | ❌ | ❌ |
| `auditor_format_repair` | ✅ | ❌ | ❌ |
| `cli_executor` | ❌ | ✅ | ❌ |
| `cli_auditor` | ❌ | ❌ | ✅ |
| `gui_executor` | ❌ | ❌ | ❌ |
| `gui_auditor` | ❌ | ❌ | ❌ |

**Environment and trajectory:** As for the executor, the `Environment` is
accepted and never called, `live_trajectory_path` is never written, and
`manager.run()` compatibility is not claimed.

**Bridge refactor:** Artifact selection and download, and the one-deployment
check, moved from `UHPWorkspaceBridge` into shared module functions
(`fetch_output_artifact`, `require_single_deployment`) so the audit transport
reuses them. Error codes, messages, and behavior are unchanged, and all 105
bridge tests pass unmodified.

**Limitations:**

- There is no live HarnessRouter proof; all validation is offline.
- The harness must cooperate by running the helper, with Python 3.8 or later
  in its sandbox. An auditor that does not run `pack-delta` produces no
  evidence, and the audit is `error`.
- Any file an audit leaves behind counts as a mutation, including tool caches
  such as `.pytest_cache`. `__pycache__` and the root runtime directories are
  excluded by the helper.
- Public broker terminal-lifecycle limitation (ADR-018): an open candidate
  cannot be distinguished from a promoted or rejected one.
- Provider or model diversity is not required.
- `manager.run()` integration is unproven: the `workspace_path` mismatch
  (ADR-018), the format-repair metadata quirk, and the fact that an auditor
  `error` aborts the whole pinned manager run are all prerequisites for the
  role-binding milestone.
- An audit report can still be semantically wrong. An independent execution
  boundary does not make model judgment correct.
- There is no verification, checkpoint, or promotion gate yet.

**Status:** Implemented on `feat/longhorizon-workspace-auditor`; merged into
`main` with a normal merge commit on top of `f3a71cb`.
See `03_PROGRESS_AND_EVIDENCE.md`.

**Amendment (2026-09-23, `feat/longhorizon-promotion-gate`): normalized
auditor verification.** `cloudeo.longhorizon.audit_result.normalize_auditor_result(primary,
*, repair=None)` turns one auditor `EpisodeResult`, plus an optional format-repair
episode, into one `AuditorVerification`. Its `status` is `VERIFIED`,
`NOT_VERIFIED`, `BLOCKED`, or `AUDITOR_ERROR`, and it also carries a `reason`,
the report text and its source, the parsed header fields, `format_repair`,
the failure classification, and deep copies of the upstream and repair
metadata.

- **Ownership:** Cloudeo owns the normalized verification semantics.
  LongHorizon remains the execution and auditing substrate. The control
  header, parsing, acceptance-constraint guard, and runtime-failure
  classification are delegated to LongHorizon's public functions
  (`audit_report_from_episode_result`, `has_valid_auditor_control_header`,
  `classify_agent_runtime_failure`, `VISIBLE_OUTPUT_KEYS`), and LongHorizon is
  not modified.
- **Native mutation keys:** workspace mutation evidence keeps LongHorizon's own
  keys, `verifier_workspace_mutation_detected` and
  `verifier_workspace_mutations`. No competing names are introduced.
- **Fail-closed order:**
  1. A mutation is `BLOCKED`.
  2. A Cloudeo audit-boundary code (drift, staleness, invalid evidence, an
     unavailable candidate) is `BLOCKED`. `workspace_upload_failed` is
     `AUDITOR_ERROR`.
  3. A runtime or provider failure, classified by LongHorizon, or
     cancellation, is `AUDITOR_ERROR`.
  4. Missing read-only guard evidence is `BLOCKED`.
  5. A missing, ambiguous, or malformed report is `BLOCKED`.

  Only after all of these checks is the report content read.
- **Deterministic report source:** the report comes only from LongHorizon's
  visible-output metadata keys, in LongHorizon's order, and is recorded as
  `report_source`. `actions_log` is never a report source; this closes the
  manager format-repair path in which a repaired `actions_log` loses to the
  primary `assistant_visible_output`. Differing texts under several keys are
  ambiguous. The selected text is given to LongHorizon's parser as the only
  report it can see.
- **Repair restores format only.** It is not verification authority. A
  repaired report is used only when the caller passes the repair episode
  explicitly, the primary report was malformed, and the repair episode is
  itself acceptable: `done`, with no runtime failure or mutation, an
  unambiguous source, and a valid header. The repaired text, parsed fields,
  source, and repair metadata are all kept, with `format_repair="accepted"`.
  Its status is capped at `NOT_VERIFIED`: a positive repaired conclusion gives
  `report_repaired_not_verification_authority`, and a negative one gives
  `report_not_complete`. An unacceptable repair leaves the result `BLOCKED`
  (`format_repair="rejected"`). Repair is never considered when an earlier
  check has already failed.
- **No structured verification path:** no structured evidence can verify
  without the auditor's own, unrepaired conclusion. The read-only guard,
  snapshot, and accepted-state evidence prove only that the audit was
  attributable and read-only, not what it concluded. `VERIFIED` therefore
  requires the primary report itself to parse as `complete / clean / aligned`.
- **`VERIFIED` is not a checkpoint or promotion decision.** That remains the
  next milestone's gate, which must also recheck the audited snapshot.


---

## ADR-020 — Verified checkpoint and promotion gate

**Decision:** Add `cloudeo.longhorizon.promotion_gate`. It provides a read-only
`evaluate_promotion_gate()` and `checkpoint_and_promote_verified()`, which
promote a candidate only when the exact state that was audited is the state
being promoted. It closes this race:

```
audit state A → the workspace changes to state B → promotion accepts B on A's audit
```

**Verification contract:**

- `AuditorVerification` (ADR-019 amendment) is the only verification contract
  the gate consumes. The auditor's prose is never read or reinterpreted:
  changing only `report_text` does not change the decision.
- The verification must be `VERIFIED` and original, not repaired: its
  `reason` is `report_complete`, and it carries no repair provenance
  (`format_repair`, a `repair.*` source).
- The mutation evidence must explicitly prove no verifier mutation
  (`verifier_workspace_mutation_detected` is `False`, not missing), and there
  must be no audit-invalid reasons.
- The audit evidence must be present and well-formed:
  - the commit IDs and the content SHA-256;
  - the auditor's own after-audit checks, recorded as `true`
    (`audit_snapshot_unchanged`, `accepted_state_unchanged`,
    `auditor_remote_workspace_unchanged`).

**Recheck immediately before the checkpoint.** Nothing captured at audit time
is trusted:

1. The audit identity must match the candidate's workspace, candidate, and
   base.
2. Accepted state must still equal the base.
3. The current candidate `HEAD` must equal the audited `HEAD`.
4. The current content hash, computed by exactly the snapshot rules
   (`current_content_sha256`), must equal the audited content hash.

**Why the recheck alone is not enough.** `checkpoint_candidate()` commits
whatever the worktree holds at that instant, so a change between the recheck
and the commit would be checkpointed. After checkpointing, the gate therefore
verifies the checkpoint commit independently, from immutable Git objects
(`rev-parse`, `ls-tree`, `cat-file`):

- its parent equals the audited `HEAD`, or it is the audited `HEAD` itself
  when the audited state was already a checkpoint;
- its committed content hash equals the audited content hash. Symlinks and
  submodules fail.

Only that proven checkpoint is passed to `promote()`. The existing broker
checks remain authoritative and are not bypassed: `promote()` still checks the
stale base, ancestry, open/rejected state, and its atomic compare-and-swap on
accepted state. Because the promoted commit is immutable, later worktree
changes cannot reach accepted state.

**Statuses:**

| Status | Meaning |
| --- | --- |
| `VERIFIED_AND_CURRENT` | Allowed, or promoted |
| `NOT_VERIFIED`, `BLOCKED`, `AUDITOR_ERROR` | Carried over from `AuditorVerification` with its reason |
| `EVIDENCE_MISSING` | Missing or malformed audit evidence |
| `VERIFICATION_STALE` | Identity mismatch, or accepted state moved, including at promote time |
| `HEAD_CHANGED` | The candidate `HEAD` is not the audited one |
| `WORKSPACE_CHANGED` | The content hash changed, or the checkpoint differs from the audit |
| `NOTHING_TO_PROMOTE` | The audited state is the base |

Any missing, stale, ambiguous, or contradictory evidence fails closed.

**How far the gate got.** `GatedPromotionResult.stage` is
`refused_before_checkpoint`, `refused_after_checkpoint`, or `promoted`, and
`checkpoint_created` says whether this call created the checkpoint or reused
an already-checkpointed audited state. A failed post-checkpoint check or
promotion returns the checkpoint and does **not** delete it or its ref. It is
candidate history, never accepted state, and it is kept as forensic evidence.
Cleanup or rejection policy belongs to a later lifecycle layer.

**Trust boundary.** The workspace snapshot proves the audited, Git-visible
candidate state: tracked files plus untracked, non-ignored files, by content
and executable bit. It does not claim identity over ignored runtime inputs
such as `.env`, caches, external services, or undeclared environment state.
Changing an ignored file after the audit does not block promotion. Those
inputs need separate declared-input evidence if they become relevant to
verification.

**Out of scope:** LongHorizon manager behavior is intentionally outside this
milestone. That includes the abort on an auditor `error`, the format-repair
quirk, and the `workspace_path` mismatch. The gate uses only the candidate,
the public broker API, and the normalized verification. LongHorizon is not
modified.

**Limitations:**

- Executable state is compared as Git records it. A file whose execute bit is
  set only for group or others, or a repository with `core.filemode=false`,
  cannot match its audit and is refused.
- The public broker still cannot report a rejected candidate. `promote()`
  refuses one.
- There is no live HarnessRouter proof; all validation is offline.

**Status:** Implemented on `feat/longhorizon-promotion-gate`; merged into
`main` with a normal merge commit on top of `b91ab83`.
See `03_PROGRESS_AND_EVIDENCE.md`.
