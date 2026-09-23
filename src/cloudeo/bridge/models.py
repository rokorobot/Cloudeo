"""Workspace bridge types: manifests, limits, task, and result."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from cloudeo.bridge.remote_helper import FORMAT
from cloudeo.execution.contracts import ExecutionOutcome
from cloudeo.workspace.models import CommitSha, Identifier

MiB = 1024 * 1024


@dataclass(frozen=True)
class BridgeLimits:
    """Explicit bounds for both directions of the bridge."""

    # Below HarnessRouter CE's default 25 MiB upload cap (HARNESS_UPLOAD_MAX_BYTES).
    max_bundle_bytes: int = 20 * MiB
    max_total_bytes: int = 256 * MiB
    max_files: int = 10_000
    max_file_bytes: int = 32 * MiB
    max_manifest_bytes: int = 8 * MiB


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class BridgeFileEntry(_Strict):
    path: str = Field(min_length=1)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    executable: bool


class InputManifest(_Strict):
    format: Literal[FORMAT]
    kind: Literal["input"]
    bridge_run_id: str
    workspace_id: Identifier
    candidate_id: Identifier
    base_commit: CommitSha
    head_commit: CommitSha
    files: tuple[BridgeFileEntry, ...]


class DeltaManifest(_Strict):
    format: Literal[FORMAT]
    kind: Literal["delta"]
    bridge_run_id: str
    workspace_id: str
    candidate_id: str
    base_commit: str
    added: tuple[BridgeFileEntry, ...]
    changed: tuple[BridgeFileEntry, ...]
    deleted: tuple[str, ...]


class WorkspaceBridgeTask(_Strict):
    """The user's task and an explicitly chosen harness/model. No routing."""

    task: str = Field(min_length=1)
    harness_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    max_step: int | None = Field(default=None, gt=0)
    timeout_seconds: int | None = Field(default=None, gt=0)


WorkspaceSyncStatus = Literal["synced", "skipped", "failed"]


class BridgeSyncError(BaseModel):
    model_config = ConfigDict(frozen=True)
    code: str
    message: str


class WorkspaceBridgeResult(BaseModel):
    """Runtime truth and workspace synchronization, kept separate.

    completed != synced; synced != verified; synced != checkpointed;
    checkpointed != promoted.
    """

    model_config = ConfigDict(frozen=True)

    outcome: ExecutionOutcome
    workspace_sync_status: WorkspaceSyncStatus
    bridge_run_id: str
    session_id: str | None = None
    input_file_count: int = 0
    added_paths: tuple[str, ...] = ()
    changed_paths: tuple[str, ...] = ()
    deleted_paths: tuple[str, ...] = ()
    # Remote-created files that local .gitignore rules ignore; not imported.
    ignored_paths: tuple[str, ...] = ()
    error: BridgeSyncError | None = None
