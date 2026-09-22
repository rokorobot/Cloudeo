# Cloudeo v2 — Target Architecture

**Status:** Target architecture; not yet implemented  
**Date:** 2026-09-22  
**Architecture principle:** Reuse mature upstream execution infrastructure. Keep Cloudeo focused on adaptive policy, verified state continuity, learning, and lifecycle governance.

## 1. Product-level objective

Cloudeo v2 is an adaptive execution layer for autonomous work.

It should:

1. represent an objective and current verified context;
2. generate a bounded set of valid execution options;
3. select an execution strategy dynamically;
4. run the strategy through typed tool planes or standardized harness infrastructure;
5. independently verify the result;
6. checkpoint only accepted progress;
7. recover from failed attempts, including by switching runtimes;
8. learn from verified execution history;
9. evaluate upstream component updates before promoting them.

A compact description is:

> **Route. Execute. Verify. Recover. Learn.**

## 2. System architecture

```text
                              USER / API
                                  |
                                  v
                        +-------------------+
                        |  WorkOrder / Goal |
                        +---------+---------+
                                  |
                                  v
                  +-------------------------------+
                  |       LONGHORIZON LOOP        |
                  | objective + verified state    |
                  | remaining work + recovery     |
                  +---------------+---------------+
                                  |
                         bounded next step
                                  |
                                  v
                  +-------------------------------+
                  |      TASK CONTEXT BUILDER     |
                  | requirements / risk / budget  |
                  | failure history / checkpoint  |
                  +---------------+---------------+
                                  |
                                  v
                  +-------------------------------+
                  |    CLOUDEO DYNAMIC ROUTER     |
                  | constraints -> candidates     |
                  | deterministic -> Jev/policy   |
                  +-------+---------------+-------+
                          |               |
             direct tool  |               | harness task
                          v               v
                   +------------+   +------------+
                   |    TREG    |   |    UHP     |
                   | capability |   |  client    |
                   +------+-----+   +------+-----+
                          |                |
                          |                v
                          |        +---------------+
                          |        | HarnessRouter |
                          |        +-------+-------+
                          |                |
                          |      +---------+----------+----------+
                          |      |         |          |          |
                          |    Codex     Claude     Hermes     future
                          |      |         |          |          |
                          |      +---------+----------+----------+
                          |                |
                          +-------+--------+
                                  |
                                  v
                      +-------------------------+
                      |   CANDIDATE OUTCOME     |
                      | files / diff / evidence |
                      +------------+------------+
                                   |
                                   v
                      +-------------------------+
                      |  VERIFICATION BOUNDARY  |
                      | deterministic checks +  |
                      | LongHorizon read-only   |
                      | Auditor                 |
                      +------------+------------+
                                   |
                           +-------+-------+
                           |               |
                         PASS             FAIL
                           |               |
                           v               v
                   accepted checkpoint   recovery event
                           |               |
                           +-------+-------+
                                   |
                                   v
                      +-------------------------+
                      |   PERFORMANCE MEMORY    |
                      | verified outcome only   |
                      +------------+------------+
                                   |
                                   +-------> future routing
```

## 3. Control-plane boundaries

### 3.1 Cloudeo owns

Cloudeo owns decisions that remain valuable regardless of which agent runtime is fashionable:

- WorkOrder API and identity;
- task/context representation;
- candidate generation;
- hard constraint filtering;
- routing policy;
- execution profile registry;
- workspace/checkpoint continuity;
- verification contracts;
- performance event schema;
- historical performance aggregation;
- recovery policy;
- upstream component lifecycle;
- operator approval gates;
- product observability.

### 3.2 Cloudeo does not own

Cloudeo should not reimplement:

- Codex's native loop;
- Claude Code's native loop;
- Hermes' native loop;
- LongHorizon's Manager/Executor/Auditor mechanics;
- UHP protocol semantics;
- HarnessRouter session/runtime management;
- Treg provider catalog internals;
- Jev model serving.

Adapters remain necessary, but they should be thin protocol boundaries, not duplicate implementations.

## 4. Core domain objects

### 4.1 WorkOrder

A durable user objective.

```text
WorkOrder
- id
- objective
- acceptance_criteria[]
- risk_class
- budget
- workspace_ref
- created_at
- status
```

