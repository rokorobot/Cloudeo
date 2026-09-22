# Cloudeo v2 — Architecture Acceptance Criteria

**Status:** Testable gates for the next development phase  
**Date:** 2026-09-22

These criteria define when the new architecture is real rather than only documented.

## A. Baseline preservation

### V2-A01 — v0.1 remains runnable

**Given** the v2 branch contains new abstractions,  
**when** the existing v0.1 test/smoke suite is run,  
**then** the current Treg/Jev/SQLite execution path still works unless a separately approved migration explicitly retires it.

### V2-A02 — historical docs remain truthful

Existing v0.1 docs are not rewritten to claim LongHorizon/UHP/HarnessRouter were already implemented.

## B. UHP integration

### V2-B01 — explicit protocol pin

Every UHP request issued by Cloudeo sends the approved `UHP-Version`.

Initial approved version: `2026-09-12`.

### V2-B02 — capability discovery

Cloudeo obtains server capability state from `GET /v1/uhp` and does not assume unsupported optional capabilities.

### V2-B03 — runtime discovery

Cloudeo obtains configured harnesses from UHP rather than a hard-coded Codex/Claude list.

### V2-B04 — model availability

Unavailable models are not selected for execution.

### V2-B05 — common execution interface

At least one Codex profile and one Claude Code profile can run the same test WorkOrder through the same Cloudeo execution interface.

### V2-B06 — no native duplicate adapters

The v2 proof does not add separate Cloudeo Codex and Claude Code process adapters when HarnessRouter/UHP already provides the boundary.

### V2-B07 — terminal statuses preserved

`completed`, `failed`, `incomplete`, and `cancelled` remain distinguishable in Cloudeo records.

### V2-B08 — partial evidence preserved

Output/artifacts emitted before failure/incomplete/cancel remain available to recovery/audit.

## C. Session and harness switching

### V2-C01 — no cross-harness session continuation

A routing decision that changes configured harness starts a new UHP session.

### V2-C02 — continuity above the session

A new harness receives the original objective, accepted checkpoint, verified state, and relevant failure evidence without requiring private native state from the previous harness.

## D. Workspace and checkpoints

### V2-D01 — immutable accepted checkpoint

An accepted checkpoint is addressable by an immutable reference.

### V2-D02 — candidate isolation

Executor work occurs against a candidate state derived from the accepted checkpoint.

### V2-D03 — failed audit cannot promote state

A failed verification leaves the accepted checkpoint unchanged.

### V2-D04 — independent reconstruction

An Auditor can reconstruct/inspect the candidate state without trusting the Executor's natural-language description.

### V2-D05 — harness switch reproducibility

A second harness can begin from the accepted checkpoint and reproduce required project state.

## E. LongHorizon integration

### V2-E01 — LongHorizon owns verified cross-round state

Cloudeo does not maintain a parallel competing long-horizon truth store with different acceptance semantics.

### V2-E02 — fresh executor context supported

A bounded Executor step can be dispatched to a newly selected execution profile.

### V2-E03 — independent audit gates completion

LongHorizon/verification cannot mark a WorkOrder complete solely because an Executor says it is done.

### V2-E04 — demonstrated cross-harness recovery

A test scenario demonstrates:

```text
attempt A -> verification fail
different profile B -> verification pass
accepted checkpoint advances only after B passes
```

## F. Dynamic routing

### V2-F01 — bounded candidate set

Every policy decision receives an explicit candidate list.

### V2-F02 — exclusion evidence

Every hard-excluded candidate records a machine-readable reason.

### V2-F03 — Jev cannot invent execution targets

A Jev-selected ID not present in the candidate set is rejected.

### V2-F04 — hard policy dominates

Jev/policy cannot select a candidate rejected for permission, capability, risk, budget, availability, or quarantine.

### V2-F05 — policy versioning

Every routing decision records the exact policy/version used.

### V2-F06 — deterministic fallback

Cloudeo can route without the Jev service for supported deterministic cases.

## G. Verification

### V2-G01 — runtime completion is not verified success

The data model distinguishes execution completion from acceptance.

### V2-G02 — evidence references

Every verified pass has evidence references sufficient to explain the acceptance decision.

### V2-G03 — deterministic checks preferred

Where a deterministic test can decide a criterion, the architecture does not replace it with model opinion.

### V2-G04 — high-risk human gate

Configured high-risk actions cannot bypass required operator approval.

## H. Performance Memory

### V2-H01 — only verified labels train routing evidence

No executor self-report can write `verified_success=true`.

### V2-H02 — version fingerprint

Every performance event records enough component/profile identity to distinguish materially different runtime configurations.

### V2-H03 — immutable events

Raw performance events are append-only; aggregate statistics are recomputable.

### V2-H04 — sample count visible

Routing evidence never reports a success estimate without its sample count.

### V2-H05 — cold start honesty

A profile with insufficient evidence is represented as under-tested, not silently ranked as superior.

## I. Recovery

### V2-I01 — structured failure class

A failed attempt maps to a defined recovery/failure class when evidence permits.

### V2-I02 — recovery candidate set

Recovery policy chooses only from allowed registered recovery actions.

### V2-I03 — timeout/incomplete test

A budget-limited attempt can be continued/replanned without being mislabeled as a generic runtime failure.

### V2-I04 — unavailable harness test

If a selected harness becomes unavailable before execution, Cloudeo re-routes or blocks according to policy without corrupting checkpoint state.

## J. Upstream lifecycle

### V2-J01 — production is never auto-upgraded

Detection of a new upstream version does not modify the production/main environment.

### V2-J02 — dev/integration first

A candidate version is staged and tested in the development/integration environment before promotion.

### V2-J03 — feature PR separation

An upstream candidate evaluation is not silently mixed into an unrelated feature PR.

### V2-J04 — exact identity

Approved upstreams have exact reproducible identities: protocol version, commit/tag, package lock, or image digest as applicable.

### V2-J05 — comparison evidence

Promotion records compatibility and representative workload results against the currently approved version.

### V2-J06 — rollback

A previously approved version can be restored without losing accepted WorkOrder state.

## K. v2 alpha release gate

Cloudeo v2 alpha may be declared only when all of these are true:

- v0.1 direct capability lane remains available;
- UHP/HarnessRouter executes at least two different harness bases through one interface;
- LongHorizon can recover across a harness switch;
- Workspace Broker controls accepted checkpoint promotion;
- independent verification gates trusted state;
- Performance Memory stores verified outcomes;
- deterministic routing uses execution profiles;
- Jev can optionally select from a bounded candidate set;
- upstream candidates are staged dev-first;
- the full test suite has a clean reproducible run.
