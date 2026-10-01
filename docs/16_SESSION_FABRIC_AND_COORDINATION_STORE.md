# ADR-031 — Session Fabric and Coordination Store boundary

**Status:** Accepted (2026-10-01); architecture only, not yet implemented.

**Decision record:** ADR-031 in `02_DECISIONS.md`, which is normative. This
document is the detailed supporting architecture (rationale, diagrams, and
examples). Where the two differ, the decision record governs.

**Amended:** 2026-10-01, before acceptance. The Session Fabric runtime
contracts and every concrete fabric adapter live in `cloudeo.execution`;
`cloudeo.orchestration` holds Session and coordination policy and lifecycle
state (see "Package boundary" below, §5, §6, §31 to §34).

## Decision

Cloudeo adds a provider-neutral **Session Fabric** and **Coordination Store**.
Session and coordination policy and lifecycle state live in
`cloudeo.orchestration`; the Session Fabric runtime contracts and every
adapter live in `cloudeo.execution` (see "Package boundary").

They provide durable lifecycle, communication, observability, runtime
coordination, provenance, and resource accounting for independently
addressable agent sessions without giving those sessions authority over
WorkOrder state, accepted workspace state, promotion, human approval, or policy.

### Package boundary (ADR-035 governs)

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

The governing dependency remains:

```text
execution providers / runtimes
           ↓
      Session Fabric
           ↓
  Cloudeo orchestration
           ↓
     Cloudeo control
           ↓
      trust kernel
```

Never the reverse.

This is the layering of authority. Package import directions are those of
ADR-030 and ADR-035.

`cloudeo.control` remains provider-blind and does not import or depend on
Session Fabric, provider session APIs, messaging transports, runtime
coordination records, or cloud-specific execution types.

A provider-native session is an execution resource. It is never itself a
Cloudeo authority.

---

## 1. Why this boundary exists

Long-running autonomous work increasingly requires several independently
steerable sessions:

```text
coordinator
   │
   ├── implementer
   ├── researcher
   ├── auditor
   └── reviewer
```

Those sessions need to:

- be created and terminated;
- remain independently observable;
- exchange messages;
- hand work over;
- share structured operational information;
- survive coordinator restarts;
- expose provider/model/runtime identity;
- expose reproducible runtime-environment identity;
- report usage, cost and failures;
- support multiple execution providers.

Provider runtimes may offer some of these functions natively, but their
semantics differ and may change independently.

Cloudeo therefore owns the coordination semantics.

Provider APIs supply execution and transport capabilities only.

---

## 2. Core concepts

ADR-031 introduces five logical concepts:

```text
Session
SessionFabricAdapter
SessionSupervisor
CoordinationMessage
CoordinationStore
```

They belong to the orchestration/runtime side of the architecture.

They do not become part of the pure control state machine.

---

## 3. Session

A **Session** is an independently addressable runtime context executing one
Cloudeo role or bounded responsibility.

A normalized Session identity records at minimum:

```text
session_id

provider
runtime
profile_fingerprint
role

project_id
workorder_id
block_id / attempt_id when applicable

parent_session_id when applicable

workspace_binding
access_mode

fabric_provider
fabric_region
runtime_class
runtime_instance_id

runtime_environment
runtime_environment_version
runtime_environment_fingerprint

created_at
last_activity_at
runtime_status
```

Additional runtime metadata may include:

```text
requested_model
actual_model

requested_harness
actual_harness

provider_session_id

capabilities

usage
runtime_cost
termination_reason
```

Requested and observed runtime identity remain separate whenever the provider
may substitute or omit identity information.

Runtime environment identity must be sufficiently stable to explain or
reproduce the environment in which a governed Session executed.

Examples of runtime environments may include:

```text
versioned VM image
container image
Claude cloud environment
local reproducible environment
future sandbox/runtime image
```

The architecture must not depend on any one environment technology.