### 4.2 TaskContext

A bounded decision input for one LongHorizon round.

```text
TaskContext
- work_order_id
- round_id
- step_objective
- surface                  # cli | gui | browser | api | mixed
- task_class               # debugging | research | data | refactor | ...
- language_stack[]
- required_capabilities[]
- forbidden_capabilities[]
- risk_class
- accepted_checkpoint
- verified_state_summary
- previous_failure_classes[]
- retry_count
- budget_remaining
- candidate_profile_ids[]
```

The router should not consume unbounded raw transcripts by default.

### 4.3 ExecutionProfile

The unit Cloudeo routes to.

```text
ExecutionProfile
- id
- execution_class          # direct_tool | uhp_harness | browser | human
- harness_id               # if UHP
- harness_base
- model
- tools
- skills
- permissions
- reasoning_profile
- timeout_seconds
- max_steps
- cost_policy
- version_fingerprint
```

Two configurations of the same harness are different profiles if their behavior can differ materially.

### 4.4 RoutingDecision

```text
RoutingDecision
- id
- task_context_hash
- candidate_ids[]
- selected_id
- policy_id
- policy_version
- confidence
- hard_constraints_applied[]
- historical_features_used[]
- created_at
```

### 4.5 CandidateOutcome

```text
CandidateOutcome
- attempt_id
- runtime_status           # completed | failed | incomplete | cancelled
- output_summary
- artifacts[]
- diff_ref
- logs_ref
- cost
- duration_ms
- runtime_metadata
```

Runtime `completed` is not the same as verified success.

### 4.6 VerificationOutcome

```text
VerificationOutcome
- attempt_id
- status                   # verified_pass | verified_fail | blocked
- deterministic_checks[]
- auditor_profile
- evidence_refs[]
- integrity_findings[]
- accepted_checkpoint
- failure_class
- created_at
```

### 4.7 PerformanceEvent

Created only after verification.

```text
PerformanceEvent
- task_features
- execution_profile_id
- routing_policy_version
- runtime_status
- verification_status
- failure_class
- duration_ms
- cost
- retries_before_success
- human_intervention
- checkpoint_delta
- upstream_versions
```

## 5. Router design

The router is a pipeline, not a single unconstrained model call.

```text
TaskContext
    |
    v
hard constraints
    |
    v
candidate generation
    |
    v
deterministic routing rules
    |
    +--> decisive? ---- yes ---> select
    |
    no
    |
    v
Jev / fast policy score
    |
    +--> confident? --- yes ---> select
    |
    no
    |
    v
optional stronger reasoning / human gate
```

### Hard constraints always win

Examples:

- required capability unavailable;
- model unavailable according to UHP discovery;
- profile exceeds remaining budget;
- profile lacks required write permission;
- tool is prohibited for the WorkOrder;
- runtime unhealthy;
- profile is quarantined by upstream regression testing.

Jev never overrides these.

## 6. Jev policy integration

Jev should receive an indexed, bounded action space.

Example:

```text
Context:
- Python/FastAPI debugging
- CLI
- tests available
- accepted checkpoint abc123
- previous Claude attempt: regression failure

Candidates:
[1] codex-gpt56-cli
[2] claude-opus-cli
[3] opencode-deepseek-cli
[4] diagnostic-only
[5] decompose-step
[6] human-gate
```

Jev selects one candidate ID and operation class.

This mirrors the safe pattern used by Jev Ultrafast: observed/registered options first, model selection second.

The Jev integration must sit behind a `PolicyEngine` interface so Cloudeo can use:

- deterministic policy;
- Jev;
- offline benchmark/replay policy;
- a future learned router;

without changing orchestration.

## 7. UHP client contract

Initial requirements:

1. explicitly send `UHP-Version: 2026-09-12`;
2. call `GET /v1/uhp` on startup/refresh;
3. discover harnesses through `GET /v1/harnesses`;
4. discover model availability through the UHP model endpoints;
5. create a new session when switching configured harness;
6. preserve partial output for `incomplete`, `failed`, and `cancelled` outcomes;
7. normalize UHP status/error objects into Cloudeo `CandidateOutcome`;
8. keep UHP-native IDs in metadata for traceability.

