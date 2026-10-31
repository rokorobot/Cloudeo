# ADR-032 — Cloud Execution Fabric and Reproducible Runtime Environments

**Status:** Accepted (2026-10-01); infrastructure architecture only, not yet implemented.

**Decision record:** ADR-032 in `02_DECISIONS.md`, which is normative. This
document is the detailed supporting architecture (rationale, diagrams, and
examples). Where the two differ, the decision record governs.

**Amended:** 2026-10-01, before acceptance. The fabric contracts and the
Ubicloud-specific implementation live in `cloudeo.execution` (see §5, CF-01,
and §38). Provider credentials are confined to the provider-specific
execution adapter (see §15, §35, and §36).

## Decision

Cloudeo adds a provider-neutral **Cloud Execution Fabric** beneath the
Session Fabric defined by ADR-031.

The Cloud Execution Fabric is responsible for provisioning, observing, and
destroying isolated compute environments in which governed Cloudeo Sessions
may run.

The first managed implementation will target **Ubicloud**, with the initial
European deployment using Ubicloud's `eu-central-h1` location.

Ubicloud is the preferred initial managed compute substrate, **not an
architectural dependency of Cloudeo**.

The architectural relationship is:

```text
                       Cloudeo
                          │
                 SessionSupervisor
                          │
                    Session Fabric
                          │
              Cloud Execution Fabric
                          │
             ┌────────────┴────────────┐
             │                         │
      UbicloudFabric             Local/Future Fabrics
             │
      isolated VM runtime
```

Cloud-specific types and APIs must not leak into `cloudeo.control`,
`cloudeo.orchestration`, WorkOrder semantics, verification semantics, or the
trust kernel.

---

## 1. Why this boundary exists

Cloudeo needs execution environments that are:

- isolated;
- reproducible;
- disposable;
- programmatically provisioned;
- auditable;
- cost-observable;
- fast enough to create on demand;
- suitable for Claude, Codex, Kimi and future agent runtimes;
- independent of one AI provider's proprietary cloud session environment.

A long-running autonomous coding system must be able to answer:

```text
Where did this Session run?
Which software environment did it use?
Which image/version created that environment?
Which compute class was allocated?
Which network was attached?
What did it cost?
Was the environment destroyed afterwards?
```

A generic cloud-runtime boundary is therefore required below ADR-031's
provider-neutral Session abstraction.

---

## 2. Relationship to ADR-031

ADR-031 defines:

```text
Session
SessionFabricAdapter
SessionSupervisor
CoordinationMessage
CoordinationStore
```

ADR-032 defines the infrastructure substrate on which some of those Sessions
may execute.

The layers are distinct.

A Session can exist on:

```text
Claude-managed cloud environment
local runtime
Ubicloud VM
future cloud VM
future container/sandbox fabric
```

ADR-031 remains valid regardless of which infrastructure substrate is used.

ADR-032 therefore specializes only the **cloud-hosted isolated-worker path**.

---

## 3. Core concepts

ADR-032 introduces:

```text
CloudExecutionFabric
CloudRuntimeSpec
RuntimeEnvironmentSpec
RuntimeInstance
RuntimeEnvironmentArtifact
RuntimeObservation
```

Conceptually:

```text
Session request
     │
     ▼
SessionSupervisor
     │
     ▼
CloudExecutionFabric
     │
     ├── choose approved runtime specification
     ├── provision isolated instance
     ├── attach network/security policy
     ├── inject ephemeral bootstrap material
     ├── observe lifecycle and usage
     └── destroy instance
```

The Cloud Execution Fabric does not own WorkOrder policy.

---

## 4. First implementation: Ubicloud

The first managed implementation is:

```text
UbicloudFabric
```

Initial location:

```text
eu-central-h1
```

Ubicloud currently exposes VM lifecycle, firewall, private-subnet and other
infrastructure APIs suitable for programmatic orchestration.

The first implementation should use Ubicloud's managed service rather than
self-hosting Ubicloud.

Cloudeo therefore chooses:

