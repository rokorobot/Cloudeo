# Cloudeo v2 — Dynamic Routing, Verification, and Performance Memory

**Status:** Design contract  
**Date:** 2026-09-22

## 1. Thesis

Cloudeo's differentiating loop is:

```text
context
  ->
valid candidates
  ->
route
  ->
execute
  ->
independently verify
  ->
record trusted outcome
  ->
improve future routing
```

The system is useful only if the learning signal represents actual task success rather than agent self-confidence.

## 2. Separation of concerns

### Router asks

> Which allowed strategy should attempt the next bounded step?

### Executor asks

> Can I perform this step?

### Verifier asks

> Did the environment actually reach the required state?

### Performance Memory asks

> What happened historically when profiles like this were used in contexts like this?

These roles must remain logically separate.

## 3. Candidate generation

Candidates come from facts, not model imagination.

Sources include:

- UHP harness discovery;
- UHP model availability;
- configured execution profiles;
- Treg capability catalog;
- configured browser profiles;
- recovery actions;
- operator/human gate.

Each candidate has an immutable ID for the decision.

Example:

```json
{
  "candidate_id": "profile:codex:cli-default:v3",
  "execution_class": "uhp_harness",
  "capabilities": ["cli", "filesystem", "git", "tests"],
  "writable": true,
  "estimated_cost_band": "medium",
  "available": true,
  "version_fingerprint": "..."
}
```

## 4. Constraint filter

Before scoring, eliminate invalid candidates.

Constraint categories:

```text
CAPABILITY
PERMISSION
AVAILABILITY
BUDGET
RISK
POLICY
WORKSPACE
VERSION_QUARANTINE
```

Every exclusion is recorded.

Example:

```json
{
  "candidate_id": "profile:hermes:research:v2",
  "excluded": true,
  "reason_code": "MISSING_CAPABILITY",
  "detail": "git_write required"
}
```

A model never gets the opportunity to resurrect an excluded candidate.

## 5. Routing policy stages

### Stage 1 — deterministic rules

Use deterministic selection when the answer is obvious.

Examples:

- exact typed Treg capability and no long-horizon state required;
- only one candidate satisfies required capabilities;
- policy forces a human gate;
- a profile is mandatory for a compliance reason.

### Stage 2 — Jev policy

Use Jev when several valid alternatives exist and a fast contextual choice is valuable.

Input should be compact and structured:

```text
step class
surface
risk
requirements
previous failure class
remaining budget
candidate profiles
verified historical features
```

Do not send arbitrary full run history unless an experiment proves it improves decisions.

### Stage 3 — escalation

For low confidence or high consequence:

- stronger reasoning policy;
- explicit operator choice;
- blocked.

## 6. Jev as an indexed policy engine

The Jev design should follow the same core safety pattern as an indexed browser action space:

```text
Cloudeo observes/discovers candidates
             |
             v
assign stable indices
             |
             v
Jev selects operation + candidate
             |
             v
Cloudeo validates selection
             |
             v
execute
```

Jev output is a routing decision, not arbitrary executable instructions.

## 7. Routing objectives

Do not optimize a single universal scalar prematurely.

Track at least:

- verified success probability;
- latency;
- cost;
- incomplete/budget-stop probability;
- recovery burden;
- human-intervention probability.

At first, policy can use explicit priorities:

```text
1. satisfy hard constraints
2. maximize evidence-supported verified success
3. respect cost/latency budget
4. prefer simpler/cheaper profile when evidence is materially equivalent
5. preserve exploration budget for under-tested profiles
```

The exact optimization formula should remain versioned policy, not buried in code.

## 8. Verification boundary

### 8.1 Runtime status

UHP/runtime statuses are execution facts:

```text
completed
failed
incomplete
cancelled
```

They are not acceptance verdicts.

### 8.2 Authoritative acceptance

A result becomes trusted only after:

```text
deterministic evidence
        +
workspace/artifact inspection
        +
independent Auditor where required
        +
human gate where policy requires
```

### 8.3 No self-verification

The same executor may report useful completion information, but its statement cannot alone advance `accepted_checkpoint`.

## 9. Verification strategy by task

### Code

Prefer:

- tests;
- typecheck/lint/build when applicable;
- diff/changed-file constraints;
- runtime probes;
- independent read-only audit.

### API/data task

Prefer:

- schema validation;
- expected-field checks;
- provider evidence;
- independent source/verification endpoint if the WorkOrder requires it.

### Browser task

Prefer:

- observed final page state;
- URL/state constraints;
- target values;
- independent readback;
- no assumption that policy `DONE` means success.

### Artifact task

Prefer:

- file exists;
- parseable format;
- content contract;
- render/visual inspection when needed;
- checksum/manifest.

## 10. Performance Memory schema

### execution_profiles

Identity and configuration of a routable option.

Key fields:

```text
id
execution_class
harness_base
harness_id
model
profile_config_hash
version_fingerprint
created_at
retired_at
```

### routing_decisions

```text
id
work_order_id
round_id
task_context_hash
policy_id
policy_version
candidate_set_json
selected_candidate_id
confidence
created_at
```

### execution_attempts

```text
id
routing_decision_id
execution_profile_id
runtime_status
started_at
ended_at
duration_ms
cost_value
cost_currency
runtime_response_id
runtime_session_id
output_ref
artifact_manifest_ref
error_class
```

### verification_outcomes

```text
id
execution_attempt_id
status
failure_class
auditor_profile_id
evidence_manifest_ref
accepted_checkpoint_before
accepted_checkpoint_after
created_at
```

### performance_events

Immutable denormalized learning records derived from attempts + verification.

### performance_aggregates

Cached statistics; always recomputable from immutable events.

## 11. Trusted-label rule

The following must be impossible:

```text
executor says "done"
    ->
performance event says verified_success=true
```

The only valid path is:

```text
executor/runtime result
    ->
verification outcome
    ->
verified event
```

## 12. Version fingerprints

Every performance event should include enough upstream identity to avoid mixing materially different systems.

At minimum:

```text
Cloudeo commit
routing policy version
UHP protocol version
HarnessRouter version/digest
LongHorizon commit/version
execution profile config hash
harness base version if observable
model ID
Jev policy/API version if observable
Treg version if used
```

If an upstream service does not expose a stable version, record the observed identity and timestamp honestly rather than inventing one.

## 13. Cold-start policy

Before sufficient data exists:

1. hard constraints;
2. manually declared profile preferences by task class;
3. deterministic fallback;
4. limited exploration;
5. no claim of "best harness."

Performance Memory begins as evidence collection.

## 14. Learning stages

### Stage A — counts and descriptive statistics

No model training.

Track:

- verified success ratio;
- failure distribution;
- median duration;
- cost;
- sample count.

### Stage B — context buckets

Example buckets:

```text
task_class x surface x language_stack x risk_class
```

Use minimum sample thresholds.

### Stage C — probabilistic/contextual routing

Only after enough verified events exist.

Possible methods:

- Bayesian/Beta success estimates;
- contextual bandit;
- calibrated classifier;
- Jev with Performance Memory features.

Do not choose an algorithm before data volume and feature quality are measured.

## 15. Exploration

A router that always chooses the current winner can stop learning.

Introduce an explicit exploration policy later:

```text
exploration_budget
minimum_samples_per_candidate
max_regret/risk allowance
excluded high-risk task classes
```

Never experiment on high-risk WorkOrders unless policy explicitly permits it.

## 16. Recovery learning

Recovery choices are also routable actions.

Performance Memory should answer questions such as:

- after `budget_incomplete`, does retrying the same profile usually work?
- after two regression failures, does switching harness improve success?
- when does decomposition outperform increasing budget?
- which profiles are good auditors versus executors?

This is more valuable than a single global harness ranking.

## 17. Evaluation protocol

Every policy change should be evaluated by replay where possible.

Minimum comparison:

```text
baseline policy
candidate policy
same historical contexts
same recorded candidate sets
same ground-truth verification outcomes
```

Online evaluation follows only after offline replay is sane.

## 18. Initial policy recommendation

For the first v2 implementation:

```text
hard filters
  ->
deterministic task-class rules
  ->
Jev only for ambiguous valid choices
  ->
human/strong-reasoning escalation
```

Do not start with a self-training router.

First collect trustworthy labels.
