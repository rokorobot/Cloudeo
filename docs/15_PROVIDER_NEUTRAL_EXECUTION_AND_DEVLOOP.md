# Cloudeo v2 — Provider-Neutral Execution and DevLoop Architecture

**Status:** Supporting draft for ADR-035, which is Accepted (2026-10-01) and governs where this draft differs; documentation only, not yet implemented  
**Date:** 2026-09-27  
**Proposed repository path:** `docs/15_PROVIDER_NEUTRAL_EXECUTION_AND_DEVLOOP.md`  
**Relationship:** Extends `13_V2_CONTROL_ARCHITECTURE.md`, `14_V2C_TRACEABILITY.md`, and accepted ADR-030 (orchestration boundary). Drafted against the post-ADR-030 implementation line whose observed HEAD on 2026-09-27 is `83c8263` (`feat/v2-orchestration-kernel-outcome-baseline`).  
**Goal:** Make Cloudeo independent of any AI provider while supporting a bounded local software-development loop across Codex/OpenAI, Claude/Anthropic, Kimi/Moonshot, UHP/HarnessRouter, and future runtimes.

---

## 1. Decision summary

Cloudeo SHALL depend on **roles, capabilities, execution contracts, and verified evidence**, never directly on an AI provider.

OpenAI, Anthropic, Moonshot, Google, DeepSeek, Mistral, local models, and future providers are replaceable execution sources. Provider-specific code is confined to adapters.

The software-development loop is a first consumer of this architecture, not a special architecture of its own:

```text
User + Cloudeo decision layer
        |
        | approved objective / plan / role bindings
        v
Cloudeo WorkOrder + Orchestration
        |
        +---------------- role: planner/reviewer ----------------+
        |                                                        |
        v                                                        |
Provider-neutral execution intent                                |
        |                                                        |
        v                                                        |
Control-store profile -> ExecutionRequest.kind -> dispatcher       |
        |                                                        |
        +--> Codex CLI / OpenAI                                  |
        +--> Claude Code / Anthropic                             |
        +--> Kimi Code / Moonshot                                |
        +--> UHP / HarnessRouter                                 |
        +--> API adapters                                        |
        +--> local/open-source runtime                            |
        |                                                        |
        v                                                        |
candidate repository state                                       |
        |                                                        |
        +---------------- role: executor -------------------------+
        |
        v
deterministic checks + independent audit
        |
        +--> REVISE (bounded)
        +--> USER_ATTENTION_REQUIRED
        +--> CODE_APPROVED
        |
        v
existing Cloudeo checkpoint / verification / promotion rules
```

The same provider-neutral mechanism MUST work outside coding. DevLoop is one orchestration recipe over generic Cloudeo primitives.

---

## 2. Non-negotiable invariants

### PN-01 — `cloudeo.control` is provider-blind

`cloudeo.control` MUST NOT import provider SDKs, provider CLI wrappers, provider authentication libraries, or provider-specific models.

It MUST NOT contain semantic branches such as:

```python
if provider == "anthropic":
    ...
elif provider == "openai":
    ...
```

Provider names may appear only as opaque recorded identity values in evidence/profile data, never as control-state transition logic.

### PN-02 — role first, provider later

The control layer asks for a role/capability:

```text
primary_code_executor
code_auditor
architecture_planner
memory_curator
...
```

It does not ask for Claude, GPT, Kimi, or another named model.

The approved Project Execution Profile binds each role to an immutable primary profile and ordered, pre-approved fallbacks as already required by the V2 control architecture.

### PN-03 — execution plane, adapter, provider, and model are different concepts

They MUST NOT be collapsed into one string.

```text
execution plane   = how the work is executed at a broad protocol level
adapter           = concrete invocation implementation
provider          = model/inference commercial identity
model             = exact requested/observed model identity
```

Examples:

```text
plane=uhp_harness
adapter=uhp
provider=anthropic
model=<exact model id>

plane=native_agent_cli
adapter=claude_code
provider=anthropic
model=<exact model id>

plane=native_agent_cli
adapter=codex_cli
provider=openai
model=<exact model id>

plane=native_agent_cli
adapter=kimi_code
provider=moonshot
model=<exact model id>

plane=model_api
adapter=openai_compatible_http
provider=moonshot
model=<exact model id>
```

A provider may be reachable through more than one adapter. An adapter is therefore the dispatch identity; provider is evidence/policy metadata.

### PN-04 — capabilities are contracts, not marketing labels

An execution profile advertises capabilities only after they are established by configuration and/or conformance tests.

Examples:

```text
repo_read
repo_write
shell
git
network
structured_output
session_resume
tool_use
mcp
browser
image_input
long_context
```

A role declares required and forbidden capabilities. Eligibility is a deterministic filter.

### PN-05 — no hidden billing-mode transition

Subscription usage, prepaid credits, and metered API usage are different execution policies.

Cloudeo MUST NOT silently fall from subscription-authenticated CLI execution to a metered API key.

If a subscription quota is exhausted and metered API use is not explicitly pre-approved, the result is a classified unavailable/quota condition followed by an allowed fallback or `USER_ATTENTION_REQUIRED`.

