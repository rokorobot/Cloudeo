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


---

## 2026-09-22 — v2 execution foundation

Implemented an internal asynchronous `ExecutionBackend` contract and
`TregExecutionBackend`. The controller accepts an optional backend and uses it
for normal execution and dry-run preparation. Existing callers default to the
Treg wrapper; discovery remains on the existing Treg client.

`UHPExecutionBackend` is not implemented yet. No HarnessRouter, LongHorizon,
Performance Memory, new dependency, configuration, API schema, or database
schema was introduced. Routing and verification remain unchanged.

Validation:

- `UV_NO_SYNC=1 UV_OFFLINE=1 uv run pytest -q`: **33 passed** (15 existing tests
  unchanged, 18 new execution-boundary regression cases).
- Ruff checks pass for the new execution package and test files.
- Compared the baseline controller at `c4db48d` with the refactor through an
  in-memory SQLite/mock HTTP harness: success, dry run, no candidates, provider
  failure, and dry-run failure. HTTP responses, history, persisted request/result
  JSON, and SQLite schema matched after normalizing UUIDs/timestamps. Dry-run
  failure still returns HTTP 502. No external service was called.
- External behavior remains unchanged for the tested paths; existing public
  models, API wiring, adapters, validators, configuration, and database code
  are unchanged.

Known legacy limitations deliberately preserved: shared/stale execution economics,
duplicate candidate ranking, and unknown Jev choice lookup in dry-run. These
remain separately scoped work, not fixes bundled into the extraction.


---

## 2026-09-22 — UHP client foundation (standalone)

Added an internal `cloudeo.uhp` package (`client.py`, `models.py`) built on the
existing `httpx`/`pydantic` dependencies. It is not wired into the controller:
`Controller.run()`, `TregExecutionBackend`, `ToolCandidate`, Jev routing,
verification, `RunRequest`/`RunResponse`, configuration, and the database schema
are unchanged. The v0.1 path remains Objective → Jev → Treg → verification →
SQLite.

Protocol source: UHP `2026-09-12`, checked against the machine-readable
`protocol/schema/uhp-2026-09-12.schema.json` and OpenAPI file in
HarnessRouter/harnessrouter at `v0.23.7` (`809392d602e34e36f0468943035c54d3350af885`).
Every request sends `UHP-Version: 2026-09-12`; a successful response whose
`UHP-Version` header is missing or different is rejected as a protocol error.

Validation:

- `uv run pytest -q`: **67 passed** (33 existing unchanged, 34 new mock-transport
  UHP cases in `tests/test_uhp_client.py`). No Docker or network required.
- Ruff checks pass for the new package, tests, and `dev/uhp_smoke.py`.

HarnessRouter CE local development instance (`dev/harnessrouter.compose.yaml`):

- Image `harnessrouter/harnessrouter@sha256:d8794a4cbaaac8920548b2e1474e84d9c54e754119f700d2817765ec89837ced`
  (Docker Hub tag `0.23.7`; source tag `v0.23.7` = commit `809392d`).
- Bound to `127.0.0.1:18810` only; named volume `cloudeo-harnessrouter-dev-data`
  at `/data`; `restart: "no"`; backends `codex,claude` with Codex `0.154.0` and
  Claude Code `2.1.280` pinned. Runs under Docker Desktop on the Windows host and
  is reachable from WSL at the same loopback address.

Live discovery through `UHPClient` (`GET /v1/uhp`, unauthenticated):

- Implementation: HarnessRouter Community Edition `0.23.7`.
- Versions `2026-09-12`, `2026-08-11`; default `2026-09-12`; conformance class
  `full`; response header `UHP-Version: 2026-09-12`.
- Capabilities all `true`: streaming, sessions, cancellation, files_input,
  files_output, session_listing, harness_management, session_sharing,
  idempotency, plugins.

Not yet proven: `GET /v1/harnesses` returns HTTP 401 without a HarnessRouter API
key. The CE body is `{"detail":"sign in to continue"}` with no UHP error
envelope and no `UHP-Version` header (the client preserved it as `http_error`
with `protocol_version=None`). Harness/model discovery, a live task, and the
two-harness proof are blocked on a Console-created API key and provider
credentials for Codex and Claude Code. No live task has been run.


---

## 2026-09-23 — UHP live execution evidence

Operator-run smoke with `dev/uhp_smoke.py` against the local HarnessRouter CE
`0.23.7` instance (`http://127.0.0.1:18810/api/harness`), UHP `2026-09-12`,
using a Console-created HarnessRouter API key held only in the operator's shell.
No key or provider credential is recorded here or in Git. This supersedes the
"Not yet proven" note in the previous entry.

| Check | Result |
| --- | --- |
| Authenticated discovery (`/v1/harnesses`, harness models) | **PASS** |
| Claude Code live task | **PASS** (runtime `completed`) |
| Codex live task | **BLOCKED_EXTERNAL** (OpenAI provider quota) |

Claude Code live task (`Reply with exactly: CLOUDEO_UHP_OK`, new session):

- Harness `chrn_56a17d779ea643e9b2924aaa1e86e175` (`Cloudeo-claude`, base
  `claude-code`); model `claude-opus-5`.
- Status `completed`; output `CLOUDEO_UHP_OK`.
- Response `resp_c44edf543ff64daeb0d119c8c6f64ca8`; session
  `hsess9f7d54617d284c8d89a64886e1371b92`.
- Response `UHP-Version: 2026-09-12`; client-measured duration 5.21 s.
- `actual_harness: null` — HarnessRouter did not echo `metadata.harness_id` on
  the response. This is observed server metadata behavior; Cloudeo must record
  the requested harness and must not infer an actual one.

`completed` is runtime completion only. It is execution evidence, not Cloudeo
verified success, and nothing was written to Performance Memory (which does not
exist yet).

Codex live task:

- Harness `chrn_bdbb7e0349a14734a2bdc7d57ba81f22` (`Cloudeo - OpenAI`, base
  `codex`); model `gpt-5.5`.
- The UHP task created a real Codex session and rollout, then failed with
  `Reconnecting... 1/5`.
- A direct OpenAI Responses API request with the same OpenAI account returned
  `type: insufficient_quota`, `code: credit_balance_exhausted`,
  `message: You have no credits remaining.`
- Classification: **BLOCKED_EXTERNAL / provider quota**. This is not a Cloudeo,
  UHP client, HarnessRouter, or Codex implementation failure. Paid OpenAI
  requests are not retried until credit is restored.

Two-harness proof status: one harness (Claude Code) proven end to end; the
Codex path reaches the runtime but is blocked by the provider account.
