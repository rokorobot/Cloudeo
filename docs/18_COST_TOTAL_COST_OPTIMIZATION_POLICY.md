# ADR-033 — COST: Total-Cost Optimization Policy

**Status:** Accepted (2026-10-01); policy architecture only, not yet implemented.

**Decision record:** ADR-033 in `02_DECISIONS.md`, which is normative. This
document is the detailed supporting architecture (rationale, diagrams, and
examples). Where the two differ, the decision record governs.

**Amended:** 2026-10-01, before acceptance. COST never selects, switches, or
reorders execution profiles for an active WorkOrder (see §10, §12, §26, §42,
§47, COST-03, and §58).

## Decision

Cloudeo introduces **COST** as the policy layer responsible for economic
optimization of already-permitted execution choices.

Its objective is:

> **Minimize expected total cost per successfully verified WorkOrder, subject to
> approved quality, safety, independence, latency, budget and policy
> constraints.**

COST is not a model router, not a cloud scheduler, and not an authority over
WorkOrder state.

It evaluates the economics of allowed choices using observed evidence from:

- model/runtime execution;
- Session Fabric;
- Cloud Execution Fabric;
- CI;
- provider/API usage;
- retries;
- evaluation systems;
- human intervention;
- historical Performance Memory.

COST may recommend or select among choices that are already permitted by the
approved envelope and execution policy.

COST never selects, switches, or reorders execution profiles for an active
WorkOrder (see §12).

It may not:

- weaken safety or verification requirements;
- bypass independence rules;
- alter a Project Execution Profile;
- introduce an unapproved provider/model/runtime;
- mutate WorkOrder state directly;
- grant human approval;
- bypass the trust kernel;
- trade away required correctness for a lower nominal price.

---

## 1. Why COST exists

A coding-agent system can waste money in many different places even when its
LLM choice appears cheap.

For one WorkOrder, the true cost may include:

```text
model inference
+ subscription allocation
+ Session runtime
+ cloud VM runtime
+ CI minutes
+ build/deploy resources
+ external APIs
+ storage/network
+ retries
+ model evaluations
+ context reconstruction
+ human intervention
```

Optimizing only:

```text
$/1M tokens
```

or:

```text
VM $/minute
```

can therefore produce a more expensive system overall.

The economically relevant outcome is:

```text
total cost
──────────────────────────────
successfully verified WorkOrders
```

not the cheapest individual resource.

---

## 2. Authority boundary

COST is subordinate to Control.

Conceptually:

```text
               approved policy
                     │
                     ▼
             cloudeo.control
                     │
          eligible execution set
                     │
                     ▼
                    COST
                     │
       economic choice / recommendation
                     │
                     ▼
             cloudeo.orchestration
                     │
                     ▼
                execution
```

COST may choose only from the eligible set supplied by policy.

If the cheapest option violates:

```text
quality threshold
risk class
auditor independence
approved role binding
latency requirement
budget rule
security rule
provider policy
```

it is not eligible.

---

## 3. Relationship to prior ADRs

COST extends but does not supersede:

- ADR-022 — V2 control layer remains the workflow authority;
- ADR-025 — the approved envelope constrains execution;
- ADR-026 — WorkOrder and block state remain control-owned;
- ADR-027 — role bindings, primary profiles, fallbacks and independence;
- ADR-028 — policy exhaustion escalates to `USER_ATTENTION_REQUIRED`;
- ADR-029 — Performance Memory is advisory and evidence-based, and its bound
  on selecting or switching profiles applies to COST;
- ADR-030 — orchestration may gather evidence but not own WorkOrder state;
- ADR-031 — Session Fabric exposes runtime and cost observations;
- ADR-032 — Cloud Execution Fabric exposes runtime class, duration, provenance
  and infrastructure-cost evidence.

COST consumes evidence from those layers.

It does not replace them.

---

## 4. Core objective

For an eligible execution strategy `s`, define conceptually:

