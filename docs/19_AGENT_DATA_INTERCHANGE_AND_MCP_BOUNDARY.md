# ADR-034 --- Agent Data Interchange and MCP Boundary

-   **Status:** Accepted (2026-10-01); not yet implemented
-   **Date:** 2026-09-30
-   **Decision record:** ADR-034 in `02_DECISIONS.md`, which is
    normative. This document is the detailed supporting architecture.
    Where the two differ, the decision record governs.
-   **Decision owners:** Cloudeo architecture
-   **Scope:** Cloudeo control plane, agent interoperability, structured
    data exchange, MCP
-   **Related:** ADR-030 Orchestration Boundary; ADR-031 Session Fabric
    / Coordination Store Boundary; ADR-032 Cloud Execution Fabric and
    Reproducible Runtime Environments; ADR-033 COST: Total-Cost
    Optimization Policy

## 1. Context

Cloudeo is intended to orchestrate heterogeneous coding and agent
runtimes without making any individual model provider, harness, or agent
protocol an architectural dependency. Claude Code, Codex/OpenAI, Astra,
Kimi/Moonshot, and future providers must be able to participate behind
stable Cloudeo boundaries.

At the same time, agents increasingly need access not merely to
documents or conversational context, but to structured operational
state: WorkOrders, Runs, execution events, artifacts, evidence,
verification outcomes, cost records, workspace state, capabilities, and
approved decisions.

Model Context Protocol (MCP) provides a useful interoperability
mechanism for exposing such information and selected operations to
compatible agents. However, exposing Cloudeo through MCP must not create
a second control plane, permit clients to mutate canonical state
directly, or couple Cloudeo's domain model to MCP itself.

The architectural requirement is therefore broader than "add an MCP
server." Cloudeo needs an **Agent Data Interchange boundary** in which
MCP is one adapter.

## 2. Decision

Cloudeo SHALL introduce a provider-neutral **Agent Data Interchange
(ADI) boundary** between external agent clients and Cloudeo's canonical
application/control services.

MCP SHALL be supported as the first standardized agent-facing protocol
adapter over this boundary.

MCP SHALL NOT become:

-   the canonical data model;
-   the system of record;
-   an alternative orchestration engine;
-   an alternative state machine;
-   a direct database-access mechanism;
-   a path around authorization, policy, verification, budget, or
    promotion gates.

All state-changing MCP operations MUST invoke the same Cloudeo
application/control services used by other interfaces.

The governing rule is:

> **MCP may expose state and request actions; it may never independently
> determine or mutate canonical control state.**

Conceptually:

``` text
Claude Code ─┐
Codex/GPT ───┤
Astra ───────┤
Kimi ────────┤
Other agents ┘
             │
        MCP / future protocols
             │
             ▼
┌───────────────────────────────┐
│ Agent Data Interchange (ADI)  │
│ resources • tools • schemas   │
└───────────────┬───────────────┘
                │
                ▼
┌───────────────────────────────┐
│ Cloudeo application services  │
│ orchestration / query layer   │
└───────────────┬───────────────┘
                │
                ▼
┌───────────────────────────────┐
│ cloudeo.control               │
│ policy • state machine • gates│
└───────────────┬───────────────┘
                │
      ┌─────────┼──────────┐
      ▼         ▼          ▼
 control     execution   evidence/
 store        fabric     artifacts
```

## 3. Architectural principles

### 3.1 Canonical models remain protocol-independent

Core domain objects MUST exist independently of MCP schemas.

Examples include:

-   `WorkOrder`
-   `Run`
-   `AgentExecution`
-   `RunEvent`
-   `Artifact`
-   `Evidence`
-   `VerificationResult`
-   `CostRecord`
-   `WorkspaceState`
-   `PromotionDecision`
-   `ProviderCapability`
-   `ExecutionRequest`
-   `ExecutionOutcome`

MCP representations are projections or serialized views of these
canonical models.

