# Cloudeo v2 — Control Architecture Contract

**Status:** Proposed; awaiting approval. Not implemented.\
**Date:** 2026-09-23\
**Decisions:** ADR-022 to ADR-029 in `02_DECISIONS.md`\
**Foundation:** the trust kernel on `main` at `d7e7c67` (ADR-015 to ADR-021)

This document defines the Project, WorkOrder, Agent Profile, Memory, and
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

- `07_TARGET_ARCHITECTURE_V2.md` remains the target system view. This contract
  refines its §4.1 WorkOrder and §4.3 ExecutionProfile and places its router
  and recovery policy (§5, §11) inside the user-approved envelope (§9 here).
  Where the two disagree, this contract and ADR-022 to ADR-029 govern.
- `09_ROUTING_VERIFICATION_AND_PERFORMANCE_MEMORY.md` remains the Performance
  Memory design; §13 here bounds its authority.
- `11_V2_ACCEPTANCE_CRITERIA.md` remains in force; §15 here adds criteria for
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

### 3.1 Normal path

```text
Project + Objective
        ↓
Context Intake                       read-only; Project Memory first, then verified against code
        ↓
Proposed Architecture / Plan         architecture_planner role
        ↓
USER PLAN APPROVAL                   the approved plan becomes the execution envelope
        ↓
WorkOrder (EXECUTING)                one candidate workspace from the approved baseline
        ↓
Implementation Block
        ↓
required Role
        ↓
Project Execution Profile            role → AgentProfile, approved by the user
        ↓
AgentProfile                         exact model, runtime, reasoning, permissions, budget
        ↓
Coding Loop                          implement → test → audit → fix/retry
        ↓
CODE_APPROVED                        candidate progress, not accepted state
        ↓
Project Memory update, if required   written into the same candidate
        ↓
Memory Audit
        ↓
next block … all blocks done
        ↓
Final Verification                   against the WorkOrder acceptance criteria
        ↓
EXISTING TRUST KERNEL                Manager → Auditor → Normalizer → Promotion Gate → Workspace Broker
        ↓
Accepted Code + Project Memory       advance together, atomically
        ↓
Performance Memory                   verified outcomes only
```

### 3.2 Exception path

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

### 3.3 Authority model

| Actor | May | May never |
| --- | --- | --- |
| **User** | approve or reject plans, envelopes, and profiles; resolve attention requests; abort | be bypassed by any automatic path for a decision this contract assigns to them |
| **Control layer** (Cloudeo) | run state machines, enforce the envelope, dispatch roles, aggregate evidence, raise attention | promote, accept, or widen the envelope on its own |
| **Agents** (through AgentProfiles) | analyze, propose, implement, audit, report | approve their own work, change the envelope, promote |
| **Trust kernel** | decide acceptance and advance accepted state | run without an original `VERIFIED` audit of the exact state |
| **Performance Memory** | record verified outcomes and recommend | change an approved profile, plan, or budget |

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
- memory_root                # path of Project Memory inside the repository (§5)
- default_execution_profile  # Project Execution Profile id + version (§8.2)
- policies                   # risk defaults, auditor independence, budgets, escalation contacts
```

- A ProjectTarget maps to exactly one broker workspace. The broker remains the
  authority for the accepted baseline (ADR-015).
- A WorkOrder records the accepted baseline it was **planned** against and the
  candidate it **executes** in (§6). If accepted state moves in between, that
  is baseline drift and is never silently absorbed (§10).

### 4.2 Candidate relationship

```text
accepted baseline B ──(create_candidate)──▶ candidate C (one per executing WorkOrder)
C accumulates CODE_APPROVED blocks, with code and memory together
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

**Where it lives:** inside the repository, under `memory_root`, as ordinary
tracked files. The proposed default is `.cloudeo/project/` (open question
Q1). Because it is Git-visible candidate state, it is:

- versioned with Git;
- part of the audited snapshot and its content hash (ADR-019 and ADR-020 trust
  boundary);
- promoted atomically with the code by the existing gate, with no second
  promotion mechanism.

**Claims carry evidence anchors.** Each memory entry is a claim that names
where it can be checked, such as paths, symbols, tests, or ADR numbers. Context
Intake and Memory Audit verify claims against those anchors. A claim without
anchors is reported as unverifiable, never assumed true.

**Update rule (ADR-023):**

1. Canonical Project Memory changes only through promotion, together with the
   code it describes.
2. Candidate memory may change only after the related block reaches
   `CODE_APPROVED`, and only within the candidate.
3. Every candidate memory change passes a Memory Audit before the block is
   done.