A profile declares its billing mode as immutable data. The allowed modes, whether metered use is allowed, and any metered cap are project-level policy approved with the Project Execution Profile (ADR-035). A metered fallback exists only as an approved fallback binding with its condition.

### PN-06 — execution completion is never verification

A provider or adapter may report that a task completed. Only Cloudeo verification can produce `CODE_APPROVED`, `BLOCK_DONE`, or promotion.

No adapter may grant itself verification authority.

### PN-07 — automation is bounded

No planner/executor/reviewer pair may converse without a WorkOrder budget.

Bounds that decide whether work may continue (repair rounds, stopping on a repeated classified failure, scope expansion, baseline drift) are **control policy**. If adopted they are added as control rules and recorded in the control store (ADR-035, "Loop policy belongs to control"). DevLoop only runs the recipe; it never decides whether work may proceed. Baseline drift continues to follow the existing control rules.

Publishing a branch or pull request, merging it, and production deployment are separate human-approved actions outside the gate (see §13.5).

### PN-08 — evidence, not prose, is authority

Agent prose such as "tests passed" or "done" is not proof.

Evidence includes, as applicable:

- exact candidate `HEAD`;
- content hash;
- diff;
- deterministic test command and exit status;
- test result references;
- adapter/runtime identity;
- requested and actual model identity when observable;
- stdout/stderr or structured output references;
- cost/usage evidence when observable;
- CI result;
- audit result.

### PN-09 — local, hosted, proprietary, and open-source runtimes are peers

Cloudeo MUST be able to support:

- subscription-authenticated local CLIs;
- UHP/HarnessRouter agents;
- metered hosted APIs;
- OpenAI-compatible APIs;
- self-hosted runtimes such as vLLM/Ollama-style endpoints;
- future execution systems.

None is architecturally privileged.

### PN-10 — adding a provider must not change control semantics

A new provider should normally require:

```text
one adapter implementation
one adapter descriptor/registration
provider-specific tests
shared conformance tests
optional profile configuration
```

It should not require changes to:

```text
WorkOrder state machine
promotion gate
workspace broker
verification semantics
human-decision semantics
Project Memory rules
```

If it does, the abstraction is wrong or the new capability is a genuinely new execution class.

### PN-11 — traceability is mandatory

The provider-neutral extension MUST be added to the existing V2C traceability discipline rather than creating a parallel compliance system.

`docs/14_V2C_TRACEABILITY.md` remains the canonical map for V2C implementation status. New provider-neutral invariants introduced by ADR-035 should either:

- be mapped into the existing traceability document when they refine a V2C invariant; or
- receive a clearly separate provider-neutral invariant namespace and traceability table when they are genuinely new.

No invariant is considered enforced merely because an adapter test passes; the traceability record must point to the enforcing code and offline test.

ADR-035 traces the genuinely new invariants in `14_V2C_TRACEABILITY.md` under a Provider-Neutral (PN) section: PN-01, PN-03, PN-04, PN-05, PN-07, and PN-10 from this document, plus PN-12 and PN-13 below. All are DEFERRED until implemented.

### PN-12 — dependency direction (from ADR-035)

`cloudeo.orchestration` may depend on `cloudeo.control` and `cloudeo.execution`. The edges `control -> execution`, `control -> orchestration`, `execution -> control`, and `execution -> orchestration` are forbidden, each with a mechanical AST check and a negative test. See §17.

### PN-13 — native-CLI isolation (from ADR-035)

A candidate Git worktree is not a security boundary. A write-capable native agent CLI runs only in an OS-isolated copy of the candidate. See §8.3.

---

## 3. Architectural layers

```text
+----------------------------------------------------------------+
|                         USER / PRODUCT                           |
| Chat, Mission Control, API, future integrations                 |
+-------------------------------+--------------------------------+
                                |
                                v
+----------------------------------------------------------------+
|                     CLOUDEO CONTROL                              |
| WorkOrder state, plan/envelope, role bindings, human gates,     |
| verification authority, checkpoint/promotion rules              |
|                                                                |
| PROVIDER-BLIND                                                  |
+-------------------------------+--------------------------------+
                                |
                public orchestration functions only
                                |
                                v
+----------------------------------------------------------------+
|                   CLOUDEO ORCHESTRATION                          |
| Build role step -> resolve approved profile -> eligibility ->   |
| invoke execution -> collect trusted runtime evidence ->         |
| return normalized evidence to control                           |
|                                                                |
| NO WorkOrder mutation outside cloudeo.control                   |
+-------------------------------+--------------------------------+
                                |
                                v
+----------------------------------------------------------------+
|             CONTROL-OWNED POLICY (cloudeo.control)               |
| ExecutionProfile registry (control store, canonical)            |
| ProjectExecutionProfile bindings, fallback conditions,          |
| billing policy, independence policy, loop policy                |
+-------------------------------+--------------------------------+
                                |
                                v
+----------------------------------------------------------------+
|     EXECUTION (cloudeo.execution): ExecutionDispatcher           |
|  routes ONLY by ExecutionRequest.kind                            |
| direct_tool | uhp_harness | native_agent_cli | model_api |      |
| browser | human | future   (each plane = one request kind)       |
+-------------------------------+--------------------------------+
                                |
                                v
+----------------------------------------------------------------+
|     ADAPTERS (adapter registry lives in cloudeo.execution)       |
| treg | uhp | codex_cli | claude_code | kimi_code |             |
| openai_compatible_http | future                                 |
+-------------------------------+--------------------------------+
                                |
                                v
+----------------------------------------------------------------+
|                 PROVIDERS / RUNTIMES / MODELS                    |
| OpenAI | Anthropic | Moonshot | local | future                  |
+----------------------------------------------------------------+
```

