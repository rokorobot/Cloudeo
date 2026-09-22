# v0.1.2.1 — Discovery Query and Capability Fix

## Evidence

The first automatic discovery request returned zero candidates because the full objective contained runtime entity tokens (person and domain) that Treg's lexical search treated as search requirements.

A direct `work email` query returned the intended `people.email.find` routed capability and concrete provider children.

A second issue was identified: v0.1.2 anchored on the first concrete result, which could be an adjacent capability requiring inputs not present in state.

## Correction

```text
objective -> capability discovery text
state     -> execution arguments
routed Treg row -> capability anchor
concrete children -> compatibility filter -> Jev routing
```

BB, Browser Use, self-improvement, frontier-LLM escalation, and autonomous write actions remain out of scope.