4. Memory never records intent as fact: planned, unverified, or rejected work
   is not written as existing architecture.

### 5.1 The distinct memories

| Memory | Holds | Lives | Authority |
| --- | --- | --- | --- |
| **Project Memory** | what exists in the project | in the repo; promoted with code | accepted project truth, after promotion |
| **WorkOrder Memory** | one WorkOrder's lifecycle, plan versions, decisions, evidence references, deviations, outcome | Cloudeo control store, append-only | the record of what was attempted and decided |
| **Performance Memory** | cross-project agent performance, cost, latency, failure and recovery patterns | Cloudeo control store (09) | advisory only (§13) |
| **LongHorizon round state** | the manager's rounds within one run | LongHorizon run ledger | within that run only (V2-E01) |

None of these substitutes for another. In particular, WorkOrder Memory is not
a competing truth store: accepted truth remains the broker's accepted commit
plus the Project Memory promoted in it (V2-E01, V2-D01).

---

## 6. WorkOrder

```text
WorkOrder
- id
- project_id
- objective                        # the user's words, kept verbatim
- planned_baseline                 # accepted commit the plan was made against
- candidate                        # workspace_id, candidate_id, base_commit (from PLAN_APPROVED)
- context_report_ref               # §7
- plan_versions[]                  # proposed plans, each immutable
- approved_plan                    # version id; defines the envelope (§9)
- acceptance_criteria[]            # from the approved plan
- risk_class
- budget                           # total cost/time, per-block attempts
- execution_profile                # Project Execution Profile id + version, snapshotted at approval
- implementation_blocks[]          # §8
- status                           # §6.1
- attention_requests[]             # §10
- evidence[]                       # references, never inlined prose as proof
- deviations[]                     # detected, and how each was resolved
- outcome                          # the ManagedPromotionResult / GatedPromotionResult of final verification
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
EXECUTING                        blocks in order (§8)
  ↓ all blocks done
FINAL_VERIFICATION               trust kernel (§12)
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
- `PROMOTED` is set only from a kernel result with `promoted == true`. No
  other signal, such as an executor's "done", LongHorizon `complete`, or
  `CODE_APPROVED`, can produce it.
- `ABORTED` never deletes evidence. Candidate cleanup policy is future work,
  as ADR-020 already notes.

---

## 7. Context Intake

**Purpose:** a read-only understanding of the project, relevant to the
objective, that the planner and the user can trust.

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

## 8. Plan, Implementation Blocks, and Roles

### 8.1 Plan proposal and the Plan Approval Gate (ADR-025)

The `architecture_planner` role proposes; the user decides.

```text
PlanProposal (immutable, versioned)
- objective (restated) and interpretation
- context report summary, including contradicted memory claims
- proposed architecture changes: components, interfaces, boundaries
- implementation_blocks[] (ordered)
- acceptance_criteria[] for the WorkOrder, including deterministic checks
- execution profile: role → AgentProfile, with approved fallbacks
- budget and risk class
- alternatives considered, known risks, open questions
- performance-memory recommendations, labelled as advisory (§13)
```

The user may approve, request changes (free-form), or reject. The approved
version becomes `approved_plan`. Any later change is a new plan version that
needs approval again. There is no execution, and no candidate write, before
approval.

### 8.2 Roles, Project Execution Profile, and AgentProfile (ADR-027)

**Roles** are what a step needs, independent of which model does it:

| Role | Workspace access | Notes |
| --- | --- | --- |
| `context_analyst` | read-only snapshot | Context Intake |
| `architecture_planner` | read-only snapshot | Plan proposals |
| `primary_code_executor` | candidate write (via bridge) | Implements blocks and memory updates |
| `code_auditor` | read-only snapshot | Independent block audit |
| `memory_auditor` | read-only snapshot | Verifies memory claims against code |
| `final_verifier` | read-only snapshot | Final audit against acceptance criteria (kernel) |
| `format_repair` | none | Syntax only; never verification authority (ADR-019 amendment) |
| `user_reporter` | none | Explains status and attention requests to the user |

Deterministic test execution is not an agent role. It is a deterministic step
of the coding loop.

**Project Execution Profile:** the user-approved, versioned mapping from each
role to exactly one primary AgentProfile, plus an ordered list of approved
fallbacks.

```text
ProjectExecutionProfile (versioned; each WorkOrder snapshots the version it was approved with)
- id, version
- role_bindings:
    architecture_planner  → <AgentProfile, e.g. "Astra 6" planner profile>
    primary_code_executor → <AgentProfile, e.g. "Opus 5.5" executor profile>
    code_auditor          → <AgentProfile, e.g. "GPT-5.6 Sol" auditor profile>
    …
  each with fallbacks[] (ordered, pre-approved)