---

## 4. Relationship to existing Cloudeo architecture

### 4.1 Existing execution contracts stay useful

The current repository already separates:

```text
DirectToolExecution
HarnessTaskExecution
ExecutionOutcome
ExecutionDispatcher
```

`ExecutionRequest.kind` is the execution-plane seam and MUST be preserved. `ExecutionDispatcher` remains the sole router by request kind. A new plane is a new request kind with a neutral request model (ADR-035).

The new design adds provider/runtime extensibility around it instead of replacing it wholesale.

### 4.2 UHP remains a preferred standardized agent plane, not a mandatory monopoly

Where a runtime is available through UHP/HarnessRouter, Cloudeo SHOULD prefer the standardized UHP path because it reduces provider-specific integration work.

However, provider independence MUST NOT depend on every useful executor being UHP-native.

Subscription-authenticated local coding CLIs may therefore be exposed through a `native_agent_cli` plane when UHP cannot preserve the required authentication, quota, filesystem, session, or interactive semantics.

### 4.3 ADR-030 boundary remains authoritative

Accepted ADR-030 is a hard boundary for this design:

- `cloudeo.control` remains pure policy/state-machine code and owns WorkOrder transitions.
- dependency direction is one-way: orchestration may depend on control's public surface; control never depends on orchestration.
- `cloudeo.orchestration` collects trusted runtime evidence and translates it into public control inputs.
- orchestration may read a WorkOrder but MUST NOT construct, copy with changes, or mutate WorkOrder state records owned by the state machine; every WorkOrder transition goes through the public control state machine. Public control input/evidence objects such as `KernelOutcome` may be constructed by orchestration as required.
- ADR-035 amends ADR-030 in one respect only: orchestration may also depend on `cloudeo.execution`.
- orchestration may consume trusted runtime evidence such as `GatedPromotionResult`, `WorkspaceBroker.accepted_state()`, `SessionEvidence`, and normalized runtime evidence without weakening their meaning.
- direct `WorkspaceBroker.promote()` remains permanently forbidden outside the authorized promotion gate path.
- `GatedPromotionResult` is mapped to the control-owned `KernelOutcome`; orchestration does not invent promotion state.
- accepted-baseline observations come from `WorkspaceBroker.accepted_state()`; baseline drift is not inferred from stale cached state.
- V2C-01 continues to constrain the control layer; ADR-030 does not expand control's authority into runtime integration.

Provider-neutral execution is added **below orchestration**. It does not create another state machine or a second route around ADR-030.

---

## 5. Core provider-neutral objects

### 5.1 `RoleExecutionIntent`

This is the orchestration-level statement of work. It is provider-neutral.

Illustrative shape:

```python
class RoleExecutionIntent(BaseModel):
    work_order_id: str
    block_id: str | None
    role: RoleId

    objective: str
    workspace_ref: WorkspaceRef | None
    input_refs: list[EvidenceRef]
    output_contract: OutputContract | None

    required_capabilities: frozenset[Capability]
    forbidden_capabilities: frozenset[Capability]

    permissions: PermissionEnvelope
    budget: StepBudget
    risk_class: RiskClass
```

It contains no provider name, model name, CLI command, API base URL, token, or secret.

### 5.2 `ExecutionProfile`

There is no new profile type here. The existing V2 control types are canonical and are not redefined by this document:

```text
_ExecutionProfileBase   profile_id, version, permissions, limits, eligible_roles
AgentProfile            runtime (harness_id/version), model (provider, model_id,
                        model_version, family, inference_provider), reasoning,
                        context_policy, session ("fresh" | "persistent")
DirectToolProfile       capability, provider
ProjectExecutionProfile role bindings and fallback bindings
```

Computed fingerprints (`ProfileRef`), model `family`, `inference_provider`, `session`, `eligible_roles`, `permissions`, and `limits` are preserved as they are. The registry is the existing control-store profile registry. Profiles remain immutable once registered.

Provider-neutral profile data that a later slice needs is added to these types as **additive fields**, each in its own slice. Candidates:

```text
adapter_id            selects the adapter within a plane's backend
execution_plane       the request kind the profile executes as
billing_mode          immutable declaration; policy lives in the project profile
auth_profile_ref      non-secret reference only
```

Adding fields changes every profile's fingerprint once, so it happens before profiles are relied on outside tests. No second profile type or profile registry is created. Adapter-owned runtime options, if any, are opaque to control and are added only with the same care.

`Permissions` is the authority a profile is granted, evaluated by control. Capabilities (§5.3) are facts about an adapter, established by conformance tests and evaluated in `cloudeo.execution`. Neither replaces the other.

