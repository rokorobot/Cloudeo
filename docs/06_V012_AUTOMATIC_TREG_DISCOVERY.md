# v0.1.2 — Automatic Treg Discovery

## Goal

Remove manual provider candidate construction from normal Cloudeo requests.

Before v0.1.2 the caller had to supply:

```text
TryKitt candidate
Tomba candidate
method
query/body
provider cost/reliability metadata
```

In v0.1.2 an empty `candidates` array means:

```text
objective
  ↓
Treg catalog search --json
  ↓
highest-ranked concrete capability
  ↓
Treg catalog get --json for matching providers
  ↓
required-input compatibility filter
  ↓
automatic query/body binding from state
  ↓
Jev provider decision
```

## Responsibility boundary

Treg answers:

```text
What tools exist?
What does each tool do?
What inputs does it require?
What does it cost?
What has Treg observed about reliability/hit rate/latency?
```

Cloudeo answers:

```text
Which compatible provider should handle this objective?
Should the result be accepted, retried, or escalated?
```

Routed `treg.*` parent endpoints are deliberately excluded from the
candidate set because v0.1.2 is testing Cloudeo's own provider routing.

## Safety constraints

v0.1.2 only auto-builds endpoints that fit the current execution adapter:

- concrete endpoints
- query parameters
- JSON request bodies
- no required path parameters
- no required header parameters
- all required inputs resolvable from request state or a single-value enum

Examples are never used as runtime values.

A provider with missing required inputs is discarded before Jev sees it.

## State aliases

The initial binder understands common semantic aliases, including:

```text
person → fullName / full_name
company_domain → domain
email → email
linkedin_url → LinkedIn/profile URL fields
```

It may also derive first/last name from `person`.

This is intentionally conservative and should grow through tested capability
adapters rather than unconstrained guessing.

## Exit criteria

A request such as:

```json
{
  "objective": "Find the verified professional email for Erol Toker at trykitt.ai",
  "state": {
    "person": "Erol Toker",
    "company_domain": "trykitt.ai"
  },
  "candidates": []
}
```

must be able to:

1. discover the relevant Treg capability,
2. identify compatible concrete providers,
3. construct their calls,
4. let Jev route between them,
5. execute the selected provider,
6. validate the result,
7. return discovery evidence in the response.

## Out of scope

Not part of v0.1.2:

- BB
- Browser Use
- self-improvement
- frontier-LLM escalation
- arbitrary path/header binding
- autonomous write actions
