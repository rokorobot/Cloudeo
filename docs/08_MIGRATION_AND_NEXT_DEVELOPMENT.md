# Cloudeo v0.1 -> v2 Migration and Next Development Plan

**Status:** Proposed implementation sequence  
**Date:** 2026-09-22  
**Rule:** No big-bang rewrite. Every phase must leave a runnable, testable system and a rollback point.

## 1. Migration strategy

The safest migration is to preserve the working v0.1 path while adding the new execution architecture beside it.

```text
v0.1 path
Jev -> Treg -> verification -> SQLite
             |
             | preserved
             v

v2 path added incrementally
TaskContext -> Router -> UHP -> HarnessRouter -> Audit -> Performance Memory
```

Only after the v2 path passes its acceptance gates should it become the default for appropriate WorkOrders.

## 2. Phase 0 — Freeze the v0.1 baseline

### Goal

Make the current behavior reproducible before architecture work begins.

### Work

- record current commit/worktree state;
- run the current test suite;
- capture a successful `/v1/runs` smoke request;
- record the current SQLite schema;
- record current adapter interfaces;
- save one mock-backend trajectory;
- save one Treg-backed trajectory if credentials are available;
- mark existing `docs/00_*` through `docs/05_*` as v0.1 baseline.

### Acceptance gate

- current tests pass;
- current API behavior is documented;
- no v2 code is required for v0.1 to run;
- a rollback to this state is trivial.

## 3. Phase 1 — Introduce execution-domain interfaces

### Goal

Create seams needed by v2 without changing runtime behavior.

### Add

Conceptual interfaces:

```text
TaskContextBuilder
CandidateProvider
PolicyEngine
ExecutionBackend
Verifier
CheckpointStore
PerformanceStore
```

Keep current implementations behind them:

```text
TregExecutionBackend
CurrentJevPolicyEngine
CurrentSQLiteStore
```

### Acceptance gate

- v0.1 behavior stays green;
- no external behavior changes;
- dependency inversion is test-covered;
- mocks can satisfy every new interface.

## 4. Phase 2 — Add UHP client + HarnessRouter development service

### Goal

Run one bounded Cloudeo task through UHP without LongHorizon migration yet.

### Add

```text
src/cloudeo/uhp/client.py
src/cloudeo/uhp/models.py
src/cloudeo/execution/uhp_backend.py
```

Names are provisional; preserve the repository's actual package conventions.

### Required behavior

- `GET /v1/uhp`;
- explicit UHP version negotiation;
- `GET /v1/harnesses`;
- model availability discovery;
- submit one response/task;
- consume terminal response;
- map `completed`, `failed`, `incomplete`, `cancelled`;
- capture session ID, response ID, harness ID;
- cancellation;
- artifact/file retrieval if used by the test task.

### Development environment

HarnessRouter is installed only in the local/dev integration environment at this phase.

### Acceptance gate

The same Cloudeo test task can be run through:

1. one Codex configuration;
2. one Claude Code configuration;

using the same `ExecutionBackend` interface.

No Cloudeo-native Codex or Claude adapter is allowed for this proof.

## 5. Phase 3 — Canonical Workspace Broker

### Goal

Prove cross-session state continuity safely.

### First scope

Git-backed coding tasks only.

### Add

```text
WorkspaceBroker
CheckpointRef
CandidateWorkspace
ArtifactManifest
```

### Flow

```text
C0 accepted
 -> create candidate from C0
 -> run harness
 -> capture candidate diff/artifacts
 -> independently audit candidate
 -> PASS: accept C1
 -> FAIL: retain C0
```

### Acceptance gate

- failed audit cannot advance the accepted checkpoint;
- switching Codex -> Claude starts from the accepted checkpoint, not Codex private session state;
- stale/foreign workspace data cannot be accepted accidentally;
- candidate and accepted states are addressable by immutable identifiers.

## 6. Phase 4 — Integrate LongHorizon as the durable loop

### Goal

Move multi-round objective state and independent audit to LongHorizon rather than growing Cloudeo's retry loop into a second long-horizon framework.

### Integration approach

Add a UHP-backed `AgentAdapter` or equivalent bridge at the existing LongHorizon adapter boundary.

Do **not** rewrite LongHorizon Manager/Executor/Auditor logic.

Cloudeo remains outside/above LongHorizon for:

- WorkOrder identity;
- routing;
- profile registry;
- Workspace Broker;
- Performance Memory;
- lifecycle governance.

### Acceptance gate

A task must demonstrate:

```text
round 1 -> harness A -> audit fail
round 2 -> harness B -> audit pass
```

while preserving:

- original objective;
- verified state;
- failure evidence;
- canonical checkpoint.

The second harness must not require the first harness's private conversation history.

## 7. Phase 5 — Deterministic multi-profile router

### Goal

Add dynamic selection infrastructure before Jev becomes authoritative.

### Candidate inputs

- UHP harness discovery;
- UHP model availability;
- Treg capabilities;
- browser execution profiles, if configured;
- human gate;
- recovery actions.

