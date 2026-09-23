# Cloudeo

> **Run autonomous AI work. Verify every result.**

Cloudeo is a **control and trust layer for autonomous AI work**.

Give Cloudeo an objective. It can select how the work should be handled, route it to the appropriate tool or executor, observe the result, verify what actually happened, preserve evidence, recover when necessary, checkpoint proven state, and only promote results that satisfy the verification boundary.

**Cloudeo makes AI agents prove their work.**

---

## Why Cloudeo

AI agents are becoming increasingly capable at coding, browsing, research, data operations, and long-running computer work.

But there is still a fundamental problem:

> An agent saying **"done"** is not the same as proving that the work is correct.

Most agent systems concentrate on execution:

```text
Goal → Agent → Action → Result
```

Cloudeo adds a control loop around execution:

```text
Objective
   ↓
Decide / Route
   ↓
Execute
   ↓
Verify
   ↓
Recover / Retry
   ↓
Prove
   ↓
Checkpoint
   ↓
Promote
```

The model, tool, or executor can change.

The trust model should not.

---

## What Cloudeo Is

Cloudeo is infrastructure for coordinating autonomous work across different tools and execution systems while applying a common control, evidence, verification, and promotion layer.

It is designed to sit around systems such as:

- coding agents
- browser and computer-use agents
- LLMs
- APIs
- CLI tools
- workflow engines
- data/provider tools
- specialized autonomous systems

Examples of execution backends may include Claude Code, Codex, Browser Use, shell workers, UHP-compatible harnesses, API-driven workers, or future agents.

Cloudeo does **not** try to replace those systems.

It controls how work is selected, executed, verified, recovered, checkpointed, and accepted.

---

## The Cloudeo Thesis

The agent ecosystem does not need one universal agent that is best at everything.

It needs infrastructure that can coordinate specialized systems **without blindly trusting them**.

The future stack may contain many models, agents, browsers, APIs, tools, and autonomous workers.

Cloudeo is being built as the layer that determines:

```text
What should perform this work?
Did the intended work actually happen?
Can the result be proven?
Should this state be accepted?
What should happen if verification fails?
```

---

## Core Principle: Proof, Not Promises

Cloudeo does not treat an executor's self-reported success as sufficient evidence.

For repository-based autonomous work, the verified promotion path is:

```text
Work
  ↓
Audit
  ↓
VERIFIED
  ↓
Recheck exact candidate state
  ↓
Create immutable checkpoint
  ↓
Verify checkpoint independently
  ↓
Promote accepted state
```

Promotion is refused if, for example:

- the candidate state changed after audit;
- the candidate `HEAD` no longer matches the audited `HEAD`;
- accepted state moved unexpectedly;
- verification evidence is missing or malformed;
- the audit identity does not match the candidate;
- a repaired report is presented as verification authority;
- the immutable checkpoint differs from the audited state.

The system is designed to **fail closed**.

---

# Architecture

A simplified view of the intended system:

```text
                         ┌──────────────────────┐
                         │      Objective       │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │   Cloudeo Manager    │
                         └──────────┬───────────┘
                                    │
                     ┌──────────────┴──────────────┐
                     │                             │
                     ▼                             ▼
            ┌────────────────┐            ┌────────────────┐
            │ Decision/Policy│            │ State / Memory │
            │                │            │                │
            │ Jev            │            │ WorkOrders     │
            │ Routing        │            │ Evidence       │
            │ Scoring        │            │ Checkpoints    │
            └───────┬────────┘            └────────────────┘
                    │
                    ▼
        ┌──────────────────────────────┐
        │          Executors           │
        │                              │
        │ Direct tools · APIs · CLI    │
        │ Coding agents · Browser Use  │
        │ UHP harnesses · future agents│
        └──────────────┬───────────────┘
                       │
                       ▼
              ┌──────────────────┐
              │     Auditor      │
              └────────┬─────────┘
                       │
                       ▼
              ┌──────────────────┐
              │ Normalized Proof │
              └────────┬─────────┘
                       │
                       ▼
              ┌──────────────────┐
              │ Promotion Gate   │
              └────────┬─────────┘
                       │
              ┌────────┴─────────┐
              │                  │
              ▼                  ▼
        Refuse / Recover     Checkpoint
                                   │
                                   ▼
                                Verify
                                   │
                                   ▼
                                Promote
```

