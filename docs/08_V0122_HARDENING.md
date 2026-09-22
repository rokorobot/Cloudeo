# v0.1.2.2 — Hardening

## Scope

No new subsystem is introduced in this release.

v0.1.2.2 hardens the proven automatic-discovery loop in four areas:

1. capability-query cleanup;
2. dry-run semantics;
3. discovery evidence;
4. execution economics.

## 1. Capability-query cleanup

Runtime entities remain separate from discovery language.

Example:

```text
User:
Find the verified professional email for Erol Toker at trykitt.ai

Discovery:
verified work email

Execution state:
person = Erol Toker
company_domain = trykitt.ai
```

The discovery query is stored in the run response.

## 2. Dry-run semantics

`dry_run=true` now ends after:

```text
discovery -> compatibility filtering -> Jev routing -> command construction
```

It does not:

- call a provider;
- invoke result verification;
- retry fallback providers.

The response status is `dry_run`.

One Jev routing decision is still expected: routing is part of what the dry run
is intended to inspect.

## 3. Discovery evidence

Each automatically discovered run now records:

- every catalog query attempted;
- count / total returned by Treg;
- selected discovery query;
- capability anchor;
- endpoints inspected;
- accepted/rejected decision;
- rejection reason;
- quoted USD cost when available.

This makes discovery failures explainable rather than returning only an empty
candidate list.

## 4. Execution economics

Each real attempt now records:

```text
quoted_cost_usd
reserved_cost_usd
settled_cost_usd
latency_ms
call_id
provider_requested
provider_served
idempotent_replay
```

Sources:

- quote: Treg catalog metadata;
- reservation: new Treg balance-ledger reserve row observed across the call;
- settlement: Treg CLI charge receipt on stderr, with ledger fallback;
- call ID: Treg CLI receipt;
- latency: measured around the actual provider call;
- provider: concrete catalog endpoint, overridden by routed response metadata if present.

Economics collection is best-effort. A metadata/ledger lookup failure must not
turn a successful provider result into a failed Cloudeo run.

## Evidence carried forward

The clean v0.1.2.1 real run:

```text
run_id: d9c38035-e4a9-4d8e-9cf0-9eaced231424
selected: trykitt.people.email.find
status: passed
deterministic validation: pass
pre-run Treg balance: $0.9945
post-run Treg balance: $0.9940
observed settlement: $0.0005
```

This demonstrated why quote/reservation and settlement need to be stored
separately.
