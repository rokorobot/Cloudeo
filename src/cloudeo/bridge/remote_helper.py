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
    for path in sorted(files):
        entry, data = declared[path], files[path]
        if hashlib.sha256(data).hexdigest() != entry["sha256"] or len(data) != entry["size"]:
            raise BridgeHelperError(f"input file {path!r} does not match its manifest")
        dest = os.path.join(root, *path.split("/"))
        if os.path.lexists(dest):
            # Check the link before opening, so an existing symlink is never followed.
            if os.path.islink(dest) or not os.path.isfile(dest):
                raise BridgeHelperError(f"workspace already has a non-file at {path!r}")
            with open(dest, "rb") as existing:
                if existing.read() != data:
                    raise BridgeHelperError(f"workspace already has a different {path!r}")
        os.makedirs(os.path.dirname(dest) or root, exist_ok=True)
        with open(dest, "wb") as handle:
            handle.write(data)
        os.chmod(dest, EXECUTABLE_MODE if entry["executable"] else REGULAR_MODE)
    return _identity(manifest, files=len(files))


def scan(root: str) -> dict:
    """Current project files as path -> entry; refuses links and special files."""
    found = {}
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
            mode = os.lstat(full).st_mode
            if stat.S_ISLNK(mode):
                raise BridgeHelperError(f"symbolic links are not supported: {rel!r}")
            if not stat.S_ISREG(mode):
                raise BridgeHelperError(f"special files are not supported: {rel!r}")
            with open(full, "rb") as handle:
                data = handle.read()
            found[check_relpath(rel)] = (file_entry(rel, data, bool(mode & 0o111)), data)
    return found


class DeltaTooLarge(BridgeHelperError):
    pass


def pack_delta(root: str, run_id: str) -> dict:
    manifest, manifest_sha256, _ = _read_input(root, run_id)
    before = {entry["path"]: entry for entry in manifest["files"]}
    now = scan(root)
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
    identity = {
        "format": FORMAT,
        "bridge_run_id": run_id,
        "workspace_id": manifest["workspace_id"],
        "candidate_id": manifest["candidate_id"],
        "base_commit": manifest["base_commit"],
        "input_manifest_sha256": manifest_sha256,
    }
    delta = {**identity, "kind": "delta", "added": added, "changed": changed, "deleted": deleted}
    archive = build_archive(delta, returned)
    limit = manifest["max_output_bundle_bytes"]
    too_large = len(archive) > limit
    if too_large:
        # One artifact only: report the overflow explicitly instead of splitting.
        error = {**identity, "kind": "error", "error": "delta_too_large"}
        archive = build_archive({**error, "delta_bytes": len(archive), "limit": limit}, {})
    temp = os.path.join(root, f".cloudeo-bridge-tmp-{run_id}")
    with open(temp, "wb") as handle:
        handle.write(archive)
    os.replace(temp, os.path.join(root, output_archive_name(run_id)))
    if too_large:
        raise DeltaTooLarge(
            f"the delta does not fit in one bridge artifact ({limit} bytes); "
            "an error artifact was written instead"
        )
    return _identity(manifest, added=len(added), changed=len(changed), deleted=len(deleted))


def _identity(manifest: dict, **counts: int) -> dict:
    keys = ("bridge_run_id", "workspace_id", "candidate_id", "base_commit")
    return {"ok": True, **{key: manifest[key] for key in keys}, **counts}


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cloudeo-bridge-helper")
    parser.add_argument("operation", choices=("unpack", "pack-delta"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    root = os.path.abspath(args.root)
    try:
        result = (unpack if args.operation == "unpack" else pack_delta)(root, args.run_id)
    except DeltaTooLarge as exc:
        print(f"cloudeo-bridge-helper: error: {exc}", file=sys.stderr)
        return 3
    except (BridgeHelperError, OSError, ValueError, KeyError, tarfile.TarError) as exc:
        print(f"cloudeo-bridge-helper: error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