### 5.3 `AdapterDescriptor`

```python
class AdapterDescriptor(BaseModel):
    adapter_id: str
    adapter_version: str
    execution_planes: frozenset[ExecutionPlane]
    capabilities: frozenset[Capability]
    auth_modes: frozenset[AuthMode]
    billing_modes: frozenset[BillingMode]
    supports_health: bool
    supports_quota_observation: bool
    supports_cancellation: bool
    supports_session_resume: bool
```

This describes the adapter, not a specific model.

### 5.4 `AdapterHealth`

```python
class AdapterHealth(BaseModel):
    status: Literal["available", "degraded", "unavailable", "unknown"]
    observed_at: datetime
    reason_class: str | None
    evidence_ref: EvidenceRef | None
```

`unknown` never means healthy.

### 5.5 `QuotaObservation`

Quota is optional evidence:

```python
class QuotaObservation(BaseModel):
    status: Literal["available", "exhausted", "unknown"]
    remaining: Decimal | None
    unit: str | None
    reset_at: datetime | None
    observed_at: datetime
    evidence_ref: EvidenceRef | None
```

Absence of quota information never means unlimited quota.

---

## 6. Authentication and billing policy

Secrets do not belong in `ExecutionProfile`, WorkOrder Memory, Project Memory, logs, or Git.

Profiles carry at most a non-secret `auth_profile_ref`. Secrets never enter profiles, Git, logs, or evidence.

Example auth modes:

```text
subscription_oauth
subscription_session
api_key
service_account
local_no_auth
external
```

Example billing modes:

```text
subscription_included
prepaid_credit
metered_api
self_hosted
unknown
```

Policy example (project-level, approved with the Project Execution Profile, not stored in an adapter or a profile):

```python
BillingPolicy(
    allowed_modes={"subscription_included"},
    allow_metered_fallback=False,
    max_metered_cost_usd=None,
)
```

The profile declares one immutable billing mode. No adapter may run in a billing mode other than the one its profile declares. There is no silent subscription-to-metered transition: a metered fallback exists only as an approved fallback binding with its condition.

A development project can therefore express:

```text
primary_code_executor:
  primary: Claude Code, subscription
  fallback 1: Codex CLI, subscription
  fallback 2: Kimi Code, subscription/pre-approved plan
  metered API: forbidden
```

Another project could explicitly allow a capped metered fallback.

The adapter MUST report the observed billing mode when known. It MUST NOT infer "subscription" merely because a CLI was used.

---

## 7. Adapter protocol

A provider adapter should be small enough to test independently. Adapters live in `cloudeo.execution` and sit **below** the dispatcher: `ExecutionDispatcher` routes by `ExecutionRequest.kind` to a plane backend, and the backend selects an adapter by `adapter_id` from the adapter registry (§10.1).

There is no `ExecutorAdapter.execute(intent, profile)` entry point and no second dispatch path beside the dispatcher. Orchestration builds the plane's neutral request model from a `RoleExecutionIntent` and an already-approved profile; the backend executes that request.

Illustrative shape of a plane-internal adapter:

```python
class PlaneAdapter(Protocol):
    descriptor: AdapterDescriptor

    async def health(self) -> AdapterHealth: ...

    async def observe_quota(self) -> QuotaObservation | None: ...

    async def run(self, request: <plane request model>) -> ExecutionOutcome: ...

    async def cancel(self, execution_ref: str) -> CancellationOutcome: ...
```

Not every adapter supports every optional method. Unsupported behavior is explicit in the descriptor.

The adapter receives an already-approved request. It never picks a different profile, provider, or model on its own authority (ADR-035). A provider-side substitution is recorded as requested versus actual identity and is never an approved fallback.

---

## 8. Execution planes

### 8.1 `direct_tool`

Existing Treg-style capability execution.

Provider-specific AI concepts are usually irrelevant.

### 8.2 `uhp_harness`

Existing standardized harness task execution.

The UHP adapter compiles a provider-neutral intent plus an `AgentProfile` into the existing `HarnessTaskExecution`.

### 8.3 `native_agent_cli`

New plane for local coding/agent CLIs where direct process invocation is required.

Initial adapters:

```text
codex_cli
claude_code
kimi_code
```

This plane is a new request kind with a neutral request model, routed by the existing dispatcher. Subprocess use belongs in `cloudeo.execution`; orchestration still may not use `subprocess`.

**Isolation rule (ADR-035, PN-13).** A candidate Git worktree is not a security boundary: it shares refs and objects with the canonical repository, so a shell-capable agent in it could move `refs/cloudeo` around the gate. Write-capable Codex, Claude, or Kimi execution requires an OS-isolated copy of the candidate (container, sandbox, or separate user) with no access to the canonical repository or accepted refs. Changes return only through the existing bundle, validate, and apply path (`build_input_bundle`, `validate_output_bundle`, `check_candidate_unchanged`, `apply_delta`), never by writing the worktree. Until that isolation exists and is tested, no native-CLI profile may be bound to a write-capable role.

The generic plane owns subprocess lifecycle semantics. The concrete adapter owns CLI syntax, authentication discovery, structured-output invocation, session continuation, and provider-specific error classification.

