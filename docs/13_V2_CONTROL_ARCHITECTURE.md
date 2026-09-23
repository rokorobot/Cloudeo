# Cloudeo v2 — Control Architecture Contract

**Status:** Accepted (2026-09-23). Not yet implemented.\
**Date:** 2026-09-23\
**Decisions:** ADR-022 to ADR-029 in `02_DECISIONS.md`\
**Foundation:** the trust kernel on `main` at `d7e7c67` (ADR-015 to ADR-021)

This document defines the Project, WorkOrder, Execution Profile, Memory, and
Human Decision layer that sits **above** the completed trust kernel. It is a
contract, not an implementation. Nothing here changes the kernel, and nothing
here is built yet.

---

## 1. Scope

**In scope:** the domain objects, state machines, authority rules, gates,
memories, and escalation model that turn a user objective on a project into
promoted code, plus the invariants any implementation must satisfy.

**Out of scope:** storage schemas and APIs beyond what the invariants need,
UI layout, Browser Use and Jev integration, multi-executor optimization, and
any change to the trust kernel.

**Relationship to existing documents:**

- `07_TARGET_ARCHITECTURE_V2.md` remains the target system view.
  - **§4.3 ExecutionProfile** stays the generic routable execution
    configuration. This contract specializes it (§8.3).
  - **§4.1 WorkOrder** is refined here.
  - **§5 dynamic router and §11 recovery policy** are replaced for role-bound
    steps by stable role bindings (§8.4): runtime routing decides which
    role or capability a step needs, not which model looks best today.
  - Where the two disagree, this contract and ADR-022 to ADR-029 govern.
- `09_ROUTING_VERIFICATION_AND_PERFORMANCE_MEMORY.md` remains the Performance
  Memory design. §13 here bounds its authority to recommendations.
- `11_V2_ACCEPTANCE_CRITERIA.md` remains in force. §15 here adds criteria for
  this layer.

---

## 2. The trust kernel (fixed foundation)

```text
Manager → Auditor → Normalizer → Promotion Gate → Workspace Broker
```

It is already on `main`, and it guarantees that accepted state advances only
to an immutable checkpoint proven to be exactly the audited, original
`VERIFIED` candidate state:

- the Workspace Broker owns accepted state and candidates (ADR-015);
- the workspace executor and bridge (ADR-017, ADR-018);
- the independent read-only auditor (ADR-019);
- `normalize_auditor_result()` (ADR-019 amendment);
- `checkpoint_and_promote_verified()` (ADR-020);
- `run_managed_with_promotion_gate()` (ADR-021).

**Kernel rule (K1):** nothing in this control layer may write accepted state,
write `refs/cloudeo`, call `promote()`, or bypass the gate. The layer decides
*what to attempt* and *when to ask the user*. Only the kernel decides *what is
accepted*.

---

## 3. Architecture

### 3.1 Project onboarding (once per project)

```text
PROJECT ONBOARDING
       ↓
register ProjectTarget (repository, broker workspace, memory paths)
       ↓
detect available runtimes, agents, and models (UHP discovery, local config)
       ↓
propose a Project Execution Profile: role → primary ExecutionProfile + fallbacks
       ↓
USER APPROVAL
       ↓
stable Project Execution Profile v1
       ↓
future WorkOrders snapshot the currently approved version
```

During normal execution a WorkOrder's profile snapshot is immutable. Changing
role bindings is a separate, explicit user decision that creates a new
project-level version. An active WorkOrder moves to it only through an
explicit, user-approved envelope amendment (§8.4, §10).

### 3.2 WorkOrder path

```text
Project + Objective
        ↓
Context Intake                        context_analyst; read-only; Project Memory first, verified against code
        ↓
Proposed Architecture                 architecture_planner
Implementation Plan                   implementation_planner
        ↓
USER PLAN APPROVAL                    the approved plan becomes the execution envelope
        ↓
WorkOrder (EXECUTING)                 one candidate from the approved baseline
        ↓
Implementation Block
        ↓
LongHorizon bounded manager run       no promotion; executor → auditor → repair/retry rounds
        ↓
Cloudeo normalized block result
        ↓
CODE_APPROVED  or  USER_ATTENTION_REQUIRED
        ↓
memory update required?
   ┌───────┴────────┐
   no              yes
   │                ↓
   │          Memory Curator          writes Project Memory paths only
   │                ↓
   │           Memory Audit           memory_auditor; independent
   │                ↓
   └──── authoritative block state (HEAD + content hash)
                    ↓
          checkpoint_candidate()
                    ↓
          verify checkpoint == audited block state   (ADR-020 principle, no promotion)
                    ↓
              BLOCK_DONE              proven candidate checkpoint; never acceptance
                    ↓
next block … all blocks BLOCK_DONE
        ↓
Final Verification                    final_verifier: fresh read-only audit of the frozen candidate
        ↓
Normalizer → Promotion Gate → Workspace Broker     (existing trust kernel)
        ↓
Accepted Code + Project Memory        advance together, atomically
        ↓
Performance Memory                    verified outcomes only; recommendations to the user
```