A Session's runtime status is observational runtime evidence.

It never means:

```text
WorkOrder success
CODE_APPROVED
BLOCK_DONE
VERIFIED
PROMOTED
human approval
```

Those meanings continue to belong to their existing authorities.

---

## 4. Normalized lifecycle

Provider-specific session states are normalized into a small Cloudeo
lifecycle such as:

```text
STARTING
RUNNING
IDLE
HANDOVER
TERMINATING
TERMINATED
FAILED
LOST
```

The fabric adapter maps native state onto this lifecycle and may retain
richer native state separately.

`LOST` means that Cloudeo can no longer reliably observe the runtime session.

It must never be normalized to successful completion.

A provider reporting that a session completed means only that the runtime
ended normally.

It does not advance a WorkOrder.

---

## 5. Session Fabric

The **Session Fabric** is the provider-neutral runtime boundary through which
Cloudeo manages addressable sessions.

Conceptually:

```text
                    SessionSupervisor
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
       Claude fabric   Codex fabric   Kimi fabric
             │             │             │
             ▼             ▼             ▼
       native/runtime  native/runtime native/runtime
         sessions        sessions       sessions
```

The provider fabrics shown are concrete adapters under `cloudeo.execution`.
`SessionSupervisor` reaches them only through the neutral
`SessionFabricAdapter` contract defined in `cloudeo.execution`.

A `SessionFabricAdapter` may support operations equivalent to:

```text
create_session
inspect_session
send_message
terminate_session
```

Optional capabilities may include:

```text
wake_session
resume_session
steer_session
list_runtime_sessions
```

These are capabilities, not assumptions.

Cloudeo must not require every provider to expose identical native session
features.

Capability discovery determines what a fabric can actually do.

---

## 6. Provider-native features are adapter mechanisms

Examples include:

```text
Claude cross-session messaging
Claude cloud session creation
Claude Remote Control
Codex processes/sessions
Kimi sessions
local harness processes
cloud VM workers
future remote workers
```

These mechanisms remain behind their Session Fabric adapters, which live
under `cloudeo.execution`.

Provider-specific concepts must not leak into:

- WorkOrder;
- ImplementationBlock;
- the control state machine;
- promotion semantics;
- verification semantics;
- HumanDecision;
- Project Execution Profile semantics.

No provider-specific type may appear in `cloudeo.orchestration` either.

A provider transport may be replaced without changing those contracts.

---

## 7. SessionSupervisor

`SessionSupervisor` is the Cloudeo orchestration component responsible for
runtime session lifecycle.

It may:

- create sessions required by an approved execution step;
- attach the correct role and ExecutionProfile;
- bind the permitted workspace;
- bind an approved runtime environment;
- observe runtime state;
- route messages;
- perform allowed handover;
- terminate sessions;
- record runtime usage and cost;
- replace or retry a failed runtime only where existing policy permits it.

It may not:

- construct or mutate WorkOrder state directly;
- derive a changed WorkOrder copy;
- alter an approved plan;
- alter Project Execution Profile bindings;
- choose an unapproved model/provider;
- weaken auditor-independence requirements;
- grant human approval;
- promote or reject accepted workspace state directly.

All WorkOrder transitions continue through the public
`cloudeo.control` state-machine boundary established by ADR-030.

---

## 8. Session-created child work is a request, not authority

A coordinator session may determine that additional work would benefit from
another session.

That does not give the coordinator authority to create arbitrary Cloudeo
workers.

The governed path is:

```text
coordinator session
        │
        ▼
child-session request
        │
        ▼
SessionSupervisor
        │
        ├── approved role?
        ├── approved envelope?
        ├── approved profile?
        ├── budget available?
        ├── independence preserved?
        ├── runtime environment allowed?
        └── workspace access valid?
                │
                ▼
        SessionFabricAdapter
                │
                ▼
           child session
```

