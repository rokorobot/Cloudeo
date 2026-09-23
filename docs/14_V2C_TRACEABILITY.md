# V2C traceability matrix

**Contract:** `13_V2_CONTROL_ARCHITECTURE.md` §15 (Accepted)\
**Slice:** V2 control-store foundation (`src/cloudeo/control/`)\
**Kept in sync by:** `tests/test_v2c_traceability.py`

Every invariant V2C-01 to V2C-23 is listed. The status is one of:

- **PASS:** enforced by this slice and proven by the listed tests.
- **PARTIAL:** the state and persistence guard is enforced and tested here;
  the remaining obligation, usually an integration, has a strict
  expected-failure test (`test_remaining_obligation[V2C-NN]`). That test turns
  red if the obligation is implemented without updating this matrix.
- **UNIMPLEMENTED:** nothing in this slice. A strict expected-failure test holds
  the place.

The meta-test fails if an invariant is missing here, in the test matrix, or in
the contract, or if a status differs between this table and the test matrix.

| Invariant | Status | Guard in this slice | Remaining obligation |
| --- | --- | --- | --- |
| V2C-01 | PASS | The control package imports no broker mutator, bridge, or LongHorizon code, makes no promote or checkpoint calls, and contains no ref strings | — |
| V2C-02 | PARTIAL | WorkOrder validator: no candidate or blocks before an approved plan; `attach_candidate` and `begin_attempt` state guards | Executor dispatch runs only through `begin_attempt` of an approved, executing WorkOrder |
| V2C-03 | PASS | Plan versions are sequential and immutable; approval requires the latest, newer version; plan history is append-only (`check_evolution`) | — |
| V2C-04 | PARTIAL | `PROMOTED` iff a promoted `KernelOutcome`; recording it requires an authoritative final audit | `KernelOutcome` is built only from a real `GatedPromotionResult` |
| V2C-05 | PASS | All blocks `BLOCK_DONE` only permits `FINAL_VERIFICATION`; validators forbid `PROMOTED` without the kernel | — |
| V2C-06 | PARTIAL | `code_approval_problem()` requires passing checks, an original `VERIFIED` code audit of the exact current state, and an in-scope diff or an approved deviation; enforced by the validator and `approve_code` | Test and change records are produced by deterministic runners and diff checks |
| V2C-07 | PASS | `AuditRecord.authoritative` excludes repaired reports and gates code, memory, and final audits | — |
| V2C-08 | UNIMPLEMENTED | None; `memory_paths` are recorded per WorkOrder | Project Memory lives in tracked documents and is promoted with code |
| V2C-09 | PARTIAL | Curation only after `CODE_APPROVED`, only by `memory_curator`, checked against `memory_paths`; a Memory Audit is required before the checkpoint | The curator's workspace writes are restricted to `memory_paths` at execution time |
| V2C-10 | UNIMPLEMENTED | None | Context Intake runs read-only and classifies memory claims with evidence |
| V2C-11 | PASS | The profile snapshot changes only through an approved `change_agent` amendment (`decide`, `check_evolution`); the snapshot must be a stored, approved version | — |
| V2C-12 | PARTIAL | The bound primary, or an approved fallback with a defined condition and evidence; every attempt is recorded | Fallbacks are triggered only by classified runtime or provider failures, or by discovery |
| V2C-13 | UNIMPLEMENTED | None; no Performance Memory or Jev integration | Performance Memory and Jev can only recommend, never select profiles |
| V2C-14 | UNIMPLEMENTED | None | The independence resolver enforces cumulative requirements per risk class |
| V2C-15 | PARTIAL | A recorded material deviation always raises attention; curator changes outside the memory paths become material deviations | Deviations are detected from diffs, audit findings, and accounting |
| V2C-16 | PASS | One open request merges all reasons; resume requires every blocking reason to be resolved or waived; decisions are recorded | — |
| V2C-17 | PARTIAL | A non-promoted kernel outcome and baseline drift always raise attention | `AUDITOR_ERROR` beyond the fallback conditions is routed to attention |
| V2C-18 | PARTIAL | Project Execution Profile versions are immutable and sequential in the store; every attempt records the exact profile fingerprint | An ExecutionProfile registry (AgentProfile, DirectToolProfile, …) with immutable versions |
| V2C-19 | PARTIAL | `BLOCK_DONE` can be constructed only with a checkpoint proving the authoritative block state; `prove_block_checkpoint` is the only setter; a mismatch escalates | The `CheckpointProof` is computed from immutable Git objects when the checkpoint is created |
| V2C-20 | PARTIAL | No write-capable step outside `EXECUTING`; the final audit must come from `final_verifier` | The final verification runner uses a fresh, read-only auditor |
| V2C-21 | PASS | Abort and defer keep the candidate, blocks, and attention; the store is append-only with no delete; superseded blocks are kept | — |
| V2C-22 | PARTIAL | Drift checks at candidate attach, execution start, final verification, resume, and resume from deferral; the planned baseline is never rebased | The accepted baseline is observed from the Workspace Broker |
| V2C-23 | PASS | `SqliteControlStore.update` uses `BEGIN IMMEDIATE` and compare-and-swap on `(id, version)` | — |

**Totals:** 8 PASS, 11 PARTIAL, 4 UNIMPLEMENTED. There are 15 strict
expected-failure tests, one per remaining obligation.
