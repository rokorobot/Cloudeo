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


---

## ADR-021 — LongHorizon manager run wrapped by the promotion gate

**Decision:** Add `cloudeo.longhorizon.manager_integration.run_managed_with_promotion_gate()`.
It is a thin wrapper around the pinned, unmodified `lh_harness.manager.run()`
and connects the LongHorizon round loop to Cloudeo's normalizer (ADR-019
amendment) and promotion gate (ADR-020). No Cloudeo-owned round loop is added,
and LongHorizon is not modified.

**Authority chain:**

```
LongHorizon manager:  "the objective appears complete"
        ↓
Cloudeo normalizer:   "the final audit is / is not authoritative"
        ↓
Promotion gate:       "this exact audited state may / may not become accepted"
```

Upstream `complete` is **only permission to attempt** the gate, never
sufficient for promotion. The wrapper makes no promotion decision itself. It
never calls `broker.promote()` or `checkpoint_candidate()`, never touches
`refs/cloudeo`, and never reads auditor prose. Only
`checkpoint_and_promote_verified()` decides.

**Flow:**

1. **Validate before anything runs** (fail closed):
   - Roles are bound through `bind_longhorizon_roles()`: manager, cli_executor,
     cli_auditor, auditor_format_repair, and final_response. Format repair and
     the final response default to the manager adapter.
   - The executor and auditor must be bound to the same `CandidateWorkspace` as
     the gate's candidate, through the same Workspace Broker.
   - `config.workspace_path` is set to the candidate path. A different
     non-default path is refused rather than substituted.
   - `config.harness_dir` and `config.log_dir` must lie outside the candidate,
     because upstream writes its own trace files there and they would change
     the audited state.
   - The GUI roles have no eligible Cloudeo adapter. They are bound to an
     explicit placeholder whose episode fails, so upstream never falls back to
     another role's adapter.
2. **Record episodes:** the auditor and format-repair adapters are wrapped,
   after validation, in recorders that keep each `EpisodeResult` unchanged, in
   order.
3. **Run upstream:** `manager.run()` runs unmodified.
4. **Normalize the final audit.** The last auditor episode, plus the repair
   that immediately followed it, goes through
   `normalize_auditor_result(primary, repair=repair)`, whatever the run's
   outcome. Earlier audits remain history, not authority. Stale ones would be
   refused by the gate's `HEAD` and content checks anyway.
5. **Attempt promotion only when** upstream reports
   `status == "complete"` with `completion_satisfied`. The gate's
   `GatedPromotionResult` is then authoritative.

**Not attempted vs refused.** These are different states, and a gate refusal
is never fabricated for a gate that did not run:

| Situation | `promotion_attempted` | Result |
| --- | --- | --- |
| No auditor episode, run failed | `False` | `promotion_not_attempted_reason="manager_failed_before_audit"` |
| No auditor episode otherwise | `False` | `"auditor_missing"` |
| An audit exists, but the objective is not complete | `False` | `"objective_not_complete"` |
| Gate called | `True` | `promotion_result.stage`: `refused_before_checkpoint`, `refused_after_checkpoint`, or `promoted` |

`ManagedPromotionResult` keeps both views: `upstream_report`, `verification`
(`AuditorVerification`), `promotion_attempted`,
`promotion_not_attempted_reason`, `promotion_result`
(`GatedPromotionResult`), `workspace_id`, `candidate_id`, `base_commit`,
`checkpoint_commit`, `auditor_episodes`, and `format_repair_used`.

**Upstream behavior resolved at the boundary, not by changing upstream:**

- **Auditor error:** upstream still ends the run as `failed`/`provider_*`, or
  `cancelled`, exactly as before. The recorded auditor episode is normalized
  afterwards (`AUDITOR_ERROR`, or `BLOCKED` for mutation or missing evidence).
  Because the objective is not complete, promotion is not attempted. Upstream
  status is not falsified.
- **Format-repair quirk:** the repair episode is passed explicitly to the
  normalizer, which caps a repaired report at `NOT_VERIFIED`. Even when upstream
  is forced to treat repaired prose as complete, the gate refuses it.
- **`workspace_path` mismatch:** the candidate is named explicitly as the
  workspace, and upstream's files are kept out of it. The bridge and audit
  transport already map "workspace path" to the extracted snapshot remotely.

**Limitations:**

- Upstream still ends the whole run on an auditor error. Recovering within the
  run would need upstream changes or a Cloudeo-owned loop, which is deferred.
- The objective-level completion signal comes from LongHorizon's prose parsing.
  It only permits an attempt; the gate still requires original `VERIFIED` and
  the exact audited state.
- GUI roles are not supported (no eligible adapter).
- There is no cleanup or rejection policy for refused checkpoints, and no
  Performance Memory.
- There is no live HarnessRouter proof; all validation is offline.

**Status:** Implemented on `feat/manager-promotion-integration`; merged into
`main` with a normal merge commit on top of `84e7591`.
See `03_PROGRESS_AND_EVIDENCE.md`.


---

## ADR-022 — V2 control layer above the trust kernel

**Status:** Accepted (2026-09-23); not yet implemented.

**Decision:** Cloudeo v2 adds a control layer for Projects, WorkOrders,
Execution Profiles, Memories, and Human Decisions **above** the trust kernel
(Manager → Auditor → Normalizer → Promotion Gate → Workspace Broker,
ADR-015 to ADR-021). The kernel stays unchanged and remains the sole
acceptance authority.

Cloudeo owns the project workflow: onboarding, WorkOrders, blocks, state,
envelope, and escalation. LongHorizon owns the inside of each bounded
autonomous coding episode. Cloudeo does not reimplement LongHorizon's agent
loop.

**Invariant (K1):** nothing in the control layer may write accepted state,
write `refs/cloudeo`, call `promote()`, or bypass the gate. `PROMOTED` is
reachable only from a kernel result with `promoted == true`.

**Consequences:** the contract refines `07_TARGET_ARCHITECTURE_V2.md` §4.1
(WorkOrder), specializes §4.3 (ExecutionProfile; see ADR-027), and replaces
§5 profile selection for role-bound steps with stable role bindings. Where
they disagree, the contract and ADR-022 to ADR-029 govern.

---

## ADR-023 — Project identity and in-repository Project Memory

**Status:** Accepted (2026-09-23); not yet implemented.

**Decision:**

- A **ProjectTarget** maps to exactly one Workspace Broker workspace. The broker
  remains the authority for the accepted baseline.
- **Project Memory** is the accepted description of what exists: architecture,
  components, interfaces, decisions, conventions, and limitations.
  - It is stored in **human-readable tracked documents** under per-project
    `memory_paths`, for example `docs/architecture/`, `docs/components/`, and
    `docs/decisions/`.
  - An optional machine index under `.cloudeo/project-memory/` only points into
    those documents.
  - Entries are claims with evidence anchors.
  - Credentials and secrets never belong in Project Memory.

**Update rule:**

- Canonical Project Memory advances only by promotion, together with the code
  it describes.
- Candidate memory changes only after `CODE_APPROVED`, only by the
  `memory_curator` role, and only within `memory_paths`. It then passes an
  independent Memory Audit.
- Memory never records planned or unverified work as existing.

**Reason:** tracked memory is Git-visible candidate state, inside the audited
snapshot and content hash (ADR-019, ADR-020). The existing gate therefore
proves and promotes code and memory atomically. WorkOrder Memory and
Performance Memory are separate stores and never live in the repository.

---

## ADR-024 — Context Intake is read-only and memory is a claim

**Status:** Accepted (2026-09-23); not yet implemented.

**Decision:** The `context_analyst` role reads Project Memory first, then
verifies each relevant claim against its anchors in the code at the planned
baseline. Each claim is reported as verified, contradicted, or unverifiable,
with evidence.

Intake runs on a read-only snapshot (reusing ADR-019 machinery) and never
writes to any workspace. A contradicted claim becomes a proposed memory
correction in the plan, for the user to approve.

**Reason:** memory speeds orientation, but unchecked memory would let stale
documentation steer execution.

---

## ADR-025 — Plan Approval Gate and the approved envelope

**Status:** Accepted (2026-09-23); not yet implemented.

**Decision:** No workspace write happens before the user approves a specific,
immutable plan version. The `architecture_planner` proposes architecture
changes, the `implementation_planner` turns them into blocks, and the user
decides.

The approved envelope contains:

- the snapshotted Project Execution Profile version (shown, not renegotiated);
- the blocks, their scopes, and the architecture changes;
- the acceptance criteria;
- the budget and the risk class.

Any later plan change is a new version that needs approval again. Automatic
behavior is limited to:

- running bound primaries;
- retries within budget;
- approved fallbacks, only under their defined conditions.

Material deviations always escalate (ADR-028). They are detected from
evidence: deterministic scope and path checks, normalized audit findings, and
accounting.

---

## ADR-026 — WorkOrder and ImplementationBlock state machines

**Status:** Accepted (2026-09-23); not yet implemented.

**Decision:**

- **WorkOrder states:**
  - main path: `DRAFT → CONTEXT_INTAKE → PLAN_PROPOSED → PLAN_APPROVED →
    EXECUTING → FINAL_VERIFICATION → PROMOTED`;
  - overlays: `USER_ATTENTION_REQUIRED`, `DEFERRED`, `ABORTED`.
- **Blocks:**
  - Each block runs as a **bounded LongHorizon manager run in a no-promotion,
    verify-only wrapper** (a variant of ADR-021). Deterministic acceptance
    checks and Cloudeo's normalization of the run's final audit follow.
  - That yields `CODE_APPROVED`, or another bounded run within the attempt
    budget, or `USER_ATTENTION_REQUIRED`.
  - After `CODE_APPROVED`, the executor is finished for the block. If memory
    impact exists, the `memory_curator` and then an independent
    `memory_auditor` run.
  - The block ends at `BLOCK_DONE`.

`CODE_APPROVED` requires all of the following:

- the deterministic checks pass;
- the audit of the exact current candidate state is original `VERIFIED`,
  never repaired;
- the diff is within the declared scope, or covers a user-approved deviation.

`BLOCK_DONE` additionally requires a passing Memory Audit where memory
changed, and that only `memory_paths` changed after `CODE_APPROVED`.

**Checkpoints:** an immutable candidate checkpoint is recorded through the
broker at the end of the block, not at `CODE_APPROVED`, so it holds coherent
code and synchronized memory.

The **authoritative block state** is the `HEAD` plus content hash of the last
approving audit: the code audit when no memory changed, otherwise the Memory
Audit. The ADR-020 immutable-object principle then applies, without
promotion:

1. The current `HEAD` and content hash are re-read and must equal the
   authoritative state.
2. `checkpoint_candidate()` records the checkpoint.
3. From Git objects, the checkpoint commit's parent must be the audited
   `HEAD` (or the commit must be that `HEAD`), and its content hash must equal
   the audited hash.

Only a proven checkpoint makes the block `BLOCK_DONE`. A raced checkpoint is
never labelled `BLOCK_DONE`: it stays as unaccepted candidate evidence, and
the WorkOrder raises `USER_ATTENTION_REQUIRED` with
`BLOCK_CHECKPOINT_MISMATCH`. Block checkpoints are candidate history only.

**Final verification:** the candidate is frozen, and a fresh read-only final
audit runs, then the normalizer, then the gate. No write-capable run takes
place. Executor completion, LongHorizon `complete`, `CODE_APPROVED`, and
`BLOCK_DONE` never imply acceptance.

---

## ADR-027 — ExecutionProfile hierarchy, roles, and stable role bindings

**Status:** Accepted (2026-09-23); not yet implemented.

**Decision:**

- **`ExecutionProfile`** (07 §4.3) stays the generic, routable execution
  configuration. It is specialized as `AgentProfile` (model/harness agents),
  `DirectToolProfile` (Treg), `BrowserExecutionProfile` (Browser Use), and
  `HumanExecutionProfile`.
  - Profiles are immutable once used and carry a version fingerprint.
  - The existing `HarnessExecutionProfile` is the runtime subset of an
    AgentProfile.
- **Roles** are distinct even when they map to the same profile:
  - `context_analyst`, `architecture_planner`, `implementation_planner`,
    `recovery_planner`;
  - `episode_manager`, `primary_code_executor`, `code_auditor`,
    `format_repair`;
  - `memory_curator`, `memory_auditor`, `final_verifier`, `user_reporter`.
  - Each role has a required workspace access. The `memory_curator` may write
    only `memory_paths`.
- **Project Execution Profile:** the role → primary ExecutionProfile bindings,
  with ordered fallbacks and fallback conditions.
  - It is **approved at project onboarding** and versioned in the Cloudeo
    control store. Each WorkOrder snapshots the current version.
  - Changing bindings is a separate, explicit, project-level user decision.
  - Credentials never live in the repository.

**Routing authority:**

- Runtime routing decides which role or capability a step needs, not which
  model.
- A role uses its bound primary while it is available and allowed.
- Fallbacks are used only under their defined conditions: unavailability, or
  classified runtime/provider failures after the allowed retries, or a policy
  prohibition. Every switch is recorded with evidence.
- Performance Memory and Jev never select or switch profiles.

**Independence:** auditor independence is cumulative per risk class. Each
requirement is mandatory for its class.

| Risk | Required |
| --- | --- |
| Low | a fresh session and a read-only workspace |
| Medium | low, plus a different model family from the producer |
| High | medium, plus a different inference provider from the producer |

It is measured by role against the producer of the audited change:

| Auditing role | Must be independent from |
| --- | --- |
| `code_auditor` | `primary_code_executor` |
| `memory_auditor` | `memory_curator` |
| `final_verifier` | every write-capable profile whose changes remain in the final candidate |

If a requirement cannot be met, `USER_ATTENTION_REQUIRED` is raised with
`INDEPENDENCE_UNAVAILABLE`. Cloudeo never weakens the policy automatically;
only the user may explicitly revise or waive it, and the decision is recorded.
`memory_auditor` is a separate binding; it may reference the same
AgentProfile as `code_auditor` when policy allows.

**Profile snapshot:** during normal execution a WorkOrder's profile snapshot
is immutable. An active WorkOrder moves to a new project-level version only
through `change_agent` (ADR-028) and a user-approved envelope amendment.

---

## ADR-028 — USER_ATTENTION_REQUIRED

**Status:** Accepted (2026-09-23); not yet implemented.

**Decision:** Whenever a WorkOrder cannot continue within the approved
envelope, it enters `USER_ATTENTION_REQUIRED`. Examples include:

- exhausted attempts or budget;
- a material deviation;
- an unavailable agent beyond its fallback conditions;
- unachievable independence;
- an `AUDITOR_ERROR`, or a non-`VERIFIED` audit beyond the retries;
- a memory conflict, a block checkpoint mismatch, or baseline drift;
- a promotion "not attempted" or "refused";
- a risk class that requires a human.

- One attention request shows **all** active reasons together, each with a
  severity, evidence references, and advisory suggested solutions (from the
  `recovery_planner` and Performance Memory, with their source). It supports
  free-form conversation.
- The user resolves it with `resume`, `replan`, `change_agent`,
  `change_budget`, `defer`, or `abort`.
- `change_agent` for an active WorkOrder follows a fixed path:
  1. a new Project Execution Profile version (a project-level decision);
  2. an explicit WorkOrder envelope amendment, which the user approves;
  3. the WorkOrder then references the new version and resumes.

  Nothing changes silently.
- Each decision is recorded. `resume` requires every blocking reason to be
  resolved or explicitly waived by the user.
- Kernel refusals, including `refused_after_checkpoint` (with the kept
  checkpoint as evidence), `AUDITOR_ERROR`, and baseline drift are never
  silently retried or absorbed.

---

## ADR-029 — Performance Memory is advisory and bounded by approved policy

**Status:** Accepted (2026-09-23); not yet implemented.

**Decision:** Performance Memory keeps the 09 design (trusted-label rule,
version fingerprints, cold start, learning stages). It stays separate from
Project Memory and WorkOrder Memory and never lives in the repository. It
learns only from verified labels, keyed by ExecutionProfile version
fingerprint, role, and task class.

It may **recommend** changes to the project's role bindings (a project-level
user decision), and suggest options in attention requests, always showing
sample size and uncertainty. It may **never** select or switch a profile,
including among approved fallbacks, because it predicts better performance.
It may never change an approved Project Execution Profile, plan, budget, risk
class, or independence policy. Jev used for policy follows the same bound.

**Storage:** the Cloudeo control store (SQLite initially) sits behind a
storage interface with record versions and compare-and-swap transitions, so
PostgreSQL can replace it without changing WorkOrder semantics.

---

## ADR-030 — Orchestration boundary: runtime integration above the control layer