A future REST, CLI, event-stream, A2A, or other protocol adapter MUST be
able to expose the same underlying semantics without translating through
MCP.

### 3.2 One control plane

There SHALL be exactly one authoritative transition path for controlled
Cloudeo state.

An MCP client may request:

``` text
create_run(...)
submit_artifact(...)
submit_evidence(...)
request_verification(...)
request_transition(...)
```

but these calls translate into commands handled by Cloudeo's existing
application/control boundary.

An MCP server MUST NOT perform direct SQL mutations of control-state
tables for such operations.

### 3.3 Read broadly, write narrowly

The initial implementation SHOULD favor rich read access and
deliberately constrained command access.

Read operations can expose approved information such as:

``` text
get_work_order(id)
get_run(id)
list_run_events(run_id)
get_artifacts(run_id)
get_evidence(work_order_id)
get_verification(work_order_id)
get_cost_breakdown(run_id)
get_workspace_state(workspace_id)
get_provider_capabilities()
```

State-changing operations SHALL be introduced only where the
authorization, idempotency, audit, policy, and state-transition
semantics are explicit.

### 3.4 Requests are not decisions

A protocol client's request does not imply that the requested transition
will occur.

For example:

``` text
Agent
  │
  └─ request_verification(work_order)
             │
             ▼
       Cloudeo control
             │
       policy + evidence
       + state + budget
             │
        ┌────┴────┐
        ▼         ▼
     accepted   rejected
```

The response SHOULD make the resulting state and reason
machine-readable.

### 3.5 Provenance survives interchange

Evidence and derived data exposed to agents MUST preserve enough
provenance to determine where the information came from and how it was
produced.

Where applicable, structured responses SHOULD carry:

-   stable object ID;
-   object/schema version;
-   creation/observation timestamp;
-   producing run/execution;
-   source or parent references;
-   verification state;
-   content hash or immutable artifact reference;
-   relevant policy/decision reference.

MCP formatting MUST NOT strip provenance that is required for later
verification.

### 3.6 UNKNOWN is preferable to invention

Missing or unavailable data SHALL remain explicitly
unknown/null/unavailable according to the canonical schema.

Protocol adapters MUST NOT synthesize plausible values merely to satisfy
an MCP response schema.

## 4. MCP surface

### 4.1 Resources

MCP resources SHOULD be used for addressable, predominantly
read-oriented state.

Candidate resource families:

``` text
cloudeo://work-orders/{id}
cloudeo://runs/{id}
cloudeo://runs/{id}/events
cloudeo://runs/{id}/artifacts
cloudeo://work-orders/{id}/evidence
cloudeo://work-orders/{id}/verification
cloudeo://workspaces/{id}/state
cloudeo://providers/capabilities
```

Exact URI structure is an implementation detail and may evolve without
changing the architectural decision.

### 4.2 Tools

Tools represent explicit operations rather than hidden side effects of
resource reads.

Initial read/query tools MAY include:

``` text
search_work_orders(...)
get_work_order(...)
get_run(...)
list_run_events(...)
get_artifacts(...)
get_evidence(...)
get_verification(...)
get_cost_breakdown(...)
get_workspace_state(...)
get_provider_capabilities(...)
```

Controlled command tools MAY later include:

``` text
create_run(...)
submit_artifact(...)
submit_evidence(...)
request_verification(...)
request_transition(...)
```

Every mutating tool MUST delegate to an authorized Cloudeo
command/application service.

### 4.3 Prompts

MCP prompts MAY be offered for convenience, but SHALL NOT contain
authoritative business logic or policy.

A prompt may guide an agent to perform a review. The actual acceptance
criteria, state transition rules, budget controls, and verification
requirements remain within Cloudeo.

## 5. Capability negotiation

Agents and harnesses differ substantially in supported features.

Cloudeo SHOULD expose machine-readable capabilities rather than require
clients to infer them.