A provider-native `create_session` facility may implement the final operation,
but it does not bypass this Cloudeo decision point.

---

## 9. Coordination Store

Cloudeo adds a durable **Coordination Store** for operational records shared
between orchestration instances and sessions.

It stores records such as:

```text
sessions
session relationships
messages
delivery state
handover records
runtime observations
execution/job references
artifact references
structured feedback/friction reports
usage and cost observations
runtime capability observations
runtime-environment provenance
```

It may also store non-authoritative operational notes or evidence references.

The Coordination Store is not a second control plane.

---

## 10. Relationship to the existing control store

ADR-029 already establishes the Cloudeo control-store abstraction:

```text
SQLite initially
storage interface
record versions
compare-and-swap transitions
future PostgreSQL replacement
```

ADR-031 extends this persistence architecture rather than creating an
independent knowledge-base authority.

Initially, Control Store and Coordination Store may use the same physical
SQLite database.

They remain **logically separate namespaces/interfaces** with different
authority.

Conceptually:

```text
Cloudeo persistence
│
├── control records
│     WorkOrders
│     plans
│     envelopes
│     profile snapshots
│     attention state
│     HumanDecisions
│
└── coordination records
      sessions
      messages
      handovers
      runtime observations
      environment provenance
      usage
      costs
      artifacts
      feedback
```

Physical co-location does not permit coordination code to mutate control
records directly.

Only the public control interfaces may transition control state.

---

## 11. No duplicate source of truth

Coordination records may reference:

```text
project_id
workorder_id
block_id
attempt_id
candidate_id
profile_fingerprint
approval_id
artifact_id
runtime_environment_fingerprint
```

They must not maintain competing mutable copies of the authoritative objects
behind those identifiers.

In particular:

```text
Coordination Store != WorkOrder authority
Coordination Store != Workspace Broker
Coordination Store != Project Memory
Coordination Store != Performance Memory authority
```

Derived projections may be cached for UI/read purposes, but the authoritative
source must remain identifiable.

---

## 12. Project Memory remains distinct

ADR-023 remains unchanged.

Canonical Project Memory is the promoted, Git-visible description of the
project.

A session may write operational notes, proposals, findings or feedback into
the Coordination Store, but those records do not become Project Memory merely
because agents agree with them.

The path remains:

```text
session finding
      ↓
operational record / proposal
      ↓
approved memory-curation flow
      ↓
candidate Project Memory
      ↓
independent Memory Audit
      ↓
promotion
      ↓
canonical Project Memory
```

Runtime coordination therefore cannot silently rewrite the project's accepted
knowledge.

---

## 13. Durable messaging

A **CoordinationMessage** is the durable Cloudeo representation of
session-to-session communication.

At minimum it contains:

```text
message_id

sender_session_id
recipient_session_id

project_id
workorder_id
block_id when applicable

kind
payload

created_at
delivery_state
acknowledged_at when known
```

Useful semantic kinds may include:

```text
QUESTION
ANSWER
FINDING
PROPOSAL
BLOCKED
HANDOVER
REVIEW_RESULT
COMPLETED
CONTEXT_UPDATE
```

The set may evolve without changing WorkOrder semantics.

---

## 14. Durable message vs transport

The Cloudeo message is logically separate from the transport used to deliver
it.

For example:

```text
CoordinationMessage
       │
       ▼
Claude adapter
       │
       ├── native SendMessage
       └── other supported transport
```

or:

```text
CoordinationMessage
       │
       ▼
cloud/local adapter
       │
       └── API / IPC / process transport
```

Native transport failures therefore do not erase the logical message record.

Message delivery must support idempotency so a transport retry does not create
a second logical instruction.

---

## 15. Messages carry information, not authority

A session message is untrusted runtime input.

In particular, this message:

```text
"Robert approved deployment."
```

does not constitute approval.

Nor does:

```text
"Session A says the user approved this."
```