```text
ExpectedVerifiedCost(s)
    =
ExpectedTotalCost(s)
──────────────────────────────
ProbabilityOfVerifiedSuccess(s)
```

This is an explanatory model, not a mandate to use one literal formula in all
cases.

The actual optimization target is:

```text
minimize expected total cost
per successfully verified WorkOrder
```

subject to hard constraints.

A cheaper option with a much lower verified-success probability may therefore
be worse than a more expensive option that succeeds reliably.

---

## 5. Hard constraints vs optimization criteria

COST must distinguish:

### Hard constraints

These cannot be traded away for savings:

```text
approved envelope
security policy
required tests
verification requirements
promotion rules
auditor independence
risk-class requirements
provider restrictions
explicit user decisions
maximum latency/SLA when mandatory
data residency where required
credential/security boundaries
```

### Optimization criteria

These may be compared after hard constraints are satisfied:

```text
expected cost
latency
throughput
context-reuse benefit
VM utilization
CI usage
provider usage
retry probability
human-attention probability
```

COST never converts a hard constraint into a weighted preference.

---

## 6. Total cost model

The conceptual total cost of a WorkOrder is:

```text
TotalWorkOrderCost =
    InferenceCost
  + SubscriptionAllocatedCost
  + SessionRuntimeCost
  + CloudRuntimeCost
  + CICost
  + ExternalAPICost
  + StorageCost
  + NetworkCost
  + RetryCost
  + EvaluationCost
  + ContextReconstructionCost
  + HumanAttentionCost
  + OtherObservedDirectCost
```

Not every term must be available initially.

Unknown components remain unknown.

COST must not silently replace missing actual cost with an invented value.

---

## 7. Inference cost

For API-metered inference, COST should record where available:

```text
provider
model
input tokens
output tokens
cached tokens if applicable
reasoning tokens if exposed
provider-reported cost
list-price estimate
billing route
```

The preferred evidence order is:

```text
actual provider-reported charge
    ↓
actual OpenRouter/router charge
    ↓
current provider price calculation
    ↓
unknown
```

Estimated list price must be labeled as an estimate.

---

## 8. Subscription-aware economics

Subscription-authenticated coding environments may not have a useful marginal
token price.

Examples may include:

```text
Claude subscription CLI usage
Codex subscription-authenticated usage
other fixed-price or quota-based agent services
```

COST must distinguish:

```text
marginal API cost
```

from:

```text
fixed subscription cost
```

and:

```text
capacity / rate-limit scarcity
```

A subscription route may therefore carry:

```text
monthly_fixed_cost
included_or_practical_capacity
current_usage_pressure
rate_limit_pressure
allocated_cost_method
```

The marginal cash cost of one additional task may be near zero while capacity
is available, but the route is not economically free if it consumes scarce
quota needed for higher-value work.

---

## 9. Subscription allocation is accounting, not provider truth

Cloudeo may allocate a subscription's fixed monthly cost across successful
WorkOrders for internal economics.

Possible methods include:

```text
per active hour
per successful WorkOrder
per weighted token-equivalent
per role-specific usage
```

The allocation method must be explicit and versioned.

Allocated subscription cost is an internal accounting view.

It must not be presented as a provider invoice.

---

## 10. Direct provider vs router economics

Production execution may use:

```text
Anthropic direct
OpenAI direct
Moonshot direct
other direct providers
OpenRouter
subscription-authenticated CLI routes
```

Evaluation may use a router without requiring production to use the same route.

COST must therefore distinguish:

```text
model
```

from:

```text
billing / routing path
```

Example:

```text
same model
├── direct provider
├── OpenRouter shared provider path
└── OpenRouter BYOK
```

These may differ in:

```text
price
latency
availability
provider identity
fallback behavior
observability
```

COST may compare them only when all are allowed by policy.

A billing/routing path is profile data (ADR-035). Moving an active WorkOrder
to a different path is therefore a profile change and follows §12.