A capability description may include:

``` json
{
  "provider": "example",
  "runtime": "coding-agent",
  "capabilities": {
    "filesystem": true,
    "shell": true,
    "structured_output": true,
    "mcp": true,
    "resume": true,
    "artifact_submission": true
  },
  "constraints": {
    "max_context": null,
    "interactive_auth": false
  }
}
```

Capability declarations are descriptive inputs to orchestration. They do
not grant authorization.

Provider-specific capabilities MUST remain behind the provider/runtime
abstraction and MUST NOT leak into the canonical WorkOrder contract
unless genuinely required by the work.

## 6. Authentication and authorization

MCP transport authentication and Cloudeo authorization are separate
concerns.

A successfully authenticated MCP client is not automatically authorized
to access every workspace or invoke every tool.

Authorization SHOULD be scoped by:

-   identity;
-   organization/tenant;
-   workspace/project;
-   resource;
-   operation;
-   role;
-   execution context where relevant.

Credentials SHOULD be short-lived or revocable where practical.

Secrets MUST NOT be returned through general-purpose MCP resources or
tools merely because they exist in an execution environment.

The MCP server MUST respect the same least-privilege principles as other
Cloudeo interfaces.

## 7. Multi-tenant isolation

All externally reachable queries and commands MUST enforce
tenant/workspace boundaries before returning data or dispatching
actions.

Identifiers alone SHALL NOT constitute authorization.

Cross-workspace retrieval SHOULD be impossible unless an explicit
privileged capability exists and is independently authorized.

Tests MUST cover attempted cross-tenant/resource access.

## 8. Auditability

Every state-changing request received through MCP MUST produce
sufficient audit information to reconstruct:

-   authenticated caller;
-   requested operation;
-   target object;
-   request time;
-   relevant input or immutable input reference;
-   Cloudeo decision;
-   resulting state;
-   execution/run correlation where applicable.

The audit record belongs to Cloudeo, not to the MCP client.

Read access to particularly sensitive operational information MAY also
be audited.

## 9. Idempotency and retries

Agent protocols and remote runtimes may retry operations.

Mutating MCP operations MUST therefore have explicit retry semantics.

Where duplicate execution would be harmful, commands SHOULD accept or
derive an idempotency key.

For example:

``` text
submit_evidence(
    work_order_id,
    evidence,
    idempotency_key
)
```

A transport retry MUST NOT accidentally create duplicate Runs, duplicate
evidence, repeated promotion, or duplicate paid execution.

This requirement aligns with COST because protocol-level retries must
not silently multiply spend.

## 10. Cost and ADR-033 interaction

MCP is an ingress mechanism, not an exemption from COST policy.

Any MCP request capable of causing paid execution MUST flow through the
same:

-   budget checks;
-   provider-selection policy;
-   reuse/cache logic;
-   cost ceilings;
-   fallback rules;
-   scheduling policy;
-   verification requirements

defined by Cloudeo and ADR-033.

An external agent SHALL NOT be able to force a specific expensive
provider or bypass a cost ceiling unless its authorization explicitly
permits that override.

Cost metadata MAY be exposed to authorized clients so that agents can
make cost-aware requests.

## 11. Execution boundary and ADR-032 interaction

MCP does not execute arbitrary workloads itself.

When an MCP command results in execution:

``` text
MCP request
    ↓
ADI
    ↓
Cloudeo orchestration
    ↓
ExecutionRequest
    ↓
Cloud/local execution fabric
    ↓
ExecutionOutcome
    ↓
Cloudeo control
```

Runtime provisioning, isolation, suspend/resume, spot/preemptible
execution, and reproducibility remain concerns of the execution fabric
defined by ADR-032.

This separation prevents MCP transport concerns from contaminating
runtime architecture.

## 12. Session fabric and ADR-031 interaction

MCP MAY expose selected session/coordination information, but SHALL NOT
become the coordination store.

