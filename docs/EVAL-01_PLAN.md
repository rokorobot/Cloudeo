# EVAL-01 development strategy and implementation plan

Status: proposed; implementation and baseline selection are not yet approved.
Prepared: 2026-10-31. Scope: Cloudeo only.

Future milestone: EVAL-02 — Controlled self-improvement scope (`EVAL-02_SCOPE.md`, not yet in the repository) covers proposed product changes and isolated experiments. Autonomous deployment is outside EVAL-01; EVAL-02 automatic promotion remains conditional and requires separate authorization.

**1. Development objective**

Make every proposed model, policy, harness, or orchestration change answer: what improved, is the improvement repeatable, what did it cost, and which guarantees or capabilities regressed?

Prioritize a small evaluation layer over additional adaptive routing, recovery loops, Performance Memory learning, and orchestration complexity. Continue trust-kernel fixes and the control integrations necessary to measure actual behavior. EVAL-01 must exercise existing authority boundaries, never become another authority for runtime promotion.

Deliver in two releases:

- **EVAL-01A — trustworthy measurement:** deterministic CI, versioned cases, trace evidence, independent grading, and reproducible reports.
- **EVAL-01B — controlled improvement:** repeated live comparisons, release gates, and independently reviewed failure-derived cases.

Do not require a capability pass rate of 50%. Regression cases protect supported behavior; capability cases measure remaining gaps. RoboLang BENCH-2 and the `.uhp-inspection` benchmarks remain external precedents, with separate corpora, graders, and baselines.

**2. Evidence and canonical baseline**

The previous audit inspected `main` at `86e7361` and `feat/v2-profile-billing-policy` at `7f88855`. It reported 566 passing tests on main and 800 passing tests plus 13 strict expected failures on the feature branch with LongHorizon. These are historical results, not tests rerun for this plan.

The retained reference checkout confirms the runtime source and branch-specific control/orchestration modules. The transferred `/code/Cloudeo` workspace contains documentation and UI files but no Git metadata; the reference checkout is `/tmp/cloudeo-reference.jAGeap`. This plan is saved in the durable project document area, not only in that temporary checkout. Remote branch freshness was not re-audited for this planning task.

Recommended baseline: review the V2 branch chain and use its accepted integration commit as the EVAL-01 target. It contains the profiles, billing policy, and neutral failure mapping the proposed cases need. Keep main's existing path covered throughout integration. Do not silently treat the feature tip as released or merge the entire chain solely to start evaluations.

The first implementation PR must record an exact commit, dependency/environment manifest, test commands, and deferred-obligation inventory. If V2 integration is postponed, start the main-compatible runner there; label V2 cases unsupported and publish separate coverage. Never combine scores from different implementation baselines.

**3. Architecture and reuse**

Use one Python package, `src/cloudeo/evaluation/`, existing Pydantic contracts, JSON case manifests, JSONL events, and SQLite trial indexing. No new service, framework, dashboard, or dependency is needed for the first slice. File names below are proposed, to be aligned with repository conventions during implementation.

| Existing boundary | EVAL-01 use |
| --- | --- |
| `core/controller.py`, `core/validators.py` | Exercise discovery, routing, deterministic verification and Jev escalation through real entry points |
| `execution/contracts.py`, `execution/dispatch.py` | Preserve execution outcomes, requested/observed identity, neutral errors, usage and cost |
| `uhp/`, `execution/uhp_backend.py`, `execution/treg_backend.py` | Instrument observable calls and correlate native trace references |
| `workspace/broker.py`, `longhorizon/promotion_gate.py` | Create disposable candidates and inspect actual checkpoint acceptance/refusal |
| `longhorizon/workspace_auditor.py` | Reuse independent runtime verification; separately grade whether its use was valid |
| V2 `control/` and `orchestration/` | Observe approved profiles, billing constraints and failure handling without bypassing control |
| `tests/test_v2c_traceability.py` | Preserve strict deferred obligations and distinguish modelled checks from integrated enforcement |

The evaluation runner owns fixtures and trial lifecycle. Cloudeo owns execution and promotion. Graders inspect collected evidence and state; analysts only propose diagnoses. Keep evaluation storage separate from operational run/control storage and use disposable test databases.

**4. Minimal contracts**

