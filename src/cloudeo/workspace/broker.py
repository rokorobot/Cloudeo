"""Workspace Broker interface and errors."""

from __future__ import annotations

from typing import Protocol

from cloudeo.workspace.models import (
    CandidateInspection,
    CandidateWorkspace,
    CanonicalWorkspaceState,
    PromotionResult,
    RejectionRecord,
    WorkspaceCheckpoint,
)


class WorkspaceBrokerError(RuntimeError):
    pass


class WorkspaceConflictError(WorkspaceBrokerError):
    """The workspace already has a different accepted state."""


class StaleCandidateError(WorkspaceBrokerError):
    """Accepted state moved after the candidate's base; nothing was overwritten."""


class ForeignCheckpointError(WorkspaceBrokerError):
    """The commit was not produced by this broker for this candidate and lineage."""


class NothingToCheckpointError(WorkspaceBrokerError):
    pass


class CandidateStateError(WorkspaceBrokerError):
    """The operation is not valid for the candidate's current lifecycle state."""


class WorkspaceBroker(Protocol):
    """Owns canonical state; executors only ever change candidates.

    Nothing here promotes automatically. Promotion is a separate, explicit call
    that a verifier-driven caller makes after an independent audit.
    """

    def accepted_state(self) -> CanonicalWorkspaceState: ...

    def create_candidate(self, state: CanonicalWorkspaceState) -> CandidateWorkspace: ...

    def inspect_candidate(self, candidate: CandidateWorkspace) -> CandidateInspection: ...

    def checkpoint_candidate(
        self, candidate: CandidateWorkspace, message: str
    ) -> WorkspaceCheckpoint: ...

    def promote(self, checkpoint: WorkspaceCheckpoint) -> PromotionResult: ...

    def reject(
        self,
        candidate: CandidateWorkspace,
        reason: str,
        checkpoint: WorkspaceCheckpoint | None = None,
    ) -> RejectionRecord: ...

    def cleanup(self, candidate: CandidateWorkspace, *, discard: bool = False) -> None: ...
