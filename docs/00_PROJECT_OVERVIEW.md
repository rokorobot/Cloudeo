# Cloudeo — Project Overview

## Purpose

Cloudeo is a control plane for autonomous software.

It is not a chatbot, not a Jev wrapper, and not a GTM-only application. Its purpose is to coordinate decisions across models, tools, APIs, browsers, agents, and deterministic software while minimizing unnecessary expensive reasoning.

The core design principle is:

> Use deterministic software for facts that can be proven, Jev for fast probabilistic judgment, and frontier LLMs only for tasks that genuinely require reasoning.

## Core loop

```text
Goal / Event
    ↓
Decision layer
    ↓
Tool / Agent / Model selection
    ↓
Execution
    ↓
Deterministic validation
    ↓
Semantic verification if needed
    ↓
PASS / RETRY / ESCALATE
```

## Current implementation

Cloudeo v0.1.1 currently runs locally in WSL2 and provides:

- FastAPI control plane
- OpenRouter Jev integration
- Treg CLI integration
- deterministic routing thresholds
- deterministic validation for verified work-email results
- Jev fallback verification for inconclusive cases
- retry / fallback logic
- SQLite audit/run persistence
- mock Jev and mock Treg backends for safe testing
- real Jev + real Treg end-to-end execution

## Current environment

Primary development runtime:

```text
WSL2 Ubuntu
/home/robert/cloudeo/cloudeo-v0.1
```

Treg source:

```text
/home/robert/treg
```

Cloudeo API:

```text
http://127.0.0.1:18800
http://127.0.0.1:18800/docs
```

Treg CLI currently talks to:

```text
https://treg.to
```

## Current status

v0.1.1 has completed a real end-to-end provider execution successfully.

Observed successful path:

```text
Objective
  ↓
Jev selected TryKitt
  ↓
Treg executed trykitt.people.email.find
  ↓
TryKitt returned a verified email
  ↓
Cloudeo deterministic validator confirmed:
    email exists
    domain matches
    validIdentity=true
    person matches
    validSMTP=true
    validity=valid
  ↓
PASS
```

The successful result did not require a second Jev verification call.

## Product direction

Cloudeo is intended to become a reusable decision and verification layer for many verticals, including:

- GTM automation
- research agents
- software engineering agents
- browser automation
- customer support
- cybersecurity
- financial-event intelligence
- procurement
- robotics / higher-level behavior arbitration

GTM is a useful proving ground, but not the product boundary.

## Guiding principles

1. Prefer deterministic checks over probabilistic judgment when facts are explicit.
2. Prefer Jev over frontier LLMs for high-volume classification, routing, scoring, and verification.
3. Use frontier LLMs only when reasoning is genuinely necessary.
4. Log decisions, evidence, costs, latency, outcomes, and failures.
5. Keep tool providers behind adapters so Cloudeo is not tightly coupled to Treg.
6. Add autonomy incrementally: read → classify → decide → verify before allowing risky writes.
7. Optimize reliability first, then cost and latency.