### 3.3 Ownership hierarchy

```text
Cloudeo WorkOrder Manager             project workflow, state, envelope, escalation
        ↓
ImplementationBlock
        ↓
LongHorizon bounded manager run       the inside of one autonomous coding episode
        ↓
executor → auditor → repair/retry rounds
        ↓
Cloudeo normalized block result
```

Cloudeo owns the project workflow. LongHorizon owns the inside of an
autonomous coding episode. Cloudeo does not reimplement LongHorizon's agent
loop (07 §3.2).

### 3.4 Exception path

```text
cannot continue within the approved envelope
        ↓
USER_ATTENTION_REQUIRED
        ↓
every active reason + evidence + suggested solutions
        ↓
user chooses: resume / replan / change agent / change budget / defer / abort
(plus free-form discussion)
```

### 3.5 Authority model

| Actor | May | May never |
| --- | --- | --- |
| **User** | approve the Project Execution Profile, plans, and envelopes; resolve attention requests; abort | be bypassed by any automatic path for a decision this contract assigns to them |
| **Control layer** (Cloudeo) | run state machines, enforce the envelope, dispatch roles to their bound profiles, aggregate evidence, raise attention | promote, accept, widen the envelope, or change role bindings on its own |
| **Agents and executors** (through ExecutionProfiles) | analyze, propose, implement, curate memory, audit, report, within their role's permissions | approve their own work, change the envelope, promote |
| **Trust kernel** | decide acceptance and advance accepted state | run without an original `VERIFIED` audit of the exact state |
| **Performance Memory / Jev** | record verified outcomes and recommend policy changes | select a profile, choose a fallback, or change any approved policy |

---

## 4. Projects

### 4.1 ProjectTarget (project identity)

What a WorkOrder belongs to.

```text
ProjectTarget
- project_id
- name
- repository                 # canonical location (path and/or remote); one Workspace Broker workspace
- workspace_id               # the broker workspace that owns accepted state
- accepted_baseline          # read from the broker (accepted_commit); never cached as truth
- memory_paths               # tracked Project Memory locations inside the repository (§5)
- execution_profile          # approved Project Execution Profile id + current version (§8.4)
- policies                   # risk defaults, independence requirements, budgets, escalation contacts
```

- A ProjectTarget maps to exactly one broker workspace. The broker remains the
  authority for the accepted baseline (ADR-015).
- A WorkOrder records the accepted baseline it was **planned** against and the
  candidate it **executes** in (§6). If accepted state moves in between, that
  is baseline drift and is never silently absorbed (§10).

### 4.2 Candidate relationship

```text
accepted baseline B ──(create_candidate)──▶ candidate C (one per executing WorkOrder)
C accumulates BLOCK_DONE checkpoints, each with coherent code and memory
C ──(trust kernel, final verification)──▶ accepted B′ = proven checkpoint of C
```

Concurrent WorkOrders on the same project have separate candidates. The first
to promote wins, and the others become stale and must replan or rebase
through the user (ADR-015 already refuses stale promotion).

---

## 5. Project Memory

**What it is:** the accepted description of what actually exists in the
project. It covers architecture, components, boundaries, interfaces,
decisions, conventions, and known limitations.

**Where it lives:** in human-readable tracked documents inside the repository,
for example:

```text
docs/architecture/         system architecture and boundaries
docs/components/           one document per component: purpose, interfaces, invariants
docs/decisions/            decision records (ADR style)
.cloudeo/project-memory/   optional machine index: claims, anchors, and cross-references
```

The exact paths are per-project `memory_paths` (§4.1). Canonical
architectural knowledge stays in readable documents. The optional index only
points into them; it never holds knowledge the documents lack. Because
everything is Git-visible candidate state, Project Memory is:

- versioned with Git;
- part of the audited snapshot and its content hash (ADR-019 and ADR-020 trust
  boundary);
- promoted atomically with the code by the existing gate, with no second
  promotion mechanism.

**Claims carry evidence anchors.** Each memory entry is a claim that names
where it can be checked, such as paths, symbols, tests, or decision records.
Context Intake and Memory Audit verify claims against those anchors. A claim
without anchors is reported as unverifiable, never assumed true.

**Update rule (ADR-023):**

1. Canonical Project Memory changes only through promotion, together with the
   code it describes.
2. Candidate memory changes only after the related block reaches
   `CODE_APPROVED`, only by the `memory_curator` role, and only within
   `memory_paths`.
3. Every candidate memory change passes an independent Memory Audit before
   the block is `BLOCK_DONE`.
4. Memory never records intent as fact: planned, unverified, or rejected work
   is not written as existing architecture.

Credentials and secrets never belong in Project Memory.

### 5.1 The distinct memories

