# Cloudeo Roadmap

## Current version

```text
v0.1.1
```

Current capability:

```text
manual objective + manual candidates
    ↓
Jev routing
    ↓
Treg execution
    ↓
deterministic validation
    ↓
Jev verification if inconclusive
    ↓
pass / retry / escalate
```

---

## v0.1.2 — Automatic Treg discovery

### Goal

Remove manual candidate construction from `POST /v1/runs`.

Target input:

```json
{
  "objective": "Find the verified professional email for Erol Toker at trykitt.ai",
  "state": {
    "person": "Erol Toker",
    "company_domain": "trykitt.ai"
  }
}
```

Target pipeline:

```text
objective
  ↓
capability inference
  ↓
Treg catalog search
  ↓
load matching endpoints
  ↓
filter by available inputs
  ↓
normalize provider metadata
  ↓
Jev chooses candidate
  ↓
execute
```

### Required work

- Treg catalog discovery adapter
- catalog result parser
- endpoint schema loader
- capability normalization
- input compatibility filtering
- provider metadata model
- candidate generation
- cost/latency/hit-rate fields
- discovery audit trail
- tests

### Exit criteria

A user can request a work email without naming TryKitt, Tomba, Hunter, or another provider.

---

## v0.2 — Reasoning escalation

### Goal

Add frontier-LLM escalation for cases where:

- Jev confidence is below routing threshold
- deterministic validation is inconclusive
- Jev verification remains ambiguous
- providers disagree
- recovery requires planning

### Requirements

- `ReasoningProvider` adapter
- model routing policy
- bounded token/cost budget
- structured reasoning result
- post-reasoning verification
- audit of why expensive reasoning was invoked

### Constraint

LLM escalation must not become the default path.

---

## v0.3 — Browser execution

### Goal

Add Browser Use or another browser worker as an execution provider.

Potential path:

```text
objective
  ↓
Jev chooses API/tool/browser
  ↓
browser worker
  ↓
page evidence
  ↓
validator/Jev
```

### Requirements

- worker protocol
- browser-action schema
- screenshot / DOM evidence
- completion verification
- recovery and retry
- side-effect policy gates

---

## v0.4 — Persistent workflows

### Goal

Move from single-request loops to long-running work orders.

Potential integrations:

- BB
- LongHorizon-Harness
- queued workers

Required concepts:

```text
WorkOrder
Step
Evidence
Checkpoint
Retry
Recovery
Completion gate
```

---

## v0.5 — Outcome-based optimization

### Goal

Use historical data to improve routing.

Collect:

```text
task type
provider/model
route probability
latency
cost
success/failure
validator result
Jev result
retry count
human correction
```

Optimize for:

```text
maximize reliability
maximize completion
minimize cost
minimize latency
minimize unnecessary LLM calls
minimize human intervention
```

Possible future mechanism:

- contextual bandit
- rules learned from historical performance
- provider priors
- per-capability thresholds
- cost-aware routing

---

## Later directions

- policy engine for risky actions
- user/organization permissions
- multi-agent execution
- event-driven workflows
- self-hosted execution workers
- server deployment
- observability dashboard
- provider SLA tracking
- model/tool benchmark harness
- human approval queues
- domain-specific validator plugins
- robotics control-plane experiments

---

## Immediate next action

Build v0.1.2 automatic Treg discovery before adding Browser Use, BB integration, or self-improvement.