```text
location
VM/runtime class
runtime environment image/version
network/security configuration
lifecycle
```

Ubicloud remains responsible for physical host placement and the underlying
managed infrastructure.

Cloudeo must not depend on knowing which particular bare-metal server hosts a
runtime instance.

---

## 5. Ubicloud is an implementation, not the architecture

The interface must permit future implementations such as:

```text
UbicloudFabric
LocalVMFabric
AWSFabric
AzureFabric
GCPFabric
HetznerDirectFabric
on-prem Fabric
future sandbox provider
```

No WorkOrder or control-layer object may require an Ubicloud-specific VM,
project, firewall, subnet, image, or location type.

Package boundary (ADR-035 governs):

- The provider-neutral Cloud Execution Fabric contracts and observation types
  live in `cloudeo.execution`.
- The Ubicloud-specific implementation (`UbicloudFabric`, with every Ubicloud
  API type, identifier format, and constraint check) also lives in
  `cloudeo.execution`, as does any later cloud implementation.
- `cloudeo.orchestration` consumes only the neutral contracts. No
  Ubicloud-specific type appears in it, and it defines no fabric interface
  for execution to implement.
- `cloudeo.execution` never imports `cloudeo.orchestration` or
  `cloudeo.control`.
- Provisioning operations, like Session Fabric lifecycle operations
  (ADR-031), are not execution request kinds and are not routed through
  `ExecutionDispatcher`.

Provider-native identifiers belong to orchestration/runtime evidence.

For example:

```text
fabric_provider: "ubicloud"
fabric_region: "eu-central-h1"
runtime_instance_id: "<provider id>"
runtime_class: "standard-2"
```

are runtime provenance, not control semantics.

---

## 6. Reproducible Runtime Environments

Cloud worker VMs must start from a reproducible, versioned runtime environment.

For the initial Ubicloud implementation, the preferred mechanism is an
**Ubicloud Machine Image (UMI)**.

Conceptually:

```text
clean base OS
    │
    ├── Python / uv
    ├── Node / pnpm
    ├── Git
    ├── Cloudeo runtime
    ├── UHP client
    ├── common build/test tooling
    ├── telemetry/bootstrap support
    └── approved agent-runtime dependencies
           │
           ▼
    cloudeo-worker@version
```

The reusable image must not contain:

```text
provider API secrets
GitHub credentials
user credentials
long-lived tokens
project-specific secrets
accepted project state
mutable WorkOrder state
```

Those are injected only at runtime through approved secret/bootstrap
mechanisms.

---

## 7. Immutable version pinning

A governed WorkOrder must execute against an immutable runtime-environment
version or fingerprint.

A moving alias such as:

```text
latest
```

may be used for development convenience but must not be the authoritative
runtime identity for an execution that needs to be reproducible.

The desired record is conceptually:

```text
runtime_environment:
  kind: machine-image
  name: cloudeo-worker
  version: v17
  fingerprint: <immutable identity>
```

If the provider exposes both a friendly version label and an immutable
provider-native identifier, Cloudeo should record both.

---

## 8. Current UMI constraints are adapter-specific

At the time of this ADR, Ubicloud documents that creating a Machine Image
version requires the source VM to be stopped and to have a single disk no
larger than 40 GiB. VMs created from the captured image require a boot disk at
least as large as the captured source disk.

These are **current Ubicloud implementation constraints**, not Cloudeo
architectural invariants.

The Ubicloud adapter must enforce or surface them.

The generic Cloud Execution Fabric must not encode a universal 40 GiB limit.

---

## 9. Worker image strategy

The initial design should use at least one small production worker image:

```text
cloudeo-worker
```

A later evaluation-specific image may exist separately:

```text
cloudeo-eval
```

where evaluation tooling would otherwise bloat the production worker.

The goal is:

```text
minimal common runtime
+ deterministic toolchain
+ fast worker startup
+ low image churn
```

Project repositories, candidate workspaces and secrets should normally be
materialized after instance creation rather than baked into the reusable image.