| Memory | Holds | Lives | Authority |
| --- | --- | --- | --- |
| **Project Memory** | what exists in the project | tracked documents in the repo; promoted with code | accepted project truth, after promotion |
| **WorkOrder Memory** | one WorkOrder's lifecycle, plan versions, decisions, evidence references, deviations, outcome | Cloudeo control store, append-only (§14.1) | the record of what was attempted and decided |
| **Performance Memory** | cross-project execution performance, cost, latency, failure and recovery patterns | Cloudeo control store (09) | advisory only (§13) |
| **LongHorizon round state** | the manager's rounds within one bounded run | LongHorizon run ledger | within that run only (V2-E01) |

None of these substitutes for another. In particular, WorkOrder Memory is not
a competing truth store: accepted truth remains the broker's accepted commit
plus the Project Memory promoted in it (V2-E01, V2-D01).

---

## 6. WorkOrder

```text
WorkOrder
- id, version                      # version for optimistic concurrency (§14.1)
- project_id
- objective                        # the user's words, kept verbatim
- planned_baseline                 # accepted commit the plan was made against
- candidate                        # workspace_id, candidate_id, base_commit (from PLAN_APPROVED)
- context_report_ref               # §7
- execution_profile_snapshot       # the approved Project Execution Profile version, snapshotted at creation
- plan_versions[]                  # proposed plans, each immutable
- approved_plan                    # version id; defines the envelope (§9)
- acceptance_criteria[]            # from the approved plan
- risk_class
- budget                           # total cost/time, per-block attempts
- implementation_blocks[]          # §8.5
- status                           # §6.1
- attention_requests[]             # §10
- evidence[]                       # references, never inlined prose as proof
- deviations[]                     # detected, and how each was resolved
- outcome                          # the final GatedPromotionResult (§12)
```

### 6.1 WorkOrder state machine

```text
DRAFT
  ↓ intake starts
CONTEXT_INTAKE                   read-only
  ↓ context report ready
PLAN_PROPOSED
  ├─ user requests changes ──▶ PLAN_PROPOSED (new plan version)
  ├─ user rejects ──────────▶ ABORTED
  └─ user approves
        ↓
PLAN_APPROVED                    envelope fixed; candidate created from the accepted baseline
  ↓
EXECUTING                        blocks in order (§8.5)
  ↓ all blocks BLOCK_DONE; candidate frozen
FINAL_VERIFICATION               fresh read-only audit → normalizer → gate (§12)
  ├─ promoted ──────────────────▶ PROMOTED (terminal)
  └─ not attempted / refused ───▶ USER_ATTENTION_REQUIRED

From CONTEXT_INTAKE, PLAN_APPROVED, EXECUTING, or FINAL_VERIFICATION:
  cannot continue within the envelope ──▶ USER_ATTENTION_REQUIRED
USER_ATTENTION_REQUIRED ──(user decision)──▶ previous state | PLAN_PROPOSED | DEFERRED | ABORTED
DEFERRED ──(user resumes)──▶ the state it was deferred from, after rechecks
```

Transition guards:

- No state before `PLAN_APPROVED` may write to any workspace. Intake and
  planning are read-only.
- `PLAN_APPROVED` requires an explicit user approval of a specific plan
  version, recorded in WorkOrder Memory.
- Entering `EXECUTING` requires the planned baseline to still equal the
  accepted baseline. Otherwise the result is baseline drift, and a new
  approval is needed.
- In `FINAL_VERIFICATION` no write-capable role runs: the candidate is frozen.
- `PROMOTED` is set only from a kernel result with `promoted == true`. No
  other signal, such as an executor's "done", LongHorizon `complete`,
  `CODE_APPROVED`, or `BLOCK_DONE`, can produce it.
- `ABORTED` never deletes evidence. Candidate cleanup policy is future work,
  as ADR-020 already notes.

---

## 7. Context Intake

**Purpose:** a read-only understanding of the project, relevant to the
objective, that the planners and the user can trust. It is performed by the
`context_analyst` role.

**Order:**

1. Read Project Memory first. It is the cheapest orientation, but it is a set
   of claims.
2. Verify each claim relevant to the objective against its evidence anchors
   in the code at the planned baseline.
3. Gather additional relevant code facts the memory does not cover.

**Output:** a ContextReport.

```text
ContextReport
- baseline_commit
- relevant_claims[]        # each: claim, anchors, status verified | contradicted | unverifiable, evidence
- code_facts[]             # discovered facts with anchors
- memory_gaps[]            # important facts memory lacks
- risks[]
```

**Rules:**

- Intake never writes to any workspace, including memory. A contradicted claim
  becomes a proposed memory correction in the plan (§8.1), for the user to
  approve like any other change.
- It runs on a read-only snapshot of the baseline, reusing the audit
  snapshot machinery (ADR-019).
- Contradictions that make the objective ambiguous are raised in the plan
  proposal, not guessed around.

---

## 8. Plan, Roles, Profiles, and Implementation Blocks

### 8.1 Plan proposal and the Plan Approval Gate (ADR-025)

The `architecture_planner` proposes architecture changes, and the
`implementation_planner` turns them into blocks. The user decides.

