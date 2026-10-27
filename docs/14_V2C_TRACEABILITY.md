# V2C traceability matrix

**Contract:** `13_V2_CONTROL_ARCHITECTURE.md` §15 (Accepted)\
**Slices:** V2 control-store foundation; ExecutionProfile registry and auditor
independence (V2C-18, V2C-14) (`src/cloudeo/control/`)\
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
| V2C-12 | DEFERRED | Supporting: bound primary, or an approved fallback with a defined condition and evidence; every attempt recorded. Execution failures are classified (`cloudeo.orchestration.execution_failure`, ADR-035 slice 2) but never establish a condition, so no execution failure triggers a fallback yet (`tests/test_orchestration_execution_failure.py`) | Fallbacks are triggered only by classified runtime or provider failures, or by discovery |
| V2C-13 | DEFERRED | — | Performance Memory and Jev can only recommend, never select profiles |
| V2C-14 | ENFORCED | An `IndependencePolicy` in the approved envelope, never weaker than the §8.6 table. Independence is measured by role against the producers, and checked at plan approval, before every write-capable step, and before any approving audit is recorded; a gap raises `INDEPENDENCE_UNAVAILABLE`. A fresh session needs both the profile's declaration and the runner's per-audit `SessionEvidence`; without that evidence the check fails closed. Only an explicit, recorded user waiver accepts a gap. Stored approvals are re-checked on every reload against the risk class they were judged by. | — |
| V2C-15 | DEFERRED | Supporting: a recorded material deviation always raises attention | Deviations are detected from diffs, audit findings, and accounting |
| V2C-16 | ENFORCED | One open request merges every reason; resume requires each blocking reason to be resolved or waived; decisions are recorded | — |
| V2C-17 | DEFERRED | Supporting: a non-promoted kernel outcome and baseline drift always raise attention. An auditing role's failed execution is routed to `AUDITOR_ERROR` attention through `machine.raise_attention`; other roles' failures to `AGENT_UNAVAILABLE` (`tests/test_orchestration_execution_failure.py`). Not yet wired into a runner, and auditor verdicts with status `AUDITOR_ERROR` are not covered | `AUDITOR_ERROR` beyond the fallback conditions is routed to attention |
| V2C-18 | ENFORCED | A registry of `AgentProfile` and `DirectToolProfile` versions, sequential and immutable. A reference's fingerprint is the canonical hash of its definition; a project profile binds only registered versions and carries their exact definitions. Every attempt and audit names a version the WorkOrder recorded in `used_profiles`, which is append-only and survives `change_agent`. | — |
| V2C-19 | DEFERRED | Supporting: `BLOCK_DONE` cannot be constructed without a proof of the authoritative block state; `prove_block_checkpoint` is the only setter, with no generic `mark_block_done()`; a mismatch escalates | The checkpoint subsystem supplies the proof from immutable Git objects |
| V2C-20 | DEFERRED | Supporting: no write-capable step outside `EXECUTING`; the final audit must come from `final_verifier` | The final verification runner creates a fresh, read-only auditing session and supplies its `SessionEvidence`, which the V2C-14 check requires |
| V2C-21 | ENFORCED | Abort and defer keep the candidate, blocks, and attention; the store is append-only with no delete; history cannot be erased | — |
| V2C-22 | DEFERRED | Supporting: drift checks at candidate attach, execution start, final verification, and both resumes; the planned baseline is never rebased | The accepted baseline is observed from the Workspace Broker |
| V2C-23 | ENFORCED | `BEGIN IMMEDIATE`, an expected-version check, revalidation, `check_evolution`, and a version-conditioned `UPDATE`; conflicts are refused, never resolved by the store | — |

**Totals:** 10 ENFORCED, 13 DEFERRED, 0 NOT_APPLICABLE; 13 strict expected-failure
obligation tests.

## Trust boundaries and open integration obligations