---

## 10. Disposable worker lifecycle

Write-capable agent workers should be disposable by default.

Lifecycle:

```text
approved execution step
        │
        ▼
provision isolated VM
        │
        ▼
attach private network/security policy
        │
        ▼
inject temporary bootstrap/secrets
        │
        ▼
materialize governed workspace
        │
        ▼
run Session
        │
        ▼
collect durable evidence/artifacts
        │
        ▼
revoke temporary credentials
        │
        ▼
destroy VM
```

A runtime VM is execution state only.

It is never accepted workspace state.

Destroying a VM must not destroy the authoritative evidence needed by Cloudeo.

---

## 11. Small persistent control plane, ephemeral heavy compute

The preferred early infrastructure shape is:

```text
             persistent
        ┌──────────────────┐
        │ Cloudeo API      │
        │ orchestration    │
        │ SessionSupervisor│
        │ Mission Control  │
        └────────┬─────────┘
                 │
        durable control /
        coordination store
                 │
     ┌───────────┴───────────┐
     │        ephemeral       │
     ▼                        ▼
 worker VM                worker VM
 create/run/destroy       create/run/destroy
```

Expensive compute should be allocated only while useful.

This ADR does not require every Cloudeo component to run in an ephemeral VM.

---

## 12. Initial VM sizing policy

ADR-032 defines the ability to select a runtime class but does not define the
economic optimizer.

Initial implementation should support a small set of explicitly approved
classes such as:

```text
small/shared or burstable
general-purpose dedicated
larger dedicated
future GPU class
```

For Ubicloud, concrete classes may include provider offerings such as
`burstable-*` and `standard-*`.

The exact class is runtime configuration.

No Cloudeo core type should assume a particular Ubicloud class name.

Right-sizing policy belongs to the later COST decision.

---

## 13. Runtime class is not equivalent to task quality

A larger VM is not automatically preferred.

The runtime layer must collect enough observations to compare:

```text
runtime class
wall-clock duration
CPU/memory pressure where available
runtime cost
execution success/failure
verification result reference
```

This permits later computation of:

```text
cost per successfully verified WorkOrder
```

rather than optimizing only for VM price per minute.

The Cloud Execution Fabric records evidence.

It does not choose an economically optimal class by itself.

---

## 14. Network boundary

Cloud worker instances should communicate over private networking where
practical.

The first Ubicloud implementation should use provider-supported private
subnets and firewalls to restrict worker connectivity.

Default posture:

```text
deny unnecessary inbound access
allow only required service paths
minimize public exposure
prefer private control-plane communication
```

Public IPv4 must not be treated as mandatory for every worker.

Public-facing services and worker execution networks should be separable.

---

## 15. Secret handling

Secrets must never be baked into reusable machine images.

Runtime credentials must be:

- injected only when required;
- scoped to the Session or execution step where possible;
- short-lived where provider support permits;
- revocable;
- absent from durable images;
- absent from CoordinationMessages;
- absent from Project Memory.

A destroyed runtime must not remain a source of reusable credentials.

Provider credentials are available only to the narrowest provider-specific
execution boundary that requires them. Ubicloud credentials are consumed only
by the Ubicloud adapter under `cloudeo.execution`.

Credentials must never appear in `cloudeo.orchestration`, `cloudeo.control`,
WorkOrder state, Session records, Coordination Store records, logs, or
model-visible context.

Orchestration receives only credential-free normalized observations and
provider/runtime identity evidence.

This states the authority boundary only. It does not decide credential
storage or secret management.

---

## 16. Workspace materialization

A cloud VM's root filesystem is not a Workspace Broker.

Before write-capable execution:

```text
Workspace Broker
      │
      ▼
CandidateWorkspace / accepted baseline identity
      │
      ▼
cloud materialization mechanism
      │
      ▼
isolated runtime workspace
```

The transport/materialization mechanism may evolve.

The invariant is that Cloudeo must know which accepted baseline and candidate
identity the runtime corresponds to.

