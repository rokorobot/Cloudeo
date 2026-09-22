"""Git-backed Workspace Broker.

All broker state lives in the repository under refs/cloudeo/workspaces/<id>/:

    accepted                                   the canonical accepted commit
    candidates/<cid>/base                      the accepted commit a candidate began from
    candidates/<cid>/checkpoints/<sha>         each checkpoint the broker recorded
    candidates/<cid>/promoted | rejected       terminal decision, kept as evidence

The broker never checks out, resets, or moves a branch or HEAD of the canonical
repository, and runs only local Git subcommands. Candidates are detached
worktrees. Worktrees isolate working files, not trust: they share refs and
objects with the repository, so they are not a security boundary against a
hostile local executor.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

from pydantic import TypeAdapter

from cloudeo.workspace.broker import (
    CandidateStateError,
    ForeignCheckpointError,
    NothingToCheckpointError,
    StaleCandidateError,
    WorkspaceBrokerError,
    WorkspaceConflictError,
)
from cloudeo.workspace.models import (
    CandidateInspection,
    CandidateWorkspace,
    CanonicalWorkspaceState,
    CommitSha,
    Identifier,
    PromotionResult,
    RejectionRecord,
    WorkspaceCheckpoint,
)

# Local subcommands only. Nothing here can reach a remote.
ALLOWED_GIT_SUBCOMMANDS = frozenset(
    {"add", "cat-file", "commit", "merge-base", "rev-parse", "status", "update-ref", "worktree"}
)
BROKER_IDENTITY = {
    "user.name": "Cloudeo Workspace Broker",
    "user.email": "workspace-broker@cloudeo.invalid",
}
# Broker-owned operations manage state; they are not project validation, so
# repository hooks do not run for them. Command-scoped only.
HOOKS_DISABLED_CONFIG = {"core.hooksPath": os.devnull}
# Checkpoint commits also use a fixed identity and never depend on signing.
BROKER_COMMIT_CONFIG = {
    **BROKER_IDENTITY,
    "commit.gpgSign": "false",
    **HOOKS_DISABLED_CONFIG,
}

_identifier = TypeAdapter(Identifier)
_commit_sha = TypeAdapter(CommitSha)


class GitCommandError(WorkspaceBrokerError):
    def __init__(self, args: tuple[str, ...], returncode: int, stderr: str):
        super().__init__(f"git {' '.join(args)} failed ({returncode}): {stderr.strip()}")
        self.args_run = args
        self.returncode = returncode
        self.stderr = stderr


class GitWorkspaceBroker:
    """Use initialize() to set the first accepted commit, or open() afterwards."""

    def __init__(self, repository: Path, workspace_id: str, worktrees_root: Path):
        self.workspace_id = _identifier.validate_python(workspace_id)
        self.repository = Path(repository).resolve()
        self.worktrees_root = Path(worktrees_root).resolve()
        self._ref_prefix = f"refs/cloudeo/workspaces/{self.workspace_id}"
        self._accepted_ref = f"{self._ref_prefix}/accepted"
        self._zero = "0" * (
            64 if self._git("rev-parse", "--show-object-format") == "sha256" else 40
        )
        self._require_outside_repository(self.worktrees_root)

    @classmethod
    def initialize(
        cls,
        repository: Path,
        workspace_id: str,
        accepted_commit: str,
        worktrees_root: Path,
    ) -> GitWorkspaceBroker:
        broker = cls(repository, workspace_id, worktrees_root)
        commit = broker._resolve_commit(accepted_commit)
        existing = broker._read_ref(broker._accepted_ref)
        if existing is None and not broker._update_ref(broker._accepted_ref, commit, broker._zero):
            existing = broker._read_ref(broker._accepted_ref)
        if existing is not None and existing != commit:
            raise WorkspaceConflictError(
                f"Workspace {workspace_id!r} already accepts {existing}; not replacing it."
            )
        return broker

    @classmethod
    def open(cls, repository: Path, workspace_id: str, worktrees_root: Path) -> GitWorkspaceBroker:
        broker = cls(repository, workspace_id, worktrees_root)
        broker.accepted_state()
        return broker

    # --- WorkspaceBroker ---

    def accepted_state(self) -> CanonicalWorkspaceState:
        accepted = self._read_ref(self._accepted_ref)
        if accepted is None:
            raise WorkspaceBrokerError(f"Workspace {self.workspace_id!r} is not initialized.")
        return CanonicalWorkspaceState(workspace_id=self.workspace_id, accepted_commit=accepted)

    def create_candidate(self, state: CanonicalWorkspaceState) -> CandidateWorkspace:
        self._require_workspace(state.workspace_id)
        current = self.accepted_state().accepted_commit
        if state.accepted_commit != current:
            raise StaleCandidateError(
                f"Accepted state is {current}, not {state.accepted_commit}; "
                "create candidates from the current accepted state."
            )
        candidate_id = uuid.uuid4().hex
        path = self._candidate_path(candidate_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        base_ref = self._candidate_ref(candidate_id, "base")
        self._update_ref(base_ref, current, self._zero, check=True)
        try:
            # Hooks disabled: a post-checkout hook must not run project side effects.
            self._git("worktree", "add", "--detach", str(path), current, hooks_disabled=True)
        except Exception as exc:
            # Unregister the candidate so no ref claims it exists. Only this
            # candidate's ref is removed; other refs and worktrees are untouched.
            rollback = self._run(("update-ref", "-d", base_ref, current), check=False)
            if rollback.returncode != 0:
                exc.add_note(f"Rollback of {base_ref} failed: {rollback.stderr.strip()}")
            raise
        return CandidateWorkspace(
            workspace_id=self.workspace_id,
            candidate_id=candidate_id,
            base_commit=current,
            local_path=path,
        )

    def inspect_candidate(self, candidate: CandidateWorkspace) -> CandidateInspection:
        self._require_candidate(candidate)
        self._require_worktree(candidate)
        paths = self._uncheckpointed_paths(candidate)
        return CandidateInspection(
            candidate=candidate,
            head_commit=self._git("rev-parse", "HEAD", cwd=candidate.local_path),
            dirty=bool(paths),
            uncheckpointed_paths=paths,
        )

    def checkpoint_candidate(
        self, candidate: CandidateWorkspace, message: str
    ) -> WorkspaceCheckpoint:
        if not message.strip():
            raise ValueError("A checkpoint message is required.")
        self._require_candidate(candidate)
        self._require_open(candidate.candidate_id)
        self._require_worktree(candidate)
        dirty = bool(self._uncheckpointed_paths(candidate))
        if dirty:
            self._git("add", "--all", cwd=candidate.local_path)
            self._git(
                "commit", "--quiet", "-m", message, cwd=candidate.local_path, broker_commit=True
            )
        head = self._git("rev-parse", "HEAD", cwd=candidate.local_path)
        checkpoint_ref = self._candidate_ref(candidate.candidate_id, f"checkpoints/{head}")
        if head == candidate.base_commit or (not dirty and self._read_ref(checkpoint_ref) == head):
            raise NothingToCheckpointError(
                f"Candidate {candidate.candidate_id} has no changes since its last checkpoint."
            )
        if not self._is_ancestor(candidate.base_commit, head):
            raise ForeignCheckpointError(
                f"Candidate HEAD {head} does not descend from base {candidate.base_commit}."
            )
        self._update_ref(checkpoint_ref, head, self._zero, check=True)
        return WorkspaceCheckpoint(
            workspace_id=self.workspace_id,
            candidate_id=candidate.candidate_id,
            base_commit=candidate.base_commit,
            commit=head,
        )

    def promote(self, checkpoint: WorkspaceCheckpoint) -> PromotionResult:
        self._require_checkpoint(checkpoint)
        self._require_open(checkpoint.candidate_id)
        base = checkpoint.base_commit
        current = self.accepted_state().accepted_commit
        if current != base:
            raise StaleCandidateError(
                f"Accepted state moved to {current} after candidate "
                f"{checkpoint.candidate_id} began from {base}; not promoting."
            )
        if checkpoint.commit == base or not self._is_ancestor(base, checkpoint.commit):
            raise ForeignCheckpointError(f"{checkpoint.commit} is not a descendant of {base}.")
        # One atomic transaction: accepted is compare-and-swapped from the base,
        # the promoted marker is created, and the rejected marker must be absent.
        # If any precondition fails, no ref changes.
        cid = checkpoint.candidate_id
        transaction = self._ref_transaction(
            f"verify {self._candidate_ref(cid, 'rejected')} {self._zero}",
            f"update {self._accepted_ref} {checkpoint.commit} {base}",
            f"create {self._candidate_ref(cid, 'promoted')} {checkpoint.commit}",
        )
        if transaction.returncode != 0:
            self._require_open(cid)
            # Read the ref itself: the transaction's view, not a cached state.
            if self._read_ref(self._accepted_ref) != base:
                raise StaleCandidateError(f"Accepted state changed during promotion of {cid}.")
            raise GitCommandError(
                ("update-ref", "--stdin"), transaction.returncode, transaction.stderr
            )
        return PromotionResult(
            workspace_id=self.workspace_id,
            previous_commit=base,
            accepted_commit=checkpoint.commit,
            checkpoint=checkpoint,
        )

    def reject(
        self,
        candidate: CandidateWorkspace,
        reason: str,
        checkpoint: WorkspaceCheckpoint | None = None,
    ) -> RejectionRecord:
        if not reason.strip():
            raise ValueError("A rejection reason is required.")
        self._require_candidate(candidate)
        self._require_open(candidate.candidate_id)
        if checkpoint is not None:
            self._require_checkpoint(checkpoint)
            if checkpoint.candidate_id != candidate.candidate_id:
                raise ForeignCheckpointError("The checkpoint belongs to another candidate.")
        rejected_commit = checkpoint.commit if checkpoint is not None else None
        # One atomic transaction that never touches accepted: the promoted marker
        # must be absent and the rejected marker is created (create fails if it
        # exists). The rejected commit stays reachable as evidence.
        cid = candidate.candidate_id
        transaction = self._ref_transaction(
            f"verify {self._candidate_ref(cid, 'promoted')} {self._zero}",
            f"create {self._candidate_ref(cid, 'rejected')} "
            f"{rejected_commit or candidate.base_commit}",
        )
        if transaction.returncode != 0:
            self._require_open(cid)
            raise GitCommandError(
                ("update-ref", "--stdin"), transaction.returncode, transaction.stderr
            )
        return RejectionRecord(
            workspace_id=self.workspace_id,
            candidate_id=candidate.candidate_id,
            base_commit=candidate.base_commit,
            rejected_commit=rejected_commit,
            reason=reason,
            accepted_commit=self.accepted_state().accepted_commit,
        )

    def cleanup(self, candidate: CandidateWorkspace, *, discard: bool = False) -> None:
        """Remove the candidate's worktree. Refs, checkpoints, and decisions are kept."""
        self._require_candidate(candidate)
        if not candidate.local_path.exists():
            self._git("worktree", "prune")
            return
        if not discard:
            paths = self._uncheckpointed_paths(candidate)
            if paths:
                raise CandidateStateError(
                    f"Candidate {candidate.candidate_id} has uncheckpointed changes: "
                    f"{', '.join(paths)}. Checkpoint them or pass discard=True."
                )
        self._git("worktree", "remove", "--force", str(candidate.local_path))

    # --- internals ---

    def _git(
        self,
        *args: str,
        cwd: Path | None = None,
        hooks_disabled: bool = False,
        broker_commit: bool = False,
    ) -> str:
        return self._run(
            args, cwd=cwd, hooks_disabled=hooks_disabled, broker_commit=broker_commit
        ).stdout.strip()

    def _run(
        self,
        args: tuple[str, ...],
        *,
        cwd: Path | None = None,
        hooks_disabled: bool = False,
        broker_commit: bool = False,
        check: bool = True,
        stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run a local Git subcommand.

        hooks_disabled: broker-owned operation; repository hooks do not run.
        broker_commit: broker checkpoint commit; hooks disabled, fixed identity,
        signing off. Both apply to this command only; the repository's
        persistent config and hook files are never changed.
        """
        if args[0] not in ALLOWED_GIT_SUBCOMMANDS:
            raise WorkspaceBrokerError(f"git {args[0]} is not permitted in the broker.")
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
        config = (
            BROKER_COMMIT_CONFIG
            if broker_commit
            else HOOKS_DISABLED_CONFIG
            if hooks_disabled
            else {}
        )
        options: list[str] = []
        for key, value in config.items():
            options += ["-c", f"{key}={value}"]
        if broker_commit:
            # These environment variables would otherwise override user.name/email.
            env |= {
                "GIT_AUTHOR_NAME": BROKER_IDENTITY["user.name"],
                "GIT_AUTHOR_EMAIL": BROKER_IDENTITY["user.email"],
                "GIT_COMMITTER_NAME": BROKER_IDENTITY["user.name"],
                "GIT_COMMITTER_EMAIL": BROKER_IDENTITY["user.email"],
            }
        process = subprocess.run(
            ["git", "-C", str(cwd or self.repository), *options, *args],
            capture_output=True,
            text=True,
            input=stdin,
            env=env,
            check=False,
        )
        if check and process.returncode != 0:
            raise GitCommandError(args, process.returncode, process.stderr)
        return process

    def _update_ref(self, ref: str, new: str, old: str, *, check: bool = False) -> bool:
        return self._run(("update-ref", ref, new, old), check=check).returncode == 0

    def _ref_transaction(self, *commands: str) -> subprocess.CompletedProcess[str]:
        """Apply update-ref commands as one atomic transaction: all or none."""
        script = "".join(f"{command}\n" for command in ("start", *commands, "prepare", "commit"))
        return self._run(("update-ref", "--stdin"), check=False, stdin=script)

    def _read_ref(self, ref: str) -> str | None:
        process = self._run(("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"), check=False)
        return process.stdout.strip() if process.returncode == 0 else None

    def _resolve_commit(self, value: str) -> str:
        sha = _commit_sha.validate_python(value)
        if self._run(("cat-file", "-e", f"{sha}^{{commit}}"), check=False).returncode:
            raise WorkspaceBrokerError(f"{sha} is not a commit in {self.repository}.")
        return sha

    def _is_ancestor(self, ancestor: str, descendant: str) -> bool:
        process = self._run(("merge-base", "--is-ancestor", ancestor, descendant), check=False)
        if process.returncode not in (0, 1):
            raise GitCommandError(("merge-base",), process.returncode, process.stderr)
        return process.returncode == 0

    def _uncheckpointed_paths(self, candidate: CandidateWorkspace) -> tuple[str, ...]:
        output = self._run(
            ("status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames"),
            cwd=candidate.local_path,
        ).stdout
        return tuple(entry[3:] for entry in output.split("\0") if entry)

    def _candidate_ref(self, candidate_id: str, leaf: str) -> str:
        return f"{self._ref_prefix}/candidates/{candidate_id}/{leaf}"

    def _candidate_path(self, candidate_id: str) -> Path:
        return self.worktrees_root / self.workspace_id / candidate_id

    def _require_outside_repository(self, path: Path) -> None:
        bare = self._git("rev-parse", "--is-bare-repository") == "true"
        roots = [Path(self._git("rev-parse", "--path-format=absolute", "--git-common-dir"))]
        if not bare:
            roots.append(Path(self._git("rev-parse", "--show-toplevel")))
        for root in roots:
            if path == root.resolve() or path.is_relative_to(root.resolve()):
                raise ValueError(f"worktrees_root must be outside the repository ({root}).")

    def _require_workspace(self, workspace_id: str) -> None:
        if workspace_id != self.workspace_id:
            raise ForeignCheckpointError(
                f"{workspace_id!r} is not this broker's workspace {self.workspace_id!r}."
            )

    def _require_candidate(self, candidate: CandidateWorkspace) -> None:
        self._require_workspace(candidate.workspace_id)
        base = self._read_ref(self._candidate_ref(candidate.candidate_id, "base"))
        if base is None or base != candidate.base_commit:
            raise ForeignCheckpointError(
                f"Candidate {candidate.candidate_id} was not created by this broker."
            )
        if candidate.local_path != self._candidate_path(candidate.candidate_id):
            raise ForeignCheckpointError(
                f"Candidate {candidate.candidate_id} does not use its broker-owned path."
            )

    def _require_checkpoint(self, checkpoint: WorkspaceCheckpoint) -> None:
        self._require_workspace(checkpoint.workspace_id)
        cid = checkpoint.candidate_id
        base = self._read_ref(self._candidate_ref(cid, "base"))
        recorded = self._read_ref(self._candidate_ref(cid, f"checkpoints/{checkpoint.commit}"))
        if base != checkpoint.base_commit or recorded != checkpoint.commit:
            raise ForeignCheckpointError(
                f"{checkpoint.commit} is not a checkpoint this broker recorded for candidate {cid}."
            )

    def _require_open(self, candidate_id: str) -> None:
        for decision in ("promoted", "rejected"):
            if self._read_ref(self._candidate_ref(candidate_id, decision)) is not None:
                raise CandidateStateError(f"Candidate {candidate_id} was already {decision}.")

    def _require_worktree(self, candidate: CandidateWorkspace) -> None:
        if not candidate.local_path.is_dir():
            raise CandidateStateError(
                f"Candidate {candidate.candidate_id} has no worktree (cleaned up?)."
            )