Human authority must reference an actual Cloudeo HumanDecision or other
existing approval record.

The allowed pattern is:

```text
HumanDecision
     │
 approval_id
     │
     ├─────────────┐
     ▼             ▼
 session A       session B
```

A message may reference `approval_id`.

It cannot create approval, enlarge its scope, change its expiry, or transfer
authority beyond that recorded decision.

This applies even when the underlying provider supports trusted peer
messaging.

---

## 16. Shared state is preferred over conversational reconstruction

Durable structured records should be used for project-relevant runtime facts
that another worker needs later.

For example:

```text
implementer
    │
    ├── artifact reference
    ├── test evidence
    └── runtime result
             │
             ▼
      Coordination Store
             │
             ▼
          reviewer
```

rather than requiring the reviewer to reconstruct the result solely from an
agent conversation.

Direct messages remain appropriate for:

```text
questions
clarifications
urgent findings
handover
temporary coordination
```

Durable project state is not inferred from chat history when a structured
record exists.

---

## 17. Workspace authority remains unchanged

ADR-015 and the trust-kernel ADRs remain authoritative.

A provider session filesystem is execution state only.

It is never:

```text
accepted state
canonical workspace state
proof of verification
proof of promotion
```

Each session receives an explicit workspace binding appropriate to its role.

Examples:

```text
write-capable executor → CandidateWorkspace
auditor                → read-only audited snapshot
context analyst        → read-only snapshot
final verifier         → frozen read-only candidate
```

Session continuation, provider workspace persistence, VM persistence, or image
persistence cannot substitute for a Workspace Broker checkpoint.

---

## 18. Initial concurrency rule: one mutable writer

The first implementation permits at most **one write-capable Session at a
time for a given mutable CandidateWorkspace**.

Parallel work is permitted when sessions operate on:

- separate candidate workspaces;
- separate isolated execution jobs;
- read-only snapshots;
- non-workspace tasks.

This avoids treating conversational coordination as protection against
concurrent filesystem mutation.

A future ADR may define safe partitioned multi-writer execution.

ADR-031 does not.

---

## 19. Handover

Sessions may overlap during handover so a successor can obtain clarification
from its predecessor.

Conceptually:

```text
session A
   │
   ├──── HANDOVER ────┐
   │                   ▼
   │                session B
   │                   │
   └── answers ────────┘
```

Handover does not imply concurrent write authority.

For a mutable candidate:

1. the predecessor stops being the active writer;
2. its relevant durable state/evidence is recorded;
3. the successor receives the write binding;
4. the predecessor may remain available for read-only clarification;
5. the predecessor is later terminated.

A handover message cannot transfer policy or approval authority.

---

## 20. Independence requirements survive Session Fabric

ADR-027 remains authoritative.

A fresh session is not automatically independent enough for every risk class.

SessionSupervisor records the observed execution identities needed to evaluate
independence, including where available:

```text
profile fingerprint
model family
inference provider
runtime/harness
session identity
workspace access
runtime-environment fingerprint
```

The control policy decides whether the required independence is satisfied.

Session Fabric must not silently weaken independence because a desired runtime
is unavailable.

If the approved requirements cannot be satisfied, the existing
`INDEPENDENCE_UNAVAILABLE` / `USER_ATTENTION_REQUIRED` path applies.

---

## 21. Provider or model switching

Session Fabric does not introduce autonomous model shopping.

A runtime session is created from the WorkOrder's snapshotted Project
Execution Profile.

Normal execution uses:

```text
bound primary
    ↓ if an approved fallback condition occurs
approved ordered fallback
```

as already defined by ADR-027.

SessionSupervisor records every actual runtime identity and switch.

It may not select an arbitrary provider because it appears cheaper, faster, or
more capable.

---

## 22. Economics are evidence, not policy

Session Fabric exposes observed resource usage and cost as evidence.

Examples:

```text
runtime duration
VM/runtime class
runtime cost
model/token usage
provider cost when available
network/storage observations when relevant
```

Session Fabric does not itself decide whether a more expensive or cheaper
resource should be used.

Economic optimization belongs to a separate COST policy and remains
subordinate to Control.

---

## 23. Runtime failures and ambiguity

A lost, unreachable, timed-out, or ambiguously terminated provider session is
recorded as runtime evidence.

It does not fabricate a WorkOrder result.

Conceptually:

```text
session unavailable
      ↓
runtime observation
      ↓
orchestration classification
      ↓
control input
      ↓
retry / fallback / USER_ATTENTION_REQUIRED
```

Retry or replacement occurs only where the approved envelope and existing
policy allow it.

Unknown runtime state fails closed where continued action would require
positive evidence.

---

## 24. Observability and Mission Control

Mission Control may read the Session Fabric projection to show:

```text
WorkOrder
│
├── coordinator       running
├── implementer       handover
├── code auditor      idle
└── final verifier    not started

messages
runtime/provider/model identity
runtime environment/version/fingerprint
workspace binding
usage
cost
artifacts
failures
handover history
```

Mission Control remains an observer/controller over Cloudeo state.

Missing runtime evidence must be displayed as unavailable or unknown, never
invented.

Provider-native UI is supplementary observability, not Cloudeo authority.

---

## 25. Auditability

The coordination layer must make it possible to answer after a run:

```text
Which sessions existed?
Why was each created?
Which role/profile did it execute?
Which provider/model/runtime actually ran?
Which runtime environment/version ran?
Which cloud/fabric region and runtime class were used?
Which workspace could it access?
Who created or requested it?
What did it send and receive?
What artifacts/evidence did it produce?
When did handover occur?
How much did it consume?
What did the runtime cost?
Why was it stopped or replaced?
Which human approvals did it reference?
```

Provider-native session history alone is insufficient as the durable Cloudeo
audit record.

---

## 26. Security boundary

Session Fabric must preserve least authority.

In particular:

- credentials are supplied through runtime secret mechanisms, not stored in
  reusable runtime images, coordination messages, or Project Memory;
- one session cannot grant another session new privileges;
- one session cannot grant user consent;
- runtime messages are treated as untrusted input;
- provider-native session creation does not bypass Cloudeo authorization;
- provider-native shared filesystems do not become accepted state;
- coordination records cannot directly mutate Workspace Broker refs;
- coordination records cannot directly mutate WorkOrder state;
- write-capable workspace access is explicitly bound and auditable.

A compromised worker therefore remains bounded by Cloudeo's control and
workspace boundaries.

---

## 27. Storage and concurrency semantics

The Coordination Store uses the same storage abstraction principles established
for the control store:

- durable identifiers;
- record versions where mutable records are required;
- compare-and-swap or transactional updates where races matter;
- idempotency identifiers for retried operations;
- append-oriented event/history records where appropriate.

SQLite is sufficient for the initial implementation.

The storage interface must not expose SQLite-specific semantics to
SessionSupervisor or control code, so PostgreSQL or another durable backend may
replace it later.

Multiple sessions writing operational records concurrently must not require Git
merges or shared markdown-file locking.

---

## 28. What agents may write

Sessions may write through narrow Cloudeo APIs appropriate to their role.

They must not receive unrestricted database mutation access.

For example:

```text
record finding
record message
acknowledge message
record runtime observation
record runtime-environment provenance
register artifact
record feedback
request child session
request handover
```

are coordination operations.

By contrast:

```text
set WorkOrder state
mark block approved
change plan
change profile
grant approval
promote candidate
change accepted baseline
```

are not coordination operations and must use their existing authoritative
boundaries.

---

## 29. Feedback / friction channel

The Coordination Store may include structured feedback from sessions about
their operating environment.

Examples:

```text
missing tool
stale instruction
permission friction
repeated context reconstruction
flaky test
runtime incompatibility
provider limitation
unexpected cost
VM undersizing/oversizing
cache miss
repeated setup work
```

Feedback is evidence for later triage.

It does not authorize an agent to rewrite policies, permissions, project
instructions, execution profiles, or architecture automatically.

Any resulting change follows the normal Cloudeo decision path.

---

## 30. Explicit non-goals

ADR-031 does not introduce:

- a provider-specific Claude architecture;
- an Ubicloud-specific core architecture;
- unrestricted self-spawning agents;
- arbitrary agent-created database schemas;
- agent-to-agent delegation of human consent;
- multi-writer mutable candidate workspaces;
- automatic modification of Project Execution Profiles;
- automatic policy learning;
- automatic Project Memory mutation;
- a replacement for Workspace Broker;
- a replacement for the trust kernel;
- a replacement for WorkOrder state;
- CPU/GPU fleet scheduling policy;
- general distributed-compute scheduling;
- an economic optimization policy;
- a requirement for always-on cloud execution.

Those belong to later decisions.

---

## 31. Boundary summary

```text
                         HUMAN
                           │
                    Mission Control
                           │
                           ▼
              ┌────────────────────────┐
              │  Cloudeo orchestration │
              │                        │
              │ SessionSupervisor      │
              │ MessageRouter          │
              │ runtime integration    │
              └───────┬────────┬───────┘
                      │        │
          runtime     │        │ policy/state inputs
                      │        ▼
                      │   ┌───────────────┐
                      │   │cloudeo.control│
                      │   └───────┬───────┘
                      │           │
                      │           ▼
                      │      trust kernel
                      │           │
                      │      promotion gate
                      │           │
                      │     Workspace Broker
                      │
          ┌───────────┼──────────────────────┐
          ▼           ▼                      ▼
       Claude       Codex                   Kimi
       Fabric       Fabric                  Fabric
          │           │                      │
       sessions    sessions               sessions


        ┌──────────────────────────────────┐
        │       Cloudeo persistence        │
        │                                  │
        │  control records                 │
        │  coordination records            │
        └──────────────────────────────────┘
```

The provider fabrics in this diagram are adapters under `cloudeo.execution`.
The orchestration box holds only provider-neutral code.

The central rule is:

> **Cloudeo owns coordination semantics and authoritative workflow state.
> Providers supply execution and communication capabilities.**

And:

> **A session may observe, reason, execute, communicate, and propose.
> It may not acquire authority merely by coordinating with another session.**

---

## 32. Relationship to prior ADRs

ADR-031 extends but does not supersede:

- ADR-015 — Workspace Broker owns canonical accepted state;
- ADR-020/021 — verification and promotion-gate authority;
- ADR-022 — V2 control layer above the trust kernel;
- ADR-023 — canonical Project Memory remains promoted repository state;
- ADR-025 — immutable user-approved execution envelope;
- ADR-026 — WorkOrder and ImplementationBlock state machines;
- ADR-027 — profile hierarchy, stable bindings, and independence;
- ADR-028 — `USER_ATTENTION_REQUIRED`;
- ADR-029 — control-store abstraction and advisory Performance Memory;
- ADR-030 — one-way orchestration → control boundary.

Where Session Fabric acquires runtime evidence, ADR-030 governs how that
evidence may enter control.

Where Session Fabric executes work, the Workspace Broker and trust kernel
continue to govern accepted state.

ADR-035 governs where provider-specific code lives and the import directions
between `cloudeo.control`, `cloudeo.orchestration`, and `cloudeo.execution`.
ADR-031 does not amend it.

A later Cloud Execution Fabric ADR may choose a first concrete cloud
implementation without changing this provider-neutral boundary.

A later COST ADR may optimize among permitted runtime choices without changing
the authority boundary.

---

## 33. Implementation gate

No provider-specific multi-session implementation should begin until ADR-031 is
accepted.