```text
PlanProposal (immutable, versioned)
- objective (restated) and interpretation
- context report summary, including contradicted memory claims
- proposed architecture changes: components, interfaces, boundaries
- implementation_blocks[] (ordered), each with scope, acceptance checks, and memory impact
- acceptance_criteria[] for the WorkOrder, including deterministic checks
- execution_profile: a reference to the snapshotted Project Execution Profile version (shown, not renegotiated)
- budget and risk class
- alternatives considered, known risks, open questions
- performance-memory observations, labelled as advisory (§13)
```

The user may approve, request changes (free-form), or reject. The approved
version becomes `approved_plan`. Any later change is a new plan version that
needs approval again. There is no execution, and no candidate write, before
approval.

### 8.2 Roles

A role is what a step needs, independent of which model or tool does it.

| Role | Workspace access | Purpose |
| --- | --- | --- |
| `context_analyst` | read-only snapshot | Context Intake (§7) |
| `architecture_planner` | read-only snapshot | Proposed architecture changes |
| `implementation_planner` | read-only snapshot | Implementation blocks, scopes, acceptance checks |
| `recovery_planner` | read-only snapshot | Recovery options for failures, deviations, and refusals; feeds attention requests and replans; never acts on them |
| `episode_manager` | none | The LongHorizon manager role inside a bounded block run |
| `primary_code_executor` | candidate write, block scope | Implements a block inside the bounded run; never runs after `CODE_APPROVED` |
| `code_auditor` | read-only snapshot | Independent block audit (the auditor inside the bounded run) |
| `format_repair` | none | Syntax only; never verification authority (ADR-019 amendment) |
| `memory_curator` | candidate write, `memory_paths` only | Updates Project Memory from the approved diff, prior memory, and audit evidence |
| `memory_auditor` | read-only snapshot | Independently verifies memory claims against the code |
| `final_verifier` | read-only snapshot | Final audit of the frozen candidate against the acceptance criteria |
| `user_reporter` | none | Explains status and attention requests to the user; also the LongHorizon final-response role |

The four planning roles (`context_analyst`, `architecture_planner`,
`implementation_planner`, `recovery_planner`) stay distinct even when they
map to the same profile. Deterministic test execution is not a role. It is a
deterministic step of the block (§8.5).

Write permissions are enforced by evidence, not trust:

- the executor's diff must stay within the block scope;
- the curator's diff must stay within `memory_paths`, and any other change
  is a material deviation (§9);
- the existing exact-type adapter eligibility in `roles.py` (ADR-018/019)
  stays the enforcement point at execution time.

### 8.3 ExecutionProfile hierarchy (ADR-027)

`ExecutionProfile` (07 §4.3) stays the generic, routable execution
configuration. It is specialized as follows:

```text
ExecutionProfile
├── AgentProfile               model/harness agents (e.g. an architecture profile, a coding profile, an audit profile)
├── DirectToolProfile          Treg capability/provider execution
├── BrowserExecutionProfile    Browser Use
└── HumanExecutionProfile      a human performs the step
```

Every ExecutionProfile has an id, a version, a version fingerprint, an
execution class, permissions (workspace access, network, tools), a budget,
and limits. It is **immutable once used**; any change is a new version.

`AgentProfile` adds the following:

```text
AgentProfile
- runtime: harness_id, harness version if observable
- model: exact provider + model id (+ date/version if observable), model family, inference provider
- reasoning: level / effort settings
- context_policy: which inputs it receives (memory sections, context report, prior audits) and size limits
- eligible_roles[]
```

The existing `HarnessExecutionProfile(harness_id, model, max_step)` is the
runtime subset of an AgentProfile. A Treg direct-tool call is a
`DirectToolProfile`, not an "agent".

### 8.4 Project Execution Profile and routing authority (ADR-027)

```text
ProjectExecutionProfile (control store; versioned; approved at onboarding)
- project_id, version, approved_by, approved_at
- role_bindings:
    architecture_planner  → primary: <AgentProfile, e.g. "Astra 6" architecture profile>
    primary_code_executor → primary: <AgentProfile, e.g. "Opus 5.5" coding profile>
    code_auditor          → primary: <AgentProfile, e.g. "GPT-5.6 Sol" audit profile>
    memory_auditor        → primary: <may reference the same AgentProfile as code_auditor if policy allows>
    …
  each: primary, fallbacks[] (ordered, pre-approved), fallback_conditions
- independence_policy: per risk class (§8.6)
```

Model names above are illustrative only.

**Rules:**

- The profile is approved **at project onboarding**. Each WorkOrder snapshots
  the currently approved version, and plan approval shows that version
  without renegotiating it.
- During normal execution, the WorkOrder's profile snapshot is **immutable**.
- Changing role bindings is a separate, explicit user decision. It creates a
  new project-level version, which later WorkOrders snapshot.
- An **active** WorkOrder moves to a new version only by the `change_agent`
  path:

  ```text
  USER_ATTENTION_REQUIRED
          ↓
  user chooses change_agent
          ↓
  new Project Execution Profile version
          ↓
  explicit WorkOrder envelope amendment
          ↓
  user approves that amendment
          ↓
  WorkOrder references the new profile version
          ↓
  resume
  ```

  Nothing changes silently, but the user can deliberately redirect an active
  WorkOrder.