Runtime-local files do not become accepted state merely because an agent
finished successfully.

---

## 17. Artifact and evidence extraction before destruction

Before an ephemeral VM is destroyed, Cloudeo must persist all governed
outputs required by the surrounding workflow.

Examples:

```text
execution result
test evidence
audit evidence
structured runtime observations
artifact references
logs required by policy
usage/cost observations
runtime provenance
workspace/checkpoint identity
```

Failure to retrieve required evidence must not be silently normalized as
success.

If positive evidence is required but unavailable, the workflow fails closed.

---

## 18. Runtime provenance

Every governed cloud Session must record, where available:

```text
fabric_provider
fabric_region
runtime_class
runtime_instance_id

runtime_environment
runtime_environment_version
runtime_environment_fingerprint

requested architecture
actual architecture

creation time
termination time
observed runtime duration

usage
runtime cost
```

This extends ADR-031's Session provenance.

Unknown fields remain explicit `unknown`/`unavailable`; requested values are
not substituted for observed actual values.

---

## 19. Architecture portability

Runtime-environment identity is generic.

Examples:

```text
ubicloud-machine-image
container-image
local-environment-lock
provider-cloud-environment
future VM image format
```

Cloudeo records the environment through generic provenance fields and
provider-native evidence.

The control layer must not need to understand how the image was built.

---

## 20. Managed PostgreSQL is optional, not required by this ADR

Ubicloud offers managed PostgreSQL and exposes PostgreSQL lifecycle APIs.

That service may become a useful deployment target for Cloudeo's persistent
stores.

However, ADR-029 currently defines SQLite as the initial control-store
implementation behind a storage interface.

ADR-032 does not silently replace that decision.

Migration to managed PostgreSQL should occur only when concurrency,
availability, deployment topology, or operational requirements justify it.

The storage interface must allow such a migration without changing WorkOrder
semantics.

---

## 21. No Kubernetes initially

Ubicloud offers managed Kubernetes, but the first Cloudeo cloud deployment
should not require Kubernetes.

Initial topology:

```text
small persistent control plane
+
durable store
+
disposable worker VMs
```

is preferred because it:

- reduces operational complexity;
- reduces fixed infrastructure cost;
- keeps the Session Fabric easy to inspect;
- preserves a straightforward VM-to-Session mapping.

Kubernetes may be reconsidered when concurrency, scheduling scale, service
density, or operational evidence demonstrates a need.

---

## 22. CI is adjacent but separate

Ubicloud also offers ephemeral GitHub Actions runners.

They may be evaluated as part of Cloudeo's broader infrastructure economics,
but GitHub Actions runner selection is not the Cloud Execution Fabric
authority.

CI optimization remains a separate concern.

In particular, cheaper runners must not substitute for:

```text
eliminating duplicate CI triggers
cancelling stale PR runs
batching agent pushes
failing fast
building once and reusing artifacts
```

A later COST policy may compare CI provider economics using observed evidence.

---

## 23. Evaluation environments are separate from production execution

Model evaluation tooling may use the same Cloud Execution Fabric.

For example:

```text
Ubicloud VM
   │
   └── cloudeo-eval@pinned-version
           │
           └── evaluation backend
```

Evaluation traffic, model routing, and comparison policy are not defined by
ADR-032.

The Cloud Execution Fabric only guarantees that the evaluation runs in a
known, reproducible environment.

This permits model evaluation systems such as Ori/OpenRouter to be added later
without making OpenRouter a production infrastructure dependency.

---

## 24. Cost observability

The Fabric must expose or derive enough information to attribute infrastructure
cost to a governed execution where practical.

At minimum:

```text
runtime class
start time
stop time
billable duration if available
provider-reported cost if available
provider pricing identity/version when known
```

Infrastructure cost is evidence.

The Fabric must not autonomously alter WorkOrder policy to reduce cost.

The later COST layer may use this evidence.

---

## 25. No always-on worker pool by default

The initial system should not keep a large standing pool of agent workers only
to reduce startup latency.

