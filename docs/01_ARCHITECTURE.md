# Cloudeo Architecture

## Architecture goal

Cloudeo is a decision and control plane that coordinates heterogeneous intelligence and execution systems.

The current architecture separates five concerns:

```text
                     ┌─────────────────────┐
                     │   Goal / Objective  │
                     └──────────┬──────────┘
                                │
                                ▼
                     ┌─────────────────────┐
                     │      Controller     │
                     └──────────┬──────────┘
                                │
                     ┌──────────▼──────────┐
                     │        Jev          │
                     │ route / classify    │
                     └──────────┬──────────┘
                                │
                     ┌──────────▼──────────┐
                     │      Tool Plane     │
                     │       Treg          │
                     └──────────┬──────────┘
                                │
                                ▼
                         Provider output
                                │
                     ┌──────────▼──────────┐
                     │ Deterministic       │
                     │ validator layer     │
                     └──────────┬──────────┘
                                │
                   pass ────────┼──────── fail
                                │
                           inconclusive
                                │
                                ▼
                     ┌─────────────────────┐
                     │      Jev verify     │
                     └──────────┬──────────┘
                                │
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
                  PASS        RETRY      ESCALATE
```

## Components

### 1. API surface

FastAPI exposes the current control plane.

Primary endpoint:

```text
POST /v1/runs
```

Other current endpoint:

```text
GET /v1/runs
```

The API accepts an objective, state, success criteria, candidate tools, and execution controls.

### 2. Controller

The controller is the orchestration core.

Responsibilities:

- send routing state to Jev
- apply route-confidence threshold
- rank candidates
- execute selected tool
- run deterministic validation
- call Jev verification only when validation is inconclusive
- retry another candidate when needed
- escalate when no candidate succeeds
- persist run metadata and result

### 3. Jev adapter

Current real backend:

```text
OpenRouter
model: typesafe/jev-1.13
endpoint: /api/alpha/decisions
```

Current uses:

- tool/provider routing
- semantic verification for ambiguous results

Mock mode is also supported for local testing.

### 4. Treg adapter

Treg is currently the tool/data execution plane.

Cloudeo invokes the local Treg repository through the CLI.

Current local source path:

```text
/home/robert/treg
```

The adapter supports:

- GET
- POST
- PUT
- PATCH
- DELETE
- query parameters
- JSON bodies
- dry-run mode

This supports providers such as:

```text
trykitt.people.email.find
tomba.people.email.find
```

### 5. Deterministic validator layer

Introduced in v0.1.1.

Purpose:

> Do not ask a probabilistic model to re-decide facts already explicit in structured output.

Current first vertical: verified work-email lookup.

Checks include:

- email exists
- returned domain matches expected company domain
- provider identity signal
- returned person matches expected person
- SMTP validation signal
- validity / verification status

Possible outcomes:

```text
pass
fail
inconclusive
```

Only `inconclusive` requires Jev semantic verification.

### 6. Persistence

SQLite currently stores run audit history.

Persisted information includes:

- run ID
- objective
- status
- selected tool
- route confidence
- request payload
- result payload

## Separation of responsibilities

### Deterministic software

Use when facts can be proven directly.

Examples:

```text
HTTP request failed
provider unavailable
email domain mismatch
validSMTP=false
status=invalid
required field absent
```

### Jev

Use for fast judgment.

Examples:

```text
which provider best fits this task?
is this result semantically sufficient?
which category does this event belong to?
should we retry or escalate?
```

### Frontier LLM

Future use for cases requiring actual reasoning.

Examples:

```text
resolve conflicting evidence
perform deeper research
interpret ambiguous documents
generate plans or personalized outputs
recover from unusual workflows
```

## Desired future architecture

```text
                        Cloudeo Control Plane

      ┌────────────────────────────────────────────────┐
      │                                                │
      │  policy     Jev      validators     evaluator  │
      │     │        │           │              │      │
      └─────┼────────┼───────────┼──────────────┼──────┘
            │        │           │              │
            ▼        ▼           ▼              ▼
        Treg/MCP   LLMs       Browser        Agents
            │        │           │              │
            └────────┴───────────┴──────────────┘
                              │
                              ▼
                         audit/evidence
                              │
                              ▼
                        optimization loop
```

## Architectural constraints

- Treg must remain behind an adapter boundary.
- Cloudeo should not depend on Treg-specific semantics at its core.
- Provider metadata and discovery should become automatic.
- Validation rules should be modular by capability.
- Cost, latency, confidence, and outcome should become first-class metrics.
- Retry logic must remain bounded.
- Risky side effects should eventually require policy/approval gates.