- **Runtime routing decides which role or capability a step needs, not which
  model.** For a role, Cloudeo uses the bound primary while it is available
  and allowed.
- **Fallbacks are used only under their defined `fallback_conditions`:**
  - the runtime or model is unavailable (UHP discovery, health);
  - a classified runtime or provider failure (authentication, quota, rate
    limit, network, model unavailable) that persists after the primary's
    allowed retries;
  - the primary is forbidden by policy for this step, for example because it
    cannot satisfy the required independence.

  Every switch is recorded with its condition and evidence.
- Performance Memory and Jev **never** switch to a fallback, or to any other
  profile, because they predict better performance. They may recommend a
  change to the project's bindings, and the user decides (§13).
- The Project Execution Profile, and all credentials, live in the Cloudeo
  control store, never in the repository or Project Memory.

### 8.5 ImplementationBlock and the coding loop (ADR-026)

```text
ImplementationBlock
- id, order
- goal
- scope                     # declared paths/components the executor may change
- acceptance_checks[]       # deterministic tests/commands + audit criteria
- memory_impact             # expected Project Memory changes, if any
- attempt_budget
- status                    # below
- attempts[]                # each: profiles used, bounded-run report, test results, normalized audit, deviations
- checkpoint                # set at BLOCK_DONE
```

**Mechanism:** each block runs as a **bounded LongHorizon manager run** in a
no-promotion, verify-only wrapper. This is a variant of ADR-021 that never
calls the gate. Inside the run, LongHorizon owns the executor → auditor →
repair/retry rounds. Cloudeo owns the block state and escalation around the
run, and it normalizes the run's final audit.

Block state machine:

```text
PENDING
  ↓
RUNNING          bounded LongHorizon run; roles: episode_manager, primary_code_executor,
                 code_auditor, format_repair, user_reporter
  ↓
TESTING          deterministic acceptance checks on the exact candidate state
  ↓
BLOCK_RESULT     Cloudeo normalizes the run's final audit (normalize_auditor_result)
  ├─ pass ────────────────────────▶ CODE_APPROVED
  └─ fail, within attempt_budget ─▶ RUNNING (new bounded run)
CODE_APPROVED                       the executor is finished for this block
  ├─ memory_impact present ─▶ MEMORY_CURATION (memory_curator) ─▶ MEMORY_AUDIT (memory_auditor)
  │                               └─ fail, bounded ─▶ MEMORY_CURATION
  │                               └─ pass ─▶ BLOCK_CHECKPOINT
  └─ none ─────────────────────────────────────────────────────▶ BLOCK_CHECKPOINT
BLOCK_CHECKPOINT  authoritative block state (HEAD + content hash) → checkpoint_candidate()
                  → verify the checkpoint commit == authoritative block state
  ├─ proven ──▶ BLOCK_DONE          immutable candidate checkpoint (candidate history only)
  └─ differs ─▶ WorkOrder USER_ATTENTION_REQUIRED (BLOCK_CHECKPOINT_MISMATCH)
Any state: attempts or budget exhausted, a material deviation, required independence
unachievable, or a runtime failure beyond the fallback conditions ──▶ WorkOrder USER_ATTENTION_REQUIRED
```

**`CODE_APPROVED` means all of the following:**

1. every deterministic acceptance check passed on the exact candidate state;
2. the block audit normalized to **original `VERIFIED`**, never a repaired
   report (ADR-019 amendment);
3. the candidate diff since the previous `BLOCK_DONE` stays within the
   block's declared scope, or a deviation was approved by the user (§9);
4. the audited state is still the current candidate state. This is the same
   identity check the gate uses: content hash and `HEAD`.

**The authoritative block state** is the exact candidate state (`HEAD` plus
content hash, by the audit snapshot rules) of the last audit that approved
the block:

- the **code audit** that produced `CODE_APPROVED`, when the block has no
  memory impact;
- the **Memory Audit** that passed, when memory changed. Its snapshot contains
  the approved code plus the curated memory.

**Before `BLOCK_DONE`, the checkpoint is proven to be that state.** This is the
same immutable-object principle as ADR-020, without promotion:

1. Re-read the candidate's `HEAD` and content hash. They must still equal the
   authoritative block state; otherwise the block does not proceed.
2. Record the checkpoint with `checkpoint_candidate()` through the broker.
3. From immutable Git objects, verify the checkpoint commit. Its parent must
   be the audited `HEAD` (or the commit must be the audited `HEAD` itself),
   and its committed content hash must equal the audited content hash.

**`BLOCK_DONE` means all of the following:**

- the block is `CODE_APPROVED`;
- any required memory curation has passed Memory Audit;
- the curator changed only `memory_paths`;
- the code is unchanged since `CODE_APPROVED`;
- the block checkpoint commit is **proven** to be the authoritative block
  state.