Preferred default:

```text
demand
  ↓
create
  ↓
execute
  ↓
destroy
```

A warm pool may later be introduced if measured startup latency or workload
volume justifies its fixed cost.

Such a change requires explicit policy and lifecycle controls.

---

## 26. Session reuse and VM reuse are different

ADR-031 may permit reuse of an eligible Session where policy allows.

That does not imply indefinite reuse of the underlying cloud VM.

Possible future relationships include:

```text
one Session : one VM
several sequential Sessions : one short-lived VM
provider-native Session : no Cloudeo-managed VM
```

The initial write-capable worker implementation should prefer a simple,
auditable mapping.

Optimization of reuse belongs to COST and must preserve isolation and
workspace authority.

---

## 27. Failure semantics

The cloud adapter must distinguish at least:

```text
provisioning rejected
provisioning failed
instance running
instance unreachable
instance stopped
instance terminated
instance lost / final state unknown
environment bootstrap failed
workspace materialization failed
evidence extraction failed
destruction confirmed
destruction unconfirmed
```

These are runtime observations.

They do not directly map to WorkOrder success.

Unknown final infrastructure state must remain explicit.

---

## 28. Cleanup is part of correctness

An ephemeral-worker design saves cost only if failed runs also clean up.

The orchestration layer must attempt bounded cleanup after:

```text
normal completion
execution failure
bootstrap failure
timeout
cancellation
orchestration restart/recovery
```

Cleanup must be idempotent.

A periodic reconciliation mechanism may later identify orphaned instances.

An orphaned VM must be visible as operational debt and cost leakage.

---

## 29. Recovery and reconciliation

The Coordination Store should retain enough information to reconcile provider
state after an orchestration restart.

Example:

```text
Session / RuntimeInstance record
        │
        ├── provider instance id
        ├── expected lifecycle state
        └── last observation
                 │
                 ▼
          provider inspection
                 │
        ┌────────┴────────┐
        ▼                 ▼
   state matches      state diverged
                         │
                         ▼
                  reconcile / escalate
```

Provider state must not be inferred solely from stale local records.

---

## 30. Physical-host opacity

For the managed Ubicloud implementation, the particular physical server
selected by Ubicloud is outside the Cloudeo contract.

Cloudeo cares about:

```text
declared location
runtime class
architecture
environment identity
provider runtime instance identity
observed execution properties
```

Cloudeo does not schedule individual underlying bare-metal hosts.

If a future self-hosted fabric exposes physical-host selection as a governed
capability, that belongs to that adapter and later scheduling policy.

---

## 31. Architecture choice: x86 first, ARM only after measurement

The initial worker environment should prefer the architecture with the lowest
compatibility risk for the Cloudeo toolchain.

ARM should not be selected merely because a provider lists a lower unit price.

Before introducing an ARM worker image, Cloudeo should validate:

```text
agent CLI compatibility
Python/native dependency compatibility
Node/native addon compatibility
container/tooling compatibility
build/test behavior
wall-clock performance
cost per verified task
```

Architecture selection belongs to empirical runtime economics, not assumption.

---

## 32. Runtime environment build discipline

Machine images must be produced through a reproducible documented build
process rather than manually configured snowflake VMs.

Desired flow:

```text
environment definition
       │
       ▼
build candidate image
       │
       ▼
bootstrap validation
       │
       ▼
toolchain validation
       │
       ▼
security/sanitization check
       │
       ▼
capture immutable image version
       │
       ▼
record fingerprint/version
       │
       ▼
eligible for governed execution
```

A failed image build never moves a production alias automatically.

Rollback should be possible by selecting an earlier known-good immutable
version.

---

## 33. Image update policy

Runtime images should be updated intentionally for:

```text
security patches
OS updates
Cloudeo runtime changes
toolchain changes
agent runtime changes
dependency changes
observability/bootstrap changes
```

Changing the image version changes the execution environment and therefore the
runtime provenance.

For controlled comparisons, the environment version must remain pinned.