---

## 11. Model choice is role-specific

There is no globally cheapest "best model."

COST evaluates models within a role/task context.

Examples:

```text
architecture_planner
primary_code_executor
code_auditor
memory_curator
memory_auditor
final_verifier
user_reporter
```

A model suitable for routine documentation may not be suitable for
high-risk independent verification.

COST therefore uses evidence keyed by at least:

```text
role
task class
profile fingerprint
model/provider
runtime environment fingerprint
risk class
```

where available.

---

## 12. Project Execution Profile remains authoritative

ADR-027 remains binding.

COST does not autonomously replace:

```text
role → primary profile
```

with a cheaper model.

Normal execution remains:

```text
approved primary
      ↓
approved fallback condition?
      ↓ yes
approved ordered fallback
```

COST is bound exactly as Performance Memory is (ADR-029). It may never select,
switch, or reorder execution profiles for an active WorkOrder, including among
approved fallbacks, because it predicts lower cost or better performance.

COST may:

- calculate costs, compare alternatives, and rank them analytically;
- recommend a revised primary or fallback ordering, with sample size and
  uncertainty;
- provide evidence for `change_agent`;
- choose automatically among explicitly permitted equivalent resources that
  are not execution profiles, such as an approved runtime class, reuse of an
  eligible Session, or an approved equivalent CI runtime.

An active WorkOrder keeps using the immutable primary and fallback ordering of
its snapshotted Project Execution Profile. A fallback is used only under its
approved fallback condition and only in that order. COST's analysis neither
triggers a fallback nor changes which one is next.

A COST recommendation affects execution only through one of two paths:

1. a user-approved Project Execution Profile revision, which reaches an active
   WorkOrder only through `change_agent` and a user-approved envelope
   amendment (ADR-028);
2. an explicit, pre-approved, deterministic policy in the approved profile or
   envelope. Its trigger is an observed, classified condition, and it makes no
   runtime performance-based profile-selection decision.

COST may not add a new model/provider/profile.

---

## 13. Performance Memory provides empirical evidence

Performance Memory should retain verified economic observations keyed by
relevant context.

Examples:

```text
role
task class
profile fingerprint
runtime environment fingerprint
fabric provider
runtime class
verified outcome
latency
retries
inference cost
VM cost
CI cost
human intervention
```

COST prefers observed project-specific evidence over generic benchmark
assumptions when the sample is sufficient.

Small samples must retain uncertainty.

---

## 14. Ori/OpenRouter as an evaluation backend

Ori Eval may be used as one model-evaluation backend.

Its role is:

```text
controlled experiment
      ↓
candidate-model evidence
      ↓
Performance Memory
      ↓
COST analysis
      ↓
recommendation
```

Ori/OpenRouter is not required for ordinary Cloudeo production execution.

A model evaluated through OpenRouter may later be run directly through its
provider if policy and economics favor that route.

Evaluation tooling is therefore evidence infrastructure, not production
authority.

---

## 15. Evaluation must have positive expected value

COST should not benchmark every new model automatically.

Before a significant evaluation, estimate conceptually:

```text
ExpectedEvalValue =
    ExpectedFutureWorkload
  × ExpectedImprovementPerTask
  - EvaluationCost
  - MigrationCost
  - OperationalRiskCost
```

If expected value is too low, keep the current approved profile.

For example:

```text
evaluation costs $20
expected saving = $0.04 / verified task

break-even ≈ 500 tasks
```

If only 50 similar tasks are expected, the evaluation is unlikely to be worth
running.

This is a policy heuristic, not a guaranteed monetary forecast.

---

## 16. Evaluation cadence

Default policy should avoid full model bake-offs on every code push.

Suggested classes:

### Small regression eval

Triggered only when relevant agent behavior, prompt, tool or harness logic
changes.

Typical scope:

```text
few high-value cases
current approved model/profile
small deterministic regression suite
```

### Model-comparison eval

Triggered by:

```text
important new model
scheduled review
material cost shift
quality regression
provider availability change
explicit human request
```

Typical scope:

```text
small candidate screen
    ↓
top candidates
    ↓
larger confirmation run
```

The exact cadence belongs to configuration.

---

## 17. Reproducible evaluation environments

Model comparisons should pin as much as practical:

```text
same WorkOrder/task set
same repository commit
same harness
same prompts
same tools
same effort/budget
same runtime environment image/version
same VM/runtime class
same network assumptions where practical
```

Then vary only the intended variable, such as:

```text
model
```

This makes the resulting evidence more interpretable.

ADR-032 runtime-environment provenance supports this.

---

## 18. Cloud runtime right-sizing

COST may compare approved runtime classes.

Example candidates:

```text
burstable/shared worker
standard-2
standard-4
future larger instance
future GPU runtime
```

The target metric is not:

```text
cheapest VM per minute
```

but:

```text
expected infrastructure cost
per successfully verified task
```

A more expensive VM may be cheaper overall if it materially reduces:

```text
build time
test time
agent idle time
timeout risk
retry rate
```

---

## 19. Ephemeral workers by default

ADR-032's default is:

```text
create
  ↓
execute
  ↓
destroy
```

COST should treat unnecessary idle VM lifetime as cost leakage.

The system should measure:

```text
provisioning time
active execution time
idle time
handover time
cleanup time
```

This enables future decisions about whether a warm pool is economically
justified.

---

## 20. Warm-pool decisions require evidence

A standing worker pool may reduce startup latency but introduces fixed cost.

COST may recommend a warm pool only when observed evidence shows:

```text
saved startup latency/value
>
idle capacity cost + operational complexity
```

Warm pools are not the default.

Any warm-pool policy must preserve isolation, secret handling and workspace
authority.

---

## 21. Session reuse

ADR-031 allows session reuse where policy permits.

COST may consider:

```text
reuse eligible existing Session
vs
start new Session
```

Potential savings include:

```text
reduced context reconstruction
reduced model tokens
reduced VM startup
reduced tool bootstrap
reduced handover cost
```

Potential risks include:

```text
stale context
role contamination
independence violation
workspace mismatch
security scope mismatch
```

Reuse is allowed only if those policy constraints remain satisfied.

---

## 22. Context reconstruction is a real cost

Starting a fresh session often consumes substantial tokens and wall-clock time
to rediscover:

```text
project architecture
recent decisions
current WorkOrder state
repository structure
previous findings
```

COST should treat avoidable reconstruction as economic waste.

Possible mitigations include:

```text
durable Coordination Store
structured handover
Project Memory
short-lived overlapping Sessions
reusable runtime environment
```

However, preserving stale or unsafe context is not automatically cheaper.

---

## 23. Overlapping handover

Keeping a predecessor Session alive briefly while a successor starts may save
more than it costs.

Conceptually:

```text
old Session
   │
   ├── durable handover
   └── short clarification window
             │
             ▼
        new Session
```

COST may compare:

```text
extra runtime/inference during overlap
```

against:

```text
avoided reconstruction and error/retry cost
```

Handover may never transfer write authority in violation of ADR-031.

---

## 24. Parallelism is not automatically cheaper

COST must not assume that more workers means better economics.

Compare:

```text
1 worker × 40 minutes
```

with:

```text
4 workers × 15 minutes
```

using:

```text
total inference
total VM runtime
coordination overhead
duplicate work
merge/reconciliation work
verified outcome
latency value
```

Parallelism should be used where the expected value justifies the multiplied
resource consumption.

---

## 25. Single mutable writer reduces economic waste

ADR-031's initial one-write-capable-Session-per-CandidateWorkspace invariant is
also an economic safeguard.

It reduces:

```text
conflicting edits
duplicate changes
retests
merge repair
context divergence
wasted CI
```

COST must not override this invariant merely to gain parallelism.

---