**Status:** Accepted (2026-09-24), with three review amendments (the
WorkOrder-transition rule, lifecycle primitives, and what the evidence digest
proves); not yet implemented.

**Context:** `cloudeo.control` (ADR-022 to ADR-029) is pure. It holds the
WorkOrder and block state machines, the Project Execution Profile, and the
invariant checks, and V2C-01 (K1) forbids it to import the broker, bridge,
LongHorizon, or `subprocess`. Its remaining DEFERRED obligations all need
facts only runtime components can supply: a real `GatedPromotionResult`
(V2C-04), the broker's accepted baseline (V2C-22), runner-created
`SessionEvidence` (V2C-14/V2C-20), and later a `CheckpointProof` from Git
objects (V2C-19). `14_V2C_TRACEABILITY.md` records these as trusted runtime
inputs whose producers do not exist yet. They need one home, with one rule
for how they enter the control layer, instead of an exception for each.

**Decision:** add a package `cloudeo.orchestration`, the runtime integration
layer.

- **`cloudeo.control` stays the pure policy and state-machine layer.**
  Nothing about it changes, including V2C-01.
- **`cloudeo.orchestration` acquires trusted runtime evidence; `cloudeo.control`
  evaluates it.** Orchestration calls runtime components, observes their
  results, converts them into control-layer inputs (`KernelOutcome`, the
  accepted baseline, `SessionEvidence`, later `CheckpointProof` and
  normalized audit records), applies them only through the
  `cloudeo.control.machine` functions, and persists through `ControlStore`.
- **Scope rule (no dumping ground):** `cloudeo.orchestration` coordinates
  runtime components and converts trusted runtime observations into control
  inputs. Policy belongs in `cloudeo.control`; low-level broker, Git, bridge,
  and kernel behavior stays in its existing owning package. A change that
  decides *whether* something is allowed goes into `cloudeo.control`. A
  change to *how* a runtime component works goes into that component's
  package.
- **Orchestration never weakens or bypasses a control decision.** It may read
  a WorkOrder and invoke the public transition operations in
  `cloudeo.control.machine`, but must never construct, copy-with-changes, or
  mutate WorkOrder state directly: every WorkOrder transition goes through
  the control state machine. It also does not pick profiles or fallbacks on
  its own authority, and does not reinterpret a rejection or an attention
  request as success.
- **Promotion stays gate-owned (K1 still applies).** Direct `promote()` is
  permanently forbidden outside the authorized promotion gate; orchestration
  may invoke that gate (`checkpoint_and_promote_verified()`, or
  `run_managed_with_promotion_gate()` which calls it), and never writes
  `refs/cloudeo`. In the V2C-04/V2C-22 slice, orchestration also makes no
  direct `checkpoint_candidate()`, `reject()`, or `cleanup()` calls. Any
  future use of those lifecycle primitives, including V2C-19 block
  checkpointing, requires an explicitly owned adapter and decision and must
  not create an alternate promotion path.

**Dependency direction** (one way):

| Package | May import | Must not import or call |
| --- | --- | --- |
| `cloudeo.control` | standard library, pydantic, `cloudeo.workspace.models` | `cloudeo.orchestration`; broker, bridge, LongHorizon, `subprocess` (V2C-01, unchanged) |
| `cloudeo.orchestration` | `cloudeo.control`; the `WorkspaceBroker` protocol and `cloudeo.workspace.models`; the gate entry points and result types in `cloudeo.longhorizon` | `cloudeo.workspace.git` (the concrete implementation is injected); `subprocess`; direct `promote()` calls (permanently); direct `checkpoint_candidate()`, `reject()`, `cleanup()` calls (in the first slice; see above); `refs/cloudeo` or `update-ref` strings |
| authorized gate (`cloudeo.longhorizon.promotion_gate`) | unchanged | unchanged; it remains the only promotion path |

V2C-01 stays scoped to `cloudeo.control`. It does not forbid orchestration to
import the runtime interfaces orchestration exists to integrate.

**Mechanical checks** (added with the first implementation slice, in the style
of the V2C-01 AST checker, each with a negative test against violating code):

1. `cloudeo.control` imports nothing from `cloudeo.orchestration`.
2. `cloudeo.orchestration` makes no `promote` attribute call (a permanent
   check). In the first slice it also makes no `checkpoint_candidate`,
   `reject`, or `cleanup` attribute call; that part of the check changes only
   with the explicit decision a lifecycle adapter requires. It imports
   neither `cloudeo.workspace.git` nor `subprocess`, and has no
   `refs/cloudeo` or `update-ref` string.
3. All WorkOrder transitions go through the control state machine. An
   AST-based check that `cloudeo.orchestration` never constructs a
   `WorkOrder` (or a record nested in one), never derives a changed copy of
   one (`evolve`, `model_copy`, `model_validate`, `model_construct`, or an
   equivalent), and never assigns to its attributes. It changes a WorkOrder
   only by calling functions from `cloudeo.control.machine` and persists it
   only through `ControlStore`. The check is scoped to WorkOrder state, so an
   unrelated object with an `evolve()` method is not rejected; a textual scan
   for `.evolve(` may be kept as an extra, coarser check.

**First slice (V2C-04 and V2C-22 only):**

- **V2C-04:** one deterministic function `GatedPromotionResult → KernelOutcome`:
  - `promotion_attempted = True` (the gate ran);
  - `stage` = the result's `stage`;
  - `checkpoint_commit` = `checkpoint.commit` when a checkpoint exists, else
    `None`;
  - `reason` = `decision.reason`;
  - `evidence` = `EvidenceRef(kind="gated_promotion_result",
    ref=<digest>)`, so the same result always maps to the same outcome. The
    digest is domain-separated and versioned: SHA-256 over the tag
    `gated-promotion-result:v1` followed by the canonical serialization of
    the result. Another evidence type, or a later serialization, therefore
    never produces a digest with the same meaning. The digest identifies the
    canonical contents of the observed `GatedPromotionResult`; it is an
    integrity/content reference, not proof that the result came from an
    authorized gate.
  - It fails closed: if the result is internally inconsistent (for example
    `stage == "promoted"` without a checkpoint or a `PromotionResult`), it
    raises instead of producing an outcome. The mapped
    `KernelOutcome.promoted` must equal `GatedPromotionResult.promoted` for
    every input.
- **V2C-22:** read `WorkspaceBroker.accepted_state()` and pass its
  `accepted_commit` into the existing `accepted_baseline=` parameters
  (`start_intake`, `attach_candidate`, `start_execution`,
  `enter_final_verification`, `decide`, `resume_deferred`). Its `workspace_id`
  must equal the candidate's once one is attached. Drift handling stays
  entirely in `cloudeo.control`.
- Validation stays offline: a real `GitWorkspaceBroker` on a temporary
  repository, and gate results produced by the real gate.

**Trust boundary:** the control layer still cannot tell who built a record;
any caller can construct a `KernelOutcome` or pass a baseline. As with
`SessionEvidence`, ENFORCED for V2C-04 and V2C-22 will mean: the
orchestration path is the producer, it is tested against the real gate and
broker, and the mechanical checks hold. It will not mean that the control
layer authenticates its inputs.

**Explicitly not in this ADR's first slice:**

- V2C-02 (dispatch only through `begin_attempt`), V2C-09 (execution-time
  `memory_paths` restriction), V2C-19 (block checkpoints), and V2C-20 (the
  final verification runner). The new package does not make them in scope.
- The `SessionEvidence` producer for code and Memory Audits (the open
  obligation in `14_V2C_TRACEABILITY.md`). It belongs to orchestration, in a
  later slice.
- Mapping `ManagedPromotionResult` "not attempted" outcomes. No manager run is
  invoked in this slice.
- Any change to the kernel, broker, bridge, adapters, gate, or LongHorizon.

**Project-to-workspace binding (limitation):** before a candidate is
attached (at intake), nothing yet says which workspace belongs to a
WorkOrder's project; the contract's `ProjectTarget` (§4.1) is not
implemented. The first slice takes the broker for the project's workspace as
an explicit argument, rather than inventing a project-to-workspace registry.
It proves that orchestration reads the broker's actual `accepted_state()` and
records its `workspace_id` and `accepted_commit`. It does not prove that the
caller supplied the broker belonging to that project. That binding remains a
future obligation once the project-target model exists.

**Consequences:** each deferred obligation gets one place for its producer,
and one rule for how that producer's output reaches policy. The package
boundary is mechanically checked from the first line of code, so it cannot
erode silently.

---

## ADR-031 — Session Fabric and Coordination Store boundary

