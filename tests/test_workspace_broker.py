import subprocess
import threading
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from cloudeo.workspace import git as git_module
from cloudeo.workspace.broker import (
    CandidateStateError,
    ForeignCheckpointError,
    NothingToCheckpointError,
    StaleCandidateError,
    WorkspaceBrokerError,
    WorkspaceConflictError,
)
from cloudeo.workspace.git import ALLOWED_GIT_SUBCOMMANDS, BROKER_IDENTITY, GitWorkspaceBroker
from cloudeo.workspace.models import CanonicalWorkspaceState, WorkspaceCheckpoint

NETWORK_SUBCOMMANDS = {"fetch", "push", "pull", "clone", "remote", "ls-remote", "submodule"}


@pytest.fixture(autouse=True)
def isolated_git(tmp_path, monkeypatch):
    """Keep the developer's Git config (signing, hooks, identity) out of these tests."""
    config = tmp_path / "gitconfig"
    config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("HOME", str(tmp_path))
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(key, raising=False)


def git(cwd, *args):
    env_identity = ["-c", "user.name=Test Author", "-c", "user.email=test@example.invalid"]
    result = subprocess.run(
        ["git", "-C", str(cwd), *env_identity, *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def commit_file(cwd, name, content, message):
    (Path(cwd) / name).write_text(content)
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", message)
    return git(cwd, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "canonical"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    commit_file(path, "README.md", "initial\n", "initial")
    return path


@pytest.fixture
def root(tmp_path):
    return tmp_path / "candidates"


@pytest.fixture
def broker(repo, root):
    return GitWorkspaceBroker.initialize(repo, "demo", git(repo, "rev-parse", "HEAD"), root)


def canonical_snapshot(repo):
    return {
        "head": git(repo, "rev-parse", "HEAD"),
        "branch": git(repo, "symbolic-ref", "--short", "HEAD"),
        "status": git(repo, "status", "--porcelain"),
        "readme": (repo / "README.md").read_text(),
    }


def accepted_ref(repo, workspace="demo"):
    return git(repo, "rev-parse", f"refs/cloudeo/workspaces/{workspace}/accepted")


def change_and_checkpoint(broker, candidate, name="feature.txt", content="work\n"):
    (candidate.local_path / name).write_text(content)
    return broker.checkpoint_candidate(candidate, f"candidate adds {name}")


# --- Initialization and explicit canonical state ---


def test_initialize_records_explicit_accepted_commit(repo, broker):
    a = git(repo, "rev-parse", "HEAD")
    assert broker.accepted_state() == CanonicalWorkspaceState(
        workspace_id="demo", accepted_commit=a
    )
    assert accepted_ref(repo) == a


def test_accepted_state_is_not_the_branch_head(repo, broker):
    a = broker.accepted_state().accepted_commit
    b = commit_file(repo, "README.md", "moved by someone\n", "canonical branch moves")
    assert git(repo, "rev-parse", "HEAD") == b
    assert broker.accepted_state().accepted_commit == a


def test_initialize_is_idempotent_and_never_replaces(repo, root, broker):
    a = broker.accepted_state().accepted_commit
    assert GitWorkspaceBroker.initialize(repo, "demo", a, root).accepted_state() == (
        broker.accepted_state()
    )
    b = commit_file(repo, "other.txt", "x\n", "another commit")
    with pytest.raises(WorkspaceConflictError):
        GitWorkspaceBroker.initialize(repo, "demo", b, root)
    assert accepted_ref(repo) == a


def test_open_requires_initialized_workspace(repo, root, broker):
    assert GitWorkspaceBroker.open(repo, "demo", root).accepted_state() == broker.accepted_state()
    with pytest.raises(WorkspaceBrokerError, match="not initialized"):
        GitWorkspaceBroker.open(repo, "other", root)


@pytest.mark.parametrize("commit", ["abc123", "HEAD", "main", "g" * 40])
def test_initialize_requires_full_commit_sha(repo, root, commit):
    with pytest.raises(ValidationError):
        GitWorkspaceBroker.initialize(repo, "demo", commit, root)


def test_initialize_requires_existing_commit(repo, root):
    with pytest.raises(WorkspaceBrokerError, match="not a commit"):
        GitWorkspaceBroker.initialize(repo, "demo", "1" * 40, root)


@pytest.mark.parametrize("workspace_id", ["", "../escape", "a/b", "has space", "-leading"])
def test_workspace_id_must_be_ref_safe(repo, root, workspace_id):
    with pytest.raises(ValidationError):
        GitWorkspaceBroker(repo, workspace_id, root)


def test_worktrees_root_must_be_outside_repository(repo):
    a = git(repo, "rev-parse", "HEAD")
    with pytest.raises(ValueError, match="outside the repository"):
        GitWorkspaceBroker.initialize(repo, "demo", a, repo / "candidates")
    with pytest.raises(ValueError, match="outside the repository"):
        GitWorkspaceBroker.initialize(repo, "demo", a, repo / ".git" / "candidates")


# --- Candidates and isolation ---


def test_candidate_starts_from_exact_accepted_content(repo, broker, root):
    state = broker.accepted_state()
    candidate = broker.create_candidate(state)
    assert candidate.base_commit == state.accepted_commit
    assert candidate.local_path == (root / "demo" / candidate.candidate_id).resolve()
    assert git(candidate.local_path, "rev-parse", "HEAD") == state.accepted_commit
    assert (candidate.local_path / "README.md").read_text() == "initial\n"
    inspection = broker.inspect_candidate(candidate)
    assert inspection.head_commit == state.accepted_commit
    assert inspection.dirty is False
    assert inspection.uncheckpointed_paths == ()


def test_candidate_changes_do_not_touch_canonical_checkout(repo, broker):
    before = canonical_snapshot(repo)
    candidate = broker.create_candidate(broker.accepted_state())
    (candidate.local_path / "README.md").write_text("candidate edit\n")
    (candidate.local_path / "new.txt").write_text("new\n")
    checkpoint = broker.checkpoint_candidate(candidate, "edit")
    assert canonical_snapshot(repo) == before
    broker.promote(checkpoint)
    # Promotion moves only the broker's ref, never the canonical branch or files.
    assert canonical_snapshot(repo) == before


def test_multiple_candidates_from_same_state_are_isolated(broker):
    state = broker.accepted_state()
    one = broker.create_candidate(state)
    two = broker.create_candidate(state)
    assert one.candidate_id != two.candidate_id
    assert one.local_path != two.local_path
    (one.local_path / "only-one.txt").write_text("1\n")
    (two.local_path / "README.md").write_text("two\n")
    assert not (two.local_path / "only-one.txt").exists()
    assert (one.local_path / "README.md").read_text() == "initial\n"
    assert broker.inspect_candidate(one).uncheckpointed_paths == ("only-one.txt",)
    assert broker.inspect_candidate(two).uncheckpointed_paths == ("README.md",)


def test_create_candidate_rejects_stale_state(repo, broker):
    stale = broker.accepted_state()
    candidate = broker.create_candidate(stale)
    broker.promote(change_and_checkpoint(broker, candidate))
    with pytest.raises(StaleCandidateError):
        broker.create_candidate(stale)


# --- Checkpoints ---


def test_checkpoint_creates_real_descendant_commit(repo, broker):
    candidate = broker.create_candidate(broker.accepted_state())
    checkpoint = change_and_checkpoint(broker, candidate)
    assert checkpoint.base_commit == candidate.base_commit
    assert git(repo, "rev-parse", f"{checkpoint.commit}^") == candidate.base_commit
    assert git(repo, "show", f"{checkpoint.commit}:feature.txt") == "work"
    assert git(repo, "log", "-1", "--format=%an <%ae>", checkpoint.commit) == (
        f"{BROKER_IDENTITY['user.name']} <{BROKER_IDENTITY['user.email']}>"
    )
    assert broker.inspect_candidate(candidate).dirty is False
    # Checkpointing does not promote.
    assert broker.accepted_state().accepted_commit == candidate.base_commit


def test_checkpoint_requires_changes(broker):
    candidate = broker.create_candidate(broker.accepted_state())
    with pytest.raises(NothingToCheckpointError):
        broker.checkpoint_candidate(candidate, "nothing")
    first = change_and_checkpoint(broker, candidate)
    with pytest.raises(NothingToCheckpointError):
        broker.checkpoint_candidate(candidate, "nothing new")
    second = change_and_checkpoint(broker, candidate, "more.txt")
    assert second.commit != first.commit


def test_checkpoint_accepts_executor_commits_on_the_candidate(repo, broker):
    candidate = broker.create_candidate(broker.accepted_state())
    executor_commit = commit_file(candidate.local_path, "exec.txt", "x\n", "executor commit")
    checkpoint = broker.checkpoint_candidate(candidate, "capture executor work")
    assert checkpoint.commit == executor_commit


def test_checkpoint_refuses_rewritten_history(repo, broker):
    candidate = broker.create_candidate(broker.accepted_state())
    git(candidate.local_path, "checkout", "-q", "--orphan", "rewritten")
    git(candidate.local_path, "commit", "-q", "-m", "unrelated root")
    with pytest.raises(ForeignCheckpointError, match="does not descend"):
        broker.checkpoint_candidate(candidate, "rewritten")


# --- Promotion, staleness, lineage ---


def test_promote_advances_accepted_state_only_on_promote(repo, broker):
    a = broker.accepted_state().accepted_commit
    candidate = broker.create_candidate(broker.accepted_state())
    checkpoint = change_and_checkpoint(broker, candidate)
    assert accepted_ref(repo) == a
    result = broker.promote(checkpoint)
    assert (result.previous_commit, result.accepted_commit) == (a, checkpoint.commit)
    assert result.checkpoint == checkpoint
    assert broker.accepted_state().accepted_commit == checkpoint.commit
    assert accepted_ref(repo) == checkpoint.commit


def test_stale_candidate_cannot_overwrite_newer_accepted_state(repo, broker):
    state = broker.accepted_state()
    first = broker.create_candidate(state)
    second = broker.create_candidate(state)
    winner = change_and_checkpoint(broker, first, "a.txt")
    loser = change_and_checkpoint(broker, second, "b.txt")
    broker.promote(winner)
    with pytest.raises(StaleCandidateError):
        broker.promote(loser)
    assert accepted_ref(repo) == winner.commit


def test_promotion_is_compare_and_swap(repo, broker, monkeypatch):
    """Even if the pre-check passes, a concurrent move of accepted wins."""
    state = broker.accepted_state()
    candidate = broker.create_candidate(state)
    checkpoint = change_and_checkpoint(broker, candidate)
    other = broker.create_candidate(state)
    concurrent = change_and_checkpoint(broker, other, "other.txt")
    git(repo, "update-ref", "refs/cloudeo/workspaces/demo/accepted", concurrent.commit)
    monkeypatch.setattr(broker, "accepted_state", lambda: state)
    with pytest.raises(StaleCandidateError, match="changed during promotion"):
        broker.promote(checkpoint)
    assert accepted_ref(repo) == concurrent.commit


def test_commit_not_recorded_by_broker_cannot_be_promoted(repo, broker):
    a = broker.accepted_state().accepted_commit
    candidate = broker.create_candidate(broker.accepted_state())
    # A real descendant of the accepted commit, made outside the broker.
    outside = commit_file(repo, "outside.txt", "x\n", "not via broker")
    forged = WorkspaceCheckpoint(
        workspace_id="demo", candidate_id=candidate.candidate_id, base_commit=a, commit=outside
    )
    with pytest.raises(ForeignCheckpointError):
        broker.promote(forged)
    assert accepted_ref(repo) == a


def test_non_descendant_or_foreign_workspace_cannot_be_promoted(repo, root, broker):
    a = broker.accepted_state().accepted_commit
    git(repo, "checkout", "-q", "--orphan", "unrelated")
    git(repo, "commit", "-q", "-m", "unrelated root")
    unrelated = git(repo, "rev-parse", "HEAD")
    candidate = broker.create_candidate(broker.accepted_state())
    with pytest.raises(ForeignCheckpointError):
        broker.promote(
            WorkspaceCheckpoint(
                workspace_id="demo",
                candidate_id=candidate.candidate_id,
                base_commit=a,
                commit=unrelated,
            )
        )
    other = GitWorkspaceBroker.initialize(repo, "other", a, root)
    other_candidate = other.create_candidate(other.accepted_state())
    foreign = change_and_checkpoint(other, other_candidate)
    with pytest.raises(ForeignCheckpointError):
        broker.promote(foreign)
    assert accepted_ref(repo) == a
    assert accepted_ref(repo, "other") == a


def test_tampered_candidate_identity_is_rejected(broker, tmp_path):
    candidate = broker.create_candidate(broker.accepted_state())
    moved = candidate.model_copy(update={"local_path": tmp_path / "elsewhere"})
    with pytest.raises(ForeignCheckpointError):
        broker.checkpoint_candidate(moved, "x")
    unknown = candidate.model_copy(update={"candidate_id": "f" * 32})
    with pytest.raises(ForeignCheckpointError):
        broker.inspect_candidate(unknown)


# --- Rejection ---


def test_reject_leaves_accepted_state_unchanged_and_keeps_evidence(repo, broker):
    a = broker.accepted_state().accepted_commit
    candidate = broker.create_candidate(broker.accepted_state())
    checkpoint = change_and_checkpoint(broker, candidate)
    record = broker.reject(candidate, "audit failed: tests missing", checkpoint)
    assert record.rejected_commit == checkpoint.commit
    assert record.base_commit == a
    assert record.accepted_commit == a
    assert record.reason == "audit failed: tests missing"
    assert accepted_ref(repo) == a
    broker.cleanup(candidate)
    # The rejected commit remains addressable after the worktree is gone.
    rejected_ref = f"refs/cloudeo/workspaces/demo/candidates/{candidate.candidate_id}/rejected"
    assert git(repo, "rev-parse", rejected_ref) == checkpoint.commit
    assert git(repo, "show", f"{checkpoint.commit}:feature.txt") == "work"


def test_reject_without_checkpoint(repo, broker):
    candidate = broker.create_candidate(broker.accepted_state())
    record = broker.reject(candidate, "executor failed before producing state")
    assert record.rejected_commit is None
    assert accepted_ref(repo) == candidate.base_commit


def test_decisions_are_final(broker):
    candidate = broker.create_candidate(broker.accepted_state())
    checkpoint = change_and_checkpoint(broker, candidate)
    broker.reject(candidate, "failed audit", checkpoint)
    with pytest.raises(CandidateStateError, match="rejected"):
        broker.promote(checkpoint)
    with pytest.raises(CandidateStateError, match="rejected"):
        broker.checkpoint_candidate(candidate, "more")

    promoted = broker.create_candidate(broker.accepted_state())
    promoted_checkpoint = change_and_checkpoint(broker, promoted)
    broker.promote(promoted_checkpoint)
    with pytest.raises(CandidateStateError, match="promoted"):
        broker.promote(promoted_checkpoint)
    with pytest.raises(CandidateStateError, match="promoted"):
        broker.reject(promoted, "too late", promoted_checkpoint)


def test_reason_is_required(broker):
    candidate = broker.create_candidate(broker.accepted_state())
    with pytest.raises(ValueError, match="reason"):
        broker.reject(candidate, "  ")


# --- Dirty state and cleanup ---


def test_cleanup_refuses_uncheckpointed_changes_unless_discarded(repo, broker):
    candidate = broker.create_candidate(broker.accepted_state())
    (candidate.local_path / "draft.txt").write_text("unsaved\n")
    inspection = broker.inspect_candidate(candidate)
    assert inspection.dirty is True
    assert inspection.uncheckpointed_paths == ("draft.txt",)
    with pytest.raises(CandidateStateError, match="draft.txt"):
        broker.cleanup(candidate)
    assert candidate.local_path.exists()
    broker.cleanup(candidate, discard=True)
    assert not candidate.local_path.exists()
    assert str(candidate.local_path) not in git(repo, "worktree", "list")


def test_cleanup_is_explicit_idempotent_and_keeps_checkpoints(repo, broker):
    candidate = broker.create_candidate(broker.accepted_state())
    checkpoint = change_and_checkpoint(broker, candidate)
    broker.cleanup(candidate)
    broker.cleanup(candidate)
    assert not candidate.local_path.exists()
    with pytest.raises(CandidateStateError, match="no worktree"):
        broker.inspect_candidate(candidate)
    # An immutable checkpoint can still be promoted after its worktree is gone.
    assert broker.promote(checkpoint).accepted_commit == checkpoint.commit


# --- Atomic terminal decisions ---


def decision_refs(repo, candidate_id, workspace="demo"):
    prefix = f"refs/cloudeo/workspaces/{workspace}/candidates/{candidate_id}"
    listed = git(repo, "for-each-ref", "--format=%(refname:lstrip=-1)", prefix)
    return {name for name in listed.split() if name in {"promoted", "rejected"}}


def test_promotion_updates_accepted_and_marker_atomically(repo, broker):
    candidate = broker.create_candidate(broker.accepted_state())
    checkpoint = change_and_checkpoint(broker, candidate)
    broker.promote(checkpoint)
    assert accepted_ref(repo) == checkpoint.commit
    assert decision_refs(repo, candidate.candidate_id) == {"promoted"}
    promoted = f"refs/cloudeo/workspaces/demo/candidates/{candidate.candidate_id}/promoted"
    assert git(repo, "rev-parse", promoted) == checkpoint.commit


def test_stale_promotion_changes_no_ref(repo, broker):
    state = broker.accepted_state()
    first, second = broker.create_candidate(state), broker.create_candidate(state)
    winner = change_and_checkpoint(broker, first, "a.txt")
    loser = change_and_checkpoint(broker, second, "b.txt")
    broker.promote(winner)
    with pytest.raises(StaleCandidateError):
        broker.promote(loser)
    assert accepted_ref(repo) == winner.commit
    assert decision_refs(repo, second.candidate_id) == set()


def test_failed_promotion_transaction_leaves_every_ref_unchanged(repo, broker, monkeypatch):
    """Accepted moves after the pre-check: the whole transaction is refused."""
    state = broker.accepted_state()
    candidate = broker.create_candidate(state)
    checkpoint = change_and_checkpoint(broker, candidate)
    other = broker.create_candidate(state)
    concurrent = change_and_checkpoint(broker, other, "other.txt")
    git(repo, "update-ref", "refs/cloudeo/workspaces/demo/accepted", concurrent.commit)
    monkeypatch.setattr(broker, "accepted_state", lambda: state)
    with pytest.raises(StaleCandidateError, match="changed during promotion"):
        broker.promote(checkpoint)
    assert accepted_ref(repo) == concurrent.commit
    assert decision_refs(repo, candidate.candidate_id) == set()


def test_promotion_after_racing_rejection_changes_nothing(repo, broker, monkeypatch):
    """Both pre-checks pass; the transaction still sees the rejection."""
    a = broker.accepted_state().accepted_commit
    candidate = broker.create_candidate(broker.accepted_state())
    checkpoint = change_and_checkpoint(broker, candidate)
    broker.reject(candidate, "audit failed", checkpoint)
    monkeypatch.setattr(broker, "_require_open", lambda cid: None, raising=True)
    with pytest.raises(WorkspaceBrokerError):
        broker.promote(checkpoint)
    assert accepted_ref(repo) == a
    assert decision_refs(repo, candidate.candidate_id) == {"rejected"}


def test_rejection_after_racing_promotion_changes_nothing(repo, broker, monkeypatch):
    candidate = broker.create_candidate(broker.accepted_state())
    checkpoint = change_and_checkpoint(broker, candidate)
    broker.promote(checkpoint)
    monkeypatch.setattr(broker, "_require_open", lambda cid: None, raising=True)
    with pytest.raises(WorkspaceBrokerError):
        broker.reject(candidate, "too late", checkpoint)
    assert accepted_ref(repo) == checkpoint.commit
    assert decision_refs(repo, candidate.candidate_id) == {"promoted"}


def race(start, errors, name, action, *args):
    start.wait()
    try:
        action(*args)
    except WorkspaceBrokerError as exc:
        errors[name] = exc


def test_concurrent_promote_and_reject_never_both_decide(repo, broker):
    for _ in range(8):
        base = broker.accepted_state().accepted_commit
        candidate = broker.create_candidate(broker.accepted_state())
        checkpoint = change_and_checkpoint(broker, candidate, f"race-{uuid.uuid4().hex}.txt")
        start = threading.Barrier(2)
        errors = {}
        threads = [
            threading.Thread(
                target=race, args=(start, errors, "promote", broker.promote, checkpoint)
            ),
            threading.Thread(
                target=race,
                args=(start, errors, "reject", broker.reject, candidate, "race", checkpoint),
            ),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        decisions = decision_refs(repo, candidate.candidate_id)
        assert len(decisions) <= 1
        assert len(errors) >= 1
        expected = checkpoint.commit if decisions == {"promoted"} else base
        assert accepted_ref(repo) == expected
        broker.cleanup(candidate, discard=True)


def test_rejection_is_canonical_state_neutral(repo, broker):
    before = accepted_ref(repo)
    snapshot = canonical_snapshot(repo)
    candidate = broker.create_candidate(broker.accepted_state())
    broker.reject(candidate, "never checkpointed")
    other = broker.create_candidate(broker.accepted_state())
    broker.reject(other, "bad work", change_and_checkpoint(broker, other))
    assert accepted_ref(repo) == before
    assert canonical_snapshot(repo) == snapshot


# --- Side-effect-free broker commits ---


def install_hooks(repo, marker_dir):
    hooks = repo / ".git" / "hooks"
    scripts = {}
    for name in ("pre-commit", "prepare-commit-msg", "commit-msg", "post-commit"):
        hook = hooks / name
        hook.write_text(f"#!/bin/sh\necho ran > '{marker_dir / name}'\nexit 1\n")
        hook.chmod(0o755)
        scripts[name] = hook.read_text()
    return scripts


def test_broker_checkpoint_runs_no_repository_hooks(repo, broker, tmp_path):
    markers = tmp_path / "markers"
    markers.mkdir()
    scripts = install_hooks(repo, markers)
    local_config = git(repo, "config", "--local", "--list")
    candidate = broker.create_candidate(broker.accepted_state())
    checkpoint = change_and_checkpoint(broker, candidate)
    assert git(repo, "cat-file", "-t", checkpoint.commit) == "commit"
    assert list(markers.iterdir()) == []
    # The user's hooks and persistent config are left exactly as they were.
    assert {name: (repo / ".git" / "hooks" / name).read_text() for name in scripts} == scripts
    assert git(repo, "config", "--local", "--list") == local_config
    # The hooks are live: an ordinary commit in the candidate is blocked by them.
    (candidate.local_path / "executor.txt").write_text("x\n")
    git(candidate.local_path, "add", "executor.txt")
    with pytest.raises(subprocess.CalledProcessError):
        git(candidate.local_path, "commit", "-q", "-m", "executor commit")
    assert (markers / "pre-commit").exists()


def test_broker_checkpoint_does_not_depend_on_signing(repo, broker):
    git(repo, "config", "--local", "commit.gpgSign", "true")
    git(repo, "config", "--local", "gpg.program", "false")
    candidate = broker.create_candidate(broker.accepted_state())
    checkpoint = change_and_checkpoint(broker, candidate)
    assert git(repo, "log", "-1", "--format=%G?", checkpoint.commit) == "N"
    assert git(repo, "config", "--local", "commit.gpgSign") == "true"
    (candidate.local_path / "signed.txt").write_text("x\n")
    git(candidate.local_path, "add", "signed.txt")
    with pytest.raises(subprocess.CalledProcessError):
        git(candidate.local_path, "commit", "-q", "-m", "would need signing")


def test_broker_identity_overrides_identity_environment(repo, broker, monkeypatch):
    for key in ("GIT_AUTHOR", "GIT_COMMITTER"):
        monkeypatch.setenv(f"{key}_NAME", "Someone Else")
        monkeypatch.setenv(f"{key}_EMAIL", "someone@example.invalid")
    candidate = broker.create_candidate(broker.accepted_state())
    checkpoint = change_and_checkpoint(broker, candidate)
    identity = f"{BROKER_IDENTITY['user.name']} <{BROKER_IDENTITY['user.email']}>"
    assert git(repo, "log", "-1", "--format=%an <%ae>", checkpoint.commit) == identity
    assert git(repo, "log", "-1", "--format=%cn <%ce>", checkpoint.commit) == identity


def install_post_checkout(hooks_dir, marker):
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook = hooks_dir / "post-checkout"
    hook.write_text(f"#!/bin/sh\necho ran >> '{marker}'\nexit 1\n")
    hook.chmod(0o755)
    return hook


def local_config(repo):
    return git(repo, "config", "--local", "--list")


def hooks_path_setting(repo):
    process = subprocess.run(
        ["git", "-C", str(repo), "config", "--local", "--get", "core.hooksPath"],
        capture_output=True,
        text=True,
        check=False,
    )
    return process.stdout.strip() if process.returncode == 0 else None


def test_candidate_creation_runs_no_post_checkout_hook(repo, broker, tmp_path):
    marker = tmp_path / "post-checkout-ran"
    hook = install_post_checkout(repo / ".git" / "hooks", marker)
    hook_script = hook.read_text()
    config_before = local_config(repo)
    state = broker.accepted_state()

    candidate = broker.create_candidate(state)

    assert not marker.exists()
    # Creation is otherwise unchanged: exact commit, base ref, detached worktree.
    assert git(candidate.local_path, "rev-parse", "HEAD") == state.accepted_commit
    base = f"refs/cloudeo/workspaces/demo/candidates/{candidate.candidate_id}/base"
    assert git(repo, "rev-parse", base) == state.accepted_commit
    worktrees = git(repo, "worktree", "list", "--porcelain").split("\n\n")
    entry = next(w for w in worktrees if f"worktree {candidate.local_path}" in w)
    assert "detached" in entry.splitlines()
    # The repository's hook and config are exactly as they were.
    assert hook.read_text() == hook_script
    assert local_config(repo) == config_before
    assert hooks_path_setting(repo) is None
    # The hook is live for an ordinary, non-broker Git operation.
    with pytest.raises(subprocess.CalledProcessError):
        git(repo, "worktree", "add", "--detach", str(tmp_path / "user-worktree"), "HEAD")
    assert marker.read_text() == "ran\n"


def test_candidate_creation_overrides_configured_hooks_path(repo, broker, tmp_path):
    marker = tmp_path / "custom-hook-ran"
    install_post_checkout(repo / "project-hooks", marker)
    git(repo, "config", "--local", "core.hooksPath", "project-hooks")
    config_before = local_config(repo)

    broker.create_candidate(broker.accepted_state())

    assert not marker.exists()
    assert hooks_path_setting(repo) == "project-hooks"
    assert local_config(repo) == config_before
    with pytest.raises(subprocess.CalledProcessError):
        git(repo, "checkout", "-q", "-b", "user-branch")
    assert marker.exists()


def test_rollback_still_works_with_post_checkout_hook(repo, broker, root, tmp_path, monkeypatch):
    marker = tmp_path / "post-checkout-ran"
    install_post_checkout(repo / ".git" / "hooks", marker)
    fixed = uuid.UUID(int=3)
    monkeypatch.setattr(git_module.uuid, "uuid4", lambda: fixed)
    (root / "demo" / fixed.hex).mkdir(parents=True)
    (root / "demo" / fixed.hex / "occupied").write_text("x\n")
    before_refs = git(repo, "for-each-ref", "refs/cloudeo")
    with pytest.raises(git_module.GitCommandError, match="worktree add"):
        broker.create_candidate(broker.accepted_state())
    assert git(repo, "for-each-ref", "refs/cloudeo") == before_refs
    assert not marker.exists()


# --- Candidate creation rollback ---


def test_failed_worktree_creation_leaves_no_candidate(repo, broker, root, monkeypatch):
    fixed = uuid.UUID(int=1)
    monkeypatch.setattr(git_module.uuid, "uuid4", lambda: fixed)
    blocking = root / "demo" / fixed.hex
    blocking.mkdir(parents=True)
    (blocking / "keep.txt").write_text("not the broker's\n")
    before_refs = git(repo, "for-each-ref", "refs/cloudeo")
    before_worktrees = git(repo, "worktree", "list", "--porcelain")
    with pytest.raises(git_module.GitCommandError, match="worktree add"):
        broker.create_candidate(broker.accepted_state())
    assert git(repo, "for-each-ref", "refs/cloudeo") == before_refs
    assert git(repo, "worktree", "list", "--porcelain") == before_worktrees
    assert (blocking / "keep.txt").read_text() == "not the broker's\n"


def test_rollback_only_removes_the_failed_candidate(repo, broker, root, monkeypatch):
    survivor = broker.create_candidate(broker.accepted_state())
    fixed = uuid.UUID(int=2)
    monkeypatch.setattr(git_module.uuid, "uuid4", lambda: fixed)
    (root / "demo" / fixed.hex).mkdir(parents=True)
    (root / "demo" / fixed.hex / "occupied").write_text("x\n")
    with pytest.raises(git_module.GitCommandError):
        broker.create_candidate(broker.accepted_state())
    assert broker.inspect_candidate(survivor).head_commit == survivor.base_commit
    base = f"refs/cloudeo/workspaces/demo/candidates/{fixed.hex}/base"
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", base], check=False
        ).returncode
        != 0
    )


# --- No network ---


def test_broker_runs_only_local_git_subcommands(repo, broker, monkeypatch):
    assert not NETWORK_SUBCOMMANDS & ALLOWED_GIT_SUBCOMMANDS
    real_run = subprocess.run
    seen = []

    def recording_run(argv, *args, **kwargs):
        # argv: git -C <path> [-c k=v ...] <subcommand> ...
        rest = argv[3:]
        while rest and rest[0] == "-c":
            rest = rest[2:]
        seen.append(rest[0])
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(git_module.subprocess, "run", recording_run)
    state = broker.accepted_state()
    candidate = broker.create_candidate(state)
    broker.inspect_candidate(candidate)
    checkpoint = change_and_checkpoint(broker, candidate)
    broker.promote(checkpoint)
    rejected = broker.create_candidate(broker.accepted_state())
    broker.reject(rejected, "no", change_and_checkpoint(broker, rejected, "rejected.txt"))
    broker.cleanup(candidate)
    broker.cleanup(rejected)
    assert seen
    assert set(seen) <= ALLOWED_GIT_SUBCOMMANDS
    with pytest.raises(WorkspaceBrokerError, match="not permitted"):
        broker._git("fetch", "origin")