After acceptance, implementation should proceed in bounded slices:

1. **Contracts only** (fabric runtime contracts and observation DTOs in
   `cloudeo.execution`; Session and coordination records in
   `cloudeo.orchestration`)
   - Session identity and normalized status;
   - runtime-environment provenance;
   - CoordinationMessage;
   - fabric capabilities;
   - narrow store protocols.

2. **Durable Coordination Store**
   - SQLite implementation;
   - migrations;
   - concurrency/idempotency tests;
   - no provider integration.

3. **SessionSupervisor with fake fabric**
   - lifecycle;
   - messaging;
   - child-session authorization;
   - single-writer invariant;
   - handover;
   - failure semantics.

4. **First real fabric adapter**
   - implemented under `cloudeo.execution`;
   - provider-native session lifecycle and messaging;
   - no provider-specific import in orchestration;
   - no control semantic changes.

5. **Mission Control projection**
   - sessions;
   - relationships;
   - messages;
   - runtime identity;
   - runtime-environment provenance;
   - usage/cost;
   - unknown/unavailable state.

Each slice must preserve the architectural checks below before the next slice
begins.

---

## 34. Required architecture checks

The implementation must enforce mechanically where practical:

### SF-01 — dependency direction

`cloudeo.control` must not import `cloudeo.orchestration`, Session Fabric, or
provider adapters.

`cloudeo.execution`, including every fabric adapter, must not import
`cloudeo.orchestration` or `cloudeo.control` (ADR-035).

### SF-02 — no WorkOrder mutation

Session/coordination code must not construct a changed WorkOrder, mutate one,
or perform WorkOrder transitions outside the public control machine.

### SF-03 — no promotion bypass

Session/coordination code must never call Workspace Broker `promote()` or
modify Cloudeo refs directly.

### SF-04 — no authority in messages

No CoordinationMessage may itself satisfy a human-approval requirement.

### SF-05 — provider neutrality

No provider-specific session type may appear in WorkOrder, control-machine, or
kernel contracts, or in `cloudeo.orchestration`.

Concrete provider-specific fabric adapters exist only under
`cloudeo.execution`. Orchestration imports no provider-specific
implementation module or type and defines no adapter interface for execution
to implement.

### SF-06 — profile discipline

Every governed Session must reference the approved/snapshotted execution
profile under which it was created.

### SF-07 — workspace discipline

Every workspace-capable Session has explicit access mode and workspace
binding.

### SF-08 — single mutable writer

At most one active write-capable Session may hold the mutable binding for the
same CandidateWorkspace in the initial implementation.

### SF-09 — runtime completion is not verification

No provider/session completion status maps directly to `CODE_APPROVED`,
`BLOCK_DONE`, `VERIFIED`, or `PROMOTED`.

### SF-10 — actual identity is evidence

Requested provider/model/harness identity must not be substituted for observed
actual identity when the runtime reports them separately.

### SF-11 — durable coordination

Cloudeo-significant session creation, handover, and cross-session messages
must have durable coordination records independent of provider-native UI.

### SF-12 — unknown fails closed

Loss of reliable session/runtime observation must never fabricate successful
completion.

### SF-13 — reproducible runtime provenance

Every governed Session must record the runtime-environment identity/version or
an explicit `unknown`/`unavailable` state.

### SF-14 — economics are observational

Session Fabric may record runtime cost and usage but must not independently
change provider/model/runtime policy for economic reasons.

---

## Consequence

Cloudeo can support self-coordinating agent sessions while remaining:

- provider-neutral;
- auditable;
- steerable;
- reproducible;
- cost-observable;
- concurrency-safe;
- compatible with Claude, Codex, Kimi and future runtimes;
- subordinate to explicit human decisions;
- unable to bypass the existing verification and promotion kernel.

This makes independently addressable agent sessions an execution capability of
Cloudeo rather than making Cloudeo dependent on any provider's agent runtime.