**Status:** Accepted (2026-10-01); architecture only, not yet implemented.
Amended 2026-10-01 before acceptance: the Session Fabric runtime contracts
and every concrete fabric adapter live in `cloudeo.execution` (see "Package
boundary"). ADR-035's boundary is preserved.

**Supporting document:** `16_SESSION_FABRIC_AND_COORDINATION_STORE.md` holds
the rationale, diagrams, and examples. This entry is the decision record and
is normative on its own. Where the two differ, this entry governs.

**Context:** long-running autonomous work needs several independently
steerable sessions (coordinator, implementer, researcher, auditor, reviewer).
They must be created and terminated, stay observable, exchange messages, hand
work over, survive coordinator restarts, and report identity, environment,
usage, cost, and failures across several execution providers. Provider
runtimes offer some of this natively, but their semantics differ and change
independently.

**Decision:** Cloudeo adds a provider-neutral **Session Fabric** and
**Coordination Store**. Session and coordination policy and lifecycle state
live in `cloudeo.orchestration`; the Session Fabric runtime contracts and
every adapter live in `cloudeo.execution` (see "Package boundary"). Together
they provide durable lifecycle, communication, observability, runtime
coordination, provenance, and resource accounting for independently
addressable agent sessions, without giving those sessions authority over
WorkOrder state, accepted workspace state, promotion, human approval, or
policy.

- Cloudeo owns the coordination semantics. Provider APIs supply execution and
  transport capabilities only.
- A provider-native session is an execution resource. It is never itself a
  Cloudeo authority.
- The governing layering of authority is execution providers and runtimes →
  Session Fabric → Cloudeo orchestration → Cloudeo control → trust kernel,
  never the reverse. Package import directions are those of ADR-030 and
  ADR-035.
- `cloudeo.control` remains provider-blind. It does not import or depend on
  Session Fabric, provider session APIs, messaging transports, runtime
  coordination records, or cloud-specific execution types.

The decision introduces five logical concepts: `Session`,
`SessionFabricAdapter`, `SessionSupervisor`, `CoordinationMessage`, and
`CoordinationStore`. They belong to the orchestration and runtime side. They
do not become part of the pure control state machine.

**Package boundary (ADR-035 governs):**

- `cloudeo.execution` owns the provider-neutral Session Fabric runtime
  contracts: the `SessionFabricAdapter` contract, its capability
  descriptions, and the observation DTOs an adapter returns (runtime status,
  requested and observed identity, usage, cost, and failures).
- Every concrete provider-specific fabric adapter (Claude Code, Codex, Kimi,
  or any other provider) also lives in `cloudeo.execution`. None lives in
  `cloudeo.orchestration`.
- `cloudeo.orchestration` owns Session and coordination policy and lifecycle
  state: `SessionSupervisor`, Session records and identities, leases,
  coordination records, and the Coordination Store. It consumes only the
  neutral execution contracts and builds its records from their
  observations. It never defines a provider adapter interface that execution
  must implement, and never imports, names, or branches on a
  provider-specific implementation module or type.
- `cloudeo.execution` never imports `cloudeo.orchestration` or
  `cloudeo.control`.
- **Session Fabric lifecycle operations are a separate execution service
  boundary.** `create_session`, messaging, handover, `terminate_session`, and
  the other fabric operations are offered by `cloudeo.execution` through the
  Session Fabric contracts, and orchestration reaches adapters only through
  that boundary. They are not execution request kinds and are not routed
  through `ExecutionDispatcher`, which remains the router for execution
  request kinds only (ADR-035).
- `SessionFabricAdapter` names the neutral contract, never a
  provider-specific class.

**Session:** a Session is an independently addressable runtime context
executing one Cloudeo role or bounded responsibility.

- A normalized Session identity records at minimum:
  - `session_id`;
  - `provider`, `runtime`, `profile_fingerprint`, `role`;
  - `project_id`, `workorder_id`, and `block_id` / `attempt_id` when
    applicable;
  - `parent_session_id` when applicable;
  - `workspace_binding`, `access_mode`;
  - `fabric_provider`, `fabric_region`, `runtime_class`,
    `runtime_instance_id`;
  - `runtime_environment`, `runtime_environment_version`,
    `runtime_environment_fingerprint`;
  - `created_at`, `last_activity_at`, `runtime_status`.
- Additional runtime metadata may include `requested_model`, `actual_model`,
  `requested_harness`, `actual_harness`, `provider_session_id`,
  `capabilities`, `usage`, `runtime_cost`, and `termination_reason`.
- Requested and observed runtime identity stay separate whenever the provider
  may substitute or omit identity information.
- Runtime-environment identity must be stable enough to explain or reproduce
  the environment in which a governed Session executed. The architecture must
  not depend on any one environment technology (VM image, container image,
  provider cloud environment, local reproducible environment, or a future
  format).
- A Session's runtime status is observational runtime evidence. It never
  means WorkOrder success, `CODE_APPROVED`, `BLOCK_DONE`, `VERIFIED`,
  `PROMOTED`, or human approval. Those meanings stay with their existing
  authorities.

**Lifecycle:** provider-specific session states are normalized into a small
Cloudeo lifecycle such as `STARTING`, `RUNNING`, `IDLE`, `HANDOVER`,
`TERMINATING`, `TERMINATED`, `FAILED`, and `LOST`. The fabric adapter maps
native state onto it and may keep richer native state separately.

- `LOST` means Cloudeo can no longer reliably observe the runtime session. It
  must never be normalized to successful completion.
- A provider reporting that a session completed means only that the runtime
  ended normally. It does not advance a WorkOrder.

**Session Fabric:** the provider-neutral runtime boundary through which
Cloudeo manages addressable sessions.

- A `SessionFabricAdapter` supports operations equivalent to
  `create_session`, `inspect_session`, `send_message`, and
  `terminate_session`.
- Optional capabilities may include `wake_session`, `resume_session`,
  `steer_session`, and `list_runtime_sessions`. These are capabilities, not
  assumptions. Cloudeo must not require every provider to expose identical
  native session features; capability discovery determines what a fabric can
  actually do.
- Provider-native features (cross-session messaging, cloud session creation,
  remote control, CLI processes, local harness processes, cloud VM workers)
  are adapter mechanisms and stay behind their Session Fabric adapters in
  `cloudeo.execution`.
- Provider-specific concepts must not leak into WorkOrder,
  ImplementationBlock, the control state machine, promotion semantics,
  verification semantics, HumanDecision, or Project Execution Profile
  semantics, and no provider-specific type may appear in
  `cloudeo.orchestration`. A provider transport may be replaced without
  changing those contracts.

**SessionSupervisor:** the orchestration component responsible for runtime
session lifecycle.

| It may | It may not |
| --- | --- |
| create sessions required by an approved execution step | construct or mutate WorkOrder state directly, or derive a changed WorkOrder copy |
| attach the correct role and ExecutionProfile | alter an approved plan |
| bind the permitted workspace and an approved runtime environment | alter Project Execution Profile bindings |
| observe runtime state and route messages | choose an unapproved model or provider |
| perform allowed handover and terminate sessions | weaken auditor-independence requirements |
| record runtime usage and cost | grant human approval |
| replace or retry a failed runtime only where existing policy permits it | promote or reject accepted workspace state directly |

All WorkOrder transitions continue through the public `cloudeo.control`
state-machine boundary established by ADR-030.

**Child sessions are requests, not authority:** a coordinator session may
decide that more work would benefit from another session. That gives it no
authority to create arbitrary Cloudeo workers. Its request goes to
`SessionSupervisor`, which checks, before any session is created:

- the role is approved;
- the request is inside the approved envelope;
- the profile is approved;
- budget is available;
- independence is preserved;
- the runtime environment is allowed;
- the workspace access is valid.

A provider-native `create_session` facility may perform the final operation,
but it never bypasses this decision point.

**Coordination Store:** a durable store for operational records shared
between orchestration instances and sessions.

- It stores sessions, session relationships, messages, delivery state,
  handover records, runtime observations, execution and job references,
  artifact references, structured feedback and friction reports, usage and
  cost observations, runtime capability observations, and
  runtime-environment provenance. It may also store non-authoritative
  operational notes or evidence references.
- It is not a second control plane.
- It extends the persistence architecture of the control store (ADR-029
  storage rule, V2C-23) and does not create an independent knowledge-base
  authority. Initially both may use the same physical SQLite database. They
  remain logically separate namespaces and interfaces with different
  authority:
  - control records: WorkOrders, plans, envelopes, profile snapshots,
    attention state, HumanDecisions;
  - coordination records: sessions, messages, handovers, runtime
    observations, environment provenance, usage, costs, artifacts, feedback.
- Physical co-location does not permit coordination code to mutate control
  records directly. Only the public control interfaces may transition control
  state.
- **No duplicate source of truth.** Coordination records may reference
  `project_id`, `workorder_id`, `block_id`, `attempt_id`, `candidate_id`,
  `profile_fingerprint`, `approval_id`, `artifact_id`, and
  `runtime_environment_fingerprint`. They must not keep competing mutable
  copies of the authoritative objects behind those identifiers. The
  Coordination Store is not the WorkOrder authority, not the Workspace
  Broker, not Project Memory, and not the Performance Memory authority.
  Derived projections may be cached for UI and read purposes, but the
  authoritative source must remain identifiable.
- **Project Memory stays distinct (ADR-023 unchanged).** A session may write
  operational notes, proposals, findings, or feedback into the Coordination
  Store. Those records do not become Project Memory because agents agree
  with them. The only path is: session finding → operational record or
  proposal → approved memory-curation flow → candidate Project Memory →
  independent Memory Audit → promotion → canonical Project Memory.
- **Storage and concurrency.** The store follows the control store's
  principles: durable identifiers; record versions where records are
  mutable; compare-and-swap or transactional updates where races matter;
  idempotency identifiers for retried operations; append-oriented history
  where appropriate. SQLite is sufficient initially. The storage interface
  must not expose SQLite-specific semantics to `SessionSupervisor` or
  control code, so PostgreSQL or another durable backend may replace it.
  Concurrent operational writes by several sessions must not require Git
  merges or shared markdown-file locking.

**What sessions may write:** sessions write only through narrow Cloudeo APIs
appropriate to their role. They never receive unrestricted database mutation
access.

| Coordination operations | Not coordination operations |
| --- | --- |
| record a finding, message, or feedback | set WorkOrder state |
| acknowledge a message | mark a block approved |
| record a runtime observation | change the plan |
| record runtime-environment provenance | change a profile |
| register an artifact | grant approval |
| request a child session | promote a candidate |
| request handover | change the accepted baseline |

The right-hand operations must use their existing authoritative boundaries.

**Messaging:** a `CoordinationMessage` is the durable Cloudeo representation
of session-to-session communication.

- It contains at minimum `message_id`, `sender_session_id`,
  `recipient_session_id`, `project_id`, `workorder_id`, `block_id` when
  applicable, `kind`, `payload`, `created_at`, `delivery_state`, and
  `acknowledged_at` when known.
- Kinds may include `QUESTION`, `ANSWER`, `FINDING`, `PROPOSAL`, `BLOCKED`,
  `HANDOVER`, `REVIEW_RESULT`, `COMPLETED`, and `CONTEXT_UPDATE`. The set may
  evolve without changing WorkOrder semantics.
- The message is logically separate from the transport that delivers it. A
  native transport failure does not erase the logical message record.
  Delivery must be idempotent, so a transport retry never creates a second
  logical instruction.
- **Messages carry information, not authority.** A session message is
  untrusted runtime input. A message saying the user approved something is
  not approval, whether first-hand or relayed. Human authority must
  reference an actual Cloudeo HumanDecision or other existing approval
  record. A message may reference an `approval_id`; it cannot create
  approval, enlarge its scope, change its expiry, or transfer authority
  beyond the recorded decision. This holds even when the provider supports
  trusted peer messaging.
- **Shared state over conversational reconstruction.** Project-relevant
  runtime facts another worker needs later (artifact references, test
  evidence, runtime results) are recorded as durable structured records.
  Direct messages remain appropriate for questions, clarifications, urgent
  findings, handover, and temporary coordination. Durable project state is
  not inferred from chat history when a structured record exists.

**Workspace authority (ADR-015 and the trust-kernel ADRs unchanged):**

- A provider session filesystem is execution state only. It is never
  accepted state, canonical workspace state, proof of verification, or proof
  of promotion.
- Each session receives an explicit workspace binding appropriate to its
  role:

  | Session | Binding |
  | --- | --- |
  | write-capable executor | CandidateWorkspace |
  | auditor | read-only audited snapshot |
  | context analyst | read-only snapshot |
  | final verifier | frozen read-only candidate |

- Session continuation, provider workspace persistence, VM persistence, and
  image persistence cannot substitute for a Workspace Broker checkpoint.
- **One mutable writer.** The first implementation permits at most one
  write-capable Session at a time for a given mutable CandidateWorkspace.
  Parallel work is permitted on separate candidate workspaces, separate
  isolated execution jobs, read-only snapshots, and non-workspace tasks.
  Conversational coordination is never treated as protection against
  concurrent filesystem mutation. Safe partitioned multi-writer execution
  needs a future ADR.
- **Handover.** Sessions may overlap so a successor can get clarification
  from its predecessor. Handover never implies concurrent write authority.
  For a mutable candidate:
  1. the predecessor stops being the active writer;
  2. its relevant durable state and evidence are recorded;
  3. the successor receives the write binding;
  4. the predecessor may remain available for read-only clarification;
  5. the predecessor is later terminated.

  A handover message cannot transfer policy or approval authority.

**Independence and routing (ADR-027 unchanged):**

- A fresh session is not automatically independent enough for every risk
  class. `SessionSupervisor` records the observed execution identities
  needed to evaluate independence, where available: profile fingerprint,
  model family, inference provider, runtime and harness, session identity,
  workspace access, and runtime-environment fingerprint. Control policy
  decides whether independence is satisfied.
- Session Fabric must not silently weaken independence because a desired
  runtime is unavailable. If the approved requirements cannot be met, the
  existing `INDEPENDENCE_UNAVAILABLE` / `USER_ATTENTION_REQUIRED` path
  applies.
- Session Fabric introduces no autonomous model shopping. A runtime session
  is created from the WorkOrder's snapshotted Project Execution Profile:
  the bound primary, then an approved ordered fallback only if an approved
  fallback condition occurs. `SessionSupervisor` records every actual
  runtime identity and switch. It may not select a provider because it looks
  cheaper, faster, or more capable.

**Economics are evidence, not policy:** Session Fabric exposes observed
usage and cost (runtime duration, runtime class, runtime cost, model and
token usage, provider cost when available, network and storage observations
when relevant). It does not decide whether a cheaper or more expensive
resource should be used. Economic optimization belongs to the COST policy
(ADR-033) and stays subordinate to control.

**Failures and ambiguity:** a lost, unreachable, timed-out, or ambiguously
terminated provider session is recorded as runtime evidence. It never
fabricates a WorkOrder result. The path is: runtime observation →
orchestration classification → control input → retry, fallback, or
`USER_ATTENTION_REQUIRED`. Retry or replacement occurs only where the
approved envelope and existing policy allow it. Unknown runtime state fails
closed wherever continuing would need positive evidence.

**Observability and audit:**

- Mission Control may read the Session Fabric projection: sessions and their
  status per WorkOrder, messages, runtime identity, runtime environment,
  workspace binding, usage, cost, artifacts, failures, and handover history.
  It remains an observer and controller over Cloudeo state. Missing runtime
  evidence is shown as unavailable or unknown, never invented.
  Provider-native UI is supplementary observability, not Cloudeo authority.
- After a run, the coordination layer must be able to answer: which sessions
  existed and why each was created; which role and profile each executed;
  which provider, model, and runtime actually ran; which runtime environment
  and version; which fabric region and runtime class; which workspace it
  could access; who created or requested it; what it sent and received; what
  artifacts and evidence it produced; when handover occurred; how much it
  consumed and cost; why it was stopped or replaced; and which human
  approvals it referenced. Provider-native session history alone is not a
  sufficient durable audit record.
- **Feedback channel.** Sessions may record structured feedback about their
  operating environment (missing tool, stale instruction, permission
  friction, flaky test, unexpected cost, mis-sized VM, repeated setup work).
  Feedback is evidence for later triage. It never authorizes an agent to
  rewrite policies, permissions, project instructions, execution profiles,
  or architecture. Any resulting change follows the normal decision path.

**Security boundary:** Session Fabric preserves least authority.

- Credentials are supplied through runtime secret mechanisms. They are never
  stored in reusable runtime images, coordination messages, or Project
  Memory.
- One session cannot grant another session new privileges or user consent.
- Runtime messages are untrusted input.
- Provider-native session creation does not bypass Cloudeo authorization.
- Provider-native shared filesystems do not become accepted state.
- Coordination records cannot directly mutate Workspace Broker refs or
  WorkOrder state.
- Write-capable workspace access is explicitly bound and auditable.

A compromised worker therefore stays bounded by Cloudeo's control and
workspace boundaries.

**Architecture checks:** enforced mechanically where practical.

| Check | Rule |
| --- | --- |
| SF-01 dependency direction | `cloudeo.control` must not import `cloudeo.orchestration`, Session Fabric, or provider adapters. `cloudeo.execution`, including every fabric adapter, must not import `cloudeo.orchestration` or `cloudeo.control` (ADR-035). |
| SF-02 no WorkOrder mutation | Session and coordination code must not construct a changed WorkOrder, mutate one, or perform WorkOrder transitions outside the public control machine. |
| SF-03 no promotion bypass | Session and coordination code must never call Workspace Broker `promote()` or modify Cloudeo refs directly. |
| SF-04 no authority in messages | No `CoordinationMessage` may itself satisfy a human-approval requirement. |
| SF-05 provider neutrality | No provider-specific session type may appear in WorkOrder, control-machine, or kernel contracts, or in `cloudeo.orchestration`. Concrete provider-specific fabric adapters exist only under `cloudeo.execution`. Orchestration imports no provider-specific implementation module or type and defines no adapter interface for execution to implement. |
| SF-06 profile discipline | Every governed Session references the approved, snapshotted execution profile under which it was created. |
| SF-07 workspace discipline | Every workspace-capable Session has an explicit access mode and workspace binding. |
| SF-08 single mutable writer | At most one active write-capable Session holds the mutable binding for the same CandidateWorkspace in the initial implementation. |
| SF-09 completion is not verification | No provider or session completion status maps directly to `CODE_APPROVED`, `BLOCK_DONE`, `VERIFIED`, or `PROMOTED`. |
| SF-10 actual identity is evidence | Requested provider, model, or harness identity must not be substituted for observed actual identity when the runtime reports them separately. |
| SF-11 durable coordination | Cloudeo-significant session creation, handover, and cross-session messages have durable coordination records independent of provider-native UI. |
| SF-12 unknown fails closed | Loss of reliable session or runtime observation must never fabricate successful completion. |
| SF-13 reproducible runtime provenance | Every governed Session records the runtime-environment identity and version, or an explicit `unknown` / `unavailable` state. |
| SF-14 economics are observational | Session Fabric may record runtime cost and usage but must not change provider, model, or runtime policy for economic reasons. |

These checks are not yet traced in `14_V2C_TRACEABILITY.md`.

**Non-goals:** this ADR does not introduce a provider-specific (Claude) or
Ubicloud-specific core architecture; unrestricted self-spawning agents;
arbitrary agent-created database schemas; agent-to-agent delegation of human
consent; multi-writer mutable candidate workspaces; automatic modification of
Project Execution Profiles; automatic policy learning; automatic Project
Memory mutation; a replacement for the Workspace Broker, the trust kernel,
or WorkOrder state; CPU/GPU fleet scheduling or general distributed-compute
scheduling; an economic optimization policy; or a requirement for always-on
cloud execution.

**Relationship to prior ADRs:** this ADR extends and does not supersede
ADR-015 (the Workspace Broker owns accepted state), ADR-020 and ADR-021
(verification and promotion-gate authority), ADR-022, ADR-023, ADR-025,
ADR-026, ADR-027, ADR-028, ADR-029, and ADR-030. Where Session Fabric
acquires runtime evidence, ADR-030 governs how it enters control. Where it
executes work, the Workspace Broker and trust kernel govern accepted state.
ADR-032 chooses a first concrete cloud implementation and ADR-033 optimizes
among permitted runtime choices, neither changing this boundary. ADR-035
governs where provider-specific code lives and the import directions between
`cloudeo.control`, `cloudeo.orchestration`, and `cloudeo.execution`. This
ADR does not amend it.

**Implementation gate:** no provider-specific multi-session implementation
begins until this ADR is accepted. After acceptance, work proceeds in bounded
slices, each preserving the checks above before the next begins:

1. **Contracts only:** Session identity and normalized status,
   runtime-environment provenance, `CoordinationMessage`, fabric
   capabilities, narrow store protocols. The fabric runtime contracts and
   observation DTOs go in `cloudeo.execution`; Session and coordination
   records go in `cloudeo.orchestration`.
2. **Durable Coordination Store:** SQLite implementation, migrations,
   concurrency and idempotency tests, no provider integration.
3. **`SessionSupervisor` with a fake fabric:** lifecycle, messaging,
   child-session authorization, the single-writer invariant, handover,
   failure semantics.
4. **First real fabric adapter, under `cloudeo.execution`:** provider-native
   session lifecycle and messaging, with no control semantic changes and no
   provider-specific import in orchestration.
5. **Mission Control projection:** sessions, relationships, messages, runtime
   identity, runtime-environment provenance, usage and cost, and
   unknown/unavailable state.

**Consequences:** Cloudeo owns coordination semantics and authoritative
workflow state; providers supply execution and communication capabilities. A
session may observe, reason, execute, communicate, and propose. It may not
acquire authority merely by coordinating with another session. Independently
addressable sessions become an execution capability of Cloudeo, compatible
with Claude, Codex, Kimi, and future runtimes, and unable to bypass the
existing verification and promotion kernel.

---

## ADR-032 — Cloud Execution Fabric and reproducible runtime environments

**Status:** Accepted (2026-10-01); infrastructure architecture only, not yet
implemented. Amended 2026-10-01 before acceptance: the fabric contracts and
the Ubicloud-specific implementation live in `cloudeo.execution` (see
"Package boundary"), and provider credentials are confined to the
provider-specific execution adapter (see "Network and secrets").

**Supporting document:**
`17_CLOUD_EXECUTION_FABRIC_AND_RUNTIME_ENVIRONMENTS.md` holds the rationale,
diagrams, examples, and the Ubicloud source references. This entry is the
decision record and is normative on its own. Where the two differ, this entry
governs.

**Context:** Cloudeo needs execution environments that are isolated,
reproducible, disposable, programmatically provisioned, auditable,
cost-observable, fast to create, suitable for Claude, Codex, Kimi, and future
runtimes, and independent of any one AI provider's proprietary cloud session
environment. It must be able to say where a Session ran, in which
environment and image version, on which compute class and network, at what
cost, and whether the environment was destroyed afterwards.

**Decision:** Cloudeo adds a provider-neutral **Cloud Execution Fabric**
beneath the Session Fabric of ADR-031. It provisions, observes, and destroys
the isolated compute environments in which governed Sessions may run.

- The first managed implementation targets **Ubicloud**, with the initial
  European deployment in Ubicloud's `eu-central-h1` location.
- Ubicloud is the preferred initial managed compute substrate, not an
  architectural dependency of Cloudeo.
- The layering is `SessionSupervisor` → Session Fabric → Cloud Execution
  Fabric → a concrete fabric (`UbicloudFabric`, or a local or future fabric)
  → an isolated runtime.
- Cloud-specific types and APIs must not leak into `cloudeo.control`,
  `cloudeo.orchestration`, WorkOrder semantics, verification semantics, or
  the trust kernel.
- The Cloud Execution Fabric does not own WorkOrder policy.

The decision introduces `CloudExecutionFabric`, `CloudRuntimeSpec`,
`RuntimeEnvironmentSpec`, `RuntimeInstance`, `RuntimeEnvironmentArtifact`,
and `RuntimeObservation`. For a Session request passed by
`SessionSupervisor`, the fabric chooses an approved runtime specification,
provisions an isolated instance, attaches network and security policy,
injects ephemeral bootstrap material, observes lifecycle and usage, and
destroys the instance.

**Package boundary (ADR-035 governs):**

- The provider-neutral Cloud Execution Fabric contracts and observation
  types named above live in `cloudeo.execution`.
- The Ubicloud-specific implementation (`UbicloudFabric`, with every
  Ubicloud API type, identifier format, and constraint check) also lives in
  `cloudeo.execution`, as does any later cloud implementation.
- `cloudeo.orchestration` consumes only the neutral contracts. No
  Ubicloud-specific type appears in it, and it defines no fabric interface
  for execution to implement.
- `cloudeo.execution` never imports `cloudeo.orchestration` or
  `cloudeo.control`.
- Provisioning operations, like Session Fabric lifecycle operations
  (ADR-031), are not execution request kinds and are not routed through
  `ExecutionDispatcher`.

**Scope against ADR-031:** ADR-031 defines what a governed Session is and
stays valid whatever the substrate (a provider-managed cloud environment, a
local runtime, an Ubicloud VM, a future cloud VM, or a future container or
sandbox fabric). This ADR specializes only the cloud-hosted isolated-worker
path.

**Ubicloud is an implementation, not the architecture:**

- The first implementation uses Ubicloud's managed service, not self-hosted
  Ubicloud. Cloudeo chooses the location, runtime class, runtime-environment
  image and version, network and security configuration, and lifecycle.
  Ubicloud remains responsible for physical host placement and the
  underlying infrastructure.
- **Physical-host opacity.** Cloudeo must not depend on knowing which
  bare-metal server hosts an instance, and does not schedule individual
  hosts. It cares about the declared location, runtime class, architecture,
  environment identity, provider instance identity, and observed execution
  properties. Host selection, if a future self-hosted fabric offers it,
  belongs to that adapter and a later scheduling policy.
- The interface must permit other implementations (a local VM fabric, AWS,
  Azure, GCP, direct Hetzner, on-premises, a future sandbox provider).
- No WorkOrder or control-layer object may require an Ubicloud-specific VM,
  project, firewall, subnet, image, or location type. Provider-native
  identifiers such as `fabric_provider`, `fabric_region`,
  `runtime_instance_id`, and `runtime_class` are runtime provenance held as
  orchestration evidence, not control semantics.
- Current Ubicloud Machine Image constraints (the source VM must be stopped
  and have a single disk of at most 40 GiB; a VM created from the image
  needs a boot disk at least as large as the captured disk) are adapter
  facts as of 2026-09-28. The Ubicloud adapter must enforce or surface them.
  The generic fabric must not encode a universal 40 GiB limit.

**Reproducible runtime environments:**

- Cloud worker VMs start from a reproducible, versioned runtime environment.
  For Ubicloud the preferred mechanism is an Ubicloud Machine Image (UMI),
  built from a clean base OS plus Python/uv, Node/pnpm, Git, the Cloudeo
  runtime, the UHP client, common build and test tooling, telemetry and
  bootstrap support, and approved agent-runtime dependencies.
- A reusable image must not contain provider API secrets, GitHub
  credentials, user credentials, long-lived tokens, project-specific
  secrets, accepted project state, or mutable WorkOrder state. Those are
  injected only at runtime through approved secret and bootstrap mechanisms.
- **Immutable pinning.** A governed WorkOrder executes against an immutable
  runtime-environment version or fingerprint. A moving alias such as
  `latest` may be used for development convenience but is never the
  authoritative runtime identity of an execution that must be reproducible.
  The record carries the kind, name, version, and immutable fingerprint.
  Where a provider exposes both a friendly version label and an immutable
  native identifier, Cloudeo records both.
- **Environment identity is generic** (for example `ubicloud-machine-image`,
  `container-image`, `local-environment-lock`, `provider-cloud-environment`).
  The control layer must not need to understand how an image was built.
- **Image strategy.** There is at least one small production worker image,
  `cloudeo-worker`. A separate `cloudeo-eval` image may hold evaluation
  tooling that would otherwise bloat it. The architecture permits several
  approved, purpose-specific images (browser, GPU, security-audit workers)
  and avoids installing every tool into every worker. Project repositories,
  candidate workspaces, and secrets are normally materialized after instance
  creation, not baked into the image.
- **Build discipline.** Images come from a reproducible, documented build,
  not manually configured snowflake VMs: environment definition → candidate
  image → bootstrap validation → toolchain validation → security and
  sanitization check → capture of an immutable version → recorded
  fingerprint and version → eligible for governed execution. A failed build
  never moves a production alias automatically. Rollback selects an earlier
  known-good immutable version.
- **Update policy.** Images are updated intentionally (security patches, OS,
  Cloudeo runtime, toolchain, agent runtime, dependency, and bootstrap
  changes). A new version changes the execution environment and therefore
  the runtime provenance. For controlled comparisons the version stays
  pinned. A new image must not silently alter an already-approved
  WorkOrder's runtime environment where that environment is part of its
  approved envelope.

**Worker lifecycle:**

- Write-capable agent workers are disposable by default: approved execution
  step → provision an isolated VM → attach private network and security
  policy → inject temporary bootstrap material and secrets → materialize the
  governed workspace → run the Session → collect durable evidence and
  artifacts → revoke temporary credentials → destroy the VM.
- A runtime VM is execution state only. It is never accepted workspace
  state. Destroying a VM must not destroy the authoritative evidence Cloudeo
  needs.
- **Topology.** The preferred early shape is a small persistent control
  plane (Cloudeo API, orchestration, `SessionSupervisor`, Mission Control)
  with a durable control and coordination store, plus ephemeral worker VMs.
  Expensive compute is allocated only while useful. Not every Cloudeo
  component has to run in an ephemeral VM.
- **No always-on worker pool by default.** The default is create on demand,
  execute, destroy. A warm pool may be introduced later only if measured
  startup latency or workload volume justifies its fixed cost, and it then
  needs explicit policy and lifecycle controls.
- **No Kubernetes initially.** The first deployment does not require it.
  Kubernetes may be reconsidered when concurrency, scheduling scale, service
  density, or operational evidence shows a need.
- **Session reuse is not VM reuse.** ADR-031 may permit reuse of an eligible
  Session; that does not imply indefinite reuse of the underlying VM. The
  initial write-capable worker implementation prefers a simple, auditable
  mapping. Optimizing reuse belongs to COST and must preserve isolation and
  workspace authority.
- **Managed PostgreSQL is optional.** This ADR does not replace the
  SQLite-first store behind a storage interface (ADR-029). A migration
  happens only when concurrency, availability, deployment topology, or
  operations justify it, and the storage interface must allow it without
  changing WorkOrder semantics.

**Runtime classes and architecture:**

- The fabric can select a runtime class but does not define the economic
  optimizer. The initial implementation supports a small set of explicitly
  approved classes (small shared or burstable, general-purpose dedicated,
  larger dedicated, a future GPU class). The exact class is runtime
  configuration. No Cloudeo core type assumes a particular Ubicloud class
  name. Right-sizing policy belongs to ADR-033.
- A larger VM is not automatically preferred. The runtime layer collects
  enough observations (runtime class, wall-clock duration, CPU and memory
  pressure where available, runtime cost, execution success or failure, and
  the verification result reference) to compute cost per successfully
  verified WorkOrder later. The fabric records evidence; it does not choose
  an economically optimal class itself.
- **x86 first.** The initial worker environment uses the architecture with
  the lowest compatibility risk for the Cloudeo toolchain. ARM is not
  selected because of a lower unit price. Before an ARM image is introduced,
  Cloudeo validates agent CLI compatibility, Python and Node native
  dependency compatibility, container and tooling compatibility, build and
  test behavior, wall-clock performance, and cost per verified task.

**Network and secrets:**

- Worker instances communicate over private networking where practical. The
  first Ubicloud implementation uses private subnets and firewalls to
  restrict worker connectivity. The default posture is: deny unnecessary
  inbound access, allow only required service paths, minimize public
  exposure, and prefer private control-plane communication. Public IPv4 is
  not mandatory for every worker. Public-facing services and worker
  execution networks are separable.
- Secrets are never baked into reusable machine images. Runtime credentials
  are injected only when required, scoped to the Session or execution step
  where possible, short-lived where the provider supports it, revocable, and
  absent from durable images, CoordinationMessages, and Project Memory. A
  destroyed runtime must not remain a source of reusable credentials.
- **Credential boundary.** Provider credentials are available only to the
  narrowest provider-specific execution boundary that requires them.
  Ubicloud credentials are consumed only by the Ubicloud adapter under
  `cloudeo.execution`. Credentials must never appear in
  `cloudeo.orchestration`, `cloudeo.control`, WorkOrder state, Session
  records, Coordination Store records, logs, or model-visible context.
  Orchestration receives only credential-free normalized observations and
  provider and runtime identity evidence. This states the authority
  boundary only; it does not decide credential storage or secret
  management.

**Workspace and evidence:**

- A cloud VM's root filesystem is not a Workspace Broker. Before
  write-capable execution, the workspace is materialized from the Workspace
  Broker's CandidateWorkspace and accepted-baseline identity into the
  isolated runtime. The materialization mechanism may evolve. The invariant
  is that Cloudeo knows which accepted baseline and candidate identity the
  runtime corresponds to. Runtime-local files never become accepted state
  because an agent finished successfully.
- **Evidence before destruction.** Before an ephemeral VM is destroyed,
  Cloudeo persists every governed output the surrounding workflow requires:
  execution result, test and audit evidence, structured runtime
  observations, artifact references, logs required by policy, usage and cost
  observations, runtime provenance, and workspace or checkpoint identity.
  Failure to retrieve required evidence is never silently normalized as
  success. If positive evidence is required but unavailable, the workflow
  fails closed.
- **Provenance.** Every governed cloud Session records, where available:
  `fabric_provider`, `fabric_region`, `runtime_class`,
  `runtime_instance_id`; `runtime_environment`,
  `runtime_environment_version`, `runtime_environment_fingerprint`;
  requested and actual architecture; creation time, termination time, and
  observed runtime duration; usage and runtime cost. This extends ADR-031's
  Session provenance. Unknown fields stay explicitly `unknown` or
  `unavailable`; a requested value is never substituted for an observed one.
- **Cost observability.** The fabric exposes or derives enough to attribute
  infrastructure cost to a governed execution where practical: at minimum
  the runtime class, start and stop time, billable duration if available,
  provider-reported cost if available, and the provider pricing identity or
  version when known. Infrastructure cost is evidence. The fabric must not
  alter WorkOrder policy to reduce cost.

**Failure, cleanup, and reconciliation:**

- The cloud adapter distinguishes at least: provisioning rejected;
  provisioning failed; instance running; instance unreachable; instance
  stopped; instance terminated; instance lost or final state unknown;
  environment bootstrap failed; workspace materialization failed; evidence
  extraction failed; destruction confirmed; destruction unconfirmed. These
  are runtime observations. They do not map directly to WorkOrder success.
  Unknown final infrastructure state stays explicit.
- **Cleanup is part of correctness.** Orchestration attempts bounded cleanup
  after normal completion, execution failure, bootstrap failure, timeout,
  cancellation, and orchestration restart or recovery. Cleanup is
  idempotent. An orphaned VM must be visible as operational debt and cost
  leakage; a periodic reconciliation may later detect orphans.
- **Reconciliation.** The Coordination Store keeps enough (provider instance
  id, expected lifecycle state, last observation) to reconcile provider
  state after an orchestration restart. Provider state is established by
  inspecting the provider, never inferred solely from stale local records. A
  divergence is reconciled or escalated.

**Adjacent concerns kept separate:**

- **CI.** Ubicloud's ephemeral GitHub Actions runners may be evaluated as
  part of infrastructure economics, but runner selection is not Cloud
  Execution Fabric authority. Cheaper runners never substitute for
  eliminating duplicate triggers, cancelling stale PR runs, batching agent
  pushes, failing fast, and building once (ADR-033).
- **Evaluation.** Evaluation tooling may use the same fabric, for example a
  pinned `cloudeo-eval` image. Evaluation traffic, model routing, and
  comparison policy are not defined here. The fabric only guarantees a
  known, reproducible environment, so an evaluation system such as
  Ori/OpenRouter can be added later without becoming a production
  infrastructure dependency.

**Security posture:** the first cloud implementation preserves least
authority: ephemeral workers by default; no long-lived credentials in images;
narrow network access; provider API credentials available only to the
provider-specific execution adapter that requires them;
workspace access appropriate to role; runtime identity and immutable image
identity recorded durably; cleanup and revocation after execution; and no
provider runtime claim becoming verification authority. A compromised worker
must not be able to mutate Cloudeo control state merely because it can reach
the orchestration network.

**First deployment profile (operational configuration, not architecture):**

| Aspect | Initial choice |
| --- | --- |
| Provider and location | Ubicloud managed service, `eu-central-h1` |
| Control plane | small persistent VM(s), sized from measured load |
| Workers | disposable VMs, explicit approved runtime classes, no large permanent pool |
| Environment | versioned UMI, initial image `cloudeo-worker`, immutable version pinned for governed execution |
| Network | private subnet where practical, restrictive firewall, public exposure only when required |
| Secrets | runtime injection only, never baked into the UMI |
| Persistence | the existing Cloudeo store abstraction; managed PostgreSQL optional later |
| Provider API | called only by the `UbicloudFabric` adapter under `cloudeo.execution`, which alone consumes the Ubicloud credentials |
| Kubernetes | not required initially |

Exact VM sizes and prices are operational configuration, not architectural
constants.

**Architecture checks:** enforced mechanically where practical.

| Check | Rule |
| --- | --- |
| CF-01 provider neutrality | No Ubicloud-specific infrastructure type may appear in `cloudeo.control`, `cloudeo.orchestration`, WorkOrder state-machine contracts, or trust-kernel contracts. The Ubicloud implementation exists only under `cloudeo.execution`. |
| CF-02 immutable environment identity | Every governed cloud Session records an immutable environment version or fingerprint, or explicitly records that it was unavailable. |
| CF-03 no secrets in image definitions | Reusable runtime images must not contain project, provider, or user credentials. |
| CF-04 runtime is not canonical state | A cloud VM filesystem must never be treated as accepted workspace state. |
| CF-05 evidence before destruction | Required governed evidence is persisted before runtime destruction is considered complete. |
| CF-06 idempotent lifecycle | Create, inspect, terminate, and reconcile operations have idempotency or equivalent duplicate-safe semantics where retries can occur. |
| CF-07 unknown remains unknown | An unreachable or ambiguously terminated VM must not be normalized to successful completion. |
| CF-08 cost observability | The fabric records enough runtime identity and duration or cost evidence for later attribution where the provider exposes it. |
| CF-09 no economic policy in the fabric | The fabric may report runtime economics but may not independently select a cheaper model, provider, or runtime class outside approved orchestration policy. |
| CF-10 no moving alias as provenance | A mutable alias such as `latest` must not be the sole environment identity recorded for governed execution. |
| CF-11 physical-host opacity | Managed-provider physical host placement must not become a Cloudeo control dependency. |
| CF-12 cleanup visibility | Instances that should have been destroyed but remain observable are detectable as orphaned runtime resources. |

These checks are not yet traced in `14_V2C_TRACEABILITY.md`.

**Non-goals:** this ADR does not define model selection; autonomous provider
switching; COST optimization policy; Ori/OpenRouter evaluation policy;
Project Execution Profile changes; multi-writer workspaces; general fleet or
GPU scheduling; Kubernetes orchestration; a mandatory PostgreSQL migration;
CI trigger policy; human-approval or promotion semantics; or a replacement
for Session Fabric or the Workspace Broker.

**Relationship to other ADRs:** this ADR extends and does not supersede
ADR-015, ADR-022, ADR-023, ADR-027, ADR-029, ADR-030, and ADR-031. ADR-035
governs package placement and import directions. ADR-031 defines what a
governed Session is. This ADR defines how a cloud-hosted Session receives an
isolated, reproducible runtime environment. ADR-033 decides how to choose
economically among already-permitted execution options.

**Implementation sequence:** after acceptance, in bounded slices, none of
which may weaken the ADR-030 or ADR-031 boundaries:

1. **Generic contracts, in `cloudeo.execution`:** `CloudExecutionFabric`,
   runtime and environment specification, runtime instance identity,
   normalized lifecycle, provenance and cost observations.
2. **Fake fabric:** deterministic lifecycle tests, idempotency, failure
   semantics, orphan reconciliation, no real cloud calls.
3. **Ubicloud adapter, under `cloudeo.execution`:** VM create, inspect, and
   terminate; region and runtime-class mapping; provider instance identity;
   no Session integration yet.
4. **Runtime image path:** a reproducible `cloudeo-worker` build,
   sanitization, version capture, immutable identity recording, bootstrap
   test.
5. **Networking and security:** private subnet and firewall, runtime secret
   injection, least-access bootstrap.
6. **Session Fabric integration:** provision a VM for an approved Session,
   materialize the workspace, execute, extract evidence, destroy, persist
   provenance.
7. **Operational reconciliation:** detect stale and orphaned VMs, recover
   after an orchestration restart, report usage and cost.

**Consequences:** Cloudeo gains a concrete path from abstract agent Sessions
to reproducible, isolated cloud execution without binding the product
architecture to one cloud provider. Cloud providers supply isolated compute;
Cloudeo owns execution semantics. Runtime environments are versioned and
reproducible, workers are disposable, and accepted state stays outside the
runtime VM. Ubicloud is the first managed implementation, not a permanent
architectural dependency.

---

## ADR-033 — COST: total-cost optimization policy

**Status:** Accepted (2026-10-01); policy architecture only, not yet
implemented. Amended 2026-10-01 before acceptance: COST never selects,
switches, or reorders execution profiles for an active WorkOrder (see
"Profile selection"). ADR-027 and ADR-029 are not amended.

**Supporting document:** `18_COST_TOTAL_COST_OPTIMIZATION_POLICY.md` holds
the rationale, worked examples, and formulas. This entry is the decision
record and is normative on its own. Where the two differ, this entry governs.

**Context:** a coding-agent system can waste money in many places even when
its model choice looks cheap. The true cost of one WorkOrder includes model
inference, subscription allocation, Session and cloud VM runtime, CI, build
and deploy resources, external APIs, storage and network, retries, model
evaluations, context reconstruction, and human intervention. Optimizing only
the token price or the VM price per minute can make the whole system more
expensive.

**Decision:** Cloudeo introduces **COST** as the policy layer responsible for
economic optimization of already-permitted execution choices. Its objective
is:

> Minimize expected total cost per successfully verified WorkOrder, subject
> to approved quality, safety, independence, latency, budget, and policy
> constraints.

- COST is not a model router, not a cloud scheduler, and not an authority
  over WorkOrder state.
- It evaluates the economics of allowed choices using observed evidence from
  model and runtime execution, Session Fabric, Cloud Execution Fabric, CI,
  provider and API usage, retries, evaluation systems, human intervention,
  and historical Performance Memory.
- It may recommend, or select among, choices that the approved envelope and
  execution policy already permit. It never selects, switches, or reorders
  execution profiles for an active WorkOrder (see "Profile selection").
- It may not weaken safety or verification requirements, bypass independence
  rules, alter a Project Execution Profile, introduce an unapproved
  provider, model, or runtime, mutate WorkOrder state directly, grant human
  approval, bypass the trust kernel, or trade away required correctness for
  a lower nominal price.

**Authority boundary:** COST is subordinate to control. Approved policy →
`cloudeo.control` → the eligible execution set → COST → an economic choice
or recommendation → `cloudeo.orchestration` → execution. COST chooses only
from the eligible set supplied by policy. An option that violates a quality
threshold, the risk class, auditor independence, an approved role binding, a
latency requirement, a budget rule, a security rule, or provider policy is
not eligible, however cheap.

**Objective hierarchy:** a lower-priority objective never overrides a higher
one.

1. Obey hard policy, security, and safety constraints.
2. Preserve required verification and independence.
3. Satisfy mandatory latency and SLA requirements.
4. Stay within the approved budget.
5. Minimize expected total cost per verified WorkOrder.
6. Where cost is materially tied, prefer lower operational complexity.

**Hard constraints and optimization criteria:**

- **Hard constraints**, never traded for savings: the approved envelope;
  security policy and credential boundaries; required tests and verification
  requirements; promotion rules; auditor independence and risk-class
  requirements; provider restrictions; data residency where required;
  explicit user decisions; and maximum latency or SLA when mandatory.
- **Optimization criteria**, compared only once the hard constraints hold:
  expected cost, latency, throughput, context-reuse benefit, VM utilization,
  CI usage, provider usage, retry probability, and human-attention
  probability.

COST never converts a hard constraint into a weighted preference.

**Cost model:** for an eligible strategy, the explanatory model is expected
total cost divided by the probability of verified success. It explains the
target and does not mandate one literal formula. A cheaper option with a much
lower verified-success probability may be worse than a dearer one that
succeeds reliably.

- Total WorkOrder cost is the sum of inference, allocated subscription,
  Session runtime, cloud runtime, CI, external API, storage, network, retry,
  evaluation, context-reconstruction, human-attention, and other observed
  direct cost.
- Not every term has to be available initially. Unknown components stay
  unknown. COST must not replace a missing actual cost with an invented
  value, and must not treat it as zero.
- **Inference.** For metered inference COST records, where available, the
  provider, model, input, output, cached and reasoning tokens,
  provider-reported cost, list-price estimate, and billing route. Evidence
  is preferred in this order: the provider-reported charge; the router's
  reported charge; a calculation from the current provider price; unknown.
  An estimate from list price is labeled as an estimate.
- **Subscriptions.** COST distinguishes marginal API cost, fixed
  subscription cost, and capacity or rate-limit scarcity. A subscription
  route may carry its fixed monthly cost, included or practical capacity,
  current usage pressure, rate-limit pressure, and allocation method. A
  near-zero marginal cost does not make a route free if it consumes scarce
  quota needed for higher-value work. Subscription routes are never compared
  to metered APIs through list token prices alone.
- **Allocation is accounting.** Cloudeo may allocate a subscription's fixed
  cost across successful WorkOrders (per active hour, per successful
  WorkOrder, per weighted token-equivalent, or per role-specific usage). The
  method is explicit and versioned. Allocated cost is an internal accounting
  view and is never presented as a provider invoice.
- **Model and billing route are different things.** The same model may be
  reached directly, through a router, or through a router with the user's
  own key, differing in price, latency, availability, provider identity,
  fallback behavior, and observability. COST compares routes only when
  policy allows all of them. A billing or routing path is profile data
  (ADR-035), so moving an active WorkOrder to a different route is a profile
  change and follows "Profile selection". Evaluation may use a router
  without production using the same route.
- **Provenance.** Every material cost observation states its source where
  practical (provider invoice or usage API, router-reported charge, cloud
  runtime record, CI runtime, list-price calculation, subscription
  allocation, human estimate), so actual charges and estimates are never
  mixed.
- **Uncertainty and freshness.** Evidence keeps its sample size, variance or
  spread where available, time window, and environment and profile
  fingerprints. A small apparent advantage from few observations is not
  treated as certain. Evidence is discounted or invalidated when its
  fingerprint no longer matches (model updates, price changes, runtime image
  changes, CI changes, repository growth, toolchain versions, provider
  performance, subscription-plan changes). Old evidence may stay for history
  but must not silently represent current economics.
- **Verified labels only.** Performance Memory and COST never learn success
  from an agent saying it is done, a runtime completing, partially passing
  tests, a created PR, or a provider returning 200. The positive label is a
  verified outcome appropriate to the workflow, ultimately a promoted or
  accepted outcome where relevant.

**Roles, profiles, and evidence:**

- There is no globally cheapest best model. COST evaluates within a role and
  task context, with evidence keyed by at least role, task class, profile
  fingerprint, model and provider, runtime-environment fingerprint, and risk
  class, where available.
- **The Project Execution Profile stays authoritative (ADR-027).** COST does
  not replace a role's primary profile with a cheaper model. Normal
  execution stays: the approved primary, then an approved ordered fallback
  only under an approved fallback condition. COST may not add a model,
  provider, or profile.
- **Performance Memory** keeps verified economic observations keyed by
  context (role, task class, profile and runtime-environment fingerprints,
  fabric provider, runtime class, verified outcome, latency, retries,
  inference, VM and CI cost, human intervention). COST prefers observed
  project-specific evidence over generic benchmark assumptions when the
  sample is sufficient.

**Profile selection (ADR-027 and ADR-029 govern):** COST is bound exactly as
Performance Memory is. It may never select, switch, or reorder execution
profiles for an active WorkOrder, including among approved fallbacks,
because it predicts lower cost or better performance.

- COST may calculate costs, compare alternatives, rank them analytically,
  recommend a revised primary or fallback ordering, and provide evidence for
  `change_agent`, always showing sample size and uncertainty.
- An active WorkOrder keeps using the immutable primary and fallback
  ordering of its snapshotted Project Execution Profile. A fallback is used
  only under its approved fallback condition and only in that order. COST's
  analysis neither triggers a fallback nor changes which one is next.
- A COST recommendation affects execution only through one of two paths:
  1. a user-approved Project Execution Profile revision, which reaches an
     active WorkOrder only through `change_agent` and a user-approved
     envelope amendment (ADR-028);
  2. an explicit, pre-approved, deterministic policy in the approved profile
     or envelope. Its trigger is an observed, classified condition, and it
     makes no runtime performance-based profile-selection decision.
- The choices COST may make automatically are never execution profiles.
  They are resources such as an approved runtime class, reuse of an eligible
  Session, or an approved equivalent CI runtime.

**Two modes:**

| Mode | When | Examples |
| --- | --- | --- |
| Automatic selection | every candidate is already policy-eligible, the decision does not amend the approved envelope, the choice stays within approved role, profile, and fallback semantics, and it is not a choice between execution profiles or a change to their order | approved VM class A or B; reusing an eligible Session or creating a fresh one; an approved equivalent CI runtime |
| Recommendation | the cheaper or better choice would need a new model, a new provider, a Project Execution Profile change, a different primary or fallback ordering, a risk-policy change, a budget change, an independence change, or a new production routing path | the recommendation enters the existing human and control decision path |

- **Decision record.** A non-trivial automatic selection records the
  `decision_id`, `workorder_id`, role and task class, the eligible choices,
  the chosen one, the hard constraints applied, expected cost, expected
  verified-success evidence, expected latency, evidence references,
  uncertainty, the reason, a timestamp, and the COST policy version.
- **COST cannot self-amend.** It may not rewrite its own hard constraints or
  policy weights, a Project Execution Profile, approved budgets, the risk
  class, or independence requirements because its data suggests it. Such
  changes go through the normal decision process.

**Budget, latency, and human attention:**

- The approved envelope may define a hard maximum cost, a soft target cost,
  a per-attempt budget, a total WorkOrder budget, and an evaluation budget.
  COST distinguishes hard caps from targets. Approaching a hard cap
  triggers, as policy permits, a cheaper eligible choice that is not a
  profile change, an approved fallback under its approved fallback
  condition, or stop and escalate. Exceeding a hard cap without explicit
  authority is forbidden.
- Latency may be a constraint (lowest expected cost subject to an SLA) or a
  penalty only where project policy defines the requirement. It is never
  converted into money by an undocumented formula.
- Human intervention is a cost signal: manual approval, debugging, conflict
  repair, provider recovery, reruns, environment repair, and review beyond
  normal policy are counted or estimated, initially as a count, duration
  estimate, or severity class. Monetization is optional.
- Mandatory human decisions (plan approval, material-deviation approval,
  `change_agent`, `change_budget`, a risk waiver, a promotion-related
  decision where required) are governance boundaries. COST may reduce
  avoidable friction. It may never bypass a required human decision because
  it is expensive.

**Runtime and session economics:**

- **Right-sizing.** COST may compare approved runtime classes. The metric is
  expected infrastructure cost per successfully verified task, not the
  cheapest VM per minute. A dearer VM may be cheaper overall if it reduces
  build time, test time, agent idle time, timeout risk, or retry rate.
- **Idle time is leakage.** With ADR-032's create, execute, destroy default,
  unnecessary idle VM lifetime is cost leakage. The system measures
  provisioning, active execution, idle, handover, and cleanup time.
- **Warm pools need evidence.** COST may recommend a warm pool only when the
  saved startup latency or value exceeds the idle capacity cost plus
  operational complexity. Warm pools are not the default, and any warm-pool
  policy preserves isolation, secret handling, and workspace authority.
- **Session reuse.** COST may compare reusing an eligible Session with
  starting a new one. Savings (less context reconstruction, fewer tokens,
  no VM startup or tool bootstrap, cheaper handover) are weighed against
  risks (stale context, role contamination, independence violation,
  workspace mismatch, security-scope mismatch). Policy eligibility is
  checked before economics; reuse is allowed only if those constraints
  hold.
- **Context reconstruction is a real cost.** Avoidable rediscovery of
  architecture, decisions, WorkOrder state, repository structure, and
  earlier findings is waste, mitigated by the Coordination Store, structured
  handover, Project Memory, short overlapping Sessions, and reusable runtime
  environments. Preserving stale or unsafe context is not automatically
  cheaper.
- **Overlapping handover** may be compared against the reconstruction and
  retry cost it avoids. It never transfers write authority in violation of
  ADR-031.
- **Parallelism is not automatically cheaper.** It is compared on total
  inference, total VM runtime, coordination overhead, duplicate work, merge
  and reconciliation work, verified outcome, and the value of latency.
- **The single mutable writer** of ADR-031 is also an economic safeguard.
  COST must not override it to gain parallelism.

**Retries:**

- Blind retry is expensive. COST consumes failure classification from
  orchestration and control (provider transient failure, deterministic
  validation failure, audit failure, baseline drift, unknown runtime state,
  budget exhaustion, environment bootstrap failure). The options are: retry
  the same route, use an approved fallback, change the runtime class, or
  stop and escalate. A retry happens only where policy permits it and its
  expected value is positive. A fallback is used only under its approved
  fallback condition and in the snapshotted order.
- Where evidence shows a deterministic failure will recur unchanged (invalid
  input, a missing credential, a policy prohibition, a failed deterministic
  test, an unsupported architecture, a known environment incompatibility),
  COST does not recommend an identical retry. The action is to fix the
  prerequisite, replan, use an approved alternative, or raise
  `USER_ATTENTION_REQUIRED`.

**CI economics:** CI is part of total WorkOrder cost. COST tracks workflow
runs attributable to a WorkOrder or PR, job runtime, runner class, duplicate
and stale runs, cache hits and misses, and build repetition.

- **Push discipline.** Local validation is the inner loop. Remote CI is a
  validation gate, not the agent's debugger. Agents may commit locally as
  often as useful; remote pushes happen at meaningful validation points.
- **No duplicate triggers.** Where the repository topology allows, the same
  expensive validation does not run twice through overlapping triggers.
  Required-check behavior stays correct; optimization never removes a
  required validation signal.
- **Cancel stale PR runs, preserve main.** Superseded PR runs are normally
  cancelled. Main and release validation is not blindly cancelled by the
  next push.
- **Fail fast and cheap.** Cheap, high-signal checks run before expensive
  ones (format, lint, static analysis, unit, integration, E2E, large build,
  deploy, adjusted per project).
- **Build once, reuse artifacts**, provided the artifact stays trustworthy
  for every consumer. COST does not encourage unsafe reuse across
  incompatible contexts.
- **Cache only stable things**, keyed by explicit stable inputs (lockfile
  fingerprint, toolchain version, runtime-environment fingerprint,
  architecture). Correct caching ranks above cache hit rate.
- **Job fragmentation has a cost** (minimum billing unit, startup overhead,
  artifact transfer, runner provisioning). The goal is neither one giant job
  nor maximal fragmentation.
- **Runner selection** is compared on cost per green authoritative
  validation, using price, duration, cache performance, queue delay, failure
  rate, architecture compatibility, and operational dependency risk.
  Changing runner provider never weakens required checks.
- **ARM requires measurement** of build and test duration, native dependency
  compatibility, emulation overhead, cache behavior, verified success, and
  total cost before it is preferred.
- **Self-hosting is not automatically cheaper.** Patching, runner lifecycle,
  disk cleanup, security, isolation, capacity planning, and human operations
  are included where material.

**Evaluation economics:**

- Ori Eval over OpenRouter may be used as one model-evaluation backend:
  controlled experiment → candidate-model evidence → Performance Memory →
  COST analysis → recommendation. It is evidence infrastructure, not
  production authority, and is not required for production execution. A
  model evaluated through a router may later run directly through its
  provider if policy and economics favor it.
- **Positive expected value.** COST does not benchmark every new model.
  Before a significant evaluation it weighs expected future workload times
  expected improvement per task against evaluation, migration, and
  operational-risk cost. If the value is too low, the current approved
  profile stays. This is a policy heuristic, not a monetary forecast.
- **Cadence.** No full model bake-off on every code push. A small regression
  evaluation runs only when relevant agent behavior, prompt, tool, or
  harness logic changes. A model comparison is triggered by an important
  new model, a scheduled review, a material cost shift, a quality
  regression, a provider availability change, or an explicit human request,
  and screens a small candidate set before a larger confirmation run. The
  exact cadence is configuration.
- **Reproducibility.** Comparisons pin, as far as practical, the task set,
  repository commit, harness, prompts, tools, effort and budget,
  runtime-environment image and version, runtime class, and network
  assumptions, and vary only the intended variable. ADR-032 provenance
  supports this.
- Before a large evaluation COST requires the question to answer, the
  candidate set, the task set, the expected evaluation cost, the expected
  future workload, and the decision threshold. Afterwards it stores the
  actual cost, candidate performance and cost, confidence and sample size,
  and the recommended action.

**Initial implementation scope:** deliberately conservative, with no
sophisticated learning system.

- Inputs: model and provider usage, Session duration, cloud runtime duration
  and class, provider-reported or estimated inference cost, VM cost, retry
  count, verified outcome, and basic CI attribution where available.
- Actions: report economics, compare eligible runtime classes, compare reuse
  against a new Session, and recommend, but never autonomously change,
  model or profile bindings.
- It may expose cost per attempt, per successful attempt, and per verified
  WorkOrder, retry cost, the inference, runtime, CI, and evaluation shares,
  and a human-attention count. Unknown components are listed separately
  (a known total plus the unknown components), never coerced to zero.
- CI economics first surface waste as a recommendation or
  repository-specific proposal. They do not rewrite workflows automatically.

**Architecture checks:** enforced mechanically where practical.

| Check | Rule |
| --- | --- |
| COST-01 no control mutation | COST must not mutate WorkOrder state directly. |
| COST-02 eligible-set discipline | Automatic choices are drawn only from options already permitted by control and policy. |
| COST-03 no profile mutation | COST must not directly change Project Execution Profile bindings, and must not select, switch, or reorder profiles or fallbacks for an active WorkOrder. |
| COST-04 no independence weakening | Economic optimization must not weaken ADR-027 independence requirements. |
| COST-05 no verification weakening | COST must not remove or downgrade required verification to save resources. |
| COST-06 actual versus estimated cost | Actual provider charges and estimated or list-price costs remain distinguishable. |
| COST-07 unknown is not zero | Missing cost evidence must not be silently treated as zero. |
| COST-08 subscription-aware accounting | Subscription routes must not be compared to metered APIs solely through list token prices. |
| COST-09 evidence fingerprinting | Economic evidence retains enough context and fingerprints to detect when it is no longer comparable. |
| COST-10 no unverified training labels | COST and Performance Memory must not learn positive outcome quality solely from runtime completion or agent self-report. |
| COST-11 explainability | Non-trivial automated selections produce a durable decision record. |
| COST-12 hard constraints dominate | No economic score may override a hard policy constraint. |

These checks are not yet traced in `14_V2C_TRACEABILITY.md`.

**Non-goals:** this ADR does not define a universal cheapest model;
unrestricted autonomous model routing; autonomous Project Execution Profile,
risk-policy, or budget changes; removal of verification or of required human
approvals to reduce cost; a universal monetary value for human attention; one
mandatory cloud provider, evaluation backend, or CI provider; a requirement
to use OpenRouter in production, Ori Eval, or subscription-authenticated
execution; or speculative financial forecasting.

**Relationship to prior ADRs:** COST extends and does not supersede ADR-022
(control is the workflow authority), ADR-025 (the approved envelope
constrains execution), ADR-026 (WorkOrder and block state are
control-owned), ADR-027 (role bindings, fallbacks, and independence),
ADR-028 (policy exhaustion escalates to `USER_ATTENTION_REQUIRED`), ADR-029
(Performance Memory is advisory and evidence-based, and its bound on
selecting or switching profiles applies to COST), ADR-030 (orchestration
gathers evidence but does not own WorkOrder state), ADR-031 (Session Fabric
exposes runtime and cost observations), and ADR-032 (the Cloud Execution
Fabric exposes runtime class, duration, provenance, and infrastructure-cost
evidence). COST consumes evidence from those layers. It does not replace
them.

**Implementation sequence:** after acceptance, in bounded slices, each
preserving the authority boundaries above:

1. **Economics schema:** cost observation types, source and provenance,
   known versus estimated versus allocated cost, verified outcome linkage.
2. **Aggregation:** attempt cost, WorkOrder cost, role and task statistics,
   runtime, inference, and CI attribution.
3. **Reporting only:** Mission Control economics, no automatic choices.
4. **Approved runtime-class optimization:** compare already-eligible classes.
5. **Session reuse economics:** reuse versus a fresh Session where ADR-031
   allows both.
6. **CI waste detection:** duplicate runs, stale runs, repeated builds, agent
   push multiplication.
7. **Evaluation economics:** the expected-value gate for model comparisons.
8. **Policy-bounded automatic selection:** among non-profile choices only,
   and only after evidence quality and the architecture checks are mature.
9. **Performance Memory integration:** uncertainty, freshness, and
   fingerprint-aware historical evidence.

**Consequences:** Cloudeo gains one economic policy that reasons across
model, infrastructure, Session, CI, and evaluation cost without letting
economics become workflow authority. COST minimizes expected total cost per
successfully verified WorkOrder, never the cheapest isolated resource.
Economics may optimize within approved policy; economics may not redefine
the policy.

---

## ADR-034 — Agent Data Interchange and MCP boundary

**Status:** Accepted (2026-10-01); not yet implemented.

**Supporting document:** `19_AGENT_DATA_INTERCHANGE_AND_MCP_BOUNDARY.md`
holds the rationale, diagrams, and candidate resource and tool names. This
entry is the decision record and is normative on its own. Where the two
differ, this entry governs.

**Scope:** the Cloudeo control plane, agent interoperability, structured data
exchange, and MCP. Related: ADR-030, ADR-031, ADR-032, ADR-033.

**Context:** Cloudeo orchestrates heterogeneous coding and agent runtimes
without making any model provider, harness, or agent protocol an
architectural dependency. Agents increasingly need structured operational
state, not only documents: WorkOrders, Runs, execution events, artifacts,
evidence, verification outcomes, cost records, workspace state,
capabilities, and approved decisions. The Model Context Protocol (MCP) is a
useful way to expose such information and selected operations. Exposing
Cloudeo through MCP must not create a second control plane, let clients
mutate canonical state directly, or couple the domain model to MCP. The
requirement is therefore an Agent Data Interchange boundary in which MCP is
one adapter.

**Decision:** Cloudeo introduces a provider-neutral **Agent Data Interchange
(ADI)** boundary between external agent clients and Cloudeo's canonical
application and control services. MCP is supported as the first standardized
agent-facing protocol adapter over this boundary.

MCP must not become:

- the canonical data model;
- the system of record;
- an alternative orchestration engine;
- an alternative state machine;
- a direct database-access mechanism;
- a path around authorization, policy, verification, budget, or promotion
  gates.

Every state-changing MCP operation must invoke the same Cloudeo application
and control services used by other interfaces. The governing rule:

> MCP may expose state and request actions; it may never independently
> determine or mutate canonical control state.

The layering is agents → MCP or a future protocol → ADI (resources, tools,
schemas) → Cloudeo application services (orchestration and query layer) →
`cloudeo.control` (policy, state machine, gates) → control store, execution
fabric, and evidence and artifacts.

**Principles:**

- **Canonical models are protocol-independent.** Core domain objects exist
  independently of MCP schemas, for example `WorkOrder`, `Run`,
  `AgentExecution`, `RunEvent`, `Artifact`, `Evidence`,
  `VerificationResult`, `CostRecord`, `WorkspaceState`, `PromotionDecision`,
  `ProviderCapability`, `ExecutionRequest`, and `ExecutionOutcome`. MCP
  representations are projections or serialized views of them. A future
  REST, CLI, event-stream, A2A, or other adapter must be able to expose the
  same semantics without translating through MCP.
- **One control plane.** There is exactly one authoritative transition path
  for controlled Cloudeo state. A client may request `create_run`,
  `submit_artifact`, `submit_evidence`, `request_verification`, or
  `request_transition`; each translates into a command handled by the
  existing application and control boundary. An MCP server must not perform
  direct SQL mutations of control-state tables.
- **Read broadly, write narrowly.** The initial implementation should favor
  rich read access to approved information and deliberately constrained
  command access. A state-changing operation is introduced only where its
  authorization, idempotency, audit, policy, and state-transition semantics
  are explicit.
- **Requests are not decisions.** A client's request does not imply the
  transition occurs. Control decides from policy, evidence, state, and
  budget, and accepts or rejects. The response should make the resulting
  state and reason machine-readable.
- **Provenance survives interchange.** Evidence and derived data exposed to
  agents must keep enough provenance to tell where the information came from
  and how it was produced. Where applicable a response should carry a stable
  object ID, object and schema version, creation or observation timestamp,
  producing run or execution, source or parent references, verification
  state, a content hash or immutable artifact reference, and the relevant
  policy or decision reference. MCP formatting must not strip provenance
  that later verification needs.
- **Unknown is preferable to invention.** Missing or unavailable data stays
  explicitly unknown, null, or unavailable according to the canonical
  schema. An adapter must not synthesize plausible values to satisfy a
  response schema.

**MCP surface:**

- **Resources** are used for addressable, mostly read-oriented state: work
  orders, runs, run events, run artifacts, evidence, verification, workspace
  state, and provider capabilities. The exact URI structure is an
  implementation detail and may evolve without changing this decision.
- **Tools** are explicit operations, never hidden side effects of resource
  reads. Initial tools may be read and query tools. Controlled command tools
  may come later. Every mutating tool must delegate to an authorized Cloudeo
  command or application service.
- **Prompts** may be offered for convenience but must not contain
  authoritative business logic or policy. Acceptance criteria, transition
  rules, budget controls, and verification requirements stay in Cloudeo.

**Capability negotiation:** Cloudeo should expose machine-readable
capabilities (for example filesystem, shell, structured output, MCP, resume,
artifact submission, and constraints such as context size or interactive
authentication) so clients do not have to infer them. Capability
declarations are descriptive inputs to orchestration and grant no
authorization. Provider-specific capabilities stay behind the provider and
runtime abstraction and must not leak into the canonical WorkOrder contract
unless the work genuinely requires them.

**Authentication, authorization, and isolation:**

- MCP transport authentication and Cloudeo authorization are separate
  concerns. An authenticated MCP client is not thereby authorized to access
  every workspace or invoke every tool.
- Authorization should be scoped by identity, organization or tenant,
  workspace or project, resource, operation, role, and execution context
  where relevant.
- Credentials should be short-lived or revocable where practical.
- Secrets must not be returned through general-purpose MCP resources or
  tools merely because they exist in an execution environment.
- The MCP server must respect the same least-privilege principles as other
  Cloudeo interfaces.
- **Multi-tenant isolation.** Every externally reachable query and command
  must enforce tenant and workspace boundaries before returning data or
  dispatching an action. An identifier alone never constitutes
  authorization. Cross-workspace retrieval should be impossible unless an
  explicit privileged capability exists and is independently authorized.
  Tests must cover attempted cross-tenant and cross-resource access.

**Auditability:** every state-changing request received through MCP must
leave enough audit information to reconstruct the authenticated caller, the
requested operation, the target object, the request time, the relevant input
or an immutable input reference, Cloudeo's decision, the resulting state,
and the execution or run correlation where applicable. The audit record
belongs to Cloudeo, not to the MCP client. Read access to particularly
sensitive operational information may also be audited.

**Idempotency and retries:** agent protocols and remote runtimes retry.
Mutating MCP operations must therefore have explicit retry semantics. Where
duplicate execution would be harmful, a command should accept or derive an
idempotency key. A transport retry must not create duplicate Runs, duplicate
evidence, repeated promotion, or duplicate paid execution.

**Failure semantics:** errors must distinguish at least invalid request,
unauthenticated, unauthorized, object not found, invalid state transition,
policy rejection, budget rejection, capability unavailable, conflict or
idempotency collision, and temporary execution or service failure. Adapters
should preserve structured Cloudeo error codes even if the external protocol
also needs a generic error representation. An agent must be able to tell
"retry later" from "this operation is forbidden or invalid".

**Interaction with other boundaries:**

- **COST (ADR-033).** MCP is an ingress mechanism, not an exemption from
  COST policy. Any MCP request that can cause paid execution must flow
  through the same budget checks, provider-selection policy, reuse and cache
  logic, cost ceilings, fallback rules, scheduling policy, and verification
  requirements. An external agent must not be able to force a specific
  expensive provider or bypass a cost ceiling unless its authorization
  explicitly permits that override. Cost metadata may be exposed to
  authorized clients.
- **Execution (ADR-032).** MCP does not execute arbitrary workloads itself.
  When a command results in execution, the path is MCP request → ADI →
  orchestration → `ExecutionRequest` → cloud or local execution fabric →
  `ExecutionOutcome` → control. Runtime provisioning, isolation, suspend and
  resume, spot or preemptible execution, and reproducibility stay concerns
  of the execution fabric.
- **Session Fabric (ADR-031).** MCP may expose selected session and
  coordination information but must not become the Coordination Store.
  Ephemeral agent communication, leases, session state, ownership, and
  coordination stay governed by ADR-031. Where a client needs session
  information, ADI presents an authorized projection.

**Versioning:** canonical schemas and MCP projections must be versionable
independently. Cloudeo should prefer additive evolution and explicit
capability and schema discovery. A breaking protocol change should arrive
through a versioned resource or tool contract, not a silent change of
semantics. A response should make its schema version discoverable when
ambiguity could affect interpretation.

**Deployment and exposure:**

- The MCP adapter should be deployable independently from core Cloudeo
  services, over stable application interfaces, so the MCP surface can be
  disabled, upgraded, rate-limited, or isolated without replacing the core
  orchestration system. The first implementation may run in-process if
  operational simplicity warrants it, provided the logical boundary stays
  enforced.
- Cloudeo should distinguish at least an **internal, privileged ADI**
  (operational data and commands for trusted coding agents, harnesses, and
  Cloudeo components) from an **external, restricted ADI** (deliberately
  exposed capabilities for third-party agents and integrations). The public
  surface must not automatically mirror every internal resource or tool.
  Exposure is an explicit product and security decision.

**HumanoidOnline applicability:** the ADI pattern is intentionally reusable
outside Cloudeo. HumanoidOnline is a strong candidate for a separate,
read-oriented MCP service over its canonical robot catalogue. That service
should expose the same canonical, provenance-aware catalogue used by its web
and API surfaces, not an MCP-specific database, and its initial public MCP
should be read-only. The discovery and update pipeline (external sources →
observations → entity matching → evidence and validation → promotion →
canonical catalogue) stays the controlled ingestion path, so an external MCP
client cannot directly update a robot, price, availability status,
specification, or evidence record in the published catalogue.

**Not decided here:** a specific MCP SDK or implementation language; HTTP
versus another MCP transport; exact resource URI naming; every tool name; the
public pricing or business model for MCP access; whether an API gateway
fronts the adapter; the detailed HumanoidOnline MCP schema; and the detailed
catalogue-discovery promotion policy. These can evolve without changing the
boundary.

**Rejected alternatives:**

- **Make MCP the Cloudeo control plane.** It would bind core orchestration
  semantics to an external interchange protocol and make non-MCP interfaces
  second-class.
- **Give agents direct database access.** It bypasses domain invariants,
  authorization, audit, state-machine enforcement, and future schema
  abstraction.
- **Build provider-specific integration paths.** Separate data interfaces
  per provider would undermine provider neutrality and multiply maintenance.
- **Expose only unstructured documents.** Documents stay useful, but agents
  need typed operational objects, provenance, state, and explicit actions.
- **Permit MCP clients to promote state directly.** Promotion and controlled
  transitions are Cloudeo decisions and stay behind the control boundary.

**Implementation sequence:**

1. Define canonical ADI DTOs and projections from existing Cloudeo domain
   models.
2. Implement read-only MCP access to a narrow set of WorkOrder, Run,
   artifact, and evidence data.
3. Add authentication, workspace authorization, audit tests, and schema and
   version metadata.
4. Add capability discovery.
5. Validate interoperability with at least two independent agent or provider
   environments.
6. Introduce narrowly scoped command tools only after idempotency and policy
   enforcement are demonstrated.
7. Keep promotion and critical state transitions behind `cloudeo.control`.
8. Reuse the pattern for a separate read-only HumanoidOnline MCP when its
   continuous catalogue update path is mature enough.

**Acceptance criteria:** this ADR is implemented when all of the following
hold:

- at least two materially independent agent environments can consume the
  same Cloudeo structured data through MCP;
- no MCP handler directly mutates canonical control state;
- state-changing MCP requests traverse the normal Cloudeo command and
  control path;
- workspace and tenant authorization is enforced and tested;
- provenance and stable identifiers survive serialization;
- retried mutating requests cannot unintentionally duplicate controlled
  operations;
- paid execution triggered through MCP remains subject to COST controls;
- MCP can be disabled without disabling Cloudeo's core orchestration;
- core domain models have no required dependency on MCP-specific types;
- another protocol can be added as a further ADI adapter without redesigning
  the control plane.

These criteria are not yet traced in `14_V2C_TRACEABILITY.md`.

**Consequences:**

- Positive: Cloudeo gains a standard agent-facing interface without
  depending on one AI provider or harness. Structured operational state
  becomes reusable by Claude Code, Codex/OpenAI, Astra, Kimi/Moonshot, and
  future compatible agents. The same canonical data and control rules stay
  authoritative across UI, CLI, API, MCP, and future adapters. MCP clients
  can take part in evidence and verification workflows without being able to
  bypass them. The boundary is a reusable pattern for HumanoidOnline and
  other structured agent-facing products.
- Costs and risks, accepted subject to the constraints above: another
  externally reachable interface adds authentication, authorization,
  versioning, rate-limiting, and security responsibilities. Poorly designed
  tools could expose excessive privilege. MCP projections could diverge from
  canonical models. Agent retries can duplicate work or cost unless
  idempotency is enforced. Clients with different interpretations or feature
  subsets need conformance testing.

The boundary is intentionally asymmetric: agents may observe structured
Cloudeo state and request permitted actions; Cloudeo alone authorizes and
performs canonical state transitions.

---

## ADR-035 — Provider-neutral execution below orchestration

**Status:** Accepted (2026-10-01); not yet implemented. Amends ADR-030 in one
respect only (see "Amendment to ADR-030"). Renumbered from ADR-031 on
2026-10-01, when ADR-031 to ADR-034 were recorded.

**Supporting document:** `15_PROVIDER_NEUTRAL_EXECUTION_AND_DEVLOOP.md` is a
draft of the target design and DevLoop. This entry is the decision record and
is normative on its own. Where the two differ, this entry governs (see
"Relationship to `15_PROVIDER_NEUTRAL_EXECUTION_AND_DEVLOOP.md`").

**Context:** Cloudeo must be AI-provider-neutral. OpenAI/Codex,
Anthropic/Claude, Moonshot/Kimi, and future providers are replaceable
execution backends. `15_PROVIDER_NEUTRAL_EXECUTION_AND_DEVLOOP.md` (a draft
under review) describes the target. This ADR fixes the architectural decisions
that draft depends on, against the code that exists after ADR-030:

- `cloudeo.control` holds roles, the V2C-18 ExecutionProfile hierarchy
  (`AgentProfile`, `DirectToolProfile`, with computed fingerprints), the
  profile registry in the control store, `ProjectExecutionProfile` bindings,
  fallback conditions, and the V2C-14 independence policy.
- `cloudeo.execution` holds the request kinds (`DirectToolExecution`,
  `HarnessTaskExecution`), `ExecutionOutcome`, `ExecutionError`,
  `RuntimeIdentity`, the `ExecutionDispatcher`, and the Treg and UHP backends.
- `cloudeo.orchestration` (ADR-030) maps trusted runtime observations into
  control inputs.

**Decision:** Cloudeo is provider-neutral by contract. `cloudeo.control`
depends only on roles, immutable execution profiles, normalized evidence, and
verification outcomes. Provider-, model-, and CLI-specific behavior lives only
in adapters inside `cloudeo.execution`.

**Amendment to ADR-030 (the only one):** `cloudeo.orchestration` may depend on
both `cloudeo.control` and `cloudeo.execution`. The dependency direction is:

| From | To | Rule |
| --- | --- | --- |
| `cloudeo.orchestration` | `cloudeo.control` | allowed (ADR-030) |
| `cloudeo.orchestration` | `cloudeo.execution` | allowed (this ADR) |
| `cloudeo.control` | `cloudeo.execution` | forbidden |
| `cloudeo.control` | `cloudeo.orchestration` | forbidden (ADR-030) |
| `cloudeo.execution` | `cloudeo.control` | forbidden |
| `cloudeo.execution` | `cloudeo.orchestration` | forbidden |

Each forbidden edge gets a mechanical AST check with a negative test, in the
style of ADR-030, when the first ADR-035 slice is implemented. Everything
else in ADR-030 stands unchanged:

- `cloudeo.control` stays pure; V2C-01 stays scoped to it.
- Orchestration may read a WorkOrder and call `cloudeo.control.machine`, but
  never constructs, copies with changes, or mutates WorkOrder state.
- Direct `promote()` is permanently forbidden outside the authorized promotion
  gate; the slice-scoped ban on `checkpoint_candidate()`, `reject()`, and
  `cleanup()`, the ban on `subprocess` and `cloudeo.workspace.git` in
  orchestration, and the `refs/cloudeo` string ban all remain.
- `cloudeo.execution` code may use `subprocess` where a plane requires it;
  orchestration still may not.

**Provider-neutral rules:**

- **Planes are request kinds.** The execution plane is
  `ExecutionRequest.kind`. A new plane is a new request kind with a neutral
  request model, never a UHP wire model reused for something else. The
  `ExecutionDispatcher` stays the only router by kind. Within a plane, the
  plane's backend selects an adapter by `adapter_id` from an adapter registry
  in `cloudeo.execution`. An adapter never picks a different profile,
  provider, or model on its own authority.
- **Session Fabric is a separate execution service boundary.** The
  provider-neutral Session Fabric runtime contracts and observation DTOs of
  ADR-031, and every concrete fabric adapter (Claude Code, Codex, Kimi, or
  any other provider), live in `cloudeo.execution`. Session Fabric lifecycle
  operations (`create_session`, messaging, handover, `terminate_session`,
  and the like) are not execution request kinds and are not routed through
  `ExecutionDispatcher`, which remains the router for execution request
  kinds only. `cloudeo.orchestration` owns Session and coordination policy
  and lifecycle state, consumes only the neutral execution contracts, never
  defines a provider adapter interface that execution must implement, and
  never imports a provider-specific implementation module or type.
- **Cloud fabric implementations live in execution.** The Cloud Execution
  Fabric contracts of ADR-032 and the Ubicloud-specific implementation live
  in `cloudeo.execution`. No Ubicloud-specific type appears in
  `cloudeo.orchestration` or `cloudeo.control`.
- **The ExecutionProfile hierarchy is not redefined.** The existing control
  types (`_ExecutionProfileBase`, `AgentProfile`, `DirectToolProfile`), their
  computed fingerprints, the control-store registry, and
  `ProjectExecutionProfile` remain canonical. Any provider-neutral profile
  data a later slice needs (for example `adapter_id`, `execution_plane`,
  `billing_mode`, or a non-secret `auth_profile_ref`) is added to those types
  as additive fields in its own slice. That changes every profile's
  fingerprint once, so it happens before profiles are relied on outside
  tests. No second profile type or profile registry is created.
- **Permissions are not capabilities.** `Permissions` is the authority a
  profile is granted and control evaluates it. Capabilities are facts about
  an adapter, established by conformance tests and evaluated in
  `cloudeo.execution`. Neither replaces the other.
- **Billing is envelope policy.** A profile declares its billing mode as
  immutable data; the allowed modes, whether metered use is allowed, and any
  metered cap are project-level policy approved with the Project Execution
  Profile, like the independence policy. No adapter may run in a billing
  mode other than the one its profile declares. A metered fallback exists
  only as an approved fallback binding with its condition.
- **Errors are classified neutrally.** `ExecutionError` gains a
  provider-neutral error class; native codes and details are kept as
  evidence. Orchestration maps error classes to the existing
  `FallbackCondition` values and to `AUDITOR_ERROR` routing: that mapping is
  the producer V2C-12 and V2C-17 still lack. The existing LongHorizon
  classification (`AuditorFailure.kind`) maps into the same classes. Control
  semantics do not change.
- **Auditor independence is unchanged.** `13_V2_CONTROL_ARCHITECTURE.md` §8.6
  and V2C-14 govern exactly: the cumulative table, measurement by role
  against the producers, runner-supplied fresh-session evidence, and
  `INDEPENDENCE_UNAVAILABLE`. Provider neutrality may add requirements (for
  example a different provider at a given risk class, through a stricter
  `IndependencePolicy`) and never relaxes one.
- **Native CLI execution requires OS isolation.** A local agent CLI (Codex
  CLI, Claude Code, Kimi Code, or similar) runs only in an OS-isolated copy
  of the candidate (container, sandbox, or separate user) with no access to
  the canonical repository or its refs. A candidate Git worktree is not a
  security boundary: it shares refs and objects with the canonical repository
  (`cloudeo/workspace/git.py`), so a shell-capable agent in it could move
  `refs/cloudeo` around the gate. The CLI's changes return only through the
  existing bundle, validate, and apply path (`build_input_bundle`,
  `validate_output_bundle`, `check_candidate_unchanged`, `apply_delta`),
  never by writing the worktree. Until that isolation exists and is tested,
  no native-CLI profile may be bound to a write-capable role.
- **Loop policy belongs to control.** Bounds that decide whether work may
  continue (repair rounds, stopping on a repeated classified failure) are
  control policy, added as control rules. DevLoop only runs the recipe
  (ADR-030 scope rule).
- **Acceptance stays gate promotion.** "Accepted" means promotion of the
  broker's accepted ref through the gate. Publishing a branch or pull
  request, or merging it, is a separate future adapter behind a human gate.

**Relationship to `15_PROVIDER_NEUTRAL_EXECUTION_AND_DEVLOOP.md`:** where that
draft conflicts with this ADR, ADR-030, `13_V2_CONTROL_ARCHITECTURE.md`, or
`14_V2C_TRACEABILITY.md`, those govern. In particular they supersede its §5.2
competing `ExecutionProfile` (stored fingerprint, no model family), its §7
adapter call that bypasses request kinds and the dispatcher, its §10.2 second
profile registry, its §12 independence levels, its §4.3 "records nested in
one" wording (the rule is: records only the state machine creates), and its
§8.3 native-CLI plane without OS isolation.

**Test for every new provider:** it is added by registering an adapter and a
profile and passing the shared conformance suite, with no change to
`cloudeo.control`. If that is impossible, the adapter is badly isolated or
the runtime is a genuinely new execution class that needs its own
provider-neutral contract.

**Traceability:** the genuinely new invariants are traced in
`14_V2C_TRACEABILITY.md` under a Provider-Neutral (PN) section, keeping the
draft's numbering: PN-01, PN-03, PN-04, PN-05, PN-07, and PN-10, plus PN-12
(the dependency direction above) and PN-13 (native-CLI isolation) from this
ADR. All are DEFERRED until implemented. Rules that only refine an existing
V2C invariant are listed there against that invariant, not duplicated.

**Consequences:** Codex CLI, Claude Code, and Kimi Code can be added without
changing control semantics, after two one-time, provider-neutral control
additions (the profile fields and the billing policy). A coding executor on
the LongHorizon path also needs its own LongHorizon adapter and an entry in
`cloudeo/longhorizon/roles.py`, outside control. The first implementation
slice stays inside `cloudeo.execution`: a neutral error class and runtime
identity fields, additive and behavior-preserving, plus the dependency
checks above.

---

## ADR-036 — Workflow-run execution plane and the gh-aw adapter

**Status:** Proposed (2026-10-27); not implemented. Extends ADR-035; amends no
accepted ADR. Depends on ADR-035 implementation slice 1 (on
`feat/v2-execution-neutral-errors` at 55ed4b3, not yet merged) and the ADR-035
profile fields (see "Implementation sequence"). The unpaid P0 transport spike
ran on 2026-10-27 against a stub engine. Transport, isolation, integrity, and
cancellation passed. Agent-sandbox behavior and the engine-dependent facts
remain UNVERIFIED. The spike's seven findings are folded into this entry,
each marked "(P0)".

**Context:** GitHub Agentic Workflows (gh-aw, `github/gh-aw`) compiles a
Markdown workflow into a pinned GitHub Actions workflow (`.lock.yml`) that runs
a coding agent (Claude Code, Codex, Copilot CLI, Gemini, Pi) in an ephemeral
runner, behind an egress firewall, with a read-only agent job and privileged
GitHub writes deferred to separate "safe output" jobs. It also offers a
Git-backed Work Queue with its own transaction log. That gives Cloudeo a
ready, isolated, remotely hosted execution substrate it does not have to
provision. It also brings a second potential lifecycle authority, metered-only
Claude authentication (`ANTHROPIC_API_KEY` or Anthropic WIF; subscription OAuth
tokens such as `CLAUDE_CODE_OAUTH_TOKEN` are not supported), and GitHub Actions
compute cost. ADR-035 requires such a runtime to enter Cloudeo as an adapter in
`cloudeo.execution`, without changing `cloudeo.control`.

**Decision:** Cloudeo adds a **workflow-run execution plane**: a bounded,
non-interactive run of a remotely hosted, pinned workflow that receives a
Cloudeo input bundle and returns an output bundle plus evidence. gh-aw is its
first adapter. gh-aw is an execution backend only. It never decides WorkOrder
state, verification, or acceptance.

**Plane and contracts (in `cloudeo.execution`):**

- **New request kind.** `WorkflowRunExecution` (`kind: "workflow_run"`) is a
  neutral request model: `adapter_id`, workflow identity (see "Pinning"),
  requested engine and model, `bridge_run_id`, the input bundle reference and
  sha256, the task prompt reference, and bounds (timeout, turn limit). It is
  not a GitHub or gh-aw wire model. `ExecutionDispatcher` stays the only router
  by kind; the plane's backend selects the adapter by `adapter_id` from the
  execution adapter registry.
- **Closed literals widen additively.** `ExecutionRequest` and
  `ExecutionOutcome.kind` gain `workflow_run`; `RuntimeIdentity.backend` and
  `ExecutionError.source` gain `gh_aw`, the backend name, alongside `treg`
  and `uhp`. The slice-1 identity fields carry the rest:
  `execution_plane = "workflow_run"` and `adapter_id = "gh-aw"`, both set by
  construction. `provider` and `inference_provider` keep their ADR-035 meaning
  (PN-03): the commercial identity of the model and inference, for example
  `anthropic`. They are set only from what the run reported and stay `None`
  otherwise. GitHub Actions is the **execution host**, not a provider. It is
  recorded as run provenance (`execution_host = "github-actions"` with the
  run and runner identity, see "Pinning and provenance"), not in `provider`.
  A `RuntimeIdentity` host field, if one is wanted, is a separate additive
  contract change. Native
  GitHub and gh-aw codes stay evidence; failures map to the slice-1
  `ErrorClass` (a digest mismatch, a write by a read-only role, or a foreign
  attempt is `workspace_violation`).
- **First populated `artifacts`.** `ExecutionOutcome.artifacts` is empty today
  ("never inferred"). This adapter is the first to fill it, and only with
  artifacts it downloaded and hashed: name, provider artifact id, size,
  sha256. A listed but undownloaded artifact is not an artifact.
- **Neither Session Fabric nor Cloud Execution Fabric.** A workflow run has no
  interactive lifecycle, messaging, or handover (ADR-031), and Cloudeo neither
  provisions nor destroys its compute (ADR-032; runner selection is not fabric
  authority). No `CloudExecutionFabric` implementation is created for GitHub
  Actions. ADR-032's provenance discipline applies anyway: immutable
  environment identity, evidence before the run counts, unknown stays unknown.

**Runner isolation:**

- **Dedicated runner repository.** gh-aw workflows live in a private runner
  repository that contains no project source and whose tokens have no access
  to the project repository. The project repository is never the workflow
  host.
- **Trigger and permissions.** `workflow_dispatch` only; no issue, PR,
  comment, schedule, or push triggers, so untrusted content enters only
  through the WorkOrder task. Agent job `permissions: contents: read`;
  `checkout:` disabled.
- **No GitHub writes from the run.** No write-capable safe outputs (no
  `create-pull-request`, `push-to-pull-request-branch`, comments, issues, or
  labels). Publishing a branch or PR stays a separate future adapter behind a
  human gate (ADR-035 "Acceptance stays gate promotion").
- **Disable gh-aw's write defaults explicitly (P0).** By default gh-aw turns
  on issue creation and failure, no-op, incomplete, and missing-tool reporting
  as issues, and it starts a GitHub MCP server. Every governed workflow must
  set all of the following, and compilation must leave no job with a `write`
  permission:
  - `create-issue: false`;
  - `report-failure-as-issue: false`, `report-failed-jobs: false`,
    `report-missing-tool: false`, `report-missing-data: false`, and
    `report-incomplete: false`;
  - `noop.report-as-issue: false`;
  - `tools.github: false`.
- **Work Queue off.** The gh-aw Work Queue is not used. WorkOrder lifecycle
  and scheduling have one authority, Cloudeo. A later ADR may admit it as a
  subordinate scheduler only.
- **Network.** The firewall allowlist is the inference provider endpoint plus
  what the approved profile names (for example package registries). The
  network policy is part of the pinned workflow identity.

**Candidate transport:**

- **One return path.** The candidate reaches the runner only as a Cloudeo
  input bundle (`build_input_bundle`, existing bridge format) and changes
  return only as an output bundle through `validate_output_bundle` →
  `check_candidate_unchanged` → `apply_delta`. This satisfies PN-13: the
  runner is OS-isolated and never sees the canonical repository or its refs.
- **Inbound.** The input bundle reaches the runner as a release asset of the
  runner repository. Only `bridge_run_id`, the asset id, and the bundle sha256
  are passed as workflow inputs. A `pre-agent-steps:` step (outside the agent
  firewall) downloads the asset, refuses it on a digest mismatch, and
  materializes it into an empty directory.
- **Asset lifecycle.** One asset belongs to exactly one `bridge_run_id`:
  1. *Create.* The adapter creates a release tagged and named by
     `bridge_run_id` and uploads the asset. The release must be published
     before dispatch, never left as a draft, because the job's `contents: read`
     token cannot see draft releases (P0). The adapter then reads the asset back
     through the API and compares its sha256 with the bundle before it
     dispatches. If any step fails, the adapter deletes what it created and
     does not dispatch.
  2. *Upload credential.* Creating and deleting releases needs a
     runner-repository `contents: write` credential. Only the adapter holds
     it, and only outside the run. It is never a workflow secret, an input, or
     visible to any job. Inside the run, tokens stay `contents: read`.
  3. *Single use.* The pre-agent step accepts the asset only if its release tag
     equals the dispatched `bridge_run_id`. Cloudeo records the first run that
     consumed it, and any other run or attempt naming the same
     `bridge_run_id` is foreign: its output is never applied.
  4. *Expiry and cleanup.* The adapter deletes the release and its tag after
     the terminal observation. It also deletes them at a TTL equal to the
     agent-job timeout plus a margin, whichever comes first. Deletion is
     idempotent.
  5. *Reconciliation.* After an orchestration restart, reconciliation lists
     releases whose `bridge_run_id` has no live run and deletes them. They are
     reported as orphaned runtime resources, as in ADR-032 CF-12.
- **Outbound.** A `post-steps:` step runs the bridge remote helper, pinned by
  sha256 to a recorded `cloudeo/bridge/remote_helper.py` version, which builds
  the delta bundle with `bridge_run_id` in its manifest, and uploads it as an
  Actions artifact. The adapter downloads it by run and artifact id, hashes it,
  and hands it to the existing validator. A manifest whose `bridge_run_id`
  differs from the request is rejected. The artifact API `digest` covers the
  zip only. The adapter's own sha256 of the inner bundle governs (P0).
- **Post-steps are not trusted (P0).** `post-steps:` run under the agent's uid,
  on paths the agent can write. They also run after a step that can write the
  job's `$GITHUB_PATH` and `$GITHUB_ENV`. Therefore:
  - post-steps call binaries by absolute path from read-only locations;
  - the pinned helper is taken from outside agent-writable paths, or
    re-hashed against its recorded sha256 immediately before it runs;
  - any hash or verdict a step prints is transport only, never evidence;
  - evidence is what the adapter computes after download.
- **Rejected alternatives.** Pushing the candidate to any project-repository
  ref (a ref outside the broker, reachable around the gate); gh-aw `aw.patch`
  or PR safe outputs (an unvalidated Git patch, a write path we do not own);
  inline workflow inputs (strings only, size-bounded); an external object
  store (new infrastructure and credentials). P0 showed the release-asset path
  works, so the orphan transport branch fallback is not needed.

**Correlation, retries, and cancellation:**

- `bridge_run_id` is the primary correlation id and the idempotency key. The
  adapter dispatches with `return_run_details: true` and an explicit
  `X-GitHub-Api-Version` header (P0: the default REST version carries a
  deprecation notice). The `workflow_run_id` in the dispatch response is the
  run id. P0 saw it on every dispatch. That run id is recorded, but it never
  replaces `bridge_run_id`. Only if it is missing is the run found by a
  `run-name` that contains `bridge_run_id`. That search tolerates the short
  window in which a queued run's title still shows the workflow name. In both
  cases the delta manifest's `bridge_run_id` must match.
- Every `run_attempt` is explicit and Cloudeo-initiated. A re-run started
  outside Cloudeo is observed as foreign and its output is not applied. A
  delta for a given `bridge_run_id` is applied at most once.
- Cancellation calls the provider cancel API and then observes. Until a
  terminal conclusion is observed, the status is `in_progress` or `unknown`,
  never `cancelled`. A cancel on a queued run can return `409 Conflict`; the
  adapter retries it, bounded. Reaching a terminal state took about 100 s in
  P0, and the observation timeout allows for that.
- **Apply only a successful attempt (P0).** A cancelled run still uploads its
  output artifact, because `always()` post-steps run on cancellation. A delta
  is applied only when the observed run `conclusion` is `success` and the
  artifact's `run_attempt` equals the Cloudeo-initiated attempt. An artifact
  from any other conclusion is evidence only and is never applied.
- A completed run whose output artifact cannot be downloaded and hashed is
  `incomplete` and fails closed (ADR-032 CF-05, CF-07). `completed` never
  implies verified.

**Billing and cost:**

- **Declared mode.** A gh-aw profile declares `billing_mode` per ADR-035. With
  the Claude engine, the only valid mode is metered API (key or WIF). The
  adapter refuses to run a profile that declares a subscription mode, and it
  never runs in a mode other than the declared one.
- **Envelope.** A gh-aw profile is usable only where the project's approved
  Execution Profile policy allows metered use and sets a cap in currency. A
  metered gh-aw profile serves as a fallback only through an approved
  fallback binding with its condition.
- **The cap must be enforceable before the run.** A run is dispatched only
  if the adapter can show that its worst-case inference spend fits the
  remaining cap. Turn and time limits (`max-turns`, `timeout-minutes`) never
  make such a bound on their own, because the tokens per turn are not
  bounded. AWF AI credits are gh-aw's own operating unit, not money, and do
  not count as a bound unless a documented, fixed conversion to tokens is
  established. An acceptable bound comes from one of two sources:
  - a provider-enforced hard spend limit on a dedicated inference workspace,
    verified before dispatch to be no higher than the remaining cap;
  - a total-token ceiling that the runtime enforces, multiplied by the maximum
    list price of the declared model.

  The adapter records the bound, its source, and the price identity it used.
- **Unprovable bound means policy refusal.** If no such bound can be shown,
  the run is not dispatched, and Cloudeo records an explicit policy refusal
  with its evidence: the cap, the missing or unenforceable bound, and the
  price identity consulted. Nothing ran, so this is not an `ExecutionError`
  and gets no `ErrorClass`. It is mapped to no `FallbackCondition`, so no
  fallback profile is tried. A dedicated refusal type in the contracts would
  be a separate, approved contract change; this ADR adds none.
- **Hard stops are not policy.** The gh-aw stops and a provider-side spend
  limit on a dedicated inference workspace are mechanisms that make the bound
  hold, plus defense in depth. None of them replaces the Cloudeo cap check.
  No paid run happens before this rule is implemented and tested.
- **Observed cost.** Token usage comes from the run's `usage` artifact where
  present and stays tokens (`ExecutionCost` never converts tokens to money).
  AWF AI credits are gh-aw's own unit and are never recorded as observed
  cost. Actions minutes and runner class are infrastructure cost evidence
  under ADR-033. Unreported values stay `unknown`.
- **Credential boundary.** The inference credential is a runner-repository
  secret that Cloudeo never holds. Cloudeo's GitHub credential (dispatch,
  asset upload and delete, run observation, artifact download) is consumed
  only by the gh-aw adapter. ADR-032's credential-boundary rule applies
  unchanged.