- auditor_independence: session | model | provider   # minimum per risk class
```

Model names above are illustrative only.

**AgentProfile:** the exact, reproducible identity of one agent
configuration. It refines 07 §4.3 ExecutionProfile, and the existing
`HarnessExecutionProfile` is its runtime subset.

```text
AgentProfile (immutable once used; any change is a new version)
- id, version, version_fingerprint
- runtime: execution_class, harness_id, harness version if observable
- model: exact provider + model id (+ date/version if observable)
- reasoning: level / effort settings
- permissions: workspace_access (none | read_only_snapshot | candidate_write), network, tools
- eligible_roles[]            # checked against the role table; exact-type adapter rules still apply (roles.py)
- context_policy: which inputs it receives (memory sections, context report, prior audits) and size limits
- budget: per episode (time, steps, cost cap)
- limits: max attempts per block for this role
- fallbacks[]                 # suggestions only; usable only if also approved in the Project Execution Profile
```

**Rules:**

- Every role binding must be eligible: the AgentProfile's permissions must
  match the role's workspace access. The existing exact-type adapter
  eligibility (`roles.py`, ADR-018/019) remains the enforcement at execution
  time, and a mismatch fails closed.
- Auditor roles must meet the profile's `auditor_independence` minimum
  relative to the executor. A fresh session is always required (ADR-019).
  Model or provider diversity is required where the risk class demands it.
- Switching to an approved fallback is within the envelope; the switch and
  its reason are recorded. Anything else needs the user.

### 8.3 ImplementationBlock and the Coding Loop (ADR-026)

```text
ImplementationBlock
- id, order
- goal
- scope                     # declared paths/components it may change
- acceptance_checks[]       # deterministic tests/commands + audit criteria
- required_role             # usually primary_code_executor
- memory_impact             # which memory entries it is expected to change, if any
- attempt_budget
- status                    # below
- attempts[]                # each: agent profile, executor result, test results, normalized audit, deviations
```

Block state machine:

```text
PENDING
  ↓
IMPLEMENTING   primary_code_executor changes the candidate (bridge, ADR-017)
  ↓
TESTING        deterministic acceptance checks on the candidate
  ↓
AUDITING       code_auditor on a read-only snapshot → normalize_auditor_result()
  ├─ pass ────────────────▶ CODE_APPROVED
  └─ fail ─▶ FIXING ─▶ TESTING …   (within attempt_budget, same or approved fallback profile)
CODE_APPROVED
  ├─ memory_impact present ─▶ MEMORY_UPDATE ─▶ MEMORY_AUDIT ─┬─ pass ─▶ DONE
  │                                                          └─ fail ─▶ MEMORY_UPDATE (bounded)
  └─ none ───────────────────────────────────────────────────▶ DONE
Any state: attempts or budget exhausted, a material deviation, or a runtime
failure beyond the approved fallbacks ──▶ WorkOrder USER_ATTENTION_REQUIRED
```

**`CODE_APPROVED` means all of the following:**

1. every deterministic acceptance check passed on the exact candidate state;
2. the block audit normalized to **original `VERIFIED`**, never a repaired
   report (ADR-019 amendment);
3. the candidate diff since the previous block stays within the block's
   declared scope, or a deviation was approved by the user (§9);
4. the audited state is still the current candidate state. This is the same
   identity check the gate uses: content hash and `HEAD`.

`CODE_APPROVED` is candidate progress. It is **not** accepted state, and it
never calls `promote()`. The block's approved state may be recorded as a
candidate checkpoint through the broker. That is candidate history, not
acceptance (open question Q4).

---

## 9. The approved envelope and deviations

The **approved envelope** is everything the user approved:

- the plan version and its blocks and scopes;
- the proposed architecture;
- the acceptance criteria;
- the Project Execution Profile version, with its role bindings and approved
  fallbacks;
- the budget;
- the risk class.

**Within the envelope, without asking:**

- retrying a block within its attempt budget;
- switching to an approved fallback profile;
- recording minor, in-scope implementation choices;
- automatic recovery actions from 07 §11, and routing or Performance Memory
  suggestions, only when they stay inside the envelope.

**Material deviation, which always escalates:**

- changes outside a block's declared scope;
- a public interface or architecture change not in the approved plan;
- a new dependency or a pin change;
- a change to acceptance criteria or the removal of a check;
- an agent, model, or runtime not in the approved profile or fallbacks;
- budget overrun, or exhausted attempts;
- a memory change that contradicts the approved architecture;
- baseline drift, where accepted state moved;
- any auditor contract finding of `needs_revision` or `invalid`.

Detection is evidence-based. Scope and dependency checks are deterministic
diff checks against the declared scope. Contract findings come from the
normalized audit. Budget comes from accounting. An agent's own claim that it
stayed in scope is never evidence.

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
                      #      AGENT_UNAVAILABLE, AUDITOR_ERROR, AUDIT_NOT_VERIFIED,
                      #      MEMORY_CONFLICT, BASELINE_DRIFT, PROMOTION_REFUSED,
                      #      RISK_REQUIRES_HUMAN, PLAN_AMBIGUITY
    - severity        # blocking | warning
    - summary
    - evidence_refs[] # audits, test output, diffs, gate results, never bare prose
    - suggested_solutions[]   # each: action, parameters, rationale, expected effect, source
- conversation[]      # free-form discussion with the user_reporter role
- resolution          # UserDecision, once resolved
```