Ephemeral agent communication, leases, session state, ownership, and
coordination remain governed by the Session Fabric / Coordination Store
boundary.

Where an MCP client needs session information, ADI presents an
authorized projection of that state.

## 13. Versioning

Canonical schemas and MCP projections MUST be versionable independently.

Cloudeo SHOULD prefer additive evolution and explicit capability/schema
discovery.

Breaking protocol changes SHOULD be introduced through a versioned
resource/tool contract rather than silently changing semantics.

A response SHOULD make its relevant schema version discoverable when
ambiguity could affect interpretation.

## 14. Failure semantics

Errors MUST distinguish at least:

-   invalid request;
-   unauthenticated;
-   unauthorized;
-   object not found;
-   invalid state transition;
-   policy rejection;
-   budget rejection;
-   capability unavailable;
-   conflict/idempotency collision;
-   temporary execution/service failure.

Protocol adapters SHOULD preserve structured Cloudeo error codes even if
the external protocol also requires a generic error representation.

Agents must be able to distinguish "retry later" from "this operation is
forbidden or invalid."

## 15. Deployment model

The MCP adapter SHOULD be deployable independently from core Cloudeo
services while using stable application interfaces.

Conceptually:

``` text
             Internet / trusted network
                       │
                MCP transport
                       │
               ┌───────▼───────┐
               │ MCP Adapter   │
               │ auth + schema │
               └───────┬───────┘
                       │
             stable internal API
                       │
               ┌───────▼───────┐
               │ Cloudeo Core  │
               └───────────────┘
```

This permits the MCP surface to be disabled, upgraded, rate-limited, or
isolated without replacing the core orchestration system.

The first implementation MAY run in-process if operational simplicity
warrants it, provided the logical boundary remains enforced.

## 16. Public versus internal surfaces

Cloudeo SHOULD distinguish at least:

**Internal/privileged ADI** --- operational data and commands used by
trusted coding agents, harnesses, and Cloudeo components.

**External/restricted ADI** --- deliberately exposed capabilities for
third-party agents or integrations.

The public surface MUST NOT automatically mirror every internal resource
or tool.

Exposure is an explicit product/security decision.

## 17. HumanoidOnline applicability

The ADI pattern is intentionally reusable outside Cloudeo.

HumanoidOnline is a strong candidate for a separate, read-oriented MCP
service over its canonical robot catalogue.

Potential tools include:

``` text
search_robots(...)
get_robot(...)
find_available_robots(...)
get_pricing(...)
get_availability(...)
get_robot_evidence(...)
get_deployments(...)
```

The HumanoidOnline MCP service SHOULD expose the same canonical,
provenance-aware catalogue used by its web/API surfaces rather than
maintaining an MCP-specific database.

Its initial public MCP SHOULD be read-only.

The HumanoidOnline discovery/update pipeline remains the controlled
ingestion path:

``` text
external sources
      ↓
discovery / observations
      ↓
entity matching
      ↓
evidence + validation
      ↓
promotion
      ↓
canonical catalogue
      │
 ┌────┼─────────────┐
 ▼    ▼             ▼
web  API        public MCP
```

Consequently, an external MCP client cannot directly "update" a robot,
price, availability status, specification, or evidence record in the
published catalogue.

This keeps automated catalogue maintenance and public agent consumption
cleanly separated.

## 18. What this ADR does not decide

This ADR deliberately does not freeze:

-   a specific MCP SDK or implementation language;
-   HTTP versus another supported MCP transport;
-   exact resource URI naming;
-   every tool name;
-   the final public pricing/business model for MCP access;
-   whether an API gateway fronts the MCP adapter;
-   the detailed HumanoidOnline MCP schema;
-   the detailed catalogue-discovery promotion policy.

Those decisions can evolve without changing the boundary established
here.

## 19. Initial implementation sequence

The preferred sequence is:

1.  Define canonical ADI DTOs/projections from existing Cloudeo domain
    models.