- **Data egress.** Candidate content leaves to GitHub and to the inference
  provider. A project may bind a gh-aw profile only if its policy permits
  that data class to leave.

**Pinning and provenance:**

- Workflow identity is the runner repository, workflow path, the commit sha of
  the compiled `.lock.yml`, and its sha256. A branch name is never the
  identity. `engine.version` and `engine.model` are pinned in the workflow.
  Without `engine.model` the harness falls back to a moving model alias (P0).
  The workflow identity also records the gh-aw compiler version (v0.93.5 at
  drafting), the AWF version, and the container image digests from the lock
  manifest (P0).
- Runtime provenance records `execution_host = "github-actions"`,
  `github_run_id`, `run_attempt`, runner image
  identity (`ImageOS`, `ImageVersion`, never the `ubuntu-*` label alone,
  ADR-032 CF-10), requested and actual engine, CLI version, and model, the
  input and output bundle digests, and start, end, and billable duration where
  reported.

**Roles:**

- **Auditor first, read-only by construction.** The first permitted role is a
  read-only auditor. Read-only is enforced, not inferred from the output. The
  AWF sandbox makes the runner workspace, `/tmp`, and `$HOME` writable by
  default. For an auditor run, the candidate is therefore materialized outside
  every agent-writable path. It is mounted read-only into the agent container
  through `sandbox.agent.mounts` (`<path>:<path>:ro`), and scratch output goes
  to a separate read-write directory (P0). The raw downloaded bundle is not
  left on an agent-visible path. As defense in depth, `pre-agent-steps:` and
  `post-steps:` each check the candidate tree against the input manifest
  (paths, types, modes, sizes, sha256). A difference, or a non-empty delta,
  makes the audit invalid (`workspace_violation`). If a read-only mount cannot be configured,
  or its enforcement against the agent is unverified, no gh-aw profile may be
  bound to an auditor role: the integrity check alone
  detects a violation but does not prevent one. Fresh-session
  evidence is the new `github_run_id`/`run_attempt` on a fresh runner, under
  V2C-14 and `13_V2_CONTROL_ARCHITECTURE.md` §8.6. A different engine or
  provider can only tighten independence. On the LongHorizon path the gh-aw
  auditor needs its own LongHorizon adapter and an explicit row in
  `cloudeo/longhorizon/roles.py`, which is keyed by exact adapter type, outside
  control.
