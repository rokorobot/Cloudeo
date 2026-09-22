# Cloudeo Progress and Evidence

## v0.1.0 — Initial control loop

Implemented:

- FastAPI application
- local WSL execution
- SQLite run persistence
- mock Jev adapter
- mock Treg adapter
- OpenRouter Jev adapter
- local Treg CLI adapter
- route threshold
- verification threshold
- bounded retries
- escalation status

Initial mock test:

```text
status: passed
selected_tool: hunter
route_confidence: 0.94
verification_probability: 0.93
```

Audit history was persisted successfully through `GET /v1/runs`.

---

## First real Jev test

Configuration:

```text
Jev: real OpenRouter
Treg: mock
```

Observed:

```text
hunter:   0.95
tomba:    0.04
escalate: 0.01
```

Jev correctly rejected mock provider output:

```text
verification_probability: 0.02
```

Result:

```text
status: escalate
```

This proved real Jev routing and verification worked.

---

## Treg local integration

Local repository:

```text
/home/robert/treg
```

Treg CLI authenticated successfully against:

```text
https://treg.to
```

Observed account:

```text
logged_in: true
active_org: rokoroko
```

Initial Treg promotional balance:

```text
$1.00
```

---

## Real provider metadata

TryKitt:

```text
endpoint: trykitt.people.email.find
method: POST
price: $0.005/success
observed works: 100%
observed hit rate: 38%
observed latency: ~3.8 s
```

Required JSON body:

```json
{
  "fullName": "...",
  "domain": "...",
  "realtime": true
}
```

Tomba:

```text
endpoint: tomba.people.email.find
method: GET
price: $0.0089/success
observed works: 100%
observed hit rate: 29%
observed latency: ~6.3 s
```

Required query fields include:

```text
domain
full_name
```

---

## v0.1 adapter upgrade

Added Treg request support for:

- HTTP method
- query parameters
- JSON body

Tests remained green.

---

## First real dry run

Jev routing:

```text
trykitt:   0.97
tomba:     0.02
escalate:  0.01
route confidence: 0.96
```

Generated TryKitt command:

```text
uv run --project /home/robert/treg treg call
trykitt.people.email.find
--method POST
--data '{"fullName":"Erol Toker","domain":"trykitt.ai","realtime":true}'
```

Generated Tomba command:

```text
uv run --project /home/robert/treg treg call
tomba.people.email.find
--query domain=trykitt.ai
--query 'full_name=Erol Toker'
```

Dry-run output was intentionally rejected by Jev.

---

## First real paid provider execution

Jev selected:

```text
TryKitt = 0.97
```

TryKitt returned:

```json
{
  "fullName": "Erol Toker",
  "domain": "trykitt.ai",
  "email": "erol@trykitt.ai",
  "validIdentity": true,
  "validSMTP": true,
  "validity": "valid"
}
```

Initial Jev verification:

```text
0.81
```

Configured threshold:

```text
0.85
```

Result therefore retried Tomba.

Tomba returned:

```text
provider_capacity_unavailable
```

Final v0.1 result:

```text
status: escalate
```

Treg ledger confirmed:

```text
TryKitt charged: $0.005
Tomba charged: $0.000
remaining promotional balance: $0.995
```

---

## v0.1.1 — Deterministic validator layer

Added deterministic validation for verified work email.

Checks:

```text
email exists
domain matches
identity signal
name match
SMTP validation
validity / verification status
```

Added outputs:

```text
deterministic_status
deterministic_evidence
verification_source
```

Test suite:

```text
4 passed
```

---

## First successful v0.1.1 real run

Jev routing:

```text
trykitt:   0.97
tomba:     0.02
escalate:  0.01
route confidence: 0.96
```

TryKitt output:

```text
email: erol@trykitt.ai
validIdentity: true
validSMTP: true
validity: valid
```

Deterministic evidence:

```text
Email returned: erol@trykitt.ai
Email domain matches expected domain trykitt.ai.
Provider reported validIdentity=true.
Returned person matches Erol Toker.
Provider reported validSMTP=true.
Provider reported valid email status.
```

Outcome:

```text
status: passed
selected_tool: trykitt
deterministic_status: pass
verification_source: deterministic
verification_probability: 1.0
```

No Jev verification call was required after execution.

No Tomba fallback was required.

This is the first fully successful real Cloudeo run.


---

## v0.1.2.1 — Automatic discovery correction

Observed: full objective with person/domain literals produced 0 Treg matches; `work email` produced 55 matches and exposed `people.email.find`. v0.1.2.1 separates capability discovery text from runtime execution state and uses routed rows as capability anchors.

---

## v0.1.2.2 — Hardening

Added clean capability-query generation, terminal dry-run semantics, structured discovery evidence, and per-attempt execution economics. See `docs/08_V0122_HARDENING.md`.