## 26. Retry policy is economic policy too

Blind retry is expensive.

COST should consume failure classification from orchestration/control.

Examples:

```text
provider transient failure
deterministic validation failure
audit failure
baseline drift
unknown runtime state
budget exhaustion
environment bootstrap failure
```

The economic options differ:

```text
retry same route
use approved fallback
change runtime class
stop and escalate
```

A retry should occur only where policy permits it and where expected value is
positive.

A fallback is used only under its approved fallback condition and in the
snapshotted order (§12).

---

## 27. Repeating deterministic failure is usually waste

If evidence indicates a deterministic failure is likely to recur unchanged,
COST should not recommend identical retries.

Examples:

```text
invalid input
missing required credential
policy prohibition
failed deterministic test
unsupported architecture
known environment incompatibility
```

The correct action may be:

```text
fix prerequisite
replan
use approved alternative
USER_ATTENTION_REQUIRED
```

rather than paying for another identical attempt.

---

## 28. CI is part of TotalWorkOrderCost

GitHub Actions and other CI execution contribute to WorkOrder economics.

COST should track:

```text
workflow runs attributable to WorkOrder/PR
job runtime
runner class
duplicate/stale runs
cache hit/miss
build repetition
```

CI is not free merely because it is external to the agent runtime.

---

## 29. Agent push discipline

The default development policy should be:

> **Use local validation as the inner loop. Use remote CI as a validation gate,
> not as the agent's debugger.**

Agents may commit locally as often as useful.

Remote pushes should occur at meaningful validation points.

This reduces duplicate CI work and unnecessary deployment/watcher activity.

---

## 30. Avoid duplicate CI triggers

Where the repository topology allows it, avoid executing the same expensive
validation twice through overlapping triggers.

Typical separation:

```text
PR validation:
  pull_request

main/release:
  push to main/tags
```

Required-check behavior must remain correct.

COST optimization must not remove a required validation signal.

---

## 31. Cancel stale PR CI, never active main validation by default

Superseded PR runs should normally be cancelled when a newer commit makes
their result obsolete.

Main/release validation should not be blindly cancelled by the next push.

The precise workflow implementation belongs to the repository, but the
economic principle is:

```text
obsolete speculative validation → stop
authoritative main/release validation → preserve
```

---

## 32. Fail fast and cheap

CI and agent validation should order work so that cheap, high-signal checks run
before expensive checks.

Typical order:

```text
format
  ↓
lint
  ↓
typecheck/static analysis
  ↓
unit tests
  ↓
integration
  ↓
E2E
  ↓
large build/image
  ↓
deploy
```

The exact order depends on the project.

The principle is to avoid starting expensive work that cannot succeed because a
cheap prerequisite already failed.

---

## 33. Build once, reuse artifacts

Repeated compilation/image construction inside one validation run is economic
waste when the result can safely be reused.

Preferred pattern:

```text
build once
    │
    ▼
immutable artifact/image
   ├── tests
   ├── E2E
   └── deploy
```

The artifact must remain trustworthy for every consumer.

COST must not encourage unsafe artifact reuse across incompatible contexts.

---

## 34. Cache only stable things

Caching can reduce:

```text
package installation
toolchain setup
build work
Docker layers
dependency downloads
```

but incorrect caches can produce stale or misleading validation.

Caches should use stable, explicit keys such as:

```text
lockfile fingerprint
toolchain version
runtime environment fingerprint
architecture
```

COST prioritizes correct caching over maximal cache hit rate.

---

## 35. CI job fragmentation has a cost

Splitting workflows can improve fail-fast behavior, but too many tiny jobs may
increase billing and orchestration overhead.

COST should consider:

```text
minimum billing unit
startup overhead
artifact transfer
runner provisioning
parallelism
```

when evaluating job structure.

The goal is neither one giant job nor maximal fragmentation.

---

## 36. Runner selection

COST may compare allowed CI runner providers and classes using:

```text
price
wall-clock duration
cache performance
queue delay
failure rate
architecture compatibility
operational dependency risk
```

The relevant measure is:

```text
cost per green authoritative validation
```

not only advertised price per minute.

Changing runner provider must not weaken required checks.

---

## 37. ARM requires measurement

A lower ARM unit price is not sufficient evidence of savings.

COST should require comparative measurements covering:

```text
build/test duration
native dependency compatibility
emulation overhead
cache behavior
verified success
total cost
```

before preferring ARM for a workload.

---

## 38. Self-hosted infrastructure is not automatically cheaper

Directly operating bare metal or self-hosted runners can reduce metered
compute cost but adds:

```text
patching
runner lifecycle
disk cleanup
security
isolation
capacity planning
human operations
```

COST must include operational/human cost where material.

The cheapest cloud invoice is not necessarily the cheapest system.

---

## 39. Human attention is a cost signal

Human intervention is often more expensive than compute.

COST should count or estimate events such as:

```text
manual approval
manual debugging
manual conflict repair
manual provider recovery
manual rerun
manual environment repair
manual review beyond normal policy
```

The value may initially be represented as:

```text
count
duration estimate
severity class
```

rather than a monetary conversion.

Monetization is optional.

---

## 40. Human attention must not be optimized away unsafely

Some human decisions are mandatory governance boundaries.

Examples:

```text
approved plan
material deviation approval
change_agent
change_budget
risk waiver
promotion-related explicit decision where required
```

COST may reduce avoidable human friction.

It may not bypass required human decisions because they are expensive.

---

## 41. Latency has economic value

For some WorkOrders, completion time matters materially.

COST may optimize a constrained objective such as:

```text
lowest expected cost
subject to completion ≤ SLA
```

or:

```text
lowest expected cost + latency penalty
```

only where the project policy defines such a latency requirement.

Latency should not be converted into money by an undocumented formula.

---

## 42. Budget semantics

The approved WorkOrder envelope may define:

```text
hard maximum cost
soft target cost
per-attempt budget
total WorkOrder budget
evaluation budget
```

COST must distinguish hard caps from targets.

Approaching a hard cap should trigger:

```text
cheaper eligible choice that is not a profile change
approved fallback under its approved fallback condition
stop/escalate
```

as policy permits.

Exceeding a hard cap without explicit authority is forbidden.

---

## 43. Forecast uncertainty

Cost optimization uses uncertain predictions.

COST must preserve uncertainty where evidence is weak.

For example:

```text
candidate A:
estimated verified cost = $0.42
sample size = 8

candidate B:
estimated verified cost = $0.47
sample size = 400
```

A tiny apparent advantage from eight observations must not be treated as
certain.

Performance Memory should retain:

```text
sample size
variance / spread where available
time window
environment/profile fingerprint
```

---

## 44. Evidence freshness

Economic evidence can become stale because of:

```text
model updates
provider price changes
runtime image changes
CI changes
repository growth
new toolchain versions
provider performance changes
subscription-plan changes
```

COST should discount or invalidate evidence when its relevant fingerprint no
longer matches.

Old evidence may remain historically useful but must not silently represent
current economics.

---

## 45. Cost provenance

Every material cost observation should indicate its source where practical.

Examples:

```text
provider invoice/usage API
OpenRouter reported charge
cloud-provider runtime record
CI-provider runtime
calculated list-price estimate
subscription allocation
human estimate
```

This permits audit and prevents mixing actual charges with estimates.

---

## 46. COST decision record

When COST makes a non-trivial allowed selection, record:

```text
decision_id
workorder_id
role/task class

eligible choices
chosen choice
hard constraints applied

expected cost
expected verified-success evidence
expected latency
evidence references
uncertainty

reason
timestamp
COST policy version
```

This makes economic routing explainable.

---

## 47. Recommendation vs automatic selection

COST has two modes.

### Automatic selection

Allowed only when:

```text
all candidates are already policy-eligible
the decision does not amend the approved envelope
the choice stays within approved role/profile/fallback semantics
the choice is not between execution profiles and does not change their order
```

Examples may include:

```text
approved VM class A vs B
reuse eligible Session vs create fresh Session
approved equivalent CI runtime
```

### Recommendation

Required when the cheaper/better choice would require:

```text
new model
new provider
Project Execution Profile change
different primary or fallback ordering
risk-policy change
budget change
independence change
new production routing path
```

The recommendation then enters the existing human/control decision path.

---

## 48. COST cannot self-amend

COST may not rewrite:

```text
its own hard constraints
its own policy weights
Project Execution Profile
approved budgets
risk class
independence requirements
```

because its historical data suggests doing so.

Such changes require explicit policy evolution through the normal decision
process.

---

## 49. No optimization against unverified success labels

Performance Memory and COST must not learn "success" from:

```text
agent said done
runtime completed
tests partially passed
PR was created
provider returned 200
```

The preferred positive label is a verified outcome appropriate to the workflow,
ultimately including promoted/accepted outcomes where relevant.

This prevents the optimizer from learning to favor cheap but unreliable agents.

---

## 50. Objective hierarchy

COST should apply the following hierarchy:

```text
1. obey hard policy/security/safety constraints
2. preserve required verification and independence
3. satisfy mandatory latency/SLA requirements
4. stay within approved budget
5. minimize expected total cost per verified WorkOrder
6. where cost is materially tied, prefer lower operational complexity
```

A lower-priority objective never overrides a higher-priority one.

---

## 51. Initial implementation scope

The first COST implementation should be intentionally conservative.

Initial inputs:

```text
model/provider usage
Session duration
Cloud runtime duration/class
provider-reported or estimated inference cost
VM cost
retry count
verified outcome
basic CI attribution where available
```

Initial actions:

```text
report economics
compare eligible runtime classes
compare reuse vs new Session
recommend, but do not autonomously change, model/profile bindings
```

No sophisticated learning system is required initially.

---

## 52. Initial calculations

The first implementation may expose:

```text
cost_per_attempt
cost_per_successful_attempt
cost_per_verified_WorkOrder
retry_cost
inference_share
runtime_share
CI_share
evaluation_share
human_attention_count
```

Unknown components should remain separate rather than being coerced to zero.

For example:

```text
known_total_cost = $0.81
unknown_components = [human_attention, network]
```

is preferable to claiming:

```text
total_cost = $0.81
```

without qualification.

---

## 53. Initial runtime-class comparison

For an approved pair of runtime classes, COST may compare:

```text
class A:
  mean runtime
  mean VM cost
  timeout rate
  verified success

class B:
  mean runtime
  mean VM cost
  timeout rate
  verified success
```

Recommendation is based on verified economics, not nominal instance price.

---

## 54. Initial Session-reuse comparison

For eligible Sessions, COST may compare:

```text
reuse:
  expected context savings
  expected extra runtime
  contamination risk
  policy eligibility

new:
  bootstrap cost
  context reconstruction cost
  VM/session startup cost
```

Policy eligibility is checked before economics.

---

## 55. Initial CI economics

COST should first surface waste rather than automatically rewrite workflows.

Examples:

```text
duplicate PR validation detected
stale runs not cancelled
same build repeated 3 times
cache hit rate poor
expensive job starts before cheap gate
agent pushes causing repeated full CI
```

The output is a recommendation or repository-specific improvement proposal.

---

## 56. Initial evaluation economics

Before running a large model evaluation, COST should require:

```text
question to answer
candidate set
task set
expected evaluation cost
expected future workload
decision threshold
```

After evaluation, store:

```text
actual evaluation cost
candidate performance
candidate cost
confidence/sample size
recommended action
```

---

## 57. Architecture checks

The implementation should mechanically enforce where practical:

### COST-01 — no control mutation

COST must not mutate WorkOrder state directly.