2.  Implement read-only MCP access to a narrow set of
    WorkOrder/Run/artifact/evidence data.
3.  Add authentication, workspace authorization, audit tests, and
    schema/version metadata.
4.  Add capability discovery.
5.  Validate interoperability with at least two independent
    agent/provider environments.
6.  Introduce narrowly scoped command tools only after idempotency and
    policy enforcement are demonstrated.
7.  Keep promotion/critical state transitions behind `cloudeo.control`.
8.  Reuse the architectural pattern for a separate HumanoidOnline
    read-only MCP when its continuous catalogue update path is
    sufficiently mature.

## 20. Acceptance criteria

ADR-034 is successfully implemented when all of the following are true:

-   At least two materially independent agent environments can consume
    the same Cloudeo structured data through MCP.
-   No MCP handler directly mutates canonical control state.
-   State-changing MCP requests traverse the normal Cloudeo
    command/control path.
-   Workspace/tenant authorization is enforced and tested.
-   Provenance and stable identifiers survive serialization.
-   Retried mutating requests cannot unintentionally duplicate
    controlled operations.
-   Paid execution triggered through MCP remains subject to COST
    controls.
-   MCP can be disabled without disabling Cloudeo's core orchestration.
-   Core domain models have no required dependency on MCP-specific
    types.
-   An alternative future protocol can be added as another ADI adapter
    without redesigning the control plane.

## 21. Consequences

### Positive

Cloudeo gains a standard agent-facing interface without becoming
dependent on one AI provider or harness.

Structured operational state becomes reusable by Claude Code,
Codex/OpenAI, Astra, Kimi/Moonshot, and future compatible agents.

The same canonical data and control rules remain authoritative across
UI, CLI, API, MCP, and future adapters.

MCP clients can participate in evidence and verification workflows
without being allowed to bypass them.

The boundary creates a reusable architectural pattern for HumanoidOnline
and other structured agent-facing products.

### Costs and risks

Another externally reachable interface increases authentication,
authorization, versioning, rate-limiting, and security responsibilities.

Poorly designed tools could accidentally expose excessive privilege.

Schema proliferation is possible if MCP projections diverge from
canonical models.

Agent retries can cause duplicate work or cost unless idempotency is
enforced.

Supporting MCP clients with different interpretations or feature subsets
requires conformance testing.

These risks are accepted subject to the constraints in this ADR.

## 22. Rejected alternatives

### Make MCP the Cloudeo control plane

Rejected. It would bind core orchestration semantics to an external
interchange protocol and make non-MCP interfaces second-class.

### Give agents direct database access

Rejected. It bypasses domain invariants, authorization, audit,
state-machine enforcement, and future schema abstraction.

### Build provider-specific integration paths

Rejected. Separate Claude/OpenAI/Astra/Kimi data interfaces would
undermine provider neutrality and multiply maintenance.

### Expose only unstructured documents

Rejected as the primary interface. Documents remain useful, but agents
need typed operational objects, provenance, state, and explicit actions.

### Permit MCP clients to promote state directly

Rejected. Promotion and controlled transitions are Cloudeo decisions and
remain behind the control boundary.

## 23. Decision summary

Cloudeo will support agent interoperability through a
protocol-independent **Agent Data Interchange boundary**, with MCP as
its first standardized adapter.

The durable architecture is:

``` text
Agents
   ↓
MCP / future agent protocols
   ↓
Agent Data Interchange
   ↓
Cloudeo application services
   ↓
Cloudeo control + policy
   ↓
canonical state / execution / evidence
```

The boundary is intentionally asymmetric:

> **Agents may observe structured Cloudeo state and request permitted
> actions. Cloudeo alone authorizes and performs canonical state
> transitions.**

This preserves provider neutrality, provenance, security, cost
governance, and a single authoritative control plane while making
Cloudeo's structured agent data accessible to an expanding agent
ecosystem.