| Contract | Required content |
| --- | --- |
| `EvalCase` | Stable ID and revision; task; fixture digest; entry point; required capabilities; approved permissions/profiles/billing; budgets; expected state; forbidden behavior; grader references; partition and severity |
| `EvalSuite` | Immutable manifest referencing exact case revisions, weights if any, partition, fixture and grader versions, and manifest digest |
| `EvalTrial` | Suite/case IDs; repetition; baseline/candidate label; timestamps; execution status; complete provenance; trace references and completeness; both grades; costs; lifecycle status |
| `EvalGrade` | Outcome and execution-policy verdicts independently: pass/fail/unknown; reason codes; evidence references; grader identity/version |
| `EvalComparison` | Baseline/candidate run manifests; matched trials; changed variables; coverage; metrics; uncertainty; critical findings; gate verdict and reasons |
| `FailureProposal` | Source trial/evidence; suspected cause and confidence; alternative explanations; proposed reproduction/case; independent validation and review state |

Provenance includes code commit and dirty-tree state; suite, prompt, profile, policy and grader digests; harness/adapter/tool versions; fixture/environment fingerprints; requested and observed model/provider/billing identity; approved budgets; trial number and seed where supported; cost, usage, duration and trace digest. Reject dirty code for release comparisons. A missing observation stays unknown, never inferred from the requested value.

Start with an evaluation evidence envelope referencing `ExecutionOutcome`, rather than making every backend promise a complete transcript immediately. Add a shared trace reference to the execution contract only when its semantics and producers are established.

**5. Implementation sequence and acceptance criteria**

| PR / milestone | Deliverable | Exit criteria |
| --- | --- | --- |
| 1 — baseline and CI | Canonical baseline record; deterministic GitHub Actions jobs for core and pinned LongHorizon integration; expected-skip inventory | Clean environment reproduces both jobs without model credentials; missing integration dependency fails its job; strict XPASS fails; artifacts identify the commit/environment |
| 2 — contracts and runner | Contracts, manifest validation, isolated fixtures, SQLite index, CLI, five end-to-end deterministic cases | Cases run through production entry points with fake external boundaries; repeated invocations cannot overwrite trials; interrupted execution is recorded; fixtures do not leak state |
| 3 — evidence and grading | Event capture, artifact hashes, independent outcome/path graders | Correct answer with an unauthorized action fails; missing/tampered evidence cannot pass; valid alternative routes pass; graders themselves reject seeded violations |
| 4 — frozen corpus v1 | Expand to 30 cases, documented partitions and coverage; reviewed fixture expectations | Every case has an independent oracle or explicit unknown outcome; unsupported paths remain visible; an intentional policy defect is detected |
| 5 — live trials and comparison | Trusted live runner, fixed budgets, repeated paired runs, machine-readable and Markdown reports | Two configurations are compared on identical tasks/environment; unsuccessful trials remain in reports; unknown identity/cost is visible; report can be regraded from retained evidence |
| 6 — enforceable gates | Required deterministic check; trusted live smoke; scheduled comparisons; upgrade/release check | Seeded critical regression blocks; missing required evidence blocks; inconclusive comparison cannot claim improvement; failed evaluation leaves prior release baseline active |
| 7 — failure-analysis proposals | Read-only analyst, proposal format, independent validation and human-reviewed promotion | One real failed trial produces a reproducible case via review; analyst cannot modify graders, frozen suites, baseline pointers or runtime policy |

Dependencies: 1 → 2 → 3 → 4 → 5 → 6 → 7. Case drafting can begin during PR 2, but freeze only after grader validation. Each PR includes relevant regression tests, progress evidence and rollback instructions. EVAL-01A completes at PR 4; EVAL-01B completes at PR 7.

The five initial cases should cover direct-tool verified success, deterministic-validation failure with permitted Jev escalation, unknown UHP execution without unsafe retry, post-audit mutation refusal, and a prohibited billing transition. On a main-only baseline, the billing case is explicitly blocked until its V2 integration lands.

**6. Corpus v1: 30 Cloudeo-specific cases**

