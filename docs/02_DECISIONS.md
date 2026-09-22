# Cloudeo Decision Log

This file records important architectural decisions so they do not have to be reconstructed from chat history.

---

## ADR-001 — Local-first MVP

**Decision:** Build and validate Cloudeo locally in WSL2 before deploying to a server.

**Reason:**

- fastest development loop
- no deployment complexity before architecture validation
- no need for local GPU
- Jev and frontier models can remain API-hosted

**Status:** Accepted.

---

## ADR-002 — Jev is a decision engine, not the whole agent

**Decision:** Use Jev for classification, routing, scoring, and probabilistic verification rather than for reasoning or generation.

**Reason:**

Jev returns structured probabilities and does not generate prose/code. This makes it suitable as a high-frequency decision layer.

**Status:** Accepted.

---

## ADR-003 — Treg is the tool/data plane

**Decision:** Use Treg to discover/call external providers and tools rather than rebuilding provider integrations inside Cloudeo.

**Reason:**

Treg already provides provider access, credential injection, OAuth, CLI, MCP, audit, provider catalog, and metering.

**Status:** Accepted.

**Constraint:** Treg remains behind a Cloudeo adapter boundary because of coupling and licensing considerations.

---

## ADR-004 — Real Jev before real Treg

**Decision:** Introduce real integrations one at a time.

Sequence:

```text
mock Jev + mock Treg
real Jev + mock Treg
real Jev + real Treg dry run
real Jev + real Treg
```

**Reason:** Easier debugging and safer cost control.

**Status:** Completed.

---

## ADR-005 — Deterministic validation before Jev verification

**Decision:** Structured facts should be validated in code first.

Pipeline:

```text
provider output
    ↓
deterministic validation
    ├── pass
    ├── fail
    └── inconclusive → Jev
```

**Reason:** A real TryKitt result contained explicit strong evidence but Jev initially gave only 0.81 probability against a 0.85 threshold. The result could be proven deterministically.

**Status:** Implemented in v0.1.1.

---

## ADR-006 — Do not simply lower confidence thresholds

**Decision:** Avoid fixing false negatives by globally lowering thresholds without understanding evidence structure.

**Reason:** Threshold reduction can increase false positives across unrelated workflows. Explicit facts should instead be extracted and validated deterministically.

**Status:** Accepted.

---

## ADR-007 — Provider failures are deterministic failures

**Decision:** Provider/transport failures such as `TREG_ERROR` should not consume a Jev verification call.

**Reason:** A failed external call is already known to be unusable.

**Status:** Implemented in v0.1.1.

---

## ADR-008 — Automatic tool discovery is the next major milestone

**Decision:** v0.1.2 should remove manually supplied provider candidate arrays.

Target:

```text
objective
  ↓
Treg capability discovery
  ↓
provider metadata
  ↓
compatibility filtering
  ↓
Jev routing
```

**Reason:** Manual candidate construction is the largest remaining non-autonomous part of the current pipeline.

**Status:** Planned.

---

## ADR-009 — LLM escalation comes after automatic discovery

**Decision:** Do not add Claude/GPT reasoning escalation until the tool discovery and validator architecture is stable.

**Reason:** Avoid hiding control-plane weaknesses behind a frontier model.

**Status:** Planned.

---

## ADR-010 — Self-improvement comes later

**Decision:** First collect structured evidence of runs before implementing self-improvement.

Log first:

- decisions
- probabilities
- provider
- costs
- latency
- success/failure
- retries
- validation evidence
- human corrections

Then optimize based on observed data.

**Status:** Planned.


---

## ADR-011 — Extract execution without changing orchestration

**Decision:** Add one internal async `ExecutionBackend` protocol with an
`ExecutionResult` carrying output and economics. Adapt the existing Treg client
through `TregExecutionBackend`; retain it as the controller's default and allow
an optional injected backend. Discovery, routing, verification, and persistence
stay in their current locations.

**Reason:** Establish the execution seam for a future UHP backend while preserving
the v0.1.2.2 path and existing construction sites. No UHP fields or other v2
interfaces are needed for this slice.

**Constraint:** Preserve normal `TREG_ERROR:` normalization, dry-run exception
propagation, and legacy economics behavior. Existing ranking and unknown-choice
behavior are unchanged. UHP remains unimplemented.

**Status:** Implemented; 33 tests pass. See the execution-foundation evidence in
`03_PROGRESS_AND_EVIDENCE.md`.


---

## ADR-012 — Standalone UHP client before execution integration

**Decision:** Add a UHP-native client (`cloudeo.uhp`) with its own request,
result, harness, model, and error types, pinned to UHP `2026-09-12`. Do not
route it through `ExecutionBackend`, `ToolCandidate`, or the controller yet.

**Reason:** A harness task (input, harness, model, step/time budgets, session
continuation, output items) is a different execution class from a Treg endpoint
call. Proving the UHP boundary independently lets the shared execution request
be designed from two concrete shapes instead of one.

**Constraint:** `completed` is runtime completion, never Cloudeo verified
success. Terminal output (including partial output of `incomplete`, `failed`,
and `cancelled`) and unknown output item types are preserved unchanged.
Structured errors keep HTTP status, UHP code, type, message, param, detail,
body, and the response `UHP-Version`. No retries or recovery policy are built
on them yet. Transport timeouts do not claim cancellation.

**Status:** Client implemented; 34 mock-transport tests. Live discovery proven
against HarnessRouter CE 0.23.7; harness listing and live tasks await an API key
and provider credentials. See `03_PROGRESS_AND_EVIDENCE.md`.
