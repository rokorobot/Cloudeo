# Cloudeo Development Workflow

## Why this file exists

Cloudeo development should not depend on chat history.

Every meaningful change should update the repository documentation so another coding agent or developer can continue without reconstructing context.

## Recommended repo structure

```text
cloudeo/
├── README.md
├── pyproject.toml
├── src/
├── tests/
├── scripts/
└── docs/
    ├── 00_PROJECT_OVERVIEW.md
    ├── 01_ARCHITECTURE.md
    ├── 02_DECISIONS.md
    ├── 03_PROGRESS_AND_EVIDENCE.md
    ├── 04_ROADMAP.md
    └── 05_DEVELOPMENT_WORKFLOW.md
```

## Rule for each milestone

Before changing code:

1. define the milestone
2. state the architectural intent
3. state expected behavior
4. define test/exit criteria

After changing code:

1. run tests
2. record real evidence
3. update architecture if behavior changed
4. add an ADR for important design decisions
5. update roadmap status
6. commit code and docs together

## Suggested commit style

Examples:

```text
feat(control): add deterministic validation layer
feat(treg): support POST bodies and query params
feat(discovery): add Treg catalog candidate generation
docs(architecture): document validator pipeline
test(validation): cover verified work-email results
```

## Evidence discipline

Do not document only intended behavior.

Record what actually happened.

Example:

```text
Expected:
TryKitt result should verify.

Observed v0.1:
Jev verification = 0.81
threshold = 0.85
result = retry

Change:
added deterministic validator

Observed v0.1.1:
deterministic_status = pass
verification_source = deterministic
result = passed
```

This creates an engineering record rather than a narrative.

## Version discipline

Current:

```text
0.1.1
```

Suggested meaning:

```text
0.1.x = local control-plane MVP
0.2.x = reasoning escalation
0.3.x = browser/worker execution
0.4.x = persistent work orders
0.5.x = optimization/history
```

## Agent handoff

Any coding agent should first read:

```text
docs/00_PROJECT_OVERVIEW.md
docs/01_ARCHITECTURE.md
docs/02_DECISIONS.md
docs/04_ROADMAP.md
```

Then inspect:

```text
git status
git log --oneline -10
pytest
```

The agent should not infer architecture only from source code.

## Definition of done

A milestone is done only when:

```text
implementation complete
tests green
real or representative execution verified
docs updated
important decisions recorded
roadmap updated
```