- **Writer later.** A write-capable role is bound only after the PN-13
  isolation and return-path conformance tests exist for this adapter. SF-08
  holds: at most one active write-capable run per CandidateWorkspace;
  `check_candidate_unchanged` rejects local drift. Parallel runs use separate
  candidates.
- **Subagents.** gh-aw subagents inside one run share its engine, privileges,
  and environment. They are never counted as independent auditors.

**Architecture checks:** DEFERRED until implemented; traced in
`14_V2C_TRACEABILITY.md` when the first slice lands.

| Check | Rule |
| --- | --- |
| WR-01 neutral request | `WorkflowRunExecution` contains no GitHub or gh-aw type; such types appear only in the gh-aw adapter module. |
| WR-02 single return path | Workflow-run changes reach a candidate only through `validate_output_bundle`, `check_candidate_unchanged`, and `apply_delta`. |
| WR-03 no GitHub writes | The runner workflow has no trigger, token, or safe output that can write to the project repository. Every gh-aw issue-reporting default is disabled and `tools.github` is false. No job in the compiled `.lock.yml` holds a `write` permission. |
| WR-04 pinned identity | A governed run records the `.lock.yml` commit sha and sha256, `engine.version`, `engine.model`, the AWF version, and the container digests. A branch, a tag, or a moving model alias alone is refused. |
| WR-05 at-most-once apply | A delta for a `bridge_run_id` is applied at most once. It is applied only when the run conclusion is `success` and the `run_attempt` matches the Cloudeo-initiated one. Foreign attempts and artifacts from cancelled or failed runs are never applied. |
| WR-06 evidence or fail closed | A run without a downloaded, hashed output artifact is `incomplete`, never `completed`. |
| WR-07 enforceable currency cap | The adapter refuses a profile whose billing mode it cannot honor. It dispatches only when a recorded worst-case spend bound, from a provider hard limit or an enforced token ceiling (never turns or time alone), fits the remaining currency cap. Otherwise it records a policy refusal with no fallback. |
| WR-08 no second lifecycle authority | The gh-aw Work Queue is disabled in every governed workflow. |
| WR-09 auditor read-only by construction | An auditor run mounts the candidate read-only and checks its integrity before and after; without a read-only mount the profile is not bindable to an auditor role. |
| WR-10 asset lifecycle | An input asset is published (not draft) and digest-verified before dispatch. It is bound to one `bridge_run_id`, created and deleted only with a credential no job can see, and deleted at terminal observation or TTL. |
| WR-11 untrusted post-steps | Post-steps use absolute binaries from read-only paths and a helper re-verified against its pinned sha256. Values printed inside the run are never recorded as evidence. |

