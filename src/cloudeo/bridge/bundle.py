"""Local side of the workspace bridge: select, bundle, validate, and apply.

The downloaded output bundle is untrusted executor output. It is validated as a
whole, into a staging directory outside the candidate, before the candidate is
touched. Only paths that were sent can be changed or deleted, and only if they
still match what was sent.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import uuid
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from cloudeo.bridge import remote_helper as helper
from cloudeo.bridge.models import (
    BridgeFileEntry,
    BridgeLimits,
    DeltaManifest,
    ErrorManifest,
    InputManifest,
)
from cloudeo.workspace.models import CandidateWorkspace

# Local, read-only Git queries only.
ALLOWED_GIT_SUBCOMMANDS = frozenset({"ls-files", "check-ignore"})


class BridgeError(Exception):
    code = "bridge_error"


class BridgeInputError(BridgeError):
    """The candidate cannot be sent; raised before anything is uploaded."""

    code = "invalid_input"


class BridgeValidationError(BridgeError):
    """The output bundle was rejected; the candidate was not touched."""

    code = "invalid_bundle"


class BridgeOutputTooLarge(BridgeValidationError):
    """The executor's delta could not fit in one bridge artifact."""

    code = "output_too_large"


class BridgeConflictError(BridgeError):
    """A sent file no longer matches locally; the candidate was not touched."""

    code = "workspace_conflict"


class CandidateDriftError(BridgeError):
    """The candidate changed while the remote episode ran; nothing was applied."""

    code = "candidate_changed_during_execution"


class BridgeUnsafePathError(BridgeError):
    """A write would pass through a local symlink or into .git; nothing was applied."""

    code = "unsafe_local_path"


class BridgeApplyError(BridgeError):
    """A filesystem write failed and every applied change was rolled back."""

    code = "apply_failed"


def new_run_id() -> str:
    return f"bridge_{uuid.uuid4().hex}"


def git(root: Path, *args: str, stdin: bytes | None = None) -> bytes:
    if args[0] not in ALLOWED_GIT_SUBCOMMANDS:
        raise BridgeError(f"git {args[0]} is not permitted in the bridge.")
    process = subprocess.run(
        ["git", "-C", str(root), *args],
        input=stdin,
        capture_output=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"},
        check=False,
    )
    # check-ignore exits 1 when nothing is ignored.
    if process.returncode not in (0, 1) or (process.returncode == 1 and args[0] != "check-ignore"):
        raise BridgeError(f"git {args[0]} failed: {process.stderr.decode(errors='replace')}")
    return process.stdout


# --- Input: select and bundle ---


@dataclass(frozen=True)
class InputBundle:
    manifest: InputManifest
    archive: bytes
    # SHA-256 of manifest.json exactly as sent; the returned delta must echo it.
    manifest_sha256: str


def manifest_sha256(manifest: InputManifest) -> str:
    """Hash of the canonical manifest bytes, identical to the archive's manifest.json."""
    return hashlib.sha256(helper._json_bytes(manifest.model_dump(mode="json"))).hexdigest()


def _has_symlink_parent(root: Path, path: str) -> bool:
    parent = root
    for part in path.split("/")[:-1]:
        parent = parent / part
        if parent.is_symlink():
            return True
    return False


def select_files(root: Path, limits: BridgeLimits) -> dict[str, tuple[bytes, bool]]:
    """Tracked plus untracked, non-ignored files: never .git, never ignored files."""
    raw = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    selected: dict[str, tuple[bytes, bool]] = {}
    total = 0
    for item in sorted({p for p in raw.split(b"\0") if p}):
        try:
            path = item.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BridgeInputError(f"non-UTF-8 path is not supported: {item!r}") from exc
        if path.endswith("/"):
            raise BridgeInputError(f"nested repositories are not supported: {path!r}")
        try:
            helper.check_relpath(path)
        except helper.BridgeHelperError as exc:
            raise BridgeInputError(str(exc)) from exc
        if helper.is_reserved(path):
            raise BridgeInputError(f"path collides with a bridge-reserved name: {path!r}")
        if _has_symlink_parent(root, path):
            # Never read project content through a symlinked directory.
            raise BridgeInputError(f"symbolic-link parent directories are not supported: {path!r}")
        full = root / path
        try:
            mode = full.lstat().st_mode
        except FileNotFoundError:
            continue  # tracked but deleted in the working tree: not sent
        if stat.S_ISLNK(mode):
            raise BridgeInputError(f"symbolic links are not supported yet: {path!r}")
        if stat.S_ISDIR(mode):
            raise BridgeInputError(f"submodules are not supported: {path!r}")
        if not stat.S_ISREG(mode):
            raise BridgeInputError(f"special files are not supported: {path!r}")
        data = full.read_bytes()
        if len(data) > limits.max_file_bytes:
            raise BridgeInputError(f"{path!r} exceeds the per-file limit")
        total += len(data)
        selected[path] = (data, bool(mode & 0o111))
    if len(selected) > limits.max_files or total > limits.max_total_bytes:
        raise BridgeInputError("the candidate exceeds the bridge file-count or size limit")
    return selected