### 8.4 `model_api`

Optional future plane for direct model APIs.

Initial generic adapter candidate:

```text
openai_compatible_http
```

Provider-specific HTTP adapters are added only where semantics differ materially.

A model API is not assumed to have repository-write, shell, or Git capabilities. Those capabilities come from a harness/tooling environment, not from the language model name.

### 8.5 `browser`

Preserved as a separate execution class because GUI/browser authority and evidence differ materially from coding-agent execution.

### 8.6 `human`

A human may satisfy a role step under an approved `HumanExecutionProfile`.

---

## 9. Runtime identity and normalized outcome

The current `RuntimeIdentity.backend: Literal["treg", "uhp"]` is too closed for the target architecture.

The runtime identity gains the following fields **additively** (existing fields and behavior are preserved) and uses extensible strings/enums at the right dimensions:

```python
class RuntimeIdentity(BaseModel):
    execution_plane: ExecutionPlane

    adapter_id: str
    adapter_version: str | None

    provider: str | None
    inference_provider: str | None

    requested_model: str | None
    actual_model: str | None
    model_fallback: bool | None

    requested_harness: str | None
    actual_harness: str | None

    session_id: str | None
    response_id: str | None
    execution_ref: str | None

    protocol_name: str | None
    protocol_version: str | None
```

No field is fabricated when the runtime does not report it.

### 9.1 Provider-neutral errors

`ExecutionError` gains a provider-neutral error class additively; native codes and details are kept as evidence. Orchestration maps error classes to the existing `FallbackCondition` values and to `AUDITOR_ERROR` routing (the producer V2C-12 and V2C-17 still lack), and the LongHorizon `AuditorFailure.kind` maps into the same classes. Control semantics do not change. Illustrative shape:

```python
class ExecutionError(BaseModel):
    error_class: ErrorClass
    source_adapter: str

    code: str | None
    message: str
    retryable: bool | None

    http_status: int | None
    native_type: str | None
    native_detail: JsonValue | None
    evidence_ref: EvidenceRef | None
```

Common error classes:

```text
authentication
authorization
quota_exhausted
rate_limited
runtime_unavailable
model_unavailable
transport
protocol
timeout
cancelled
invalid_request
workspace_violation
tool_failure
unknown
```

Fallback policy consumes the common class. Provider-specific codes remain evidence.

### 9.2 Native results must not force core-schema edits for every provider

Instead of growing:

```python
native_result: TregResult | UHPResult | ClaudeResult | CodexResult | KimiResult | ...
```

use an opaque envelope/reference:

```python
class NativeResultEnvelope(BaseModel):
    adapter_id: str
    schema_version: str
    payload: JsonValue | None
    payload_ref: EvidenceRef | None
```

The normalized fields are stable; the original adapter evidence is retained without making provider SDK models part of Cloudeo's core type graph.

---

## 10. Registry and discovery

Profile and adapter registries have different owners and are never merged.

### 10.1 Adapter registry

Maps `adapter_id` to implementation.

```text
codex_cli    -> CodexCliAdapter
claude_code  -> ClaudeCodeAdapter
kimi_code    -> KimiCodeAdapter
uhp          -> UHPAdapter
treg         -> TregAdapter
...
```

The adapter registry belongs only in `cloudeo.execution`. A plane's backend selects an adapter by `adapter_id`; the dispatcher still routes only by request kind. Registration may be built-in, Python-entry-point based, or configuration driven. The control package must not import these implementations.

### 10.2 Profile registry

The existing control-store profile registry is canonical and holds immutable approved execution profiles. No second profile registry is introduced.

Role bindings reference profile IDs + versions (`ProfileRef`), never loose provider/model strings.

### 10.3 Discovery is advisory until approved

Runtime discovery may detect:

- installed CLIs;
- authenticated sessions;
- UHP harnesses;
- supported models;
- health;
- quota observations.

Discovery may propose profiles but does not silently change role bindings.

---

## 11. Eligibility and routing

Eligibility is deterministic:

```text
approved role binding
        |
        v
primary profile
        |
        +--> profile version matches snapshot?
        +--> adapter registered?
        +--> required capabilities satisfied?
        +--> forbidden capabilities absent?
        +--> permissions fit?
        +--> billing policy allowed?
        +--> health acceptable?
        +--> independence policy satisfied?
        |
        v
execute
```

Fallback occurs only for conditions already approved in the snapshotted Project Execution Profile.

Performance Memory may recommend future profile changes but does not change a live WorkOrder.

---

## 12. Provider independence for review/audit

Execution and verification SHOULD be separable across providers, for example a Codex planner, a Claude executor, and a Kimi reviewer.

This document defines no independence levels. `13_V2_CONTROL_ARCHITECTURE.md` §8.6 and V2C-14 are authoritative: the cumulative risk table, measurement by role against the producers, runner-supplied fresh-session evidence, and `INDEPENDENCE_UNAVAILABLE`. Provider neutrality may add requirements (for example a different provider at a given risk class, through a stricter `IndependencePolicy`) and never relaxes one.

Provider diversity reduces correlated errors but never replaces deterministic tests.

