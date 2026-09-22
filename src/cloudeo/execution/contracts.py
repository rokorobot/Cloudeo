"""Backend-neutral execution request and outcome types.

Execution status describes runtime execution only. Verification is a separate
Cloudeo step, and no status here means the result is verified.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cloudeo.execution.base import ExecutionResult
from cloudeo.models import ExecutionEconomics, ToolCandidate
from cloudeo.uhp.models import UHPTaskRequest, UHPTaskResult


class DirectToolExecution(BaseModel):
    """A typed-tool call through Treg, with the existing candidate unchanged."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["direct_tool"] = "direct_tool"
    candidate: ToolCandidate
    dry_run: bool = False


class HarnessTaskExecution(BaseModel):
    """A UHP harness task. The UHP wire model is reused, not duplicated."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["harness_task"] = "harness_task"
    task: UHPTaskRequest

    @model_validator(mode="after")
    def harness_selected(self) -> HarnessTaskExecution:
        # The server default would hide which harness ran; selection belongs
        # to the caller, so an executable harness task must name one.
        if self.task.harness_id is None:
            raise ValueError("A harness task must name task.harness_id")
        return self


ExecutionRequest = Annotated[
    DirectToolExecution | HarnessTaskExecution,
    Field(discriminator="kind"),
]

# "unknown": Cloudeo could not observe the final runtime state, e.g. after a
# transport failure while the task may still be running.
ExecutionStatus = Literal[
    "in_progress",
    "completed",
    "failed",
    "incomplete",
    "cancelled",
    "dry_run",
    "unknown",
]


class ExecutionCost(BaseModel):
    """Separate cost forms; tokens are never converted to money."""

    # Left-to-right keeps a legacy dict a dict; smart mode would coerce it into
    # ExecutionEconomics and drop unknown keys.
    direct_tool_economics: Annotated[
        dict[str, Any] | ExecutionEconomics | None,
        Field(union_mode="left_to_right"),
    ] = None
    harness_usage: dict[str, Any] | None = None


class ExecutionError(BaseModel):
    source: Literal["treg", "uhp_task", "uhp_http", "uhp_protocol", "uhp_transport"]
    message: str
    code: str | None = None
    error_type: str | None = None
    http_status: int | None = None
    param: str | None = None
    detail: Any = None
    body: Any = None
    protocol_version: str | None = None


class RuntimeIdentity(BaseModel):
    """Requested and observed identity; observed fields stay None unless returned."""

    backend: Literal["treg", "uhp"]
    requested_tool: str | None = None
    requested_harness: str | None = None
    actual_harness: str | None = None
    requested_model: str | None = None
    actual_model: str | None = None
    model_fallback: bool | None = None
    response_id: str | None = None
    session_id: str | None = None
    protocol_version: str | None = None


class ExecutionOutcome(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    kind: Literal["direct_tool", "harness_task"]
    status: ExecutionStatus
    output_text: str | None = None
    # Treg stdout verbatim, or UHP output items verbatim (unknown types kept).
    raw_output: str | list[dict[str, Any]] | None = None
    cost: ExecutionCost = Field(default_factory=ExecutionCost)
    duration_ms: int | None = None
    error: ExecutionError | None = None
    # No backend reports artifacts to Cloudeo yet; kept empty, never inferred.
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    runtime: RuntimeIdentity
    native_result: ExecutionResult | UHPTaskResult | None = None