| Family | Cases | Examples |
| --- | ---: | --- |
| Discovery and routing | 4 | Typed capability match, missing capability, malformed catalog, excluded profile |
| Validation and Jev | 3 | Deterministic pass, justified escalation, persuasive but invalid result |
| Identity and ambiguous completion | 4 | Actual-model mismatch, hidden fallback, unknown status, incomplete response |
| Authorization, workspace and secret handling | 4 | Denied write, workspace escape, unapproved dispatch, synthetic secret in output |
| Billing and budgets | 3 | Forbidden billing transition, unknown billing mode, exhausted budget |
| Auditor independence and evidence | 4 | Reused session, missing producer evidence, malformed audit, post-audit mutation |
| Checkpoints and promotion | 4 | Stale candidate, accepted-state drift, race, valid promotion |
| Recovery and refusal | 4 | Tool failure, provider timeout, harness unavailable, correct refusal without authorized recovery |
| **Total** | **30** | |

Proposed allocation: 18 regression, 8 capability, 4 holdout. Severity is an independent tag; critical cases must be represented in the regression gate, not exclusively hidden in holdout. Four holdout cases are only an initial contamination check, not strong statistical evidence; expand before consequential upgrade decisions.

Some cases reuse existing test scenarios, but run through the relevant orchestration entry point and inspect resulting state. Do not simply rename 30 unit tests as a live capability benchmark. Mark each case as deterministic, live, or both, and report these populations separately.

Holdout fixtures/prompts/expected answers belong in restricted evaluation storage, with only IDs/digests in the development manifest. Keep families of near-duplicate cases in the same partition. Developers and failure analysts must not receive holdout content; diagnosis requiring disclosure retires the affected case and replaces it in a new suite version.

**7. Trace completeness and grading rules**

Capture ordered observable events: approved context, discovery and routing decision, dispatch, tool input/output, runtime identity, errors/retries, workspace changes, audit, checkpoint and final state. Include actor, timestamps, correlation IDs and evidence digests. Collect tool-visible conversation and actions where supported; private model reasoning is neither required nor evidence of compliance.

Declare coverage explicitly: complete for required surfaces, partial, or unavailable. An opaque harness cannot pass a case that requires unseen internal tool actions. A final answer alone cannot establish absence of forbidden side effects. Instrument the actual side-effect boundary or keep that grade unknown.

Outcome grading checks result and final state. Execution grading checks authorization, identity, billing, independence, evidence and mutations. Overall success requires both to pass. A correct refusal passes when refusal is the expected outcome. Critical violations override aggregate scores.

Retain immutable, access-controlled evidence and publish redacted reports. Use synthetic secrets for leakage tests. Redaction must preserve the evidence needed to grade; otherwise mark the verdict unknown. Record artifact hashes and a configurable retention policy, and ensure CI artifacts contain no credentials.

Use deterministic graders first. Any later model judge requires versioned prompts, calibration against independently labelled examples and recorded disagreements. It cannot override a deterministic critical violation. The runtime auditor and evaluation grader have different jobs: the latter must not merely trust the auditor's self-reported success.

**8. Comparisons, budgets and release policy**

Begin with five repetitions per live case/configuration as a pilot, then choose additional repetitions from observed uncertainty and the minimum effect worth detecting. Five trials do not establish a small uplift. Pair by case, fixture and environment; randomize/interleave baseline and candidate order to reduce provider/time drift. Freeze all variables except the intended change and label multi-component changes as system comparisons.

Report joint verified success, outcome success, execution-policy violations, per-case reliability, cost per verified success, latency median/p95 where sample size supports it, and failure attribution. Preserve raw numerators/denominators. Summarize differences with paired, case-clustered uncertainty; do not pretend repeated runs of one case are independent new tasks.

Keep all attempted trials. Distinguish agent failure, infrastructure-invalid, unsupported, and unknown evidence; publish counts and reasons. Infrastructure failures may get bounded separately identified reruns, but cannot disappear or become successes. Gate minimum coverage in addition to pass rate. Missing monetary cost is unknown, not zero; report tokens and reported currency costs separately.

Before each comparison, freeze minimum acceptable coverage, maximum trials/spend/time, quality non-inferiority margin, cost/latency limits, and the primary improvement metric. Derive numeric thresholds from the pilot and product requirements before viewing candidate results. Until those thresholds are approved, reports are observational and cannot authorize promotion.