---

## 13. DevLoop: provider-neutral software-development orchestration

DevLoop is a bounded orchestration recipe using existing V2 roles.

### 13.1 V1 objective

Eliminate the repetitive manual loop:

```text
copy ChatGPT suggestion
paste into coding agent
wait for implementation
copy response back
ask for review
copy corrections back
repeat
```

After a WorkOrder/plan is approved, the local Cloudeo process handles the repetitive execution/review cycle.

### 13.2 Roles

Reuse existing roles:

```text
context_analyst
architecture_planner
implementation_planner
primary_code_executor
code_auditor
memory_curator
memory_auditor
final_verifier
user_reporter
```

Do not create provider-named roles.

### 13.3 One implementation block

```text
approved ImplementationBlock
        |
        v
primary_code_executor
        |
        v
candidate diff + runtime evidence
        |
        v
deterministic checks
        |
        v
code_auditor (read-only, independence policy)
        |
        +--> VERIFIED
        |       |
        |       v
        |   CODE_APPROVED
        |
        +--> REVISE
        |       |
        |       v
        |   repair instruction derived from evidence
        |   (only if control policy permits another round)
        |       |
        |       +----> primary_code_executor
        |
        +--> BLOCKED / material deviation
                |
                v
        USER_ATTENTION_REQUIRED
```

The provider may change only through an already-approved fallback condition or an explicit user-approved `change_agent` path.

### 13.4 Loop policy is control policy

DevLoop executes the recipe; it does not decide whether work may proceed. Whether another repair round is allowed, how many rounds a block may use, and whether a repeated classified failure stops the work are control policy. If adopted they are added as control rules (ADR-035) and the control store records every round.

Candidate rules for that later control slice (not decided here):

```text
repair/audit round budget per block
same classified failure twice
new scope discovered
baseline drift (existing control rules)
```

No autonomous "keep trying until it works."

### 13.5 Git behavior

The executor may, inside an OS-isolated candidate copy (§8.3):

- edit only what the block allows;
- run deterministic checks;
- produce a candidate delta that returns through the existing bundle/validate/apply path.

"Accepted" means promotion of the broker's accepted ref through the gate. Publishing a branch or pull request, or merging it, is a separate future adapter behind a human-approved gate; it is not part of acceptance.

V1 MUST NOT automatically:

- publish or merge to protected branches;
- force-push protected branches;
- deploy production;
- change repository security settings;
- widen filesystem/network permissions.

Those remain explicit human/product gates unless a future project policy deliberately changes them.

---

## 14. This Chat vs local automation

The browser conversation is a decision surface, not a required runtime protocol.

Cloudeo must not depend on scraping or automating the ChatGPT or Claude web UIs.

The stable handoff is a WorkOrder/plan stored through a Cloudeo-controlled ingress, for example:

```text
Mission Control API/UI
CLI command
GitHub issue/PR integration
future ChatGPT/Claude connector
custom MCP integration
other approved ingress
```

Once the approved WorkOrder exists, the repetitive local loop can run without copying agent prose between web chats.

This chat may remain the place where the user discusses:

- product direction;
- architecture;
- plan approval;
- ambiguity;
- material deviations;
- agent/profile changes;
- publishing, merge, and deployment decisions (separate human-approved actions).

The local loop handles routine implementation, testing, evidence collection, and bounded repair.

---

## 15. Initial adapters

None of these is implemented by the first slice (see §25). Native-CLI adapters additionally require the OS isolation of §8.3 before binding to any write-capable role.

### 15.1 Codex CLI adapter

Purpose:

- subscription-authenticated or explicitly configured execution;
- repo inspection/editing inside an OS-isolated copy;
- shell/test tasks where supported;
- planner/reviewer/executor roles according to profile permissions.

Adapter-specific CLI syntax stays inside `codex_cli.py`.

### 15.2 Claude Code adapter

Purpose:

- subscription-authenticated local software execution;
- repo editing and testing inside an OS-isolated copy, according to profile permissions.

The adapter MUST distinguish subscription session use from explicit API-key billing when observable/configured.

It MUST NOT silently inject an API key as fallback.

### 15.3 Kimi Code adapter

Purpose:

- establish Moonshot/Kimi as a first-class third provider;
- prove that provider portability is real rather than an OpenAI/Anthropic special case.

Kimi-specific CLI/auth/output/error behavior stays inside the adapter.

### 15.4 UHP adapter

Preserve existing UHP execution and use it where standardized harness access is available.

A UHP harness may itself front Codex, Claude, Kimi, or another runtime. The recorded identity therefore keeps both harness and provider/model dimensions when observable.

### 15.5 OpenAI-compatible HTTP adapter

Later generic adapter for compatible model APIs.

It is not a coding-agent adapter by itself. Repository/shell capabilities require a harness or tool environment around the model.

---

## 16. Suggested package structure

Target structure, subject to alignment with the accepted ADR-030 implementation:

```text
src/cloudeo/
    control/
        ...                         # provider-blind; existing authority

    orchestration/
        devloop.py                  # bounded software-development recipe
        role_execution.py           # intent -> approved profile -> request kind
        evidence.py                 # trusted runtime evidence collection
        ...

    execution/
        contracts.py                # normalized execution contracts
        registry.py                 # adapter registration / lookup (not profiles)
        errors.py                   # provider-neutral error taxonomy
        conformance.py              # shared adapter tests/contracts

        planes/
            direct_tool.py
            uhp_harness.py
            native_agent_cli.py
            model_api.py

        adapters/
            treg.py
            uhp.py
            codex_cli.py
            claude_code.py
            kimi_code.py
            openai_compatible.py

    auth/
        refs.py                     # non-secret auth references only
        ...                         # secrets never enter profiles or Git
```

Do not implement this tree mechanically if the newer local ADR-030 branch already established better module locations. The dependency rules are more important than exact filenames.

---

## 17. Dependency rules

ADR-035 fixes the dependency direction:

| From | To | Rule |
| --- | --- | --- |
| `cloudeo.orchestration` | `cloudeo.control` | allowed (ADR-030) |
| `cloudeo.orchestration` | `cloudeo.execution` | allowed (ADR-035) |
| `cloudeo.control` | `cloudeo.execution` | forbidden |
| `cloudeo.control` | `cloudeo.orchestration` | forbidden (ADR-030) |
| `cloudeo.execution` | `cloudeo.control` | forbidden |
| `cloudeo.execution` | `cloudeo.orchestration` | forbidden |

Each forbidden edge gets a mechanical AST check with a negative test when the first ADR-035 slice is implemented.

Provider adapters MUST NOT import or mutate WorkOrder state. Provider SDK objects and secrets MUST NOT cross into `control`. Everything else in ADR-030 stands: direct `promote()` is forbidden outside the authorized gate; the `subprocess` and `cloudeo.workspace.git` bans apply to orchestration (not to `cloudeo.execution`).

---

## 18. Adapter conformance suite

Every adapter must pass a common suite before it is eligible for an approved profile.

Required checks:

1. **Identity:** adapter reports its own stable ID/version.
2. **No false verification:** `completed` never maps to verified success.
3. **Timeout semantics:** timeout does not claim cancellation unless cancellation is observed.
4. **Transport loss:** uncertain final runtime state maps to `unknown` where appropriate.
5. **Error mapping:** native errors preserve original code/detail and map to common error classes.
6. **Secret hygiene:** tokens/session secrets do not appear in normalized logs/evidence.
7. **Billing guard:** forbidden metered mode cannot be entered automatically.
8. **Capability honesty:** advertised capabilities match conformance behavior.
9. **Workspace scope:** write-capable adapters run only in an OS-isolated copy with no access to the canonical repository or accepted refs, and cannot bypass the bundle/validate/apply path.
10. **Output preservation:** provider-native output is retained in an opaque evidence envelope.
11. **Requested vs actual identity:** no invented actual model/harness/provider values.
12. **Session isolation:** audit sessions are distinct when policy requires it.
13. **Cancellation:** if supported, cancellation evidence is recorded.
14. **Structured output:** malformed provider output cannot directly mutate control state.
15. **Determinism of normalization:** the same native result normalizes the same way.

---

## 19. Provider-independence acceptance tests

The architecture is not accepted as provider-neutral merely because interfaces exist.

It is accepted when these tests pass.

### PI-01 — same intent, three providers

The same `RoleExecutionIntent` can be executed by profiles backed by:

```text
Codex/OpenAI
Claude/Anthropic
Kimi/Moonshot
```

Changing the provider requires changing only profile binding/configuration, not WorkOrder/control logic.

### PI-02 — control import boundary

Static checks prove each forbidden edge of the §17 table, and that `cloudeo.control` and `cloudeo.orchestration` import no provider-specific module and contain no provider SDK imports.

### PI-03 — provider removal

Removing any one provider adapter leaves control tests and other provider conformance tests unchanged.

### PI-04 — no silent paid fallback

With:

```text
allowed billing = subscription_included
metered fallback = false
```

simulate exhausted subscription quota.

Expected result:

```text
allowed pre-approved subscription fallback
OR
USER_ATTENTION_REQUIRED
```

Never metered API execution.

### PI-05 — independent audit

Configure executor provider A and required-auditor provider B.

Cloudeo refuses to run the audit on provider A when the risk policy requires provider separation.

### PI-06 — bounded loop

Force every implementation attempt to fail verification.

The loop stops exactly at the budget set by control policy and raises attention; it never continues recursively. The stop decision is made by control, not by DevLoop.

### PI-07 — evidence identity

Every execution record includes the profile version, adapter identity, requested provider/model identity when configured, actual identity only when observed, and candidate state anchors.

---

## 20. Implementation sequence

**Observed implementation baseline for this draft:** local branch
`feat/v2-orchestration-kernel-outcome-baseline` at `83c8263` on 2026-09-27,
with accepted ADR-030 at `a7b4c58`. This SHA is evidence of the drafting
baseline, not a permanent architectural dependency.


### Phase 0 — architecture reconciliation and decision (done)

Provider neutrality was recorded as ADR-035 and accepted on 2026-10-01 (ADR-031 to ADR-034 were taken by intervening ADRs). This document is its supporting document and is reconciled to it. No Codex/Claude/Kimi-specific execution code exists or is added until the slices below land.

