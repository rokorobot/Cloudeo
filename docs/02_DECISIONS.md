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
from. Promotion requires the accepted commit to still equal that base, and then
advances it with Git's atomic `update-ref <ref> <new> <expected-old>`. If
accepted moved from A to B after candidate C began from A, promoting C fails as
stale and B is kept. There is no auto-rebase, force-reset, or history rewrite;
every promotion is a fast-forward. Only commits the broker recorded as
checkpoints for that candidate and workspace can be promoted.

**Rejection:** leaves accepted state unchanged and keeps the rejected commit
reachable through a `rejected` ref, so the evidence is not lost. The returned
`RejectionRecord` carries the reason; storing reasons and richer evidence
durably is future work.

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