def _entries(files: dict[str, tuple[bytes, bool]]) -> tuple[BridgeFileEntry, ...]:
    return tuple(
        BridgeFileEntry(**helper.file_entry(path, data, executable))
        for path, (data, executable) in sorted(files.items())
    )


def build_input_bundle(
    candidate: CandidateWorkspace, head_commit: str, run_id: str, limits: BridgeLimits
) -> InputBundle:
    files = select_files(candidate.local_path, limits)
    manifest = InputManifest(
        format=helper.FORMAT,
        kind="input",
        bridge_run_id=run_id,
        workspace_id=candidate.workspace_id,
        candidate_id=candidate.candidate_id,
        base_commit=candidate.base_commit,
        head_commit=head_commit,
        max_output_bundle_bytes=limits.max_output_bundle_bytes,
        files=_entries(files),
    )
    archive = helper.build_archive(manifest.model_dump(mode="json"), files)
    if len(archive) > limits.max_input_bundle_bytes:
        raise BridgeInputError("the input bundle exceeds the upload limit")
    return InputBundle(
        manifest=manifest, archive=archive, manifest_sha256=manifest_sha256(manifest)
    )


def check_candidate_unchanged(root: Path, sent: InputManifest, limits: BridgeLimits) -> None:
    """Optimistic concurrency: the snapshot that was sent is the apply precondition.

    Rebuilds the candidate manifest with the same selection and hashing rules and
    requires it to equal what was sent. Any local edit, addition, deletion, or
    executable-bit change made while the remote episode ran is refused; the two
    sides are never merged.
    """
    try:
        current = _entries(select_files(root, limits))
    except BridgeInputError as exc:
        raise CandidateDriftError(f"the candidate can no longer be read as sent: {exc}") from exc
    if current == sent.files:
        return
    before = {entry.path: entry for entry in sent.files}
    now = {entry.path: entry for entry in current}
    changes = sorted(
        [f"added {p}" for p in now.keys() - before.keys()]
        + [f"deleted {p}" for p in before.keys() - now.keys()]
        + [f"modified {p}" for p in now.keys() & before.keys() if now[p] != before[p]]
    )
    shown = ", ".join(changes[:10]) + (", ..." if len(changes) > 10 else "")
    raise CandidateDriftError(f"the candidate changed locally during execution: {shown}")


# --- Output: validate the whole untrusted bundle before any mutation ---


@dataclass
class ValidatedDelta:
    manifest: DeltaManifest
    staging: Path
    staged: dict[str, Path] = field(default_factory=dict)


class _BoundedReader:
    """Decompresses lazily and refuses to produce more than `limit` bytes."""

    def __init__(self, data: bytes, limit: int):
        self._gzip = gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb")
        self._limit = limit
        self._read = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._gzip.read(size if size and size > 0 else 1024 * 1024)
        self._read += len(chunk)
        if self._read > self._limit:
            raise BridgeValidationError("output bundle exceeds the decompressed-size limit")
        return chunk


def _unique_keys(pairs: list) -> dict:
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise BridgeValidationError("manifest has duplicate keys")
    return dict(pairs)