An ENFORCED status means the control layer requires and checks the listed
evidence. It does not make that evidence authentic: `cloudeo.control` is pure
and cannot tell who constructed a record. The integration layer (not yet
built) must be the only producer of these runtime inputs:

- **`SessionEvidence` (V2C-14).** It is trusted runtime input, never an
  auditor's assertion. Only the audit runner that created the session may
  create it; the auditing agent must never be able to attest its own
  freshness. Producers:
  - final verification: owned by V2C-20 (DEFERRED);
  - code and Memory Audits: **no invariant owns this yet.** It is an explicit
    integration-layer obligation. Until a runner supplies the evidence, no
    code or Memory Audit can approve, because V2C-14 fails closed.
- `KernelOutcome` (V2C-04), the accepted baseline (V2C-22), and
  `CheckpointProof` (V2C-19) are likewise runtime inputs whose producers are
  the DEFERRED obligations in the table.

## Provider-neutral (PN) invariants

**Source:** ADR-035 (Accepted 2026-10-01) and the draft
`15_PROVIDER_NEUTRAL_EXECUTION_AND_DEVLOOP.md`, whose PN numbering is kept.
Where the draft conflicts with ADR-030, ADR-035, `13_V2_CONTROL_ARCHITECTURE.md`,
or this document, those govern.

These rows cover only invariants that are genuinely new. They are
architecture requirements. The first ADR-035 slice enforces PN-01, PN-03, and
PN-12; the other rows are DEFERRED. Unlike the V2C table, PN rows are not yet
held by strict expected-failure tests or checked by the traceability
meta-tests: an ENFORCED PN row names its tests here and is checked only by
those tests. Extending the meta-tests to PN rows is a separate decision. A PN
row is never ENFORCED because an adapter test passes; it needs the enforcing
code and an offline negative test.

| Invariant | Status | Current state | Required before ENFORCED |
| --- | --- | --- | --- |
| PN-01 | ENFORCED | No provider SDK import and no comparison to a provider-name constant anywhere in `cloudeo.control`. Guard and tests: `tests/test_execution_boundary.py::test_control_imports_no_provider_sdk_and_has_no_provider_branching`; negative: `test_provider_blindness_check_catches_sdk_imports_and_provider_branches`. The check is syntactic (a fixed SDK and provider-name list); it does not prove the absence of every provider-specific branch. | — |
| PN-03 | ENFORCED | `RuntimeIdentity` gains optional `execution_plane`, `adapter_id`, `provider`, and `inference_provider` alongside the unchanged `backend`. Treg and UHP set plane and adapter by construction; provider fields stay `None` unless a runtime reports them (`tests/test_execution_contracts.py::test_uhp_identity_records_plane_and_adapter_but_never_invents_provider`). `ExecutionError` gains a closed neutral `error_class` (`test_error_class_defaults_to_unknown_and_rejects_unlisted_values` is the negative test). | Provider and inference provider populated from reported metadata once a provider adapter exists. |
| PN-04 | DEFERRED | No adapter descriptor, capability set, or conformance suite exists. `Permissions` (granted authority) is enforced by control. | Adapter capabilities established by a shared conformance suite and kept distinct from `Permissions`. |
| PN-05 | DEFERRED | Profiles carry no billing mode, and projects no billing policy. Fallbacks already run only as approved bindings with a defined condition (V2C-12 supporting). | Billing mode on profiles, billing policy in the approved envelope, and a runtime refusal when the observed billing mode differs from the declared one. |
| PN-07 | DEFERRED | `Budget.max_attempts_per_block` bounds attempts, and a failed audit counts against it through `fail_attempt`. There is no separate repair budget and no stop on a repeated classified failure. | Those bounds as control rules (ADR-035), with negative tests. |
| PN-10 | DEFERRED | No provider adapter exists yet, so provider replacement is untested. | The draft's PI-01 and PI-03 acceptance tests: the same role step on three providers, and removing one adapter, with no `cloudeo.control` change. |
| PN-12 | ENFORCED | All four forbidden edges (control ↛ execution, control ↛ orchestration, execution ↛ control, execution ↛ orchestration) are checked by AST in `tests/test_execution_boundary.py::test_forbidden_dependency_edges_are_absent`, with negative tests `test_edge_check_catches_each_forbidden_edge` and `test_edge_check_catches_a_relative_import_of_the_target`. The ADR-030 edge is also covered by `tests/test_orchestration_boundary.py`. | — |
| PN-13 | DEFERRED | No native-CLI plane exists. Candidate worktrees share refs with the canonical repository and are not a security boundary (`cloudeo/workspace/git.py`). The bridge's bundle, validate, and apply path exists for UHP. | OS-isolated execution with no access to the canonical repository, changes returned only through bundle, validate, and apply, and tests proving both. Until then no native-CLI profile may hold a write-capable role. |

