# EVAL-01 baseline record (PR 1)

Plan: [EVAL-01_PLAN.md](EVAL-01_PLAN.md). Recorded 2026-10-31.

## Canonical baseline

| Candidate | Commit | Status |
| --- | --- | --- |
| `main` | `86e7361e9927ff8c0d100a351434b96c87476917` | Supported path; covered by CI from this PR |
| `feat/v2-profile-billing-policy` (V2 chain tip, 15 linear commits on `main`) | `7f8885538d884aded4bf5a4d3e87322402830e0d` | **Recommended** EVAL-01 target; not yet accepted or merged |

**Decision (owner, 2026-10-31):** the V2 chain is accepted and integrated into
`main` via `integrate/v2-control-chain`. The canonical EVAL-01 baseline is the
resulting `main` merge commit, recorded in `03_PROGRESS_AND_EVIDENCE.md` after
merge. EVAL-01 work targets `main`. Later baseline changes need a new record
here; scores from different baselines are never combined.

Remote freshness was checked on 2026-10-31: both refs above were the tips of
`origin/main` and `origin/feat/v2-profile-billing-policy`.

## Reproduced results (2026-10-31, clean clone, Python 3.12, uv 0.13.6, `uv sync --locked`)

| Commit | Job | Result |
| --- | --- | --- |
| `main` + this PR | core | 319 passed, 7 skipped (inventory) |
| `main` + this PR | longhorizon | 566 passed |
| `7f88855` | core | 548 passed, 8 skipped, 13 xfailed |
| `7f88855` | longhorizon | 800 passed, 13 xfailed |

These match the historical audit (566; 800 + 13 strict xfail).

## Test commands

```bash
# core: no optional extras
uv sync --locked --extra dev
uv run pytest -q --junitxml=junit.xml
uv run python scripts/ci_check_junit.py core junit.xml

# longhorizon: pinned LongHorizon-Harness (ff76d6a, ADR-016)
uv sync --locked --extra dev --extra longhorizon
uv run python -c "import lh_harness"
uv run pytest -q --junitxml=junit.xml
uv run python scripts/ci_check_junit.py longhorizon junit.xml

# environment manifest (commit, dirty state, interpreter, lock digest, packages)
uv run python scripts/ci_env_manifest.py <job> environment.json
```

CI (`.github/workflows/ci.yml`) runs both jobs on every PR and on pushes to
`main`, with a read-only token and no secrets, and uploads
`environment.json`, `junit.xml` and `summary.json` per job.

## Guarantees and negative controls

| Exit criterion | Mechanism | Verified |
| --- | --- | --- |
| No model credentials needed | Workflow has no secrets; all tests pass offline from external models | Clean clone, no credentials |
| Missing integration dependency fails its job | `import lh_harness` step; `longhorizon` inventory allows zero skips | Core report checked as `longhorizon` → fails with 7 unexpected skips |
| Strict XPASS fails | `xfail_strict = true` in `pyproject.toml` (V2C obligations already use `strict=True`) | Seeded passing xfail → `1 failed` |
| Unexpected or stale skips fail | `tests/expected_skips.json` compared both ways | V2 tip core run → fails on `test_orchestration_kernel_outcome` (see below) |
| Artifacts identify commit/environment | `environment.json` per job | Records commit, `dirty`, Python, `uv.lock` SHA-256, package versions and Git pins |

The V2 integration added `"::tests.test_orchestration_kernel_outcome"` to the
`core` inventory; without it the check failed, by design.

## Deferred-obligation inventory (V2 tip `7f88855`)

13 strict xfails in `tests/test_v2c_traceability.py`. None may become ENFORCED
because an evaluation passes with synthetic evidence (plan §9). Affected cases
are assigned as cases are written (PR 2–4).

| ID | Obligation (deferred) | Initial affected cases |
| --- | --- | --- |
| V2C-02 | No workspace write before an approved plan | Authorization: denied write, unapproved dispatch |
| V2C-04 | PROMOTED only from a real trust-kernel result | Checkpoints: valid promotion |
| V2C-06 | CODE_APPROVED evidence from deterministic runners and diff checks | Auditor evidence: missing producer evidence |
| V2C-08 | Project Memory in tracked documents, promoted with code | — |
| V2C-09 | Curator writes restricted to `memory_paths` at execution | Authorization: workspace escape |
| V2C-10 | Context Intake read-only with evidence-classified claims | — |
| V2C-12 | Fallbacks only on classified runtime/provider failures or discovery | Identity: hidden fallback; Recovery family |
| V2C-13 | Performance Memory and Jev only recommend, never select profiles | Routing: excluded profile |
| V2C-15 | Material deviations detected from diffs, audits, accounting | Billing: exhausted budget |
| V2C-17 | AUDITOR_ERROR beyond fallback conditions routed to attention | Auditor: malformed audit |
| V2C-19 | CheckpointProof from immutable Git objects | Checkpoints: race, accepted-state drift |
| V2C-20 | Final verifier gets a fresh read-only session with SessionEvidence | Auditor: reused session |
| V2C-22 | Accepted baseline observed from the Workspace Broker | Checkpoints: stale candidate |

## Follow-ups (non-blocking)

- `ruff check .` reports 15 pre-existing errors on `main`; lint is not a
  required CI check until they are fixed.
- Required-check names (`ci / core`, `ci / longhorizon`) must be set in branch
  protection for `main`; the workflow alone does not block merges.
- The plan links `EVAL-02_SCOPE.md`, which is not in the repository yet.

## Rollback

Revert this PR. It adds CI, two scripts, one inventory file, these docs, and
`xfail_strict = true`; no runtime code changes.