def validate_output_bundle(
    data: bytes, sent: InputBundle, limits: BridgeLimits, staging_root: Path | None = None
) -> ValidatedDelta:
    if len(data) > limits.max_output_bundle_bytes:
        raise BridgeValidationError("output bundle exceeds the compressed-size limit")
    staging = Path(tempfile.mkdtemp(prefix="cloudeo-bridge-", dir=staging_root))
    try:
        return _validate(data, sent, limits, staging)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _validate(data: bytes, sent: InputBundle, limits: BridgeLimits, staging: Path):
    # Headers plus the member data we accept bound the decompressed stream.
    cap = limits.max_total_bytes + limits.max_manifest_bytes + 1024 * (limits.max_files + 8)
    names: set[str] = set()
    manifest_raw: bytes | None = None
    staged: dict[str, tuple[Path, int, str]] = {}
    total = 0
    try:
        with tarfile.open(fileobj=_BoundedReader(data, cap), mode="r|") as tar:
            for member in tar:
                if len(names) >= limits.max_files + 1:
                    raise BridgeValidationError("output bundle has too many members")
                name = member.name
                if name in names:
                    raise BridgeValidationError(f"duplicate member {name!r}")
                names.add(name)
                if not member.isreg() or member.issparse():
                    raise BridgeValidationError(f"member {name!r} is not a regular file")
                if name == helper.MANIFEST_MEMBER:
                    if member.size > limits.max_manifest_bytes:
                        raise BridgeValidationError("manifest exceeds its size limit")
                    manifest_raw = _read_member(tar, member)
                    continue
                if not name.startswith(helper.FILES_PREFIX):
                    raise BridgeValidationError(f"undeclared member {name!r}")
                path = _safe(name[len(helper.FILES_PREFIX) :])
                if member.size > limits.max_file_bytes:
                    raise BridgeValidationError(f"{path!r} exceeds the per-file limit")
                total += member.size
                if total > limits.max_total_bytes:
                    raise BridgeValidationError("output files exceed the total-size limit")
                target = staging / f"f{len(staged)}"
                digest = _stage_member(tar, member, target)
                staged[path] = (target, member.size, digest)
    except (tarfile.TarError, EOFError, OSError, zlib.error) as exc:
        raise BridgeValidationError(f"malformed output bundle: {exc}") from exc
    if manifest_raw is None:
        raise BridgeValidationError("output bundle has no manifest")
    try:
        parsed = json.loads(manifest_raw, object_pairs_hook=_unique_keys)
        if isinstance(parsed, dict) and parsed.get("kind") == "error":
            report = ErrorManifest.model_validate_json(manifest_raw)
        else:
            manifest = DeltaManifest.model_validate_json(manifest_raw)
    except (ValueError, ValidationError) as exc:
        raise BridgeValidationError(f"invalid output manifest: {exc}") from exc
    if isinstance(parsed, dict) and parsed.get("kind") == "error":
        _check_identity(report, sent)
        if staged:
            raise BridgeValidationError("an error report must not carry files")
        raise BridgeOutputTooLarge(
            f"the executor's delta ({report.delta_bytes} bytes) does not fit in one bridge "
            f"artifact (limit {report.limit} bytes); nothing was applied"
        )
    _check_identity(manifest, sent)
    _check_paths(manifest, sent.manifest, staged)
    return ValidatedDelta(
        manifest=manifest,
        staging=staging,
        staged={path: target for path, (target, _, _) in staged.items()},
    )