The proven checkpoint holds coherent approved code together with its
synchronized candidate memory. It is recovery and evidence history, never
acceptance, and it never calls `promote()`. A checkpoint that fails the proof
(a raced checkpoint) is **never labelled `BLOCK_DONE`**. It stays as unaccepted
candidate evidence, and the WorkOrder raises `USER_ATTENTION_REQUIRED` with
`BLOCK_CHECKPOINT_MISMATCH`.

### 8.6 Auditor independence

Independence dimensions are **cumulative requirements**, not a single level:

| Risk | Fresh session | Read-only workspace | Different model family from executor | Different inference provider from executor |
| --- | --- | --- | --- | --- |
| Low | required | required | — | — |
| Medium | required | required | required | — |
| High | required | required | required | required |

Independence is measured against the **producer** of the audited change, by
role:

| Auditing role | Must be independent from |
| --- | --- |
| `code_auditor` | `primary_code_executor` |
| `memory_auditor` | `memory_curator` |
| `final_verifier` | every write-capable profile whose changes remain in the final candidate (every `primary_code_executor` and `memory_curator` profile used, including fallbacks) |

Every requirement is mandatory for its risk class, including a different
inference provider at high risk. If the bound profiles cannot meet a
requirement, the WorkOrder raises `USER_ATTENTION_REQUIRED` with
`INDEPENDENCE_UNAVAILABLE`. Cloudeo never weakens the policy automatically.
Only the user can explicitly revise or waive it, and that decision is
recorded.

---

## 9. The approved envelope and deviations

The **approved envelope** is everything the user approved:

- the snapshotted Project Execution Profile version, with its bindings,
  fallbacks, fallback conditions, and independence policy;
- the plan version, with its blocks, scopes, and architecture changes;
- the acceptance criteria;
- the budget;
- the risk class.

**Within the envelope, without asking:**

- running the bound primary profile for each role;
- retrying a block within its attempt budget;
- switching to an approved fallback **only when its defined condition holds**;
- recording minor, in-scope implementation choices.

**Material deviation, which always escalates:**

- executor changes outside a block's declared scope;
- curator changes outside `memory_paths`;
- a public interface or architecture change not in the approved plan;
- a new dependency or a pin change;
- a change to acceptance criteria or the removal of a check;
- any profile not in the snapshotted bindings, or a fallback used without its
  condition;
- budget overrun, or exhausted attempts;
- required independence that cannot be met;
- a memory change that contradicts the approved architecture;
- baseline drift, where accepted state moved;
- any auditor contract finding of `needs_revision` or `invalid`.

Detection is evidence-based. Scope checks are deterministic diff checks
against the declared scope and `memory_paths`. Contract findings come from
the normalized audit. Budget comes from accounting. An agent's own claim that
it stayed in scope is never evidence.

---

## 10. USER_ATTENTION_REQUIRED (ADR-028)

A WorkOrder enters `USER_ATTENTION_REQUIRED` whenever it cannot continue
within the approved envelope. The attention request always shows **every
active reason together**, never one at a time.

```text
AttentionRequest
- id, work_order_id, raised_from_state, created_at
- reasons[]           # all active reasons
    - code            # e.g. BUDGET_EXHAUSTED, ATTEMPTS_EXHAUSTED, MATERIAL_DEVIATION,
                      #      AGENT_UNAVAILABLE, INDEPENDENCE_UNAVAILABLE, AUDITOR_ERROR,
                      #      AUDIT_NOT_VERIFIED, MEMORY_CONFLICT, BLOCK_CHECKPOINT_MISMATCH,
                      #      BASELINE_DRIFT,
                      #      PROMOTION_REFUSED, RISK_REQUIRES_HUMAN, PLAN_AMBIGUITY
    - severity        # blocking | warning
    - summary
    - evidence_refs[] # audits, test output, diffs, gate results, never bare prose
    - suggested_solutions[]   # from recovery_planner / Performance Memory; action, parameters, rationale, source
- conversation[]      # free-form discussion with the user_reporter role
- resolution          # UserDecision, once resolved
```

User actions:

| Action | Effect |
| --- | --- |
| `resume` | Continue in the same state, only if every blocking reason is resolved or explicitly waived by the user |
| `replan` | A new plan version, which needs approval again |
| `change_agent` | A new Project Execution Profile version (a project-level decision), then an explicit envelope amendment for this WorkOrder that the user approves; only then does the WorkOrder reference the new version and resume (§8.4) |
| `change_budget` | An approved budget amendment |
| `defer` | Park the WorkOrder; rechecks run on resume (baseline, profile availability) |
| `abort` | End the WorkOrder; evidence and candidate are kept |

**Rules:**

- Every decision is recorded with actor, time, action, parameters, and the
  message.
- Suggested solutions are advisory, and none is applied without the user's
  choice.
- The following states always raise attention; none may be silently retried
  or absorbed:
  - a kernel result of "not attempted" or "refused", including
    `refused_after_checkpoint`, where the kept checkpoint is shown as
    evidence;
  - an `AUDITOR_ERROR` beyond the fallback conditions;
  - baseline drift.

---

## 11. Memory curation and Memory Audit

After `CODE_APPROVED`, if the block has memory impact:

1. **Memory Curator.** The `memory_curator` receives the block's approved diff,
   the prior Project Memory, and the block's audit evidence. It writes only
   within `memory_paths` on the candidate. A deterministic check confirms that
   no other path changed.
2. **Memory Audit.** The `memory_auditor` independently checks, on a read-only
   snapshot, that:
   - every changed or added claim is supported by its anchors in the candidate
     code;
   - no claim describes planned or unapproved work as existing;
   - no claim contradicts the approved architecture, unless a user-approved
     deviation covers it.

The Memory Audit is normalized like any audit, and only original `VERIFIED`
passes. `memory_auditor` is its own role binding, even when it references the
same AgentProfile as `code_auditor` and the independence policy allows that.

---

## 12. Final verification and promotion

When every block is `BLOCK_DONE`, the candidate is frozen: no write-capable
role runs again for this WorkOrder.

1. The `final_verifier` runs a **fresh, read-only** audit of the whole
   candidate against the WorkOrder's acceptance criteria and Project Memory
   consistency, with the required independence.
2. `normalize_auditor_result()`. Only original `VERIFIED` may proceed.
3. `checkpoint_and_promote_verified()` (ADR-020) decides. Because the frozen
   candidate's `HEAD` is the last `BLOCK_DONE` checkpoint, the gate reuses that
   audited checkpoint and promotes code and Project Memory together.
4. `promoted` makes the WorkOrder `PROMOTED`. Any "not attempted" or
   "refused" result raises `USER_ATTENTION_REQUIRED`, with the kernel result
   as evidence.
5. Verified outcomes are then emitted to Performance Memory (§13).

No write-capable manager execution runs during final verification.

---

## 13. Performance Memory (ADR-029)

Performance Memory keeps the design in 09 (schemas, version fingerprints,
cold start, learning stages). This contract bounds its authority:

- It is separate from Project Memory and WorkOrder Memory, and it is never
  written into the repository.
- It learns only from verified labels, per the 09 trusted-label rule. These
  include block results, memory audits, final verification, kernel outcomes,
  user decisions, cost, latency, failure classes, and recovery paths, keyed
  by the ExecutionProfile version fingerprint, the role, and the task class.
- It may **recommend**: a change to the project's role bindings (a
  project-level user decision), in onboarding reviews, and as suggestions in
  attention requests.
- It may **never** select or switch a profile, including among approved
  fallbacks. It may never change an approved Project Execution Profile, plan,
  budget, risk class, or independence policy.
- Recommendations always show sample size and uncertainty (V2-H04, V2-H05).
  Jev follows the same bound when used for policy.

---

## 14. Implementation notes

### 14.1 Control store

SQLite initially, in the existing footprint (07 §10), **behind a storage
interface** so that PostgreSQL can replace it without changing WorkOrder
semantics:

- every mutable record (ProjectTarget, Project Execution Profile, WorkOrder,
  block, attention request) carries a `version`;
- state transitions are compare-and-swap on `(id, version)`, so concurrent
  writers fail explicitly instead of overwriting each other;
- WorkOrder Memory is append-only events plus current-state projections;
- Performance Memory uses separate tables.

### 14.2 Relationship to the implemented code

| This contract | Existing code or document |
| --- | --- |
| Accepted baseline, candidate, block checkpoints | `WorkspaceBroker`, `CandidateWorkspace`, `checkpoint_candidate()` (ADR-015) |
| Bounded block run | `run_managed_with_promotion_gate()` (ADR-021); needs a verify-only variant that never calls the gate |
| `primary_code_executor` | `UHPWorkspaceExecutorAdapter` + bridge (ADR-017/018) |
| Read-only roles (`code_auditor`, `memory_auditor`, `final_verifier`, `context_analyst`, planners) | `UHPWorkspaceAuditorAdapter` + audit transport (ADR-019), read-only snapshot |
| `memory_curator` | an executor-class profile restricted to `memory_paths`; needs a path-restricted write check (new) |
| Audit verdicts | `normalize_auditor_result()` → `AuditorVerification` |
| Acceptance | `checkpoint_and_promote_verified()` |
| Role eligibility | `roles.py` exact-type table (extended per role, not bypassed) |
| AgentProfile runtime subset | `HarnessExecutionProfile(harness_id, model, max_step)` |
| ExecutionProfile | 07 §4.3 (kept as the generic parent) |
| Performance Memory | 09 |

New code will be needed for:

- the control store, the onboarding flow, and the state machines;
- the verify-only bounded-run wrapper;
- the read-only planning and intake roles;
- deterministic scope and path checks;
- the attention and decision records.

None of it touches the kernel.

---

## 15. Invariants and acceptance criteria (V2C)

Each invariant must be enforced in code and proven by an offline test before
the related milestone is complete.

- **V2C-01:** nothing in the control layer can write accepted state or
  `refs/cloudeo`, or call `promote()` except through the gate (K1).
- **V2C-02:** no workspace write happens before an approved plan version
  exists.
- **V2C-03:** every plan change after approval creates a new version that
  needs a new approval.