User actions:

| Action | Effect |
| --- | --- |
| `resume` | Continue in the same state, only if every blocking reason is resolved or explicitly waived by the user |
| `replan` | A new plan version, which needs approval again |
| `change_agent` | A new Project Execution Profile version for this WorkOrder, recorded as an approval |
| `change_budget` | An approved budget amendment |
| `defer` | Park the WorkOrder; rechecks run on resume (baseline, profile availability) |
| `abort` | End the WorkOrder; evidence and candidate are kept |

**Rules:**

- Every decision is recorded with actor, time, action, parameters, and the
  message.
- Suggested solutions are advisory. Their source may be Performance Memory,
  the recovery policy (07 §11), or an agent, and none is applied without the
  user's choice.
- The following states always raise attention; none may be silently retried
  or absorbed:
  - a kernel result of "not attempted" or "refused", including
    `refused_after_checkpoint`, where the kept checkpoint is shown as
    evidence;
  - an `AUDITOR_ERROR`;
  - baseline drift.

---

## 11. Memory Audit

After a block's `MEMORY_UPDATE`, the `memory_auditor` checks on a read-only
snapshot of the candidate:

- every changed or added claim is supported by its anchors in the candidate
  code;
- no claim describes planned or unapproved work as existing;
- no claim contradicts the approved architecture, unless a user-approved
  deviation covers it.

The result goes through the same normalization rules as any audit. Only
original `VERIFIED` passes. Final verification checks Project Memory
consistency again for the whole candidate.

---

## 12. Final verification and promotion

When every block is `DONE`:

1. The `final_verifier` audits the whole candidate against the WorkOrder's
   acceptance criteria and Project Memory consistency, on a read-only
   snapshot.
2. The result is normalized. Only original `VERIFIED` may proceed.
3. The trust kernel decides: `checkpoint_and_promote_verified()` (ADR-020),
   through the manager path (ADR-021) or a direct final audit (open question
   Q6). Either way the gate is the sole authority, and code and Project Memory
   advance together as one proven checkpoint.
4. `promoted` makes the WorkOrder `PROMOTED`. Any "not attempted" or
   "refused" result raises `USER_ATTENTION_REQUIRED`, with the kernel result
   as evidence.
5. Verified outcomes are then emitted to Performance Memory (§13).

---

## 13. Performance Memory (ADR-029)

Performance Memory keeps the design in 09 (schemas, version fingerprints,
cold start, learning stages). This contract bounds its authority:

- It is separate from Project Memory and WorkOrder Memory, and it is never
  written into the repository.
- It learns only from verified labels, per the 09 trusted-label rule. These
  include block audits, final verification, kernel outcomes, user decisions,
  cost, latency, failure classes, and recovery paths, keyed by the AgentProfile
  version fingerprint, the role, and the task class.
- It may **recommend**: in plan proposals, in attention requests, and when
  choosing among approved fallbacks.
- It may **never** change an approved Project Execution Profile, plan,
  budget, risk class, or auditor-independence policy, and never select an
  agent outside the approved envelope.
- Recommendations always show sample size and uncertainty (V2-H04, V2-H05).

---

## 14. Relationship to the implemented code