A new image must not silently alter an already-approved WorkOrder's runtime
environment if that environment is part of its approved execution envelope.

---

## 34. Runtime environment classes

The architecture should permit multiple approved images rather than one
universal image.

Examples:

```text
cloudeo-worker
cloudeo-eval
future browser-worker
future GPU-worker
future security-audit-worker
```

Each image should remain as small and purpose-specific as practical.

Cloudeo should avoid installing every possible tool into every worker.

This reduces:

```text
image size
startup cost
attack surface
maintenance burden
environment drift
```

---

## 35. Security posture

The first cloud implementation must preserve least authority.

Required principles:

- ephemeral workers by default;
- no long-lived credentials in images;
- narrow network access;
- provider API credentials available only to the provider-specific execution
  adapter that requires them;
- workspace access appropriate to role;
- runtime identity recorded durably;
- immutable image/version identity recorded;
- cleanup/revocation after execution;
- no provider runtime claim becomes verification authority.

A compromised worker must not be able to mutate Cloudeo control state merely
because it can reach the orchestration network.

---

## 36. Ubicloud-specific first implementation profile

The initial deployment profile should be approximately:

```text
provider:
  Ubicloud managed service

location:
  eu-central-h1

control plane:
  small persistent VM(s), sized from measured load

workers:
  disposable VMs
  explicit approved runtime classes
  no large permanent worker pool

environment:
  versioned Ubicloud Machine Image
  initial image: cloudeo-worker
  immutable version pinned for governed execution

network:
  private subnet where practical
  restrictive firewall
  public exposure only when required

secrets:
  runtime injection only
  never baked into UMI

persistence:
  existing Cloudeo store abstraction
  managed PostgreSQL optional later

provider API:
  called only by the UbicloudFabric adapter under cloudeo.execution,
  which alone consumes the Ubicloud credentials

kubernetes:
  not required initially
```

Exact VM sizes and prices are operational configuration, not architectural
constants.

---

## 37. Required architecture checks

The implementation should mechanically enforce where practical:

### CF-01 — provider neutrality

No Ubicloud-specific infrastructure type may appear in `cloudeo.control`,
`cloudeo.orchestration`, WorkOrder state-machine contracts, or trust-kernel
contracts.

The Ubicloud implementation exists only under `cloudeo.execution`.

### CF-02 — immutable environment identity

Every governed cloud Session must record an immutable environment version or
fingerprint, or explicitly record that it was unavailable.

### CF-03 — no secrets in image definitions

Reusable runtime images must not contain project/provider/user credentials.

### CF-04 — runtime is not canonical state

A cloud VM filesystem must never be treated as accepted workspace state.

### CF-05 — evidence before destruction

Required governed evidence must be persisted before runtime destruction is
considered complete.

### CF-06 — idempotent lifecycle

Create/inspect/terminate/reconcile operations must have idempotency or
equivalent duplicate-safe semantics where retries can occur.

### CF-07 — unknown remains unknown

An unreachable or ambiguously terminated VM must not be normalized to
successful completion.

### CF-08 — cost observability

The Fabric must record sufficient runtime identity and duration/cost evidence
for later attribution where the provider exposes it.

### CF-09 — no economic policy in Fabric

The Fabric may report runtime economics but may not independently select a
cheaper model/provider/runtime class outside approved orchestration policy.

### CF-10 — no moving image alias as authoritative provenance

A mutable alias such as `latest` must not be the sole environment identity
recorded for governed execution.

### CF-11 — physical-host opacity

Managed-provider physical host placement must not become a Cloudeo control
dependency.

### CF-12 — cleanup visibility

Instances that should have been destroyed but remain observable must be
detectable as orphaned runtime resources.

---

## 38. Implementation sequence

After ADR-032 is accepted, implementation should proceed in bounded slices:

1. **Generic contracts** (in `cloudeo.execution`)
   - `CloudExecutionFabric`;
   - runtime/environment specification;
   - runtime instance identity;
   - normalized lifecycle;
   - provenance/cost observations.

