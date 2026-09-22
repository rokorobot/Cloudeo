"""Workspace Broker types.

Canonical state changes only through an explicit promotion. An executor can
only produce a candidate; its completion, runtime status, or claims never
change the accepted state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# Full SHA-1 or SHA-256 object name; abbreviated or symbolic names are not accepted.
CommitSha = Annotated[str, Field(pattern=r"^([0-9a-f]{40}|[0-9a-f]{64})$")]
# Safe as one Git ref path component.
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CanonicalWorkspaceState(_Frozen):
    """The accepted state: an explicit commit, never an implied branch head."""

    workspace_id: Identifier
    accepted_commit: CommitSha


class CandidateWorkspace(_Frozen):
    workspace_id: Identifier
    candidate_id: Identifier
    base_commit: CommitSha
    # Local and internal: where an executor on this machine may work. Not part
    # of any public or remote protocol shape.
    local_path: Path


class WorkspaceCheckpoint(_Frozen):
    """An immutable candidate state an auditor can inspect by commit."""

    workspace_id: Identifier
    candidate_id: Identifier
    base_commit: CommitSha
    commit: CommitSha


class CandidateInspection(_Frozen):
    candidate: CandidateWorkspace
    head_commit: CommitSha
    dirty: bool
    # Paths with changes not yet captured by a checkpoint, as Git reports them.
    uncheckpointed_paths: tuple[str, ...]


class PromotionResult(_Frozen):
    workspace_id: Identifier
    previous_commit: CommitSha
    accepted_commit: CommitSha
    checkpoint: WorkspaceCheckpoint


class RejectionRecord(_Frozen):
    """A rejected candidate stays addressable as evidence; canonical is unchanged."""

    workspace_id: Identifier
    candidate_id: Identifier
    base_commit: CommitSha
    # The rejected checkpoint, or None when the candidate never checkpointed.
    rejected_commit: CommitSha | None
    reason: str = Field(min_length=1)
    accepted_commit: CommitSha