---

## Jev's Role

Jev is a **decision engine**, not the autonomous worker.

Cloudeo uses or intends to use Jev for bounded, high-frequency decisions such as:

- classification;
- routing;
- candidate scoring;
- compatibility decisions;
- probabilistic verification when deterministic proof is unavailable.

Jev returns structured decisions and probabilities rather than carrying out arbitrary work itself.

That separation is deliberate:

```text
                 ┌───────────────┐
Objective ──────►│ Cloudeo       │
                 │               │
                 │ Jev: decide   │
                 └───────┬───────┘
                         │
                         ▼
                  choose executor
                         │
             ┌───────────┼───────────┐
             ▼           ▼           ▼
           Treg        Browser      Agent
           tool          Use       harness
```

Deterministic software remains responsible for policy and state transitions.

---

## Treg's Role

Treg is the tool/data plane for direct external-provider operations.

Cloudeo can use Treg for:

- provider discovery;
- provider metadata;
- credential-backed external tools;
- read/search/enrichment operations;
- direct tool execution.

Treg remains behind a Cloudeo adapter boundary.

If a run request does not provide candidate tools, the controller can discover candidates from the Treg catalog before routing.

The conceptual direct-tool path is therefore:

```text
Objective
   ↓
Treg capability discovery
   ↓
Candidate filtering
   ↓
Jev routing
   ↓
Treg execution
   ↓
Deterministic validation
   ↓
Jev verification when needed
   ↓
PASS / retry / ESCALATE
```

---

# Core Capabilities

## 1. Execution abstraction

Different tools and agents can operate behind explicit execution contracts.

Cloudeo already distinguishes direct tool execution from harness-style execution rather than flattening both into one generic task model.

The execution layer can therefore evolve toward:

```text
                      ┌─ Treg / direct tool
                      ├─ API worker
Objective → Cloudeo ──┼─ CLI / shell
                      ├─ coding agent
                      ├─ Browser Use
                      ├─ UHP harness
                      └─ future executor
```

The executor performs the work.

Cloudeo owns the control and acceptance boundary.

---

## 2. Deterministic validation first

Structured facts should be validated in deterministic code before spending a model call on probabilistic verification.

```text
provider output
    ↓
deterministic validation
    ├── pass
    ├── fail
    └── inconclusive
            ↓
           Jev
```

A transport or provider failure is also a deterministic failure and should not consume a Jev verification call.

This keeps the high-frequency decision layer focused on questions that actually require probabilistic judgment.

---

## 3. Independent verification

Execution and verification are separate responsibilities.

The component that performed the task should not be the sole authority deciding whether the task succeeded.

For long-horizon repository work, Cloudeo normalizes auditor results into structured verification states:

```text
VERIFIED
NOT_VERIFIED
BLOCKED
AUDITOR_ERROR
```

A repaired audit report may restore formatting, but it can never become verification authority.

The original audit must itself support verification.

---

## 4. Evidence-preserving checkpoints

Verified work can be captured as an immutable checkpoint before promotion.

The checkpoint is independently checked against the audit evidence.

This creates a durable boundary between:

```text
what the agent claimed
```

and:

```text
what Cloudeo can prove existed
```

A checkpoint that is created but later refused is preserved as forensic evidence rather than silently destroyed.

---

## 5. Safe promotion

Accepted state advances only through the promotion gate.

The gate checks, in order:

```text
original VERIFIED result
        ↓
audit identity
        ↓
accepted state
        ↓
candidate HEAD
        ↓
current content hash
        ↓
checkpoint
        ↓
checkpoint parent
        ↓
checkpoint content hash
        ↓
broker promotion
```

The broker's own promotion checks remain authoritative.

No shortcut can silently promote stale or changed work.

---

## 6. Long-horizon recovery