def _read_member(tar: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    handle = tar.extractfile(member)
    data = handle.read(member.size + 1) if handle else b""
    if len(data) != member.size:
        raise BridgeValidationError(f"truncated member {member.name!r}")
    return data


def _stage_member(tar: tarfile.TarFile, member: tarfile.TarInfo, target: Path) -> str:
    handle = tar.extractfile(member)
    digest = hashlib.sha256()
    written = 0
    with open(target, "wb") as out:
        while handle is not None:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > member.size:
                raise BridgeValidationError(f"member {member.name!r} is longer than declared")
            digest.update(chunk)
            out.write(chunk)
    if written != member.size:
        raise BridgeValidationError(f"truncated member {member.name!r}")
    return digest.hexdigest()


def _safe(path: str) -> str:
    try:
        helper.check_relpath(path)
    except helper.BridgeHelperError as exc:
        raise BridgeValidationError(str(exc)) from exc
    if helper.is_excluded(path):
        raise BridgeValidationError(f"{path!r} is excluded from bridge output")
    return path


def _check_identity(manifest: DeltaManifest | ErrorManifest, sent: InputBundle) -> None:
    for key in ("bridge_run_id", "workspace_id", "candidate_id", "base_commit"):
        if getattr(manifest, key) != getattr(sent.manifest, key):
            raise BridgeValidationError(f"output {key} does not match this bridge run")
    # Not a trust boundary: prevents applying a delta made from another snapshot.
    if manifest.input_manifest_sha256 != sent.manifest_sha256:
        raise BridgeValidationError(
            "output input_manifest_sha256 does not match the snapshot sent for this run"
        )


def _check_paths(
    manifest: DeltaManifest, sent: InputManifest, staged: dict[str, tuple[Path, int, str]]
) -> None:
    sent_paths = {entry.path for entry in sent.files}
    returned = [entry.path for entry in (*manifest.added, *manifest.changed)]
    every = [*returned, *manifest.deleted]
    for path in every:
        _safe(path)
    if len(every) != len(set(every)):
        raise BridgeValidationError("a path appears more than once in the delta")
    if set(returned) != set(staged):
        raise BridgeValidationError("archive members do not match the manifest")
    for entry in manifest.added:
        if entry.path in sent_paths:
            raise BridgeValidationError(f"added {entry.path!r} was already sent")
    for path in [entry.path for entry in manifest.changed] + list(manifest.deleted):
        if path not in sent_paths:
            raise BridgeValidationError(f"{path!r} was not sent, so it cannot change")
    for entry in (*manifest.added, *manifest.changed):
        _, size, digest = staged[entry.path]
        if size != entry.size or digest != entry.sha256:
            raise BridgeValidationError(f"{entry.path!r} does not match its manifest hash")
    final = (sent_paths - set(manifest.deleted)) | set(returned)
    for path in final:
        parts = path.split("/")
        for depth in range(1, len(parts)):
            if "/".join(parts[:depth]) in final:
                raise BridgeValidationError(f"{path!r} would be inside the file {parts[0]!r}")


# --- Apply the validated delta to the candidate ---


@dataclass(frozen=True)
class AppliedDelta:
    added: tuple[str, ...]
    changed: tuple[str, ...]
    deleted: tuple[str, ...]
    ignored: tuple[str, ...]


def apply_delta(root: Path, delta: ValidatedDelta, sent: InputManifest) -> AppliedDelta:
    """Plan fully, then mutate; restore project files if a write fails midway."""
    root = root.resolve()
    manifest = delta.manifest
    sent_by_path = {entry.path: entry for entry in sent.files}

    # Plan: every precondition is checked before the first mutation. Path safety
    # comes first for every path in the delta, including ignored additions, so a
    # symlinked parent or .git is refused outright (fail closed) and Git is never
    # queried about a path beyond a symlink.
    every = [entry.path for entry in (*manifest.changed, *manifest.added)]
    targets = {path: _target(root, path) for path in [*every, *manifest.deleted]}
    ignored = _ignored(root, [entry.path for entry in manifest.added])
    added = [entry for entry in manifest.added if entry.path not in ignored]
    for path in [entry.path for entry in manifest.changed] + list(manifest.deleted):
        if not _matches(targets[path], sent_by_path[path]):
            raise BridgeConflictError(f"{path!r} changed locally since it was sent")
    for entry in added:
        target = targets[entry.path]
        if os.path.lexists(target):
            raise BridgeConflictError(f"{entry.path!r} was created locally since the send")

    journal = _Journal(root, delta.staging / "backup")
    try:
        for entry in manifest.changed:
            journal.write(entry.path, delta.staged[entry.path], entry.executable)
        for entry in added:
            journal.write(entry.path, delta.staged[entry.path], entry.executable)
        for path in manifest.deleted:
            journal.delete(path)
    except BaseException as exc:
        try:
            journal.rollback()
        except BaseException as rollback_exc:
            # Surface the original failure; the rollback failure is secondary evidence
            # (in the note, and as __context__).
            exc.add_note(f"Rollback also failed; the candidate may be inconsistent: {rollback_exc}")
            raise exc from rollback_exc
        raise BridgeApplyError(f"applying the delta failed and was rolled back: {exc}") from exc
    return AppliedDelta(
        added=tuple(entry.path for entry in added),
        changed=tuple(entry.path for entry in manifest.changed),
        deleted=tuple(manifest.deleted),
        ignored=tuple(sorted(ignored)),
    )


def _ignored(root: Path, paths: list[str]) -> set[str]:
    if not paths:
        return set()
    stdin = b"".join(path.encode("utf-8") + b"\0" for path in paths)
    output = git(root, "check-ignore", "--stdin", "-z", stdin=stdin)
    return {item.decode("utf-8") for item in output.split(b"\0") if item}


def _target(root: Path, path: str) -> Path:
    """Resolve inside the candidate; never .git, never through any symlinked parent.

    In a worktree `.git` is usually a file, so `.git` itself is refused as well as
    anything under it. A symlinked parent is refused even when it is ignored or was
    never part of the uploaded snapshot, so `candidate/some_link/file` cannot escape.
    """
    parts = path.split("/")
    if parts[0].lower() == ".git":
        raise BridgeUnsafePathError(f"{path!r} is .git or inside it")
    target = root.joinpath(*parts)
    ancestor = root
    for part in parts[:-1]:
        ancestor = ancestor / part
        if ancestor.is_symlink():
            raise BridgeUnsafePathError(f"{path!r} passes through the symlink {ancestor.name!r}")
        if ancestor.exists() and not ancestor.is_dir():
            raise BridgeConflictError(f"{path!r} has a non-directory parent")
    real_parent = Path(os.path.realpath(target.parent))
    if real_parent != root and root not in real_parent.parents:
        raise BridgeUnsafePathError(f"{path!r} resolves outside the candidate")
    git_path = root / ".git"
    if real_parent == git_path or git_path in real_parent.parents:
        raise BridgeUnsafePathError(f"{path!r} resolves into .git")
    return target


def _matches(target: Path, expected: BridgeFileEntry) -> bool:
    try:
        mode = target.lstat().st_mode
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(mode) or bool(mode & 0o111) != expected.executable:
        return False
    return hashlib.sha256(target.read_bytes()).hexdigest() == expected.sha256


class _Journal:
    """Records each mutation so project files can be restored; never touches .git."""

    def __init__(self, root: Path, backups: Path):
        self.root = root
        self.backups = backups
        self.steps: list[tuple[str, Path, Path | None, int | None]] = []
        self.created_dirs: list[Path] = []
        self.pruned_dirs: list[Path] = []

    def _backup(self, target: Path) -> tuple[Path, int]:
        self.backups.mkdir(parents=True, exist_ok=True)
        backup = self.backups / f"b{len(self.steps)}"
        shutil.copyfile(target, backup)
        return backup, stat.S_IMODE(target.stat().st_mode)

    def _make_parents(self, parent: Path) -> None:
        missing = []
        while not parent.exists():
            missing.append(parent)
            parent = parent.parent
        for directory in reversed(missing):
            directory.mkdir()
            self.created_dirs.append(directory)

    def write(self, path: str, source: Path, executable: bool) -> None:
        target = self.root.joinpath(*path.split("/"))
        existed = target.exists()
        backup, mode = self._backup(target) if existed else (None, None)
        self._make_parents(target.parent)
        self.steps.append(("write", target, backup, mode))
        _replace(target, source, helper.EXECUTABLE_MODE if executable else helper.REGULAR_MODE)

    def delete(self, path: str) -> None:
        target = self.root.joinpath(*path.split("/"))
        backup, mode = self._backup(target)
        self.steps.append(("delete", target, backup, mode))
        target.unlink()
        parent = target.parent
        while parent != self.root and not any(parent.iterdir()):
            parent.rmdir()
            self.pruned_dirs.append(parent)
            parent = parent.parent

    def rollback(self) -> None:
        for directory in reversed(self.pruned_dirs):
            directory.mkdir(exist_ok=True)
        for action, target, backup, mode in reversed(self.steps):
            if backup is not None:
                _replace(target, backup, mode)
            elif action == "write" and os.path.lexists(target):
                target.unlink()
        for directory in reversed(self.created_dirs):
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()


def _replace(target: Path, source: Path, mode: int) -> None:
    temp = target.parent / f".cloudeo-bridge-tmp-{uuid.uuid4().hex}"
    try:
        shutil.copyfile(source, temp)
        os.chmod(temp, mode)
        os.replace(temp, target)
    finally:
        if os.path.lexists(temp):
            os.unlink(temp)