### Phase 1 — first slice (ADR-035)

Inside `cloudeo.execution`, additive and behavior-preserving:

- provider-neutral `ExecutionError` classification (§9.1);
- additive runtime identity metadata (§9);
- the dependency and provider-blindness checks of §17.

Not in this slice: provider adapters, native CLI subprocess execution, sandbox implementation, profile migration, Session Fabric implementation, COST implementation, MCP implementation.

### Phase 2 — provider-neutral control additions and registry

Each in its own slice:

- additive profile fields on the canonical control types (§5.2);
- project-level billing policy (§6);
- loop-policy control rules (§13.4);
- `ExecutionPlane` as the request kind, adapter descriptor, and adapter registry in `cloudeo.execution` (§7, §10.1).

Preserve Treg and UHP behavior through compatibility tests.

### Phase 3a — OS isolation and native CLI plane

Prerequisite: the OS-isolated candidate copy of §8.3, implemented and tested. No native-CLI profile is bound to a write-capable role before then.

Implement the generic process lifecycle once (cwd/workspace binding, timeout, stdout/stderr capture, cancellation, environment filtering, secret redaction, exit classification, evidence capture), then plug concrete CLI adapters into it.

### Phase 3b — three-provider proof

Implement:

```text
codex_cli
claude_code
kimi_code
```

Run the same conformance suite against all three.

The milestone is portability, not sophisticated routing.

### Phase 4 — DevLoop V1 (after the isolation prerequisite)

Wire the bounded orchestration recipe:

```text
approved block
-> executor
-> deterministic checks
-> auditor
-> repair or approval
-> block completion
```

Respect existing WorkOrder and promotion state machines.

### Phase 5 — health, quota, and fallback evidence

Add observational health/quota hooks where reliable.

Apply only pre-approved fallback conditions.

No performance-driven live profile mutation.

### Phase 6 — optional API/local adapters

Add only when useful:

```text
openai_compatible_http
self-hosted endpoint
other providers
```

Each must pass the same conformance boundary.

---

## 21. DevLoop V1 definition of done

V1 is complete when all of the following are true:

```text
[ ] User approves one WorkOrder/implementation plan.
[ ] Role bindings are snapshotted and immutable for the active WorkOrder.
[ ] At least two native coding adapters can execute the same implementation block.
[ ] Kimi/Moonshot is integrated as the third-provider portability proof.
[ ] Executor runs in an OS-isolated copy; changes return only via bundle/validate/apply.
[ ] Deterministic tests are captured as evidence.
[ ] Auditor reads a frozen snapshot and cannot mutate it.
[ ] Failed audit can generate a bounded repair round.
[ ] Round budget is a control rule, mechanically enforced.
[ ] Same classified failure twice can stop/escalate, as a control rule.
[ ] Metered API fallback is impossible unless explicitly allowed.
[ ] `CODE_APPROVED` cannot originate from an adapter.
[ ] Acceptance is gate promotion; publishing or merging a branch/PR is a separate human-approved action.
[ ] Production deployment remains a human gate.
[ ] Provider replacement does not modify control state-machine code.
[ ] Shared adapter conformance tests pass.
```

---

## 22. Explicit non-goals for the first implementation

Do not build yet:

- automatic model benchmarking and ranking;
- autonomous cost optimization;
- provider bidding;
- dynamic Jev-driven live role switching;
- autonomous publishing or merging;
- autonomous production deployment;
- browser-UI scraping of ChatGPT/Claude/Kimi;
- a universal prompt language;
- a new trust kernel;
- a second WorkOrder state machine;
- a second promotion mechanism.

First prove the provider boundary and bounded DevLoop.

---

## 23. Architectural test question

For every new provider/runtime, ask:

> Can this be added by registering an adapter/profile and passing conformance tests, without changing Cloudeo control semantics?

If **yes**, the provider abstraction is healthy.

If **no**, classify why:

1. the adapter is poorly isolated; or
2. the runtime introduces a genuinely new execution class/capability that deserves an explicit provider-neutral contract.

Never patch provider-specific behavior into the control state machine.

---

## 24. Relationship to ADR-035

This document is a supporting document for ADR-035 and proposes no ADR wording of its own. The decision is recorded and accepted as ADR-035 (2026-10-01) in `02_DECISIONS.md`. ADR-035 is normative; where this document differs from it, ADR-030, `13_V2_CONTROL_ARCHITECTURE.md`, or `14_V2C_TRACEABILITY.md`, those govern.

---

## 25. Immediate next development slice

The first implementation slice is the one ADR-035 fixes. It stays inside `cloudeo.execution` and is additive and behavior-preserving:

- provider-neutral `ExecutionError` classification;
- additive runtime identity metadata;
- dependency/provider-blindness checks (§17).

It must not yet include provider adapters, native CLI subprocess execution, a sandbox implementation, profile migration, Session Fabric implementation, COST implementation, or MCP implementation. It adds no provider SDK dependency and keeps all existing tests green.

Only after later slices (§20) land should Codex CLI, Claude Code, and Kimi Code adapters be implemented.