### COST-02 — eligible-set discipline

Automatic choices must be drawn only from options already permitted by
control/policy.

### COST-03 — no profile mutation

COST must not directly change Project Execution Profile bindings, and must not
select, switch, or reorder profiles or fallbacks for an active WorkOrder.

### COST-04 — no independence weakening

Economic optimization must not weaken ADR-027 independence requirements.

### COST-05 — no verification weakening

COST must not remove or downgrade required verification to save resources.

### COST-06 — actual vs estimated cost

Actual provider charges and estimated/list-price costs must remain
distinguishable.

### COST-07 — unknown is not zero

Missing cost evidence must not be silently treated as zero.

### COST-08 — subscription-aware accounting

Subscription routes must not be compared to metered APIs solely through list
token prices.

### COST-09 — evidence fingerprinting

Economic evidence must retain enough context/fingerprints to detect when it is
no longer comparable.

### COST-10 — no unverified training labels

COST/Performance Memory must not learn positive outcome quality solely from
runtime completion or agent self-report.

### COST-11 — explainability

Non-trivial automated selections must produce a durable decision record.

### COST-12 — hard constraints dominate

No economic score may override a hard policy constraint.

---

## 58. Implementation sequence

After ADR-033 is accepted, implementation should proceed in bounded slices:

1. **Economics schema**
   - cost observation types;
   - source/provenance;
   - known vs estimated vs allocated cost;
   - verified outcome linkage.

2. **Aggregation**
   - attempt cost;
   - WorkOrder cost;
   - role/task statistics;
   - runtime/inference/CI attribution.

3. **Reporting only**
   - Mission Control economics;
   - no automatic choices.

4. **Approved runtime-class optimization**
   - compare already-eligible VM/runtime classes.

5. **Session reuse economics**
   - reuse vs fresh Session where ADR-031 allows both.

6. **CI waste detection**
   - duplicate runs;
   - stale runs;
   - repeated builds;
   - agent push multiplication.

7. **Evaluation economics**
   - expected-value gate for Ori/other model comparisons.

8. **Policy-bounded automatic selection**
   - among non-profile choices only;
   - only after evidence quality and architecture checks are mature.

9. **Performance Memory integration**
   - uncertainty;
   - freshness;
   - fingerprint-aware historical evidence.

Each slice must preserve the authority boundaries above.

---

## 59. Explicit non-goals

ADR-033 does not define:

- a universal cheapest model;
- unrestricted autonomous model routing;
- autonomous Project Execution Profile changes;
- autonomous risk-policy changes;
- autonomous budget increases;
- removal of verification to reduce cost;
- removal of required human approvals;
- a universal monetary value for human attention;
- one mandatory cloud provider;
- one mandatory evaluation backend;
- one mandatory CI provider;
- a requirement to use OpenRouter in production;
- a requirement to use Ori Eval;
- a requirement to use subscription-authenticated execution;
- speculative financial forecasting.

---

## 60. Consequence

Cloudeo gains a unified economic policy that can reason across model,
infrastructure, Session, CI and evaluation costs without allowing economics to
become workflow authority.

The intended architecture becomes:

```text
                         HUMAN
                           │
                    Cloudeo Control
                           │
                 approved eligible set
                           │
                           ▼
                          COST
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
       models           Sessions         runtime
   direct/router      reuse/new       VM class/fabric
          │                │                │
          └────────────────┼────────────────┘
                           │
                           ▼
                    orchestration
                           │
                           ▼
                       execution
                           │
                           ▼
                   verified evidence
                           │
                           ▼
                 Performance Memory
                           │
                           └──────► COST
```

For models and routes, COST's output in this diagram is a recommendation
(§12, §47). Automatic selection applies only to non-profile choices.

The central rule is:

> **COST minimizes expected total cost per successfully verified WorkOrder,
> never the cheapest isolated resource.**

And:

> **Economics may optimize within approved policy; economics may not redefine
> the policy.**