**Refinements traced against existing invariants, not duplicated:**

- PN-02 (role first, provider later): V2C-11 and V2C-12 role bindings.
- PN-06 (execution completion is never verification): V2C-05 and V2C-06.
- PN-08 (evidence, not prose): V2C-06 and contract §9.
- Provider diversity in audits: V2C-14, unchanged; it may only be made
  stricter through `IndependencePolicy`.
- The neutral error class mapped to fallback conditions and `AUDITOR_ERROR`:
  the missing producers of V2C-12 and V2C-17. See "Execution failure
  mapping" below.

**Execution failure mapping (ADR-035 slice 2).**
`cloudeo.orchestration.execution_failure` maps one failed `ExecutionOutcome`
to an attention reason. It reports, for each error class, only the fallback
condition the class could support once its establishing evidence exists, and
never authorizes one; control remains the only gate (`begin_attempt`).

| Error class | Condition if established | Established by (13 §8.4) |
| --- | --- | --- |
| `runtime_unavailable` | `runtime_unavailable` | discovery or health evidence |
| `model_unavailable` | `model_unavailable` | discovery or health evidence |
| `authentication`, `quota_exhausted`, `rate_limited`, `transport` | `provider_failure_persistent` | persistence after the primary's allowed retries |
| `authorization`, `timeout`, `protocol`, `invalid_request`, `workspace_violation`, `tool_failure`, `cancelled`, `unknown` | none (fail closed) | — |

Every assessed failure raises attention: `AUDITOR_ERROR` for
`code_auditor`, `memory_auditor`, and `final_verifier`; `AGENT_UNAVAILABLE`
for any other role. Only `failed` and `cancelled` are marked safe for a
second execution; `unknown` and `incomplete` never are. The original
`ExecutionError`, `RuntimeIdentity`, and `ProfileRef` are kept, and the
reason's evidence is a tagged digest of them.

Gaps recorded, not closed (each needs a control decision):

- No producer of discovery or health evidence exists, so
  `runtime_unavailable` and `model_unavailable` are never established.
  Today every UHP 5xx, 408, transport, and protocol failure has status
  `unknown`, so it is also unsafe to re-execute.
- Control defines no "allowed retries" for a primary, so
  `provider_failure_persistent` cannot be established without orchestration
  inventing loop policy (ADR-035 assigns that to control).
- `AttentionCode` has no code for "the run failed" distinct from
  unavailability; `invalid_request`, `tool_failure`, and
  `workspace_violation` use `AGENT_UNAVAILABLE`, with the class in the
  summary and evidence.
- Whether an execution failure should count against the block's attempt
  budget (`fail_attempt`) instead of raising attention is loop policy and
  undecided.
- The traceability meta-tests index only control test modules, so these
  orchestration tests are supporting evidence and V2C-12 and V2C-17 stay
  DEFERRED.

PN-09 (peer runtimes) and PN-11 (traceability) are principles, not testable
invariants, and have no row.