2. **Fake fabric**
   - deterministic lifecycle tests;
   - idempotency;
   - failure semantics;
   - orphan reconciliation;
   - no real cloud calls.

3. **Ubicloud adapter** (under `cloudeo.execution`)
   - VM create/inspect/terminate;
   - region/runtime class mapping;
   - provider instance identity;
   - no Session integration yet.

4. **Runtime image path**
   - reproducible `cloudeo-worker` build;
   - sanitization;
   - version capture;
   - immutable identity recording;
   - bootstrap test.

5. **Networking/security**
   - private subnet/firewall;
   - runtime secret injection;
   - least-access bootstrap.

6. **Session Fabric integration**
   - provision VM for approved Session;
   - materialize workspace;
   - execute;
   - extract evidence;
   - destroy;
   - persist provenance.

7. **Operational reconciliation**
   - detect stale/orphaned VMs;
   - recover after orchestration restart;
   - usage/cost reporting.

No later slice should weaken ADR-030 or ADR-031 boundaries.

---

## 39. Explicit non-goals

ADR-032 does not define:

- model selection;
- autonomous provider switching;
- COST optimization policy;
- Ori/OpenRouter evaluation policy;
- Project Execution Profile changes;
- multi-writer workspaces;
- general fleet scheduling;
- GPU scheduling policy;
- Kubernetes orchestration;
- a mandatory PostgreSQL migration;
- CI trigger policy;
- human-approval semantics;
- promotion semantics;
- a replacement for Session Fabric;
- a replacement for Workspace Broker.

These belong to existing or later ADRs.

---

## 40. Relationship to other ADRs

ADR-032 extends but does not supersede:

- ADR-015 — Workspace Broker owns canonical accepted state;
- ADR-022 — V2 control layer remains above the trust kernel;
- ADR-023 — Project Memory remains promoted repository state;
- ADR-027 — approved role/profile bindings and independence;
- ADR-029 — storage abstraction and SQLite-first control store;
- ADR-030 — orchestration → control dependency boundary;
- ADR-031 — Session Fabric and Coordination Store boundary.

ADR-035 governs package placement and import directions.

ADR-031 defines **what a governed Session is**.

ADR-032 defines **how a cloud-hosted Session may receive an isolated,
reproducible runtime environment**.

A later ADR should define **COST**, which decides how to economically choose
among already-permitted execution options.

---

## 41. Consequence

Cloudeo gains a concrete path from abstract agent Sessions to reproducible,
isolated cloud execution without binding the product architecture to one cloud
provider.

The initial architecture becomes:

```text
                         HUMAN
                           │
                    Mission Control
                           │
                           ▼
                 Cloudeo Control
                           │
                           ▼
                 Cloudeo Orchestration
                           │
                    SessionSupervisor
                           │
                    Session Fabric
                           │
                Cloud Execution Fabric
                           │
                    UbicloudFabric
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
       disposable worker          disposable worker
           VM + UMI                   VM + UMI
              │                         │
            agent                     agent
```

The central rules are:

> **Cloud providers supply isolated compute. Cloudeo owns execution semantics.**

> **Runtime environments are versioned and reproducible; workers are
> disposable; accepted state remains outside the runtime VM.**

> **Ubicloud is the first managed Cloud Execution Fabric implementation, not a
> permanent architectural dependency.**

---

## Non-normative source basis

This ADR's initial Ubicloud feasibility assumptions were checked against
Ubicloud's official documentation and product material on 2026-09-28.

Relevant official sources:

- Ubicloud Machine Images:
  https://www.ubicloud.com/blog/announcing-ubicloud-machine-images
- Ubicloud Compute:
  https://www.ubicloud.com/use-cases/ubicloud-compute
- Ubicloud API documentation:
  https://www.ubicloud.com/docs/api-reference
- Ubicloud Managed PostgreSQL:
  https://www.ubicloud.com/use-cases/postgresql

These provider capabilities and constraints may evolve. They are adapter
evidence, not permanent Cloudeo invariants.
