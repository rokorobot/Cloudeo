#!/usr/bin/env python3
"""Cloudeo workspace bridge helper.

Transport infrastructure supplied by Cloudeo, not task code. It is uploaded to
the harness session verbatim and uses the Python standard library only.

    unpack --run-id RUN       extract the candidate snapshot into this directory
    pack-delta --run-id RUN   write the changes since unpack as one output archive

The snapshot never contains .git. The output is a delta against the input
manifest: added and changed files, plus an explicit list of deleted paths.
Cloudeo validates the output independently; nothing here is trusted by it.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import stat
import sys
import tarfile

FORMAT = "cloudeo.workspace-bridge/1"
HELPER_NAME = ".cloudeo-bridge-helper.py"
MANIFEST_MEMBER = "manifest.json"
FILES_PREFIX = "files/"
RUN_ID_PATTERN = re.compile(r"^bridge_[0-9a-f]{32}$")
# Bridge-owned names at the workspace root; never project content.
RESERVED_ROOT_PREFIXES = (".cloudeo-bridge", "cloudeo-bridge-output-")
# Harness runtime state at the workspace root; never part of the delta.
ROOT_RUNTIME_DIRS = frozenset({".claude", ".codex", ".harness"})
# Excluded at any depth.
ANY_DEPTH_EXCLUDED = frozenset({".git", "__pycache__"})
EXECUTABLE_MODE = 0o755
REGULAR_MODE = 0o644
# HarnessRouter writes one of these at the workspace root before the harness
# starts (runner `_write_agent_doc`), overwriting any existing copy, and marks
# its managed block with this marker. They are NOT excluded project paths: only
# the bootstrap copy is reconciled at unpack; afterwards they sync normally.
MANAGED_ROOT_DOCS = ("AGENTS.md", "CLAUDE.md", "QWEN.md", "GEMINI.md")
HARNESSROUTER_MANAGED_MARKER = b"<!-- harness-skills:begin -->"


class BridgeHelperError(Exception):
    pass


def input_archive_name(run_id: str) -> str:
    return f".cloudeo-bridge-input-{run_id}.tar.gz"


def output_archive_name(run_id: str) -> str:
    return f"cloudeo-bridge-output-{run_id}.tar.gz"


def check_relpath(path: object) -> str:
    """A safe, normalized, relative POSIX path that cannot escape the workspace."""
    if not isinstance(path, str) or not path:
        raise BridgeHelperError(f"invalid path {path!r}")
    if "\x00" in path or "\\" in path or path.startswith("/"):
        raise BridgeHelperError(f"unsafe path {path!r}")
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise BridgeHelperError(f"unsafe path {path!r}")
    if re.match(r"^[A-Za-z]:", parts[0]):
        raise BridgeHelperError(f"unsafe path {path!r}")
    if any(part.lower() == ".git" for part in parts):
        raise BridgeHelperError(f"path inside .git refused: {path!r}")
    return path


def is_reserved(path: str) -> bool:
    return path.split("/", 1)[0].startswith(RESERVED_ROOT_PREFIXES)


def is_excluded(path: str) -> bool:
    parts = path.split("/")
    if parts[0] in ROOT_RUNTIME_DIRS or is_reserved(path):
        return True
    return any(part in ANY_DEPTH_EXCLUDED or part.lower() == ".git" for part in parts)


def file_entry(path: str, data: bytes, executable: bool) -> dict:
    return {
        "path": path,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "executable": executable,
    }


def build_archive(manifest: dict, files: dict) -> bytes:
    """Deterministic tar.gz: manifest.json plus files/<path>; files maps path -> (data, exec)."""
    buffer = io.BytesIO()
    members = [(MANIFEST_MEMBER, _json_bytes(manifest), False)]
    members += [(FILES_PREFIX + p, files[p][0], files[p][1]) for p in sorted(files)]
    # Nested on purpose: parenthesized multi-context `with` needs Python 3.10, and
    # this helper must run on whatever python3 the harness sandbox provides.
    with gzip.GzipFile(filename="", fileobj=buffer, mode="wb", mtime=0) as gz:  # noqa: SIM117
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for name, data, executable in members:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = EXECUTABLE_MODE if executable else REGULAR_MODE
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _json_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _read_input(root: str, run_id: str) -> tuple:
    if not RUN_ID_PATTERN.match(run_id):
        raise BridgeHelperError(f"invalid run id {run_id!r}")
    path = os.path.join(root, input_archive_name(run_id))
    if not os.path.isfile(path):
        raise BridgeHelperError(f"input archive {input_archive_name(run_id)} not found")
    manifest = None
    manifest_sha256 = None
    files = {}
    with tarfile.open(path, mode="r:gz") as tar:
        for member in tar:
            if not member.isreg() or member.issparse():
                raise BridgeHelperError(f"unexpected input member type: {member.name!r}")
            data = tar.extractfile(member).read()
            if member.name == MANIFEST_MEMBER:
                manifest = json.loads(data)
                manifest_sha256 = hashlib.sha256(data).hexdigest()
            elif member.name.startswith(FILES_PREFIX):
                files[check_relpath(member.name[len(FILES_PREFIX) :])] = data
            else:
                raise BridgeHelperError(f"undeclared input member {member.name!r}")
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise BridgeHelperError("input manifest missing or of an unknown format")
    if manifest.get("kind") != "input" or manifest.get("bridge_run_id") != run_id:
        raise BridgeHelperError("input manifest does not belong to this bridge run")
    return manifest, manifest_sha256, files


def unpack(root: str, run_id: str) -> dict:
    manifest, _, files = _read_input(root, run_id)
    declared = {entry["path"]: entry for entry in manifest["files"]}
    if set(declared) != set(files):
        raise BridgeHelperError("input archive members do not match its manifest")
    for path, data in files.items():
        entry = declared[path]
        if hashlib.sha256(data).hexdigest() != entry["sha256"] or len(data) != entry["size"]:
            raise BridgeHelperError(f"input file {path!r} does not match its manifest")
    # Before any project file is written: HarnessRouter's bootstrap docs must not
    # become part of the project baseline.
    bootstrap = reconcile_bootstrap_docs(root, files)
    for path in sorted(files):
        entry, data = declared[path], files[path]
        dest = _safe_destination(root, path)
        if os.path.lexists(dest) and bootstrap.get(path) != "replaced":
            # Check the link before opening, so an existing symlink is never followed.
            if os.path.islink(dest) or not os.path.isfile(dest):
                raise BridgeHelperError(f"workspace already has a non-file at {path!r}")
            with open(dest, "rb") as existing:
                if existing.read() != data:
                    raise BridgeHelperError(f"workspace already has a different {path!r}")
        with open(dest, "wb") as handle:
            handle.write(data)
        os.chmod(dest, EXECUTABLE_MODE if entry["executable"] else REGULAR_MODE)
    return _identity(manifest, files=len(files), bootstrap_docs=bootstrap)


def reconcile_bootstrap_docs(root: str, files: dict) -> dict:
    """Remove or mark for replacement HarnessRouter's bootstrap instruction docs.

    For each known root doc that exists: it must be a regular file (a symlink is
    never followed). If it carries HarnessRouter's managed marker it is bootstrap
    state: replaced by the candidate's copy when the snapshot has that path,
    otherwise removed. An unmarked file is unknown remote state: allowed only if
    it already equals the candidate's copy, otherwise the unpack fails closed and
    the file is left alone.
    """
    actions = {}
    for name in MANAGED_ROOT_DOCS:
        path = os.path.join(root, name)
        if not os.path.lexists(path):
            continue
        mode = os.lstat(path).st_mode
        if not stat.S_ISREG(mode):
            kind = "symlink" if stat.S_ISLNK(mode) else "non-regular file"
            raise BridgeHelperError(f"remote {name} is a {kind}; refusing to use it")
        with open(path, "rb") as handle:
            existing = handle.read()
        if HARNESSROUTER_MANAGED_MARKER in existing:
            if name in files:
                actions[name] = "replaced"
            else:
                os.unlink(path)
                actions[name] = "removed"
        elif name in files and existing == files[name]:
            actions[name] = "identical"
        else:
            raise BridgeHelperError(
                f"unexpected remote {name} without the HarnessRouter marker; "
                "refusing to overwrite or delete it"
            )
    return actions


def _safe_destination(root: str, path: str) -> str:
    """Create missing parents without ever writing through a symlink or a file.

    Walks every parent component under the workspace root: an existing symlink or
    non-directory is refused, and the final parent must resolve inside the root.
    """
    real_root = os.path.realpath(root)
    parent = root
    for part in path.split("/")[:-1]:
        parent = os.path.join(parent, part)
        if os.path.islink(parent):
            raise BridgeHelperError(f"refusing to write {path!r} through the symlink {part!r}")
        if os.path.lexists(parent):
            if not os.path.isdir(parent):
                raise BridgeHelperError(f"refusing to write {path!r}: {part!r} is not a directory")
        else:
            os.mkdir(parent)
    real_parent = os.path.realpath(parent)
    if real_parent != real_root and not real_parent.startswith(real_root + os.sep):
        raise BridgeHelperError(f"refusing to write {path!r} outside the workspace")
    return os.path.join(parent, path.split("/")[-1])


class OutputLimitExceeded(BridgeHelperError):
    """The remote workspace exceeds a bridge output limit; no delta is built."""

    def __init__(self, error: str, message: str, limit: int, observed: int, path=None):
        super().__init__(message)
        self.error, self.limit, self.observed, self.path = error, limit, observed, path


def scan(root: str, limits: dict | None = None) -> dict:
    """Current project files as path -> entry; refuses links and special files.

    Sizes are checked with lstat before a file is read, so an oversized executor
    workspace is refused without being loaded into memory.
    """
    limits = limits or {}
    max_files = limits.get("max_output_files")
    max_total = limits.get("max_output_total_bytes")
    max_file = limits.get("max_output_file_bytes")
    found = {}
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        base = os.path.relpath(dirpath, root)
        prefix = "" if base == "." else base.replace(os.sep, "/") + "/"
        kept = []
        for name in dirnames:
            rel = prefix + name
            if is_excluded(rel):
                continue
            if os.path.islink(os.path.join(dirpath, name)):
                raise BridgeHelperError(f"symbolic links are not supported: {rel!r}")
            kept.append(name)
        dirnames[:] = sorted(kept)
        for name in sorted(filenames):
            rel = prefix + name
            if is_excluded(rel):
                continue
            full = os.path.join(dirpath, name)
            info = os.lstat(full)
            if stat.S_ISLNK(info.st_mode):
                raise BridgeHelperError(f"symbolic links are not supported: {rel!r}")
            if not stat.S_ISREG(info.st_mode):
                raise BridgeHelperError(f"special files are not supported: {rel!r}")
            if max_file is not None and info.st_size > max_file:
                raise OutputLimitExceeded(
                    "output_file_too_large",
                    f"{rel!r} is {info.st_size} bytes; the per-file limit is {max_file}",
                    max_file,
                    info.st_size,
                    rel,
                )
            if max_files is not None and len(found) + 1 > max_files:
                raise OutputLimitExceeded(
                    "output_file_count_exceeded",
                    f"more than {max_files} project files",
                    max_files,
                    len(found) + 1,
                )
            total += info.st_size
            if max_total is not None and total > max_total:
                raise OutputLimitExceeded(
                    "output_total_bytes_exceeded",
                    f"project files exceed {max_total} bytes in total",
                    max_total,
                    total,
                )
            with open(full, "rb") as handle:
                data = handle.read()
            found[check_relpath(rel)] = (file_entry(rel, data, bool(info.st_mode & 0o111)), data)
    return found


OUTPUT_LIMIT_KEYS = (
    "max_output_files",
    "max_output_total_bytes",
    "max_output_file_bytes",
    "max_output_bundle_bytes",
)


def pack_delta(root: str, run_id: str) -> dict:
    manifest, manifest_sha256, _ = _read_input(root, run_id)
    identity = {
        "format": FORMAT,
        "bridge_run_id": run_id,
        "workspace_id": manifest["workspace_id"],
        "candidate_id": manifest["candidate_id"],
        "base_commit": manifest["base_commit"],
        "input_manifest_sha256": manifest_sha256,
    }
    limits = {key: manifest[key] for key in OUTPUT_LIMIT_KEYS}
    try:
        return _pack(root, run_id, manifest, identity, limits)
    except OutputLimitExceeded as exc:
        # One small error artifact instead of a partial or split delta.
        report = {
            **identity,
            "kind": "error",
            "error": exc.error,
            "limit": exc.limit,
            "observed": exc.observed,
            "path": exc.path,
        }
        _write_output(root, run_id, build_archive(report, {}))
        raise


def _write_output(root: str, run_id: str, archive: bytes) -> None:
    temp = os.path.join(root, f".cloudeo-bridge-tmp-{run_id}")
    with open(temp, "wb") as handle:
        handle.write(archive)
    os.replace(temp, os.path.join(root, output_archive_name(run_id)))


def _pack(root: str, run_id: str, manifest: dict, identity: dict, limits: dict) -> dict:
    before = {entry["path"]: entry for entry in manifest["files"]}
    now = scan(root, limits)
    added, changed, returned = [], [], {}
    for path, (entry, data) in sorted(now.items()):
        old = before.get(path)
        if old is None:
            added.append(entry)
        elif old["sha256"] == entry["sha256"] and old["executable"] == entry["executable"]:
            continue
        else:
            changed.append(entry)
        returned[path] = (data, entry["executable"])
    deleted = sorted(p for p in before if p not in now and not is_excluded(p))
    delta = {**identity, "kind": "delta", "added": added, "changed": changed, "deleted": deleted}
    archive = build_archive(delta, returned)
    limit = limits["max_output_bundle_bytes"]
    if len(archive) > limit:
        raise OutputLimitExceeded(
            "output_too_large",
            f"the delta ({len(archive)} bytes) does not fit in one bridge artifact ({limit})",
            limit,
            len(archive),
        )
    _write_output(root, run_id, archive)
    return _identity(manifest, added=len(added), changed=len(changed), deleted=len(deleted))


def _identity(manifest: dict, **details: object) -> dict:
    keys = ("bridge_run_id", "workspace_id", "candidate_id", "base_commit")
    return {"ok": True, **{key: manifest[key] for key in keys}, **details}


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cloudeo-bridge-helper")
    parser.add_argument("operation", choices=("unpack", "pack-delta"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    root = os.path.abspath(args.root)
    try:
        result = (unpack if args.operation == "unpack" else pack_delta)(root, args.run_id)
    except OutputLimitExceeded as exc:
        print(
            f"cloudeo-bridge-helper: error: {exc.error}: {exc}; "
            "a bridge error artifact was written instead of a delta",
            file=sys.stderr,
        )
        return 3
    except (BridgeHelperError, OSError, ValueError, KeyError, tarfile.TarError) as exc:
        print(f"cloudeo-bridge-helper: error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