Cloudeo is being built for work that may require many steps instead of a single prompt-response cycle.

The intended loop is:

```text
Plan
  ↓
Act
  ↓
Verify
  ↓
Checkpoint or Recover
  ↓
Repeat
```

This makes progress explicit and allows failures to become recoverable state transitions rather than silent corruption of accepted state.

---

# Current Status

Cloudeo is under active development.

## Implemented foundations

Current foundations include:

- local controller and HTTP service;
- mock and real Jev integration;
- Treg integration;
- automatic Treg candidate discovery;
- direct-tool execution abstraction;
- UHP-native client;
- discriminated direct-tool and harness execution contracts;
- execution dispatcher;
- Workspace Broker and canonical accepted state;
- LongHorizon integration;
- workspace executor;
- workspace auditor;
- audit-result normalization;
- immutable candidate checkpointing;
- verified checkpoint promotion;
- promotion-race defenses;
- structured promotion outcomes;
- evidence preservation after post-checkpoint refusal;
- extensive offline tests around the current trust boundary.

The **Verified Checkpoint & Promotion Gate** milestone is complete.

Current gated promotion results distinguish:

```text
refused_before_checkpoint
refused_after_checkpoint
promoted
checkpoint_created
```

The exact audited state is rechecked before checkpoint creation.

The immutable checkpoint is then independently verified before accepted state can advance.

---

## Current trust boundary

For repository work, the present proof covers Git-visible candidate state:

- tracked files;
- untracked non-ignored files;
- file paths;
- file contents;
- executable state.

It does **not** currently prove arbitrary external runtime state such as:

- ignored `.env` files;
- environment variables;
- caches;
- remote services;
- undeclared external dependencies;
- other state outside the audited workspace.

Those limits are explicit by design.

For the original direct-tool service, the conservative policy remains:

> Treat the current prototype as suitable for read/search/enrichment-style operations, not irreversible or consequential actions.

Human approval and explicit action policy are required before expanding into high-risk write operations.

---

# Running Cloudeo Today

## Requirements

- Ubuntu / WSL2
- Python 3.12+
- `uv`
- a cloned Treg repository for real Treg execution
- an OpenRouter API key for real Jev execution

The project runs in **mock mode by default**, allowing the control loop to be tested without provider credentials.

---

## Install locally

A typical local checkout can be installed with:

```bash
uv sync --extra dev
cp .env.example .env
```

The LongHorizon-Harness integration is optional.

The repository currently pins the LongHorizon integration to upstream v0.1.7, commit:

```text
ff76d6a
```

Install that extra with:

```bash
uv sync --extra dev --extra longhorizon
```

---

## Zero-cost local smoke test

Leave the mock defaults in `.env`:

```env
CLOUDEO_JEV_BACKEND=mock
CLOUDEO_TREG_BACKEND=mock
```

Start Cloudeo:

```bash
uv run cloudeo
```

Then from another terminal:

```bash
curl -s http://127.0.0.1:18800/health | python -m json.tool

curl -s http://127.0.0.1:18800/v1/runs \
  -H 'Content-Type: application/json' \
  --data @scripts/demo.json | python -m json.tool
```

The repository also provides:

```bash
scripts/smoke.sh
```

A successful mock run should produce a passed result, a selected mock tool, and verification above the configured threshold.

---

## Turn on real Jev through OpenRouter

OpenRouter exposes Jev through the Decisions endpoint rather than the normal chat-completions interface.

Configure `.env`:

```env
CLOUDEO_JEV_BACKEND=openrouter
OPENROUTER_API_KEY=your_key_here
CLOUDEO_JEV_MODEL=typesafe/jev-1.13
CLOUDEO_JEV_URL=https://openrouter.ai/api/alpha/decisions
```

Restart:

```bash
uv run cloudeo
```

A direct Jev decision can be tested with:

```bash
curl -s http://127.0.0.1:18800/v1/decide \
  -H 'Content-Type: application/json' \
  -d '{
    "state": {
      "ticket": "Checkout is blank after clicking Pay"
    },
    "questions": {
      "is_bug": {
        "type": "noul",
        "instructions": "Is the customer reporting a software defect?",
        "criteria": {
          "true": "Broken behavior",
          "false": "Not broken behavior"
        }
      }
    }
  }' | python -m json.tool
```

