# V2C traceability matrix

**Contract:** `13_V2_CONTROL_ARCHITECTURE.md` §15 (Accepted)\
**Slice:** V2 control-store foundation (`src/cloudeo/control/`)\
**Kept in sync by:** `tests/test_v2c_traceability.py`

Every invariant V2C-01 to V2C-23 has exactly one status:

- **ENFORCED:** a guard exists in this slice. Positive tests pass, and at
  least one negative test (marked `negative`) proves the prohibited state or
  transition is rejected.
- **DEFERRED:** the contract obligation belongs to a later milestone. It is
  held by a strict expected-failure test (`test_deferred_obligation[V2C-NN]`)
  whose reason names the invariant. If later work makes it pass unexpectedly,
  CI fails until this record is deliberately updated. Guards this slice
  already provides are listed as supporting evidence only; they do not make
  the invariant ENFORCED. For example, the model can carry and validate a
  checkpoint proof, but checkpoint integrity stays DEFERRED until the
  checkpoint subsystem supplies that proof.
- **NOT_APPLICABLE:** only if the accepted contract makes the invariant
  irrelevant to this layer, with a written reason. No invariant has this status
  today.

The meta-tests check that:

- every invariant has exactly one status and named, existing tests;
- every DEFERRED obligation is a strict expected failure naming its invariant;
- every ENFORCED invariant has a real negative test;
- this table matches the matrix.

| Invariant | Status | In this slice | Deferred obligation |
| --- | --- | --- | --- |
| V2C-01 | ENFORCED | The control package imports no broker mutator, bridge, LongHorizon code, or subprocess, and has no promote, checkpoint, reject, or cleanup calls and no ref strings. The checker itself is tested against violating code. | — |
| V2C-02 | DEFERRED | Supporting: no candidate or blocks before an approved plan; `attach_candidate` and `begin_attempt` state guards | Executor dispatch runs only through `begin_attempt` of an approved, executing WorkOrder |
| V2C-03 | ENFORCED | Sequential, immutable plan versions; approval only of the latest, newer version; append-only plan history | — |
| V2C-04 | DEFERRED | Supporting: `PROMOTED` iff a promoted `KernelOutcome`; recording it requires an authoritative final audit | `KernelOutcome` is built from a real `GatedPromotionResult` |
| V2C-05 | ENFORCED | All blocks `BLOCK_DONE` only permits `FINAL_VERIFICATION`; `PROMOTED` impossible without a promoted kernel outcome | — |
| V2C-06 | DEFERRED | Supporting: `code_approval_problem()` requirements, enforced by the validator and `approve_code` | Checks and scope records come from deterministic runners and diff checks |
| V2C-07 | ENFORCED | `AuditRecord.authoritative` excludes repaired reports and gates code, memory, and final audits | — |
| V2C-08 | DEFERRED | — | Project Memory lives in tracked documents and is promoted with code |
| V2C-09 | DEFERRED | Supporting: curation only after `CODE_APPROVED`, only by `memory_curator`, checked against `memory_paths`; Memory Audit before the checkpoint | The curator's writes are restricted to `memory_paths` at execution time |
| V2C-10 | DEFERRED | — | Context Intake runs read-only and classifies memory claims with evidence |
| V2C-11 | ENFORCED | The profile snapshot changes only through an approved `change_agent` amendment; it must be a stored, approved version | — |
| V2C-12 | DEFERRED | Supporting: bound primary, or an approved fallback with a defined condition and evidence; every attempt recorded | Fallbacks are triggered only by classified runtime or provider failures, or by discovery |
| V2C-13 | DEFERRED | — | Performance Memory and Jev can only recommend, never select profiles |
| V2C-14 | DEFERRED | — | The independence resolver enforces cumulative requirements per risk class |
| V2C-15 | DEFERRED | Supporting: a recorded material deviation always raises attention | Deviations are detected from diffs, audit findings, and accounting |
| V2C-16 | ENFORCED | One open request merges every reason; resume requires each blocking reason to be resolved or waived; decisions are recorded | — |
| V2C-17 | DEFERRED | Supporting: a non-promoted kernel outcome and baseline drift always raise attention | `AUDITOR_ERROR` beyond the fallback conditions is routed to attention |
| V2C-18 | DEFERRED | Supporting: immutable, sequential Project Execution Profile versions with a canonical hash that is stable across processes; exact profile fingerprint on every attempt | An ExecutionProfile registry (AgentProfile, DirectToolProfile, …) with immutable versions |
| V2C-19 | DEFERRED | Supporting: `BLOCK_DONE` cannot be constructed without a proof of the authoritative block state; `prove_block_checkpoint` is the only setter, with no generic `mark_block_done()`; a mismatch escalates | The checkpoint subsystem supplies the proof from immutable Git objects |
| V2C-20 | DEFERRED | Supporting: no write-capable step outside `EXECUTING`; the final audit must come from `final_verifier` | The final verification runner uses a fresh, read-only auditor |
| V2C-21 | ENFORCED | Abort and defer keep the candidate, blocks, and attention; the store is append-only with no delete; history cannot be erased | — |
| V2C-22 | DEFERRED | Supporting: drift checks at candidate attach, execution start, final verification, and both resumes; the planned baseline is never rebased | The accepted baseline is observed from the Workspace Broker |
| V2C-23 | ENFORCED | `BEGIN IMMEDIATE`, an expected-version check, revalidation, `check_evolution`, and a version-conditioned `UPDATE`; conflicts are refused, never resolved by the store | — |

**Totals:** 8 ENFORCED, 15 DEFERRED, 0 NOT_APPLICABLE; 15 strict expected-failure
obligation tests.