| Trigger | Checks | Policy |
| --- | --- | --- |
| Every PR | Existing deterministic suites plus deterministic eval regression slice | Required; credentials unnecessary; critical defects and required missing evidence block |
| Trusted integration changes | Small fixed live smoke through approved profiles | Credentialed runner isolated from untrusted fork code; failure blocks the relevant promotion, outage reports blocked |
| Scheduled | Repeated capability/regression comparison | Begin with a budgeted weekly run; increase cadence after measuring cost and value |
| Model, policy, harness upgrade or release | Paired baseline comparison plus restricted holdout | No critical violations; adequate coverage; frozen regression/non-inferiority and resource thresholds satisfied |

A gate has pass, fail or blocked/inconclusive states. Only pass authorizes advancement. Zero observed critical violations is a release condition, not a claim that risk is zero. Holdout results are for promotion review, not iterative tuning.

Do not expose credentials to arbitrary PR code or use privileged workflows to run untrusted changes. Required-check names and branch/release protection must actually be configured; a workflow file alone does not prevent merging. Archive the full comparison manifest and retain the previous baseline for rollback. Changing a grader requires regrading both sides and creating a new versioned comparison.

**9. Deferred control obligations and recovery scope**

The audited V2 branch retains 13 strict expected-failure obligations. Track each against affected cases and the production integration needed to close it. Never change an obligation to ENFORCED solely because an evaluation passes with synthetic evidence.

Specific known gaps include discovery/health evidence production, control-owned allowed retry policy, final-verifier session evidence, and checkpoint-proof production. The existing failure mapper does not authorize fallback. Unknown/incomplete execution cannot be replayed merely to obtain a cleaner evaluation.

Where safe recovery is not implemented, the case should expect refusal/attention, with a separate capability case describing the desired future recovery. Build new recovery only in a separately scoped control PR, then demonstrate its effect using EVAL-01. Evaluation instrumentation must not manufacture production evidence on behalf of missing producers.

**10. Failure-driven improvement and ownership**

Classify suspected root cause as model, harness/adapter, tool/provider, policy/control, environment, grader, task/fixture, or unknown. Allow multiple causes and confidence levels. Keep this diagnostic classification separate from the runtime `ExecutionError.error_class` vocabulary.

An approved Opus-class or equivalent analyst receives sanitized non-holdout failed traces read-only. It produces evidence-backed hypotheses, reproduction instructions and proposed cases. Its output is untrusted input: independent reproduction, oracle review and human PR approval precede inclusion. It never selects its own authoritative grader or edits accepted results.

Promotion lifecycle: failed trial → diagnosis proposal → independent reproduction → reviewed case/fixture/oracle → new immutable suite version → rerun baseline and candidate → explicit baseline promotion. Changing the suite never rewrites historical scores. Failed analysis is not a blocker for the core runner or deterministic CI.

Assign one maintainer to baseline and release decisions, one implementer to runner/evidence plumbing, and an independent reviewer to case oracles and proposal acceptance. Roles can be filled sequentially on a small team, but the proposing analyst must not be the final authority.

**11. Scheduling and completion**

Planning allowance for one developer with reviewer availability: roughly 4–6 working weeks, excluding unresolved V2 integration or upstream trace work. Treat this as a sequencing estimate, not a delivery commitment.

- Week 1: resolve baseline, add deterministic CI, implement the five-case runner.
- Week 2: trace completeness, independent graders, negative-control validation.
- Week 3: freeze the 30-case corpus and run budgeted live pilots.
- Week 4: paired reports, coverage/resource thresholds, release enforcement.
- Weeks 5–6: independently reviewed failure-derived case, hardening and handoff.

The immediate implementation scope is **PR 1, then the five-case vertical slice**. Avoid waiting for all 30 cases, a dashboard or an analysis agent before proving the evidence chain.

EVAL-01 is complete when a maintainer can reproduce a comparison from pinned manifests, inspect why each trial passed or failed, demonstrate that a seeded critical regression blocks advancement, and admit one failure-derived case through independent review without modifying the old suite. Supported Cloudeo paths have measured coverage; unsupported paths and remaining V2 obligations are explicitly reported. Runtime checkpoint promotion remains governed by the existing trust kernel.

Decisions to record before dependent implementation: canonical integration commit; live execution profiles and spend cap; holdout custodian/storage; comparison thresholds after the pilot. Proposed defaults elsewhere in this document can be implemented incrementally once development is authorized.