- **V2C-04:** `PROMOTED` is reachable only from a kernel result with
  `promoted == true`.
- **V2C-05:** executor completion, LongHorizon `complete`, `CODE_APPROVED`, and
  `BLOCK_DONE` never imply acceptance.
- **V2C-06:** `CODE_APPROVED` requires passing deterministic checks, an
  original `VERIFIED` audit of the exact current candidate state, and an
  in-scope diff or a user-approved deviation.
- **V2C-07:** a repaired audit never produces `CODE_APPROVED`, a memory-audit
  pass, or a final-verification pass.
- **V2C-08:** Project Memory lives in tracked repository documents and
  advances canonically only by promotion, together with code.
- **V2C-09:** candidate memory changes only after `CODE_APPROVED`, only by
  `memory_curator`, only within `memory_paths`, and passes an independent
  Memory Audit.
- **V2C-10:** Context Intake is read-only and reports memory claims as
  verified, contradicted, or unverifiable, with evidence.
- **V2C-11:** the Project Execution Profile is approved at onboarding.
  - A WorkOrder snapshots it, and the snapshot is immutable during normal
    execution.
  - Changing bindings creates a new project-level version by explicit user
    decision.
  - An active WorkOrder references a new version only after a user-approved
    envelope amendment.
- **V2C-12:** each role uses its bound primary while it is available and
  allowed. Fallbacks are used only under their defined conditions, and every
  switch is recorded with evidence.
- **V2C-13:** Performance Memory and Jev never select or switch profiles and
  never change approved policy. They learn only from verified labels.
- **V2C-14:** auditor independence meets every cumulative requirement for the
  risk class.
  - Independence is measured by role against the producer: `code_auditor`
    against `primary_code_executor`, `memory_auditor` against
    `memory_curator`, and `final_verifier` against every write-capable profile
    whose changes remain.
  - If a requirement can't be met, `INDEPENDENCE_UNAVAILABLE` is raised.
  - The policy is never weakened automatically.
- **V2C-15:** every material deviation (§9) raises `USER_ATTENTION_REQUIRED`
  and is never silently absorbed.
- **V2C-16:** an attention request lists all active reasons with evidence and
  suggested solutions. Resolution records the user's decision.
- **V2C-17:** kernel "not attempted" or "refused", `AUDITOR_ERROR` beyond the
  fallback conditions, and baseline drift always raise attention.
- **V2C-18:** ExecutionProfiles are immutable once used, and every attempt
  records the exact version fingerprint.
- **V2C-19:** a block becomes `BLOCK_DONE` only when its checkpoint commit is
  proven from immutable Git objects to be the authoritative block state
  (`HEAD` plus content hash of the last approving audit).
  - A raced checkpoint is never labelled `BLOCK_DONE` and raises
    `BLOCK_CHECKPOINT_MISMATCH`.
  - Block checkpoints are candidate history only and never call `promote()`.
- **V2C-20:** final verification runs no write-capable role; it is a fresh
  read-only audit, then the normalizer, then the gate.
- **V2C-21:** `ABORTED` and `DEFERRED` keep all evidence and the candidate.
- **V2C-22:** baseline drift between planning and execution, or between
  execution and final verification, is detected from the broker and never
  silently rebased.
- **V2C-23:** control-store state transitions are compare-and-swap on the
  record version.

---

## 16. Non-goals for this milestone

- any implementation;
- any change to the trust kernel, broker, bridge, adapters, gate, or LongHorizon;
- UI, HTTP API, or storage schemas beyond the invariants;
- Browser Use, Jev routing, and multi-executor optimization;
- a Performance Memory implementation;
- a cleanup or rejection policy for refused checkpoints.

---

## 17. Resolved design decisions

| # | Question | Decision |
| --- | --- | --- |
| Q1 | Project Memory location | Human-readable tracked documents (e.g. `docs/architecture/`, `docs/components/`, `docs/decisions/`), per-project `memory_paths`, plus an optional machine index under `.cloudeo/project-memory/` |
| Q2 | Project Execution Profile location | The Cloudeo control store is authoritative; versioned project-level bindings, snapshotted per WorkOrder; credentials never in the repo |
| Q3 | Coding-loop mechanism | A bounded LongHorizon manager run per block, in a no-promotion / verify-only wrapper; Cloudeo owns the WorkOrder and block state around it |
| Q4 | Block checkpoints | Yes, at `BLOCK_DONE`, after optional Memory Curator and Memory Audit; the checkpoint is proven to be the authoritative audited block state; candidate history only |
| Q5 | Auditor independence | Cumulative dimensions per risk class, measured by role against the producer (§8.6); all mandatory; unachievable independence raises `INDEPENDENCE_UNAVAILABLE`; only the user may revise or waive it |
| Q6 | Final verification | A fresh direct read-only final audit → normalizer → gate; no write-capable manager run |
| Q7 | Control store | SQLite behind a storage interface, with version/CAS fields designed now (§14.1) |
| Q8 | Memory Audit binding | A separate `memory_auditor` role binding; it may reference the same AgentProfile as `code_auditor` when policy allows |