No new Cloudeo runtime should require a dedicated native adapter if a conformant UHP server exposes it.

## 8. Workspace Broker

### 8.1 Why it exists

UHP sessions preserve their own working directory and configured harness. HarnessRouter isolates sessions. LongHorizon, however, requires a trustworthy shared concept of accepted progress.

Cloudeo therefore needs a canonical state above runtime sessions.

### 8.2 v2 coding implementation

Start Git-first.

```text
accepted checkpoint: C0
        |
        v
create candidate workspace from C0
        |
        v
executor session changes candidate
        |
        v
export diff/artifacts
        |
        v
candidate checkpoint C1
        |
        v
fresh read-only audit of C1
       / \
    PASS FAIL
     |     |
     v     v
accept C1 keep C0
```

Rules:

- the accepted checkpoint never advances before audit;
- failed candidates remain evidence but not trusted state;
- an Auditor receives the candidate state independently of the Executor's claims;
- switching harnesses never requires native session-state migration;
- a new harness begins from the accepted checkpoint plus explicit verified context.

### 8.3 Later generalization

For non-Git workflows, introduce an artifact manifest and content-addressed checkpoint representation. Do not build this before the Git-backed path works.

## 9. Verification model

Verification is evidence-first.

Priority:

1. deterministic tests/checks where possible;
2. artifact/state inspection;
3. LongHorizon read-only Auditor;
4. human approval for configured risk classes.

The router and executor are never authoritative verifiers of their own work.

## 10. Performance Memory

Performance Memory answers:

> Given this context and these allowed profiles, which execution profile has historically produced independently verified success with acceptable cost and latency?

It must distinguish:

- runtime completion rate;
- verified success rate;
- incomplete/budget-stop rate;
- failure classes;
- retries;
- recovery success;
- median/p95 latency;
- actual cost where measurable;
- human intervention;
- component versions.

Initial implementation should use the existing SQLite development footprint. Postgres can follow when the control plane moves to a server.

## 11. Recovery policy

A failed audit produces structured recovery candidates rather than an opaque retry.

Examples:

```text
RETRY_SAME_PROFILE
SWITCH_HARNESS
SWITCH_MODEL
DECOMPOSE_STEP
DIAGNOSTIC_ONLY
INCREASE_BUDGET
RESTORE_CHECKPOINT
HUMAN_GATE
BLOCKED
```

Hard policy filters unsafe or impossible actions. Jev/policy chooses among the remaining options.

## 12. Upstream lifecycle

Every upstream component is pinned.

Suggested identity:

```text
component
source
version/tag/commit/digest
license
protocol_version
last_validated_at
validation_suite
promotion_status
```

A new upstream release is a candidate, not an automatic upgrade.

See `10_UPSTREAM_COMPONENT_LIFECYCLE.md`.

## 13. Deployment stages

### Stage A — local WSL2

- Cloudeo FastAPI;
- SQLite;
- HarnessRouter local Docker;
- local LongHorizon;
- exact Git checkpoints;
- one Codex profile;
- one Claude Code profile;
- mocks for unavailable external services.

### Stage B — single Linux server

- Docker Compose;
- Postgres;
- persistent HarnessRouter volume;
- isolated execution workspaces;
- central artifact/evidence storage;
- authentication;
- upstream watcher in non-production integration environment.

### Stage C — distributed execution

Only after Stage B demonstrates a real capacity need:

- separate runners;
- remote workspace/artifact store;
- queue/scheduler;
- multi-tenant policy isolation;
- regional execution.

## 14. Non-goals for the first v2 milestone

Do not build yet:

- a custom replacement for UHP;
- a custom replacement for HarnessRouter;
- a new LongHorizon implementation;
- online reinforcement learning;
- automatic production dependency upgrades;
- a distributed scheduler;
- arbitrary cross-session filesystem synchronization;
- autonomous source-code self-modification of Cloudeo;
- a large dashboard redesign.

The milestone is execution interoperability plus verified continuity.

## References

- UHP: https://unifiedharnessprotocol.org/
- HarnessRouter: https://github.com/HarnessRouter/harnessrouter
- LongHorizon-Harness: https://github.com/AMAP-ML/LongHorizon-Harness
- Jev Ultrafast: https://github.com/browser-use/jev-ultrafast
