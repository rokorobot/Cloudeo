# 12 — Execution Request and Outcome (Proposal)

**Status:** Types, mappers, and dispatch implemented on
`feat/execution-contracts`, with the deviations recorded in the ADR-013
amendment (`02_DECISIONS.md`). Nothing is wired into `Controller.run()`. The
sketches below are the original proposal, kept for history.

**Inputs:** the merged `ExecutionBackend`/`TregExecutionBackend`
(`src/cloudeo/execution/`), the standalone UHP client (`src/cloudeo/uhp/`), and
the live evidence recorded on 2026-09-23 in `03_PROGRESS_AND_EVIDENCE.md`.

## 1. What exists today

| | Treg lane (merged) | UHP lane (standalone) |
| --- | --- | --- |
| Request | `ToolCandidate` + `dry_run` | `UHPTaskRequest` |
| Target | `treg_tool_id`, `method`, `query`, `body`, `provider`, `capability` | `harness_id`, `model` |
| Work description | implicit in endpoint and bound inputs | `input`, `instructions` |
| Budgets | `quoted_cost_usd` (recorded, not enforced); CLI timeout in config | `max_step`, `timeout_seconds`, `max_output_tokens` |
| Continuation | none | `previous_response_id` (same harness only) |
| Result | `ExecutionResult(output: str, economics)` | `UHPTaskResult` |
| Status | implicit: stdout, or `TREG_ERROR:` prefix | explicit: `in_progress`, `completed`, `failed`, `incomplete`, `cancelled` |
| Output | one text blob | list of output items, unknown types preserved, partial output on terminal states |
| Cost | `ExecutionEconomics` (USD quoted/reserved/settled, latency, `call_id`, providers, replay) | `usage` tokens, or `null` when unknown |
| Identity | `call_id` | `response_id`, `session_id`, actual `model`, fallback metadata, protocol version |
| Errors | `TregError` → prose in output | `UHPError` hierarchy; `error` object on failed results |

Common ground is small: attempt identity, terminal status, evidence, cost,
duration, error. Everything else is class-specific.

## 2. Proposed types

Illustrative Pydantic; field names are proposals.

```python
class DirectToolExecution(BaseModel):
    kind: Literal["direct_tool"] = "direct_tool"
    attempt_id: str
    candidate: ToolCandidate          # existing public model, unchanged
    dry_run: bool = False


class HarnessBudget(BaseModel):
    max_step: int | None = None
    timeout_seconds: int | None = None
    max_output_tokens: int | None = None


class HarnessTaskExecution(BaseModel):
    kind: Literal["harness_task"] = "harness_task"
    attempt_id: str
    profile_id: str | None = None     # reference only; profile lives in policy
    harness_id: str
    model: str | None = None          # None = harness default
    input: str | list[dict[str, Any]]
    instructions: str | None = None
    budget: HarnessBudget = HarnessBudget()
    previous_response_id: str | None = None
    store: bool = True


ExecutionRequest = Annotated[
    DirectToolExecution | HarnessTaskExecution,
    Field(discriminator="kind"),
]

ExecutionStatus = Literal[
    "completed", "failed", "incomplete", "cancelled", "in_progress", "dry_run"
]


class CostEvidence(BaseModel):
    economics: ExecutionEconomics | None = None   # USD ledger evidence (Treg)
    usage: dict[str, Any] | None = None           # token usage as reported (UHP)


class ExecutionError(BaseModel):
    source: Literal["treg", "uhp", "transport"]
    code: str
    message: str
    http_status: int | None = None
    detail: dict[str, Any] | None = None


class RuntimeIdentity(BaseModel):
    requested_harness_id: str | None = None
    echoed_harness_id: str | None = None   # None when the server did not echo it
    harness_base: str | None = None
    requested_model: str | None = None
    actual_model: str | None = None
    model_fallback: bool | None = None
    session_id: str | None = None
    response_id: str | None = None
    call_id: str | None = None             # Treg ledger call
    protocol_version: str | None = None


class ArtifactRef(BaseModel):
    uri: str
    media_type: str | None = None
    source: str


class ExecutionOutcome(BaseModel):
    attempt_id: str
    kind: Literal["direct_tool", "harness_task"]
    status: ExecutionStatus
    output_text: str | None               # text the validators read today
    evidence: list[dict[str, Any]] = []   # UHP output items / Treg raw record
    cost: CostEvidence = CostEvidence()
    duration_ms: int | None = None
    error: ExecutionError | None = None
    artifacts: list[ArtifactRef] = []     # empty until files are integrated
    runtime: RuntimeIdentity = RuntimeIdentity()
    native_result: TregNativeResult | UHPTaskResult | None = None
```