---

## Connect a local Treg clone

Point Cloudeo to the cloned `rokorobot/treg` repository:

```env
CLOUDEO_TREG_BACKEND=cli
CLOUDEO_TREG_REPO=/home/robert/treg
```

A Windows-hosted clone can be addressed through WSL, for example:

```env
CLOUDEO_TREG_REPO=/mnt/c/Users/Robert/treg
```

Cloudeo invokes catalog tools through the Treg CLI:

```bash
uv run --project "$CLOUDEO_TREG_REPO" treg call <tool-id> --query key=value ...
```

Treg itself must already be configured for any real providers being used.

For a safe first check of real Jev plus real Treg command construction without actually executing the Treg call, use:

```json
{
  "dry_run": true
}
```

in the relevant run payload.

If no candidate tools are supplied, Cloudeo can discover candidates from the Treg catalog before routing.

---

## Run tests

```bash
uv run pytest -q
```

---

# HTTP API

Current service endpoints include:

```text
GET  /health
POST /v1/decide
POST /v1/runs
GET  /v1/runs
GET  /docs
```

### `GET /health`

Reports current service/back-end information.

### `POST /v1/decide`

Direct Jev decision primitive.

### `POST /v1/runs`

Runs the Cloudeo route → execute → validate/verify loop.

### `GET /v1/runs`

Returns recent local run/audit records.

### `GET /docs`

FastAPI interactive documentation.

The long-horizon workspace executor, auditor, normalization, broker, and promotion-gate components currently exist primarily as library/control-plane code and are not yet exposed as the completed HTTP orchestration path.

---

# Routing Policy

Current prototype defaults include:

```env
CLOUDEO_ROUTE_CONFIDENCE=0.65
CLOUDEO_VERIFY_PROBABILITY=0.85
CLOUDEO_MAX_ATTEMPTS=2
```

These are **prototype values, not production safety thresholds**.

Real thresholds should be calibrated on labeled examples for each workflow rather than globally lowered to hide false negatives.

---

# Example Use Cases

## Autonomous software engineering

A coding agent can modify a repository over an extended period.

Cloudeo can:

1. maintain the work objective;
2. create or identify candidate state;
3. execute through an appropriate worker;
4. independently audit the result;
5. normalize the verification evidence;
6. reject stale or inconsistent verification;
7. checkpoint the exact verified candidate;
8. independently verify the immutable checkpoint;
9. promote only proven state.

---

## Browser and web operations

Browser Use can become an execution backend while Cloudeo remains the control and verification layer:

```text
Objective
   ↓
Decision / routing
   ↓
Browser executor
   ↓
Observed result
   ↓
Independent verification
   ↓
Evidence
   ↓
Accept / recover / escalate
```

Jev can support action selection, classification, routing, scoring, or verification within that control loop without being the browser executor itself.

---

## Multi-executor workflows

Different stages can use different systems:

```text
Research tool
     ↓
Coding agent
     ↓
Browser executor
     ↓
Independent auditor
     ↓
Promotion gate
```

Cloudeo provides the common state and trust layer between them.

---

## Long-running autonomous work

A task may require dozens or hundreds of actions.

Instead of assuming that every previous action remains valid, Cloudeo can repeatedly apply:

```text
Act → Verify → Checkpoint → Continue
```

Failures therefore become explicit recovery decisions rather than silent changes to accepted state.

---

# Design Principles

**Verification authority must be independent.**\
The executor should not be the sole authority deciding whether its own work succeeded.

**State must be explicit.**\
Critical state should be represented structurally rather than inferred from conversational prose.

**Deterministic proof comes before probabilistic judgment.**\
If software can establish a fact directly, use that before asking a model to estimate it.

**Promotion must be harder than execution.**\
Agents may try many things. Only proven outcomes should become accepted state.

**Race conditions are part of the trust model.**\
Verification is meaningless if the candidate can change between audit and acceptance.