**Test for this adapter:** it is added by registering the adapter and a
profile and passing the shared conformance suite, with no change to
`cloudeo.control`. A fake workflow-run backend covers dispatch, observe,
cancel, retry, missing-artifact, and drift cases without network.

**Non-goals:** the gh-aw Work Queue; issue or PR triggers; publishing branches
or PRs; Copilot or other engines' billing modes (each gets its own profile
decision); interactive Sessions on GitHub Actions; a GitHub Actions
`CloudExecutionFabric`; COST policy changes; forking or patching gh-aw.

**Relationship to other ADRs:** extends ADR-035 (new plane, adapter
placement, billing envelope, PN-13). Uses the bridge of ADR-017 and its bundle
API. Applies ADR-032 provenance, evidence, and credential rules by reference
without making GitHub Actions a fabric. Respects ADR-031 SF-08 and SF-14, and
ADR-033 cost accounting. ADR-030 boundaries are unchanged.

**Implementation sequence:**

0. **P0 transport spike, unpaid, outside Cloudeo code. Done 2026-10-27.** The
   spike used a synthetic candidate, a stub engine through `engine.command`,
   and no inference credential. It ran in a dedicated runner repository with no
   project access. Its criteria were:
   1. The asset is created, read back, and digest-verified through the API
      before dispatch, using a credential no job sees.
   2. `pre-agent-steps:` can fetch it under the network policy while the job
      token stays `contents: read`.
   3. Dispatch with `return_run_details: true` returns `workflow_run_id`, or
      else `run-name` correlation works.
   4. The materialized directory is reachable from the job's agent step, and
      files written there are visible to `post-steps:`. A deterministic stub
      stands in for the agent. That shows the runner-level file path only. It
      does not show what an agent inside the AWF sandbox can read or write.
   5. A read-only mount of the candidate can be configured, and the
      before/after integrity check detects a deliberate write made by the stub.
   6. The delta artifact downloads and hashes, whether or not the artifact API
      exposes a digest; if it does not, the adapter's own sha256 governs.
   7. `checkout: false` removes the agent-job checkout. The docs say the
      separate activation checkout stays, which is acceptable because the
      runner repository holds no project source.
   8. Cancellation reaches a terminal conclusion.
   9. The release and its tag are deleted after the run.

   Results are judged separately for **transport** (1, 3, 6, 9),
   **isolation** (2, 7), **integrity** (5 and the integrity check),
   cancellation (8), and **agent-sandbox behavior**. Agent-sandbox behavior
   covers the agent's actual read and write access inside AWF, and whether the
   read-only mount holds against the agent itself. It stays UNVERIFIED until a
   test runs inside the real sandbox. A property is never marked verified just
   because transport works.

   **Outcome:**
   - Transport, isolation, integrity, and cancellation: PASS.
   - The tamper run was detected and failed closed.
   - The `:ro` mount refused writes from a process in the AWF container
     (runner level).
   - Agent-sandbox behavior: UNVERIFIED.
   - Engine-dependent facts (the `usage` token data, the actual model
     identity): UNVERIFIED. They wait for a separately approved paid run, or an
     engine-free sandbox probe if the owner accepts one.
   - The seven findings marked "(P0)" above are part of this entry.

   An UNVERIFIED agent-sandbox result still blocks binding any role.
1. **ADR-035 slice 1 and profile fields** (prerequisite, not this ADR). Slice
   1 already holds the neutral error class, the runtime identity fields, and
   the dependency AST checks (`feat/v2-execution-neutral-errors` at 55ed4b3,
   PR #2). Still open: the additive profile fields (`adapter_id`,
   `execution_plane`, `billing_mode`, `auth_profile_ref`) and the billing
   envelope policy, including the currency cap of WR-07.
2. **Contracts and fake backend:** `WorkflowRunExecution`, the widened
   literals, dispatcher routing, and the conformance suite against a fake.
3. **gh-aw adapter, auditor role only:** dispatch, observe, cancel, bundle
   transport, provenance, cost evidence, WR-01 to WR-11 checks, and, for the
   LongHorizon path, the auditor adapter and its `roles.py` row.
4. **Writer role:** only after the PN-13 conformance tests pass for this
   adapter.

**Consequences:** Cloudeo gains a hosted, isolated, provider-diverse execution
backend, useful first for independent audits with a different engine,
without a second lifecycle authority and without any path around the
promotion gate. The costs are metered inference, Actions minutes, a dedicated
runner repository to operate, and a GitHub dependency limited to this one
adapter.
