"""The accepted baseline, observed from the Workspace Broker (ADR-030, V2C-22).

Reads only the broker's public accepted_state() and returns the observation;
its accepted_commit is what the control layer's accepted_baseline= parameters
take. Drift detection stays in cloudeo.control.

Limitation: this proves what the supplied broker reports as accepted state. It
does not prove that the broker belongs to the WorkOrder's project; that binding
waits for the ProjectTarget model (contract §4.1).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from cloudeo.control.model import EvidenceRef, WorkOrder
from cloudeo.workspace.broker import WorkspaceBroker
from cloudeo.workspace.models import CommitSha, Identifier


class BaselineWorkspaceMismatch(ValueError):
    """The broker reports a different workspace than the WorkOrder's candidate."""


class ObservedBaseline(BaseModel):
    """What the broker reported as accepted state when it was asked."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: Identifier
    accepted_commit: CommitSha

    @property
    def evidence(self) -> EvidenceRef:
        return EvidenceRef(
            kind="broker_accepted_state", ref=f"{self.workspace_id}@{self.accepted_commit}"
        )


def observe_accepted_baseline(
    broker: WorkspaceBroker, work_order: WorkOrder | None = None
) -> ObservedBaseline:
    """The broker's accepted state now; once a candidate is attached, from its workspace."""
    state = broker.accepted_state()
    candidate = work_order.candidate if work_order is not None else None
    if candidate is not None and candidate.workspace_id != state.workspace_id:
        raise BaselineWorkspaceMismatch(
            f"the broker reports workspace {state.workspace_id!r}; the WorkOrder's candidate "
            f"is in {candidate.workspace_id!r}"
        )
    return ObservedBaseline(workspace_id=state.workspace_id, accepted_commit=state.accepted_commit)