**Evidence should survive failure.**\
A refused checkpoint may still be valuable forensic evidence.

**Executors should remain replaceable.**\
Claude, Codex, Browser Use, APIs, UHP harnesses, local models, and future systems should be able to evolve independently of Cloudeo's trust layer.

**Decision engines and executors are different roles.**\
Jev decides; execution backends act.

---

# Roadmap

The immediate engineering sequence is:

```text
Verified checkpoint & promotion gate
                ✓
                │
                ▼
Manager → promotion-gate integration
                │
                ▼
Live end-to-end execution proof
                │
                ▼
Rejection / cleanup lifecycle
                │
                ▼
Performance Memory
                │
                ▼
Browser Use executor integration
                │
                ▼
Multi-executor routing and optimization
```

## Next: manager integration

The next bounded milestone is connecting `manager.run()` to the completed promotion gate without weakening the existing trust boundary.

The manager should orchestrate execution and auditing.

The promotion gate remains authoritative for whether verified work can advance.

Known manager-integration issues include the existing auditor-error behavior, format-repair interaction, and workspace-path mismatch.

These should be resolved at the orchestration boundary rather than by weakening the promotion gate.

---

## Live end-to-end proof

The current checkpoint/promotion proof is offline.

A subsequent milestone should demonstrate the complete execution → audit → verification → checkpoint → promotion path against a live harness environment while preserving the same evidence boundary.

---

## Rejection and cleanup lifecycle

Post-checkpoint refusals intentionally keep checkpoints as evidence today.

A later lifecycle layer should define explicit policy for:

- retained refused checkpoints;
- rejection state;
- cleanup;
- evidence retention;
- candidate expiration.

That policy should remain separate from the verification gate.

---

## Performance Memory

Cloudeo is intended to learn from structured execution history only after sufficient evidence exists.

Useful signals include:

- task class;
- selected executor;
- decisions and probabilities;
- provider;
- latency;
- cost;
- success/failure;
- retries;
- validation evidence;
- recovery paths;
- human corrections;
- verification outcomes.

Performance Memory can eventually improve:

- executor selection;
- routing;
- recovery strategy;
- cost/latency tradeoffs;
- reliability estimates;
- verification policy.

Learning from history must not make the executor its own verification authority.

---

## Other planned work

Additional planned capabilities include:

- frontier-model escalation when bounded decision logic is insufficient;
- explicit action policy for read/write/high-risk operations;
- run and evidence timeline UI;
- evaluation datasets;
- threshold-calibration tooling;
- richer declared-input verification beyond Git-visible workspace state.

---

# Project Documentation

The repository's detailed architectural decisions and evidence live under `docs/`.

Important entry points include:

```text
docs/00_PROJECT_OVERVIEW.md
docs/01_ARCHITECTURE.md
docs/02_DECISIONS.md
docs/03_PROGRESS_AND_EVIDENCE.md
docs/04_ROADMAP.md
docs/05_DEVELOPMENT_WORKFLOW.md
```

The root README is intentionally the product and contributor entry point.

The ADRs remain the authority for detailed design constraints and historical decisions.

---

# Cloudeo Is Not Another Agent

Cloudeo is not intended to compete with every coding agent, browser agent, or foundation model.

Those systems can become execution backends.

```text
Claude Code    ─┐
Codex          ─┤
Browser Use    ─┤
UHP harnesses  ─┼──► Cloudeo control + verification layer
CLI tools      ─┤
APIs           ─┤
Future agents  ─┘
```

Jev occupies a different role:

```text
Jev ──► decision / routing / scoring / probabilistic verification
```

Agent capabilities will change.

Models will change.

Browser automation will change.

Cloudeo's job is to provide a stable layer for:

**decision → routing → execution → evidence → verification → recovery → checkpoint → trusted promotion**

---

## In One Sentence

> **Cloudeo is the control and trust layer that lets autonomous AI systems do real work without asking you to blindly trust that they did it correctly.**

---

> **Run autonomous AI work. Verify every result.**

> **Cloudeo makes AI agents prove their work.**