| This contract | Existing code or document |
| --- | --- |
| Accepted baseline, candidate | `WorkspaceBroker`, `CandidateWorkspace` (ADR-015) |
| `primary_code_executor` | `UHPWorkspaceExecutorAdapter` + bridge (ADR-017/018) |
| `code_auditor`, `memory_auditor`, `final_verifier`, `context_analyst` | `UHPWorkspaceAuditorAdapter` + audit transport (ADR-019), read-only snapshot |
| Audit verdicts | `normalize_auditor_result()` → `AuditorVerification` |
| Acceptance | `checkpoint_and_promote_verified()`; `run_managed_with_promotion_gate()` |
| Role eligibility | `roles.py` exact-type table (extended per role, not bypassed) |
| AgentProfile runtime subset | `HarnessExecutionProfile(harness_id, model, max_step)` |
| AgentProfile concept | 07 §4.3 ExecutionProfile (refined; AgentProfile is the canonical name) |
| Performance Memory | 09 |

New code will be needed for the control store, the state machines, the
Context Intake and planner roles, deterministic scope checks, and the
attention and decision records. None of it touches the kernel.

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
- **V2C-05:** executor completion, LongHorizon `complete`, and `CODE_APPROVED`
  never imply acceptance.
- **V2C-06:** `CODE_APPROVED` requires passing deterministic checks, an
  original `VERIFIED` audit of the exact current candidate state, and an
  in-scope diff or a user-approved deviation.
- **V2C-07:** a repaired audit never produces `CODE_APPROVED`, a memory-audit
  pass, or a final-verification pass.
- **V2C-08:** Project Memory lives in the repository and advances canonically
  only by promotion, together with code.
- **V2C-09:** candidate memory changes only after `CODE_APPROVED` and passes a
  Memory Audit.
- **V2C-10:** Context Intake is read-only and reports memory claims as
  verified, contradicted, or unverifiable, with evidence.
- **V2C-11:** every role binding uses an approved AgentProfile version eligible
  for that role. A mismatch fails closed.
- **V2C-12:** only approved fallbacks are used without the user. Every switch
  is recorded.
- **V2C-13:** auditor independence meets the profile's minimum, and a fresh
  session is always required.
- **V2C-14:** every material deviation (§9) raises `USER_ATTENTION_REQUIRED`
  and is never silently absorbed.
- **V2C-15:** an attention request lists all active reasons with evidence and
  suggested solutions. Resolution records the user's decision.
- **V2C-16:** kernel "not attempted" or "refused", `AUDITOR_ERROR`, and
  baseline drift always raise attention.
- **V2C-17:** Performance Memory cannot change approved policy or select
  outside the envelope. It learns only from verified labels.
- **V2C-18:** AgentProfiles are immutable once used, and every attempt records
  the exact version fingerprint.
- **V2C-19:** `ABORTED` and `DEFERRED` keep all evidence and the candidate.
- **V2C-20:** baseline drift between planning and execution, or between
  execution and final verification, is detected from the broker and never
  silently rebased.

---

## 16. Non-goals for this milestone

- any implementation;
- any change to the trust kernel, broker, bridge, adapters, gate, or LongHorizon;
- UI, HTTP API, or storage schemas beyond the invariants;
- Browser Use, Jev routing, and multi-executor optimization;
- a Performance Memory implementation;
- a cleanup or rejection policy for refused checkpoints.

---

## 17. Open questions for approval

- **Q1 — Project Memory location and format:** propose `.cloudeo/project/` as
  tracked Markdown with explicit claim and anchor blocks. The alternative is
  under `docs/`.
- **Q2 — Where the Project Execution Profile lives:** propose the Cloudeo
  control store, versioned and snapshotted per WorkOrder, because model
  choices are operational policy rather than project truth. The alternative is
  a tracked file in the repository.
- **Q3 — Coding-loop mechanism:** propose running each block as a bounded
  LongHorizon manager run in a verify-only mode, which has no promotion. That
  respects V2-E01 and reuses ADR-021, but needs a variant of the wrapper. The
  alternative is a Cloudeo-owned block loop over the same executor, auditor,
  and normalizer.
- **Q4 — Block checkpoints:** should `CODE_APPROVED` states be recorded as
  broker candidate checkpoints? They are candidate history, not acceptance.
  The gate already reuses an audited existing checkpoint (ADR-020).
- **Q5 — Default auditor independence per risk class:** for example, `session`
  for low risk, `model` for medium, and `provider` for high.
- **Q6 — Final verification path:** a direct final audit plus the gate, or a
  full manager run (ADR-021).
- **Q7 — Control store:** propose SQLite in the existing footprint (07 §10),
  holding WorkOrder Memory and Performance Memory in separate tables.
- **Q8 — Memory Audit profile:** reuse the `code_auditor` profile, or require
  a separate `memory_auditor` binding.