`TregNativeResult` would hold the raw stdout, the `TREG_ERROR` text if any, and
the economics object exactly as the Treg client produced them.

## 3. Mapping rules

| Source | `status` | Notes |
| --- | --- | --- |
| Treg stdout | `completed` | `output_text` = stdout |
| Treg `TregError` (normal run) | `failed` | `output_text` keeps `TREG_ERROR: …` so validators behave as today; `error.source = "treg"` |
| Treg dry run | `dry_run` | Dry-run exceptions still propagate, as today |
| UHP `completed` / `failed` / `incomplete` / `cancelled` / `in_progress` | same | `evidence` = `output` items unchanged; `output_text` = concatenated `output_text` parts, if any |
| UHP `UHPHTTPError` / `UHPProtocolError` | `failed` | `error.source = "uhp"`, code/status/detail preserved |
| UHP `UHPTransportError` | `failed` | `error.source = "transport"`; the task may still be running, so it is never recorded as `cancelled` |

Rules that hold throughout:

1. `status` is execution state only. Verification (deterministic validators and
   Jev) remains a separate step, and `completed` never means passed.
2. `incomplete` is kept distinct from `failed`, because a budget stop is usually
   worth continuing.
3. Partial output on `failed`, `incomplete`, and `cancelled` is kept in
   `evidence` and `native_result`.
4. Nothing is inferred. The live run returned no `metadata.harness_id`, so
   `echoed_harness_id` stays `None`. Usage stays `None` when the server reports
   none, rather than becoming zero. USD is never derived from tokens.

## 4. Backend shape

Keep one typed backend per execution class and add a thin dispatcher:

```python
class ExecutionBackend(Protocol[R]):
    async def execute(self, request: R) -> ExecutionOutcome: ...

class ExecutionDispatcher:
    direct: ExecutionBackend[DirectToolExecution]     # TregExecutionBackend
    harness: ExecutionBackend[HarnessTaskExecution]   # future UHPExecutionBackend

    async def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
        ...  # match on request.kind
```

The generic parameter types each backend; the discriminated request is what the
controller holds. A bare `ExecutionBackend[T]` with no common outcome would push
the Treg/UHP differences into the controller.

## 5. Where things live

- **ExecutionProfile** (which harness/model/budgets suit a task class) belongs to
  the routing/policy layer. It produces a `HarnessTaskExecution`; the request
  carries only `profile_id` for traceability.
- **harness_id, model, and budgets** live on `HarnessTaskExecution`, not on
  `ToolCandidate`, `RunRequest`, or a shared base class.
- **Session binding:** a session is bound to one harness. The component issuing
  continuations must pass the same `harness_id` it used before; it cannot rely on
  the server echoing it. A harness switch always starts a new session.

## 6. What flattening now would lose

- Harness and model identity, including requested vs actual model and fallback.
- Session and response IDs needed for continuation and cancellation.
- The `incomplete` vs `failed` vs `cancelled` distinction.
- Structured output items and future item types, which a single string drops.
- Token usage vs USD ledger economics. They measure different things.
- Treg's endpoint, method, and bound inputs, which a harness task has no
  equivalent for.

## 7. Suggested migration (not started)

1. Add the types, and have `TregExecutionBackend` return an `ExecutionOutcome`.
   The controller reads `output_text` and `cost.economics`, so the change is
   behavior-preserving. Existing tests pass unchanged, and payload-equivalence
   checks are rerun.
2. Add `UHPExecutionBackend` behind the dispatcher, tested with the mock
   transport only.
3. Decide how a routing decision produces a `HarnessTaskExecution` (profile
   selection). Only then add an optional, backwards-compatible attempt field to
   persisted results.

LongHorizon, Performance Memory, and dynamic Jev routing are out of scope for all
three steps.