### Initial policy

Rules only.

Examples:

```text
typed API capability available and sufficient -> Treg
CLI coding + tests + writable Git workspace -> coding harness candidates
browser-only task -> browser profile
high-risk mutation with no verifier -> human gate
```

### Acceptance gate

Every routing decision records:

- full candidate set;
- excluded candidates + reason;
- selected profile;
- policy version;
- task-context hash.

## 8. Phase 6 — Performance Memory v1

### Goal

Turn verified runs into comparable execution evidence.

### Initial storage

SQLite.

Suggested tables:

```text
execution_profiles
routing_decisions
execution_attempts
verification_outcomes
performance_events
performance_aggregates
upstream_versions
```

### Critical invariant

`performance_events.verified_success = true` may be written only after the authoritative verification boundary passes.

### Initial metrics

- attempts;
- verified successes;
- verified failures;
- incompletes;
- cancellations;
- failure classes;
- median duration;
- cost;
- retry count;
- recovery success;
- human intervention;
- version fingerprint.

### Acceptance gate

Two identical replayed runs do not duplicate one attempt identity, and an executor self-report cannot create a verified-success row.

## 9. Phase 7 — Jev-backed dynamic policy

### Goal

Use Jev where it adds value: fast contextual choice among already valid execution options.

### Inputs

Compact TaskContext plus candidate summaries and relevant Performance Memory features.

### Output

One candidate ID plus confidence/operation metadata.

### Safety boundary

Jev cannot:

- invent a runtime;
- invent a tool;
- bypass hard constraints;
- write directly to accepted state;
- declare verified success.

### Fallback

If Jev is unavailable or below confidence threshold:

1. deterministic policy;
2. optional stronger reasoning policy if configured;
3. human gate for unresolved high-risk decisions.

### Acceptance gate

Offline replay must show that the Jev policy can consume historical candidate sets without performing live mutations.

## 10. Phase 8 — Adaptive cross-harness recovery

### Goal

Use structured failures and verification evidence to choose the next recovery action.

### Failure taxonomy v1

```text
runtime_unavailable
runtime_failed
budget_incomplete
tool_unavailable
test_failure
artifact_mismatch
permission_failure
environment_failure
verification_failure
repeated_no_progress
ambiguous_objective
```

### Recovery candidates

```text
retry_same
switch_profile
switch_harness
switch_model
diagnostic_only
decompose
restore_checkpoint
increase_budget
human_gate
blocked
```

### Acceptance gate

At least three deterministic fault injections must recover correctly:

- timeout/incomplete;
- executor output with failing tests;
- selected harness unavailable.

## 11. Phase 9 — Upstream lifecycle automation

### Goal

Monitor upstreams without allowing upstream churn to destabilize production.

### First scope

Monitor:

- UHP specification;
- HarnessRouter;
- LongHorizon-Harness;
- Jev/jev-ultrafast;
- Codex;
- Claude Code;
- Hermes;
- Treg.

### Rule

Candidate updates are installed/pinned only in a **development/integration checkout/environment** first.

The watcher must not:

- modify production automatically;
- merge a feature PR;
- replace a production pin;
- copy arbitrary upstream source into Cloudeo.

### Acceptance gate

A simulated upstream version bump produces:

1. candidate record;
2. dev-only staged version;
3. compatibility test result;
4. benchmark comparison;
5. explicit promote/reject decision;
6. rollback data.

## 12. Phase 10 — Server migration

Only after local v2 is stable:

```text
WSL2/SQLite
    ->
single Ubuntu 24.04 server
Docker Compose
Postgres
persistent HarnessRouter storage
artifact/evidence storage
```

Do not distribute runners until measurements show one server is insufficient.

## 13. Recommended immediate next work

The next coding checkpoint should contain only:

1. v0.1 baseline evidence;
2. UHP client abstraction;
3. HarnessRouter local dev configuration;
4. one `UHPExecutionBackend`;
5. one integration test through a mock/fake UHP server;
6. one live smoke through HarnessRouter;
7. no dynamic learning yet.

Then prove two harnesses through the same contract.

## 14. Stop conditions

Pause the migration if any of these occur:

- UHP cannot expose a capability LongHorizon requires without runtime-specific escape hatches;
- candidate workspace state cannot be reproduced independently;
- audit depends on executor-native hidden state;
- v2 requires invasive changes to LongHorizon core rather than a thin adapter;
- verified outcome schemas cannot represent current v0.1 Treg runs;
- dependency upgrades cannot be pinned/reproduced.

Resolve the boundary problem before adding more layers.

## 15. Definition of v2 alpha

Cloudeo v2 alpha exists when:

- v0.1 direct Treg execution still works;
- two UHP harness profiles execute through one backend interface;
- LongHorizon can switch harness between rounds;
- accepted state survives the switch;
- independent audit controls checkpoint promotion;
- verified outcomes enter Performance Memory;
- a deterministic router can use that memory;
- Jev can optionally select among a bounded candidate set;
- upstream updates are staged outside production.
