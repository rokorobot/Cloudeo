"""Offline end-to-end tests for the candidate <-> UHP workspace bridge.

Real GitWorkspaceBroker, CandidateWorkspace, ExecutionDispatcher,
UHPHarnessTaskBackend, UHPClient, and bridge helper; the HarnessRouter side is
a fake behind httpx.MockTransport that mirrors the pinned server's behavior:
input files are written into the session working directory under their upload
names, and the session listing applies HarnessRouter's visibility filter.
"""

import ast
import base64
import gzip
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

import httpx
import pytest

from cloudeo.bridge import bundle as bundle_module
from cloudeo.bridge import remote_helper as helper
from cloudeo.bridge.bridge import HELPER_SOURCE, UHPWorkspaceBridge
from cloudeo.bridge.bundle import (
    BridgeError,
    BridgeInputError,
    BridgeValidationError,
    build_input_bundle,
    validate_output_bundle,
)
from cloudeo.bridge.models import BridgeLimits, WorkspaceBridgeTask
from cloudeo.execution.dispatch import ExecutionDispatcher
from cloudeo.execution.uhp_backend import UHPHarnessTaskBackend
from cloudeo.uhp.client import UHPClient
from cloudeo.uhp.models import UHP_VERSION
from cloudeo.workspace.git import GitWorkspaceBroker

HEADERS = {"UHP-Version": UHP_VERSION}
TASK = WorkspaceBridgeTask(
    task="Refactor the app and update the docs.",
    harness_id="chrn_claude",
    model="claude-opus-5",
    max_step=20,
    timeout_seconds=600,
)
SESSION = "hsess_bridge"


# --- Git fixtures ---


@pytest.fixture(autouse=True)
def isolated_git(tmp_path, monkeypatch):
    config = tmp_path / "gitconfig"
    config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("HOME", str(tmp_path))
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(key, raising=False)


def git(cwd, *args):
    identity = ["-c", "user.name=Test Author", "-c", "user.email=test@example.invalid"]
    return subprocess.run(
        ["git", "-C", str(cwd), *identity, *args], capture_output=True, text=True, check=True
    ).stdout.strip()


BINARY = bytes(range(256)) * 4


def init_repo(path, extra=None):
    files = {
        "README.md": b"initial readme\n",
        "src/app.py": b"print('app')\n",
        "bin/run.sh": b"#!/bin/sh\necho run\n",
        "assets/logo.bin": BINARY,
        ".gitignore": b".env\n*.log\nbuild/\n",
        ".github/workflows/ci.yml": b"on: pull_request\n",
        "docs/old.md": b"obsolete\n",
        **(extra or {}),
    }
    for name, data in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_bytes(data)
    os.chmod(path / "bin/run.sh", 0o755)
    git(path, "init", "-q", "-b", "main")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "initial")
    return path


@pytest.fixture
def repo(tmp_path):
    return init_repo(tmp_path / "canonical")


def project_with(tmp_path, extra):
    """A repo whose accepted commit tracks `extra`, its broker, and a candidate."""
    repo = init_repo(tmp_path / "canonical", extra)
    broker = GitWorkspaceBroker.initialize(
        repo, "demo", git(repo, "rev-parse", "HEAD"), tmp_path / "candidates"
    )
    return repo, broker, broker.create_candidate(broker.accepted_state())


@pytest.fixture
def broker(repo, tmp_path):
    return GitWorkspaceBroker.initialize(
        repo, "demo", git(repo, "rev-parse", "HEAD"), tmp_path / "candidates"
    )


@pytest.fixture
def candidate(broker):
    candidate = broker.create_candidate(broker.accepted_state())
    root = candidate.local_path
    (root / ".env").write_text("SECRET=local-only\n")  # ignored: must never be sent
    (root / "debug.log").write_text("noise\n")  # ignored
    (root / "notes").mkdir()
    (root / "notes/new.txt").write_text("untracked but not ignored\n")
    return candidate


def tree(root: Path) -> dict:
    out = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if rel == ".git" or rel.startswith(".git/"):
            continue
        if path.is_symlink():
            out[rel] = ("symlink", os.readlink(path))
        elif path.is_file():
            out[rel] = (
                hashlib.sha256(path.read_bytes()).hexdigest(),
                stat.S_IMODE(path.stat().st_mode),
            )
        else:
            out[rel + "/"] = "dir"
    return out


def snapshot(repo, candidate):
    root = candidate.local_path
    return {
        "tree": tree(root),
        "git_file": (root / ".git").read_bytes(),
        "candidate_head": git(root, "rev-parse", "HEAD"),
        "canonical_head": git(repo, "rev-parse", "HEAD"),
        "canonical_branch": git(repo, "symbolic-ref", "--short", "HEAD"),
        "refs": git(repo, "for-each-ref", "refs/cloudeo"),
    }


def accepted(repo):
    return git(repo, "rev-parse", "refs/cloudeo/workspaces/demo/accepted")


# --- Fake HarnessRouter ---

_HR_HIDE_PREFIXES = (
    ".git/", ".harness/", ".claude/", ".codex/", "tmp/", "node_modules/",
    "__pycache__/", ".venv/", "venv/", ".cache/", ".next/",
)  # fmt: skip
_HR_HIDE_NAMES = {".gitignore", "AGENTS.md", "CLAUDE.md"}


def hr_agent_doc(user_doc="Harness-configured instructions."):
    """What pinned HarnessRouter `_write_agent_doc` writes: user doc + managed block."""
    return (
        f"{user_doc}\n\n<!-- harness-skills:begin -->\n## Workspace\n\n"
        "Your working directory is this task's workspace.\n<!-- harness-skills:end -->\n"
    ).encode()


def hr_visible(path):
    """HarnessRouter CE 0.23.7 _ws_visible, copied for realism."""
    if path in _HR_HIDE_NAMES or path.startswith("."):
        return False
    return not any(path.startswith(p) or f"/{p}" in path for p in _HR_HIDE_PREFIXES)


class FakeHarnessRouter:
    def __init__(
        self,
        root,
        *,
        work=None,
        status="completed",
        session_id=SESSION,
        pack=True,
        output=None,
        extra_files=(),
        task_reply=None,
        listing_reply=None,
        bootstrap_doc="CLAUDE.md",
        bootstrap_content=None,
        before_unpack=None,
        response_overrides=None,
    ):
        self.remote = root / "remote"
        self.response_overrides = response_overrides or {}
        # HarnessRouter's runner writes the backend's instruction doc after the
        # input files and before the harness starts (`_write_agent_doc`).
        self.bootstrap_doc = bootstrap_doc
        self.bootstrap_content = (
            bootstrap_content if bootstrap_content is not None else hr_agent_doc()
        )
        self.before_unpack = before_unpack
        self.helper_outputs = []
        self.work = work
        self.status = status
        self.session_id = session_id
        self.pack = pack
        self.output = output
        self.extra_files = list(extra_files)
        self.extra_blobs = {}
        self.task_reply = task_reply
        self.listing_reply = listing_reply
        self.uploads = {}
        self.task_payloads = []
        self.requests = []
        self.helper_runs = []
        self.workspace = None

    def __call__(self, request):
        path = request.url.path.removeprefix("/api/harness")
        self.requests.append((request.method, path))
        if request.method == "POST" and path == "/v1/files":
            return self._upload(request)
        if request.method == "POST" and path == "/v1/responses":
            return self._task(request)
        if match := re.fullmatch(r"/v1/sessions/([^/]+)/files", path):
            return self._listing(match[1])
        if match := re.fullmatch(r"/v1/containers/([^/]+)/files/([^/]+)/content", path):
            return self._download(match[1], match[2])
        return httpx.Response(404, json={"error": {"code": "not_found"}}, headers=HEADERS)

    def _upload(self, request):
        from test_uhp_files import parse_multipart

        parts = parse_multipart(request)
        file_id = f"file_{len(self.uploads)}"
        self.uploads[file_id] = {
            "filename": parts["file"]["filename"],
            "content": parts["file"]["payload"],
            "purpose": parts["purpose"]["payload"].decode(),
        }
        body = {
            "id": file_id,
            "object": "file",
            "bytes": len(parts["file"]["payload"]),
            "created_at": 1786400000,
            "filename": parts["file"]["filename"],
            "purpose": "user_data",
        }
        return httpx.Response(200, json=body, headers=HEADERS)

    def input_manifest(self):
        """The input manifest of the most recent task (each episode uploads its own)."""
        inputs = [u for u in self.uploads.values() if u["filename"].endswith(".tar.gz")]
        upload = inputs[-1]
        with tarfile.open(fileobj=io.BytesIO(upload["content"]), mode="r:gz") as tar:
            return json.loads(tar.extractfile(helper.MANIFEST_MEMBER).read())

    def _run_helper(self, operation, run_id):
        process = subprocess.run(
            [sys.executable, helper.HELPER_NAME, operation, "--run-id", run_id],
            cwd=self.workspace,
            capture_output=True,
            text=True,
            check=False,  # a failing pack-delta is itself a scenario under test
        )
        self.helper_runs.append((operation, process.returncode, process.stderr))
        self.helper_outputs.append(process.stdout)
        return process.returncode

    def _task(self, request):
        payload = json.loads(request.content)
        self.task_payloads.append(payload)
        if self.task_reply is not None:
            return self.task_reply(request) if callable(self.task_reply) else self.task_reply
        text = next(p["text"] for p in payload["input"][0]["content"] if p["type"] == "input_text")
        run_id = re.search(r"Bridge run id: (bridge_[0-9a-f]{32})", text)[1]
        # Without previous_response_id every task is a fresh session and workspace.
        n = len(self.task_payloads) - 1
        sid = self.session_id if not self.session_id or n == 0 else f"{self.session_id}_{n}"
        self.workspace = self.remote / (sid or f"no-session-{n}")
        self.workspace.mkdir(parents=True)
        for part in payload["input"][0]["content"]:
            if part["type"] == "input_file":
                upload = self.uploads[part["file_id"]]
                (self.workspace / upload["filename"]).write_bytes(upload["content"])
        if self.bootstrap_doc:
            (self.workspace / self.bootstrap_doc).write_bytes(self.bootstrap_content)
        if self.before_unpack:
            self.before_unpack(self.workspace)
        # A cooperative harness stops if unpack fails, so no delta is produced.
        if self.pack and self._run_helper("unpack", run_id) == 0:
            if self.work:
                self.work(self.workspace)
            self._run_helper("pack-delta", run_id)
        if self.output is not None:
            data = self.output(run_id, self.input_manifest())
            (self.workspace / helper.output_archive_name(run_id)).write_bytes(data)
        metadata = {"session_id": sid} if sid else {}
        body = {
            "id": "resp_bridge",
            "object": "response",
            "created_at": 1786400000,
            "status": self.status,
            "model": payload.get("model", "m"),
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Done."}],
                }
            ],
            "error": None,
            "incomplete_details": None,
            "usage": None,
            "metadata": metadata,
            "previous_response_id": None,
            # A dict for every task, or a function of the task index.
            **(
                self.response_overrides(n)
                if callable(self.response_overrides)
                else self.response_overrides
            ),
        }
        return httpx.Response(200, json=body, headers=HEADERS)

    def _listing(self, sid):
        if self.listing_reply is not None:
            return self.listing_reply
        files = []
        if self.workspace is not None:
            for path in sorted(self.workspace.rglob("*")):
                rel = path.relative_to(self.workspace).as_posix()
                if path.is_file() and not path.is_symlink() and hr_visible(rel):
                    fid = "wf_" + base64.urlsafe_b64encode(rel.encode()).decode().rstrip("=")
                    files.append(
                        {
                            "object": "file",
                            "id": fid,
                            "container_id": sid,
                            "filename": rel.rsplit("/", 1)[-1],
                            "path": rel,
                            "bytes": path.stat().st_size,
                        }
                    )
        files += self.extra_files
        return httpx.Response(200, json={"session_id": sid, "files": files}, headers=HEADERS)

    def _download(self, container_id, file_id):
        if file_id in self.extra_blobs:
            data = self.extra_blobs[file_id]
        else:
            raw = file_id[3:]
            rel = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode()
            data = (self.workspace / rel).read_bytes()
        headers = {
            **HEADERS,
            "Content-Type": "application/gzip",
            "X-Content-Type-Options": "nosniff",
        }
        return httpx.Response(200, content=data, headers=headers)


@pytest.fixture
def staging(tmp_path):
    path = tmp_path / "staging"
    path.mkdir()
    return path


def make_bridge(broker, server, staging, limits=None):
    client = UHPClient(
        "http://uhp.test/api/harness", "test-not-a-real-key", transport=httpx.MockTransport(server)
    )
    dispatcher = ExecutionDispatcher(harness_task=UHPHarnessTaskBackend(client))
    return UHPWorkspaceBridge(
        broker, client, dispatcher, limits=limits, staging_root=staging
    ), client


async def run_bridge(broker, candidate, server, staging, limits=None):
    bridge, client = make_bridge(broker, server, staging, limits)
    async with client:
        return await bridge.run(candidate, TASK)


def standard_work(ws: Path):
    (ws / "README.md").write_text("updated readme\n")
    (ws / "assets/logo.bin").write_bytes(bytes(reversed(range(256))) * 8)
    (ws / "src/pkg").mkdir()
    (ws / "src/pkg/new_module.py").write_text("VALUE = 1\n")
    (ws / "docs/old.md").unlink()
    (ws / ".github/workflows/ci.yml").write_text("on: push\n")
    os.chmod(ws / "bin/run.sh", 0o644)
    (ws / "tools.sh").write_text("#!/bin/sh\necho tools\n")
    os.chmod(ws / "tools.sh", 0o755)
    (ws / ".env").write_text("SECRET=remote\n")  # ignored locally
    (ws / "build").mkdir()
    (ws / "build/out.o").write_bytes(b"\x00\x01")  # ignored locally
    (ws / ".claude").mkdir()
    (ws / ".claude/state.json").write_text("{}")  # harness runtime state
    (ws / "src/__pycache__").mkdir()
    (ws / "src/__pycache__/app.cpython-312.pyc").write_bytes(b"pyc")


# --- The architectural acceptance test ---


async def test_bridge_round_trip_never_advances_accepted_state(
    repo, broker, candidate, staging, tmp_path
):
    a = accepted(repo)
    server = FakeHarnessRouter(tmp_path, work=standard_work)

    result = await run_bridge(broker, candidate, server, staging)

    assert result.outcome.status == "completed"
    assert result.workspace_sync_status == "synced", result.error
    assert result.session_id == SESSION
    assert result.added_paths == ("src/pkg/new_module.py", "tools.sh")
    assert result.changed_paths == (
        ".github/workflows/ci.yml",
        "README.md",
        "assets/logo.bin",
        "bin/run.sh",
    )
    assert result.deleted_paths == ("docs/old.md",)
    assert result.ignored_paths == (".env", "build/out.o")

    root = candidate.local_path
    assert (root / "README.md").read_text() == "updated readme\n"
    assert (root / "assets/logo.bin").read_bytes() == bytes(reversed(range(256))) * 8
    assert (root / "src/pkg/new_module.py").read_text() == "VALUE = 1\n"
    assert (root / ".github/workflows/ci.yml").read_text() == "on: push\n"
    assert not (root / "docs/old.md").exists()
    assert not (root / "docs").exists()
    assert not os.access(root / "bin/run.sh", os.X_OK)
    assert os.access(root / "tools.sh", os.X_OK)
    assert (root / ".env").read_text() == "SECRET=local-only\n"  # local secret untouched
    assert not (root / "build").exists()
    assert not (root / ".claude").exists()
    assert not (root / "src/__pycache__").exists()

    # Synced means dirty and uncheckpointed; nothing else moved.
    assert broker.inspect_candidate(candidate).dirty is True
    assert git(root, "rev-parse", "HEAD") == a
    assert accepted(repo) == a
    assert "checkpoints" not in git(repo, "for-each-ref", "refs/cloudeo")

    # Only the broker can checkpoint, and checkpointing still does not promote.
    checkpoint = broker.checkpoint_candidate(candidate, "bridge result")
    assert accepted(repo) == a
    assert git(repo, "show", f"{checkpoint.commit}:src/pkg/new_module.py") == "VALUE = 1"

    # Only an explicit promote advances accepted state.
    broker.promote(checkpoint)
    assert accepted(repo) == checkpoint.commit


async def test_bridge_uses_only_read_only_broker_calls(broker, candidate, staging, tmp_path):
    calls = []

    class SpyBroker:
        def __getattr__(self, name):
            calls.append(name)
            return getattr(broker, name)

    server = FakeHarnessRouter(tmp_path, work=standard_work)
    result = await run_bridge(SpyBroker(), candidate, server, staging)
    assert result.workspace_sync_status == "synced"
    assert calls == ["inspect_candidate"]


# --- What crosses the bridge ---


async def test_upload_excludes_git_and_ignored_files(repo, broker, candidate, staging, tmp_path):
    server = FakeHarnessRouter(tmp_path)
    await run_bridge(broker, candidate, server, staging)
    helper_upload, input_upload = server.uploads["file_0"], server.uploads["file_1"]
    assert helper_upload["filename"] == helper.HELPER_NAME
    assert helper_upload["content"] == HELPER_SOURCE
    with tarfile.open(fileobj=io.BytesIO(input_upload["content"]), mode="r:gz") as tar:
        names = tar.getnames()
        manifest = json.loads(tar.extractfile(helper.MANIFEST_MEMBER).read())
    sent = sorted(n.removeprefix(helper.FILES_PREFIX) for n in names if n != "manifest.json")
    assert sent == [
        ".github/workflows/ci.yml",
        ".gitignore",
        "README.md",
        "assets/logo.bin",
        "bin/run.sh",
        "docs/old.md",
        "notes/new.txt",
        "src/app.py",
    ]
    assert not any(".git" in n.split("/") for n in names)
    assert all(b"SECRET=local-only" not in u["content"] for u in server.uploads.values())
    assert manifest["workspace_id"] == "demo"
    assert manifest["max_output_bundle_bytes"] == BridgeLimits().max_output_bundle_bytes
    assert manifest["candidate_id"] == candidate.candidate_id
    assert manifest["base_commit"] == candidate.base_commit
    assert {e["path"]: e["executable"] for e in manifest["files"]}["bin/run.sh"] is True


async def test_task_request_is_one_fresh_session_with_explicit_profile(
    broker, candidate, staging, tmp_path
):
    server = FakeHarnessRouter(tmp_path)
    await run_bridge(broker, candidate, server, staging)
    assert len(server.task_payloads) == 1
    payload = server.task_payloads[0]
    assert "previous_response_id" not in payload
    assert payload["metadata"] == {"harness_id": "chrn_claude"}
    assert (payload["model"], payload["max_step"], payload["timeout_seconds"]) == (
        "claude-opus-5",
        20,
        600,
    )
    content = payload["input"][0]["content"]
    assert [part["type"] for part in content] == ["input_text", "input_file", "input_file"]
    assert {part["file_id"] for part in content[1:]} == {"file_0", "file_1"}
    text = content[0]["text"]
    protocol, task = text.split("=== TASK ===")
    assert "unpack --run-id" in protocol and "pack-delta --run-id" in protocol
    assert task.strip() == TASK.task


def test_input_bundle_is_deterministic(candidate, broker):
    head = broker.inspect_candidate(candidate).head_commit
    run_id = "bridge_" + "a" * 32
    first = build_input_bundle(candidate, head, run_id, BridgeLimits())
    # Change only things that must not matter: mtimes and permission bits beyond
    # the executable flag.
    root = candidate.local_path
    for path in root.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            os.utime(path, (1_000_000_000, 1_000_000_000))
    os.chmod(root / "README.md", 0o600)
    os.chmod(root / "bin/run.sh", 0o700)
    second = build_input_bundle(candidate, head, run_id, BridgeLimits())

    assert first.archive == second.archive
    assert first.manifest_sha256 == second.manifest_sha256

    # gzip header: no embedded filename or comment, zero mtime.
    header = first.archive[:10]
    assert header[:3] == b"\x1f\x8b\x08"
    assert header[3] & 0x18 == 0  # FNAME and FCOMMENT unset
    assert header[4:8] == b"\0\0\0\0"
    with tarfile.open(fileobj=io.BytesIO(first.archive), mode="r:gz") as tar:
        members = tar.getmembers()
        manifest_bytes = tar.extractfile(helper.MANIFEST_MEMBER).read()
    names = [m.name for m in members]
    assert names[0] == helper.MANIFEST_MEMBER
    assert names[1:] == sorted(names[1:])
    for member in members:
        assert member.isreg()
        assert (member.uid, member.gid, member.uname, member.gname, member.mtime) == (
            0,
            0,
            "",
            "",
            0,
        )
        assert member.mode in (0o644, 0o755)
    modes = {m.name: m.mode for m in members}
    assert modes["files/README.md"] == 0o644
    assert modes["files/bin/run.sh"] == 0o755
    assert hashlib.sha256(manifest_bytes).hexdigest() == first.manifest_sha256


def test_executable_bit_change_is_part_of_the_snapshot(candidate, broker):
    """Unlike irrelevant mode bits, the executable flag must change the bundle."""
    head = broker.inspect_candidate(candidate).head_commit
    run_id = "bridge_" + "a" * 32
    readme = candidate.local_path / "README.md"
    os.chmod(readme, 0o600)
    before = build_input_bundle(candidate, head, run_id, BridgeLimits())
    os.chmod(readme, 0o700)
    after = build_input_bundle(candidate, head, run_id, BridgeLimits())
    assert before.archive != after.archive
    assert before.manifest_sha256 != after.manifest_sha256
    flags = [{e.path: e.executable for e in b.manifest.files}["README.md"] for b in (before, after)]
    assert flags == [False, True]


# --- Remote helper: unpack safety ---


def _input_archive(ws, run_id, files, executable=()):
    manifest = {
        "format": helper.FORMAT,
        "kind": "input",
        "bridge_run_id": run_id,
        "workspace_id": "demo",
        "candidate_id": "c" * 32,
        "base_commit": "1" * 40,
        "head_commit": "1" * 40,
        "files": [helper.file_entry(p, d, p in executable) for p, d in sorted(files.items())],
    }
    data = helper.build_archive(manifest, {p: (d, p in executable) for p, d in files.items()})
    (ws / helper.input_archive_name(run_id)).write_bytes(data)


@pytest.mark.parametrize(
    "setup,path",
    [
        ("symlink_parent", "link/file.txt"),
        ("nested_symlink_parent", "dir/link/file.txt"),
        ("file_parent", "afile/file.txt"),
    ],
)
def test_remote_unpack_never_writes_through_a_parent(tmp_path, setup, path):
    ws, outside = tmp_path / "ws", tmp_path / "outside"
    ws.mkdir()
    outside.mkdir()
    if setup == "symlink_parent":
        (ws / "link").symlink_to(outside, target_is_directory=True)
    elif setup == "nested_symlink_parent":
        (ws / "dir").mkdir()
        (ws / "dir/link").symlink_to(outside, target_is_directory=True)
    else:
        (ws / "afile").write_text("a file, not a directory\n")
    run_id = "bridge_" + "d" * 32
    _input_archive(ws, run_id, {path: b"payload"})
    assert helper.main(["unpack", "--run-id", run_id, "--root", str(ws)]) == 2
    assert list(outside.iterdir()) == []
    assert not (tmp_path / "file.txt").exists()


def test_remote_unpack_creates_nested_directories(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    run_id = "bridge_" + "e" * 32
    _input_archive(ws, run_id, {"a/b/c.txt": b"deep", "top.txt": b"top"})
    assert helper.main(["unpack", "--run-id", run_id, "--root", str(ws)]) == 0
    assert (ws / "a/b/c.txt").read_bytes() == b"deep"


async def test_symlink_in_candidate_fails_before_upload(broker, candidate, staging, tmp_path):
    (candidate.local_path / "link").symlink_to("README.md")
    server = FakeHarnessRouter(tmp_path)
    with pytest.raises(BridgeInputError, match="symbolic links"):
        await run_bridge(broker, candidate, server, staging)
    assert server.requests == []


# --- HarnessRouter bootstrap instruction docs ---

PROJECT_DOC = b"# Project rules\nRun the tests before finishing.\n"


def unpack_report(server):
    return json.loads(server.helper_outputs[0])


def synced_paths(result):
    return set(result.added_paths + result.changed_paths + result.deleted_paths)


async def test_a_bootstrap_claude_doc_is_removed_and_never_imported(
    broker, candidate, staging, tmp_path
):
    seen = {}

    def work(ws):
        seen["exists_after_unpack"] = (ws / "CLAUDE.md").exists()
        standard_work(ws)

    server = FakeHarnessRouter(tmp_path, work=work)  # Claude-style bootstrap by default
    result = await run_bridge(broker, candidate, server, staging)
    assert unpack_report(server)["bootstrap_docs"] == {"CLAUDE.md": "removed"}
    assert seen["exists_after_unpack"] is False
    assert result.workspace_sync_status == "synced"
    assert "CLAUDE.md" not in synced_paths(result) | set(result.ignored_paths)
    assert not (candidate.local_path / "CLAUDE.md").exists()


@pytest.mark.parametrize(
    "doc,executable",
    [("CLAUDE.md", False), ("AGENTS.md", False), ("AGENTS.md", True)],
)
async def test_b_c_tracked_project_doc_replaces_bootstrap_copy(tmp_path, staging, doc, executable):
    _, broker, candidate = project_with(tmp_path, {doc: PROJECT_DOC})
    if executable:
        os.chmod(candidate.local_path / doc, 0o755)
    seen = {}

    def work(ws):
        seen["bytes"] = (ws / doc).read_bytes()
        seen["executable"] = os.access(ws / doc, os.X_OK)

    server = FakeHarnessRouter(tmp_path, bootstrap_doc=doc, work=work)
    result = await run_bridge(broker, candidate, server, staging)
    assert unpack_report(server)["bootstrap_docs"] == {doc: "replaced"}
    assert seen == {"bytes": PROJECT_DOC, "executable": executable}
    assert result.workspace_sync_status == "synced"
    assert doc not in synced_paths(result)  # unchanged project doc: no delta
    assert (candidate.local_path / doc).read_bytes() == PROJECT_DOC


async def test_d_agent_edit_of_project_agents_doc_syncs_as_changed(tmp_path, staging):
    _, broker, candidate = project_with(tmp_path, {"AGENTS.md": PROJECT_DOC})
    edited = PROJECT_DOC + b"Also update the changelog.\n"
    server = FakeHarnessRouter(
        tmp_path, bootstrap_doc="AGENTS.md", work=lambda ws: (ws / "AGENTS.md").write_bytes(edited)
    )
    result = await run_bridge(broker, candidate, server, staging)
    assert result.workspace_sync_status == "synced"
    assert result.changed_paths == ("AGENTS.md",)
    assert (candidate.local_path / "AGENTS.md").read_bytes() == edited


async def test_e_agent_created_agents_doc_syncs_as_added(broker, candidate, staging, tmp_path):
    created = b"# Agent guide written during the task\n"
    server = FakeHarnessRouter(
        tmp_path, bootstrap_doc="AGENTS.md", work=lambda ws: (ws / "AGENTS.md").write_bytes(created)
    )
    result = await run_bridge(broker, candidate, server, staging)
    assert unpack_report(server)["bootstrap_docs"] == {"AGENTS.md": "removed"}
    assert result.workspace_sync_status == "synced"
    assert result.added_paths == ("AGENTS.md",)
    content = (candidate.local_path / "AGENTS.md").read_bytes()
    assert content == created
    assert helper.HARNESSROUTER_MANAGED_MARKER not in content


@pytest.mark.parametrize("candidate_tracks_it", [False, True])
async def test_f_unknown_unmarked_root_doc_fails_closed(tmp_path, staging, candidate_tracks_it):
    extra = {"AGENTS.md": PROJECT_DOC} if candidate_tracks_it else {}
    repo, broker, candidate = project_with(tmp_path, extra)
    before = snapshot(repo, candidate)
    unknown = b"# Something else put this here\n"
    server = FakeHarnessRouter(
        tmp_path, bootstrap_doc="AGENTS.md", bootstrap_content=unknown, work=standard_work
    )
    result = await run_bridge(broker, candidate, server, staging)
    operation, returncode, stderr = server.helper_runs[0]
    assert (operation, returncode) == ("unpack", 2)
    assert "without the HarnessRouter marker" in stderr
    assert (server.workspace / "AGENTS.md").read_bytes() == unknown  # not deleted
    assert (result.workspace_sync_status, result.error.code) == (
        "failed",
        "output_artifact_missing",
    )
    assert snapshot(repo, candidate) == before


@pytest.mark.parametrize("candidate_tracks_it", [False, True])
async def test_g_symlinked_root_doc_is_never_followed(tmp_path, staging, candidate_tracks_it):
    extra = {"CLAUDE.md": PROJECT_DOC} if candidate_tracks_it else {}
    repo, broker, candidate = project_with(tmp_path, extra)
    before = snapshot(repo, candidate)
    outside = tmp_path / "outside-CLAUDE.md"
    outside.write_bytes(hr_agent_doc())  # even a marked target must not be touched

    server = FakeHarnessRouter(
        tmp_path,
        bootstrap_doc=None,
        before_unpack=lambda ws: (ws / "CLAUDE.md").symlink_to(outside),
        work=standard_work,
    )
    result = await run_bridge(broker, candidate, server, staging)
    operation, returncode, stderr = server.helper_runs[0]
    assert (operation, returncode) == ("unpack", 2)
    assert "symlink" in stderr
    assert outside.read_bytes() == hr_agent_doc()
    assert (server.workspace / "CLAUDE.md").is_symlink()
    assert result.workspace_sync_status == "failed"
    assert snapshot(repo, candidate) == before


@pytest.mark.parametrize("name", helper.MANAGED_ROOT_DOCS)
def test_helper_reconciles_every_managed_root_doc(tmp_path, name):
    run_id = "bridge_" + "f" * 32

    def workspace(label, existing=None):
        ws = tmp_path / label
        ws.mkdir()
        if existing is not None:
            (ws / name).write_bytes(existing)
        return ws

    # Marked bootstrap, absent from the snapshot: removed before the baseline.
    ws = workspace("removed", hr_agent_doc())
    _input_archive(ws, run_id, {"a.txt": b"a"})
    assert helper.main(["unpack", "--run-id", run_id, "--root", str(ws)]) == 0
    assert not (ws / name).exists()

    # Marked bootstrap, in the snapshot: replaced with exact bytes and exec state.
    ws = workspace("replaced", hr_agent_doc())
    _input_archive(ws, run_id, {name: PROJECT_DOC}, executable={name})
    assert helper.main(["unpack", "--run-id", run_id, "--root", str(ws)]) == 0
    assert (ws / name).read_bytes() == PROJECT_DOC
    assert os.access(ws / name, os.X_OK)

    # Unmarked but identical to the snapshot: accepted as-is.
    ws = workspace("identical", PROJECT_DOC)
    _input_archive(ws, run_id, {name: PROJECT_DOC})
    assert helper.main(["unpack", "--run-id", run_id, "--root", str(ws)]) == 0

    # Unmarked and not in the snapshot, or different from it: fail closed, keep it.
    for label, files in (("unknown", {"a.txt": b"a"}), ("different", {name: b"other\n"})):
        ws = workspace(label, PROJECT_DOC)
        _input_archive(ws, run_id, files)
        assert helper.main(["unpack", "--run-id", run_id, "--root", str(ws)]) == 2
        assert (ws / name).read_bytes() == PROJECT_DOC

    # A directory at the doc path is refused.
    ws = workspace("directory")
    (ws / name).mkdir()
    _input_archive(ws, run_id, {"a.txt": b"a"})
    assert helper.main(["unpack", "--run-id", run_id, "--root", str(ws)]) == 2
    assert (ws / name).is_dir()


@pytest.mark.parametrize("name", helper.MANAGED_ROOT_DOCS)
def test_managed_root_docs_are_not_excluded_project_paths(tmp_path, name):
    assert not helper.is_excluded(name)
    assert bundle_module._safe(name) == name
    (tmp_path / name).write_text("project doc\n")
    assert name in helper.scan(str(tmp_path))


# --- Selecting this run's artifact ---


async def test_other_runs_artifacts_are_never_used(repo, broker, candidate, staging, tmp_path):
    before = snapshot(repo, candidate)
    stale = "cloudeo-bridge-output-bridge_" + "0" * 32 + ".tar.gz"
    server = FakeHarnessRouter(
        tmp_path,
        pack=False,
        extra_files=[{"id": "file_stale", "container_id": SESSION, "filename": stale}],
    )
    result = await run_bridge(broker, candidate, server, staging)
    assert (result.workspace_sync_status, result.error.code) == (
        "failed",
        "output_artifact_missing",
    )
    assert snapshot(repo, candidate) == before


async def test_duplicate_output_artifact_fails_closed(repo, broker, candidate, staging, tmp_path):
    before = snapshot(repo, candidate)

    def output(run_id, manifest):
        server.extra_files.append(
            {
                "id": "file_dup",
                "container_id": SESSION,
                "filename": helper.output_archive_name(run_id),
            }
        )
        return build_delta(manifest, added={"x.txt": b"x"})

    server = FakeHarnessRouter(tmp_path, pack=False, output=output)
    result = await run_bridge(broker, candidate, server, staging)
    assert (result.workspace_sync_status, result.error.code) == (
        "failed",
        "output_artifact_ambiguous",
    )
    assert snapshot(repo, candidate) == before


async def test_nested_file_with_output_name_is_not_selected(
    repo, broker, candidate, staging, tmp_path
):
    def work(ws):
        run_id = next(ws.glob(".cloudeo-bridge-input-*")).name[len(".cloudeo-bridge-input-") : -7]
        (ws / "sub").mkdir()
        (ws / "sub" / helper.output_archive_name(run_id)).write_bytes(b"not it")

    server = FakeHarnessRouter(tmp_path, work=work)
    result = await run_bridge(broker, candidate, server, staging)
    assert result.workspace_sync_status == "synced"
    assert "sub/" + helper.output_archive_name(result.bridge_run_id) in result.added_paths


# --- Runtime state gates synchronization ---


@pytest.mark.parametrize(
    "status,sync,code",
    [
        ("in_progress", "skipped", "runtime_state_unobserved"),
        ("failed", "skipped", "runtime_not_completed"),
        ("cancelled", "skipped", "runtime_not_completed"),
    ],
)
async def test_non_completed_runtime_leaves_candidate_untouched(
    repo, broker, candidate, staging, tmp_path, status, sync, code
):
    before = snapshot(repo, candidate)
    server = FakeHarnessRouter(tmp_path, work=standard_work, status=status)
    result = await run_bridge(broker, candidate, server, staging)
    assert result.outcome.status == status
    assert (result.workspace_sync_status, result.error.code) == (sync, code)
    assert not any("/files" in path for _, path in server.requests if "sessions" in path)
    assert snapshot(repo, candidate) == before


async def test_unknown_runtime_leaves_candidate_untouched(
    repo, broker, candidate, staging, tmp_path
):
    before = snapshot(repo, candidate)

    def timeout(request):
        raise httpx.ReadTimeout("timed out", request=request)

    server = FakeHarnessRouter(tmp_path, task_reply=timeout)
    result = await run_bridge(broker, candidate, server, staging)
    assert result.outcome.status == "unknown"
    assert (result.workspace_sync_status, result.error.code) == (
        "skipped",
        "runtime_state_unobserved",
    )
    assert [p for _, p in server.requests if "sessions" in p or "containers" in p] == []
    assert snapshot(repo, candidate) == before


async def test_incomplete_without_artifact_fails(repo, broker, candidate, staging, tmp_path):
    before = snapshot(repo, candidate)
    server = FakeHarnessRouter(tmp_path, status="incomplete", pack=False)
    result = await run_bridge(broker, candidate, server, staging)
    assert (result.workspace_sync_status, result.error.code) == (
        "failed",
        "output_artifact_missing",
    )
    assert snapshot(repo, candidate) == before


async def test_missing_session_id_fails(repo, broker, candidate, staging, tmp_path):
    before = snapshot(repo, candidate)
    server = FakeHarnessRouter(tmp_path, session_id=None, work=standard_work)
    result = await run_bridge(broker, candidate, server, staging)
    assert (result.workspace_sync_status, result.error.code) == ("failed", "missing_session_id")
    assert snapshot(repo, candidate) == before


async def test_listing_failure_fails(repo, broker, candidate, staging, tmp_path):
    before = snapshot(repo, candidate)
    reply = httpx.Response(500, json={"error": {"code": "server_error"}}, headers=HEADERS)
    server = FakeHarnessRouter(tmp_path, work=standard_work, listing_reply=reply)
    result = await run_bridge(broker, candidate, server, staging)
    assert (result.workspace_sync_status, result.error.code) == (
        "failed",
        "artifact_listing_failed",
    )
    assert snapshot(repo, candidate) == before


async def test_remote_symlink_means_no_artifact(repo, broker, candidate, staging, tmp_path):
    before = snapshot(repo, candidate)
    server = FakeHarnessRouter(tmp_path, work=lambda ws: (ws / "evil").symlink_to("/etc/passwd"))
    result = await run_bridge(broker, candidate, server, staging)
    assert server.helper_runs[-1][0] == "pack-delta" and server.helper_runs[-1][1] != 0
    assert (result.workspace_sync_status, result.error.code) == (
        "failed",
        "output_artifact_missing",
    )
    assert snapshot(repo, candidate) == before


# --- Crafted (hostile) bundles ---


def input_sha(manifest):
    """SHA-256 of the canonical input manifest, as the helper computes it."""
    return hashlib.sha256(helper._json_bytes(manifest)).hexdigest()


def identity(manifest):
    keys = ("bridge_run_id", "workspace_id", "candidate_id", "base_commit")
    return {**{key: manifest[key] for key in keys}, "input_manifest_sha256": input_sha(manifest)}


def build_delta(manifest, added=None, changed=None, deleted=(), **override):
    added, changed = added or {}, changed or {}
    delta = {
        "format": helper.FORMAT,
        "kind": "delta",
        **identity(manifest),
        "added": [helper.file_entry(p, d, False) for p, d in sorted(added.items())],
        "changed": [helper.file_entry(p, d, False) for p, d in sorted(changed.items())],
        "deleted": list(deleted),
        **override,
    }
    files = {p: (d, False) for p, d in {**added, **changed}.items()}
    return helper.build_archive(delta, files)


def raw_archive(members):
    """members: (name, kind, data) with kind in file/symlink/hardlink/dir/fifo."""
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as gz:  # noqa: SIM117
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for name, kind, data in members:
                info = tarfile.TarInfo(name)
                if kind == "file":
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
                    continue
                info.type = {
                    "symlink": tarfile.SYMTYPE,
                    "hardlink": tarfile.LNKTYPE,
                    "dir": tarfile.DIRTYPE,
                    "fifo": tarfile.FIFOTYPE,
                    "char": tarfile.CHRTYPE,
                }[kind]
                info.linkname = data.decode() if data else ""
                tar.addfile(info)
    return buffer.getvalue()


def manifest_member(manifest, **delta):
    body = {
        "format": helper.FORMAT,
        "kind": "delta",
        **identity(manifest),
        "added": [],
        "changed": [],
        "deleted": [],
        **delta,
    }
    return ("manifest.json", "file", json.dumps(body).encode())


def hostile(kind):
    """Returns output(run_id, manifest) -> bytes for one attack."""

    def output(run_id, m):
        evil = helper.file_entry("placeholder", b"evil", False)
        if kind == "traversal":
            e = {**evil, "path": "../escape.txt"}
            return raw_archive(
                [manifest_member(m, added=[e]), ("files/../escape.txt", "file", b"evil")]
            )
        if kind == "absolute":
            e = {**evil, "path": "/tmp/evil"}
            return raw_archive(
                [manifest_member(m, added=[e]), ("files//tmp/evil", "file", b"evil")]
            )
        if kind == "git_dir":
            e = {**evil, "path": ".git/config"}
            return raw_archive(
                [manifest_member(m, added=[e]), ("files/.git/config", "file", b"evil")]
            )
        if kind == "git_case":
            e = {**evil, "path": "sub/.GIT/hooks/post-checkout"}
            return raw_archive(
                [
                    manifest_member(m, added=[e]),
                    ("files/sub/.GIT/hooks/post-checkout", "file", b"evil"),
                ]
            )
        if kind == "backslash":
            e = {**evil, "path": "a\\..\\..\\x"}
            return raw_archive(
                [manifest_member(m, added=[e]), ("files/a\\..\\..\\x", "file", b"evil")]
            )
        if kind in ("symlink", "hardlink", "dir", "fifo", "char"):
            return raw_archive([manifest_member(m), (f"files/{kind}", kind, b"/etc/passwd")])
        if kind == "hash_mismatch":
            e = helper.file_entry("new.txt", b"claimed", False)
            return raw_archive(
                [manifest_member(m, added=[e]), ("files/new.txt", "file", b"actual")]
            )
        if kind == "undeclared_member":
            return raw_archive([manifest_member(m), ("files/extra.txt", "file", b"x")])
        if kind == "missing_member":
            e = helper.file_entry("new.txt", b"x", False)
            return raw_archive([manifest_member(m, added=[e])])
        if kind == "outside_prefix":
            return raw_archive([manifest_member(m), ("README.md", "file", b"x")])
        if kind == "duplicate_member":
            e = helper.file_entry("new.txt", b"x", False)
            return raw_archive(
                [
                    manifest_member(m, added=[e]),
                    ("files/new.txt", "file", b"x"),
                    ("files/new.txt", "file", b"x"),
                ]
            )
        if kind == "duplicate_manifest_keys":
            raw = json.dumps(
                {
                    **identity(m),
                    "format": helper.FORMAT,
                    "kind": "delta",
                    "added": [],
                    "changed": [],
                    "deleted": [],
                }
            )
            raw = raw[:-1] + ', "kind": "delta"}'
            return raw_archive([("manifest.json", "file", raw.encode())])
        if kind == "no_manifest":
            return raw_archive([("files/new.txt", "file", b"x")])
        if kind in (
            "bridge_run_id",
            "workspace_id",
            "candidate_id",
            "base_commit",
            "input_manifest_sha256",
        ):
            wrong = {
                "bridge_run_id": "bridge_" + "f" * 32,
                "workspace_id": "other",
                "candidate_id": "f" * 32,
                "base_commit": "0" * 40,
                # Identity fields right, but made from a different snapshot.
                "input_manifest_sha256": "0" * 64,
            }[kind]
            return build_delta(m, added={"new.txt": b"x"}, **{kind: wrong})
        if kind == "git_file":
            e = {**evil, "path": ".git"}
            return raw_archive([manifest_member(m, added=[e]), ("files/.git", "file", b"evil")])
        if kind == "delete_unsent":
            return build_delta(m, deleted=[".env"])
        if kind == "change_unsent":
            return build_delta(m, changed={"debug.log": b"x"})
        if kind == "add_existing":
            return build_delta(m, added={"README.md": b"x"})
        if kind == "file_parent_conflict":
            return build_delta(m, added={"README.md/inner.txt": b"x"})
        if kind == "excluded_path":
            return build_delta(m, added={".claude/settings.json": b"{}"})
        if kind == "reserved_path":
            return build_delta(m, added={".cloudeo-bridge-helper.py": b"x"})
        if kind == "malformed":
            return b"\x1f\x8b" + os.urandom(200)
        if kind == "not_gzip":
            return b"definitely not an archive"
        if kind == "truncated":
            return build_delta(m, added={"new.txt": b"x" * 5000})[:-40]
        raise AssertionError(kind)

    return output


ATTACKS = [
    "traversal", "absolute", "git_dir", "git_case", "backslash", "symlink", "hardlink",
    "dir", "fifo", "char", "hash_mismatch", "undeclared_member", "missing_member",
    "outside_prefix", "duplicate_member", "duplicate_manifest_keys", "no_manifest",
    "bridge_run_id", "workspace_id", "candidate_id", "base_commit",
    "input_manifest_sha256", "git_file", "delete_unsent", "change_unsent",
    "add_existing", "file_parent_conflict", "excluded_path", "reserved_path",
    "malformed", "not_gzip", "truncated",
]  # fmt: skip


# Each attack must be refused for its own reason, not an incidental one.
EXPECTED_REASON = {
    "traversal": "unsafe path",
    "absolute": "unsafe path",
    "git_dir": r"\.git",
    "git_case": r"\.git",
    "backslash": "unsafe path",
    "symlink": "not a regular file",
    "hardlink": "not a regular file",
    "dir": "not a regular file",
    "fifo": "not a regular file",
    "char": "not a regular file",
    "hash_mismatch": "does not match its manifest hash",
    "undeclared_member": "archive members do not match the manifest",
    "missing_member": "archive members do not match the manifest",
    "outside_prefix": "undeclared member",
    "duplicate_member": "duplicate member",
    "duplicate_manifest_keys": "duplicate keys",
    "no_manifest": "no manifest",
    "bridge_run_id": "bridge_run_id does not match",
    "workspace_id": "workspace_id does not match",
    "candidate_id": "candidate_id does not match",
    "base_commit": "base_commit does not match",
    "input_manifest_sha256": "input_manifest_sha256 does not match the snapshot sent",
    "git_file": r"\.git",
    "delete_unsent": "was not sent",
    "change_unsent": "was not sent",
    "add_existing": "was already sent",
    "file_parent_conflict": "would be inside the file",
    "excluded_path": "excluded from bridge output",
    "reserved_path": "excluded from bridge output",
    "malformed": "malformed",
    "not_gzip": "malformed",
    "truncated": "malformed|truncated",
}
assert set(EXPECTED_REASON) == set(ATTACKS)


@pytest.mark.parametrize("kind", ATTACKS)
async def test_hostile_bundle_leaves_candidate_untouched(
    repo, broker, candidate, staging, tmp_path, kind
):
    before = snapshot(repo, candidate)
    server = FakeHarnessRouter(tmp_path, work=standard_work, output=hostile(kind))
    result = await run_bridge(broker, candidate, server, staging)
    assert result.outcome.status == "completed"
    assert result.workspace_sync_status == "failed"
    assert result.error.code == "invalid_bundle", result.error
    assert re.search(EXPECTED_REASON[kind], result.error.message), result.error.message
    assert snapshot(repo, candidate) == before
    assert list(staging.iterdir()) == []  # staging cleaned up
    assert not (tmp_path / "escape.txt").exists()


async def test_non_cooperative_oversized_artifact_is_refused(
    repo, broker, candidate, staging, tmp_path
):
    """An artifact over the output cap is refused even if the helper was bypassed."""
    before = snapshot(repo, candidate)
    big = os.urandom(300_000)
    server = FakeHarnessRouter(
        tmp_path, output=lambda run_id, m: build_delta(m, added={"big.bin": big})
    )
    limits = BridgeLimits(max_output_bundle_bytes=200_000)
    result = await run_bridge(broker, candidate, server, staging, limits)
    assert (result.workspace_sync_status, result.error.code) == ("failed", "invalid_bundle")
    assert "size limit" in result.error.message
    assert snapshot(repo, candidate) == before


def _write_many(count, size):
    def work(ws):
        for i in range(count):
            (ws / f"generated_{i}.bin").write_bytes(os.urandom(size))

    return work


OUTPUT_LIMITS = {
    # error code: (remote work, limits); every candidate input file is < 1100 bytes.
    "output_too_large": (_write_many(1, 300_000), BridgeLimits(max_output_bundle_bytes=100_000)),
    "output_file_too_large": (_write_many(1, 5_000), BridgeLimits(max_file_bytes=4_000)),
    "output_file_count_exceeded": (_write_many(5, 10), BridgeLimits(max_files=10)),
    "output_total_bytes_exceeded": (_write_many(2, 1_500), BridgeLimits(max_total_bytes=3_000)),
}


@pytest.mark.parametrize("code", list(OUTPUT_LIMITS))
async def test_remote_output_limits_fail_clearly_and_apply_nothing(
    repo, broker, candidate, staging, tmp_path, code
):
    work, limits = OUTPUT_LIMITS[code]
    before = snapshot(repo, candidate)
    server = FakeHarnessRouter(tmp_path, work=work)
    result = await run_bridge(broker, candidate, server, staging, limits)
    operation, returncode, stderr = server.helper_runs[-1]
    assert (operation, returncode) == ("pack-delta", 3)
    assert code in stderr and "error artifact was written" in stderr
    assert (result.workspace_sync_status, result.error.code) == ("failed", code)
    assert "nothing was applied" in result.error.message
    assert snapshot(repo, candidate) == before


def test_helper_rejects_oversized_file_before_reading_it(tmp_path, monkeypatch):
    (tmp_path / "small.txt").write_bytes(b"ok")
    (tmp_path / "huge.bin").write_bytes(b"\0" * 10_000)
    opened = []
    real_open = open

    def guarded_open(path, *args, **kwargs):
        opened.append(os.path.basename(path))
        assert os.path.basename(path) != "huge.bin", "an over-limit file was read"
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(helper, "open", guarded_open, raising=False)
    with pytest.raises(helper.OutputLimitExceeded) as caught:
        helper.scan(str(tmp_path), {"max_output_file_bytes": 1_000})
    assert (caught.value.error, caught.value.path) == ("output_file_too_large", "huge.bin")
    assert "huge.bin" not in opened


def test_default_limits_fit_harnessrouter_caps():
    limits = BridgeLimits()
    harnessrouter_cap = 25 * 1024 * 1024  # upload and produced-file defaults, both 25 MiB
    assert limits.max_input_bundle_bytes <= harnessrouter_cap
    assert limits.max_output_bundle_bytes <= harnessrouter_cap


# --- Validator limits (direct) ---


def sent_bundle(broker, candidate):
    head = broker.inspect_candidate(candidate).head_commit
    return build_input_bundle(candidate, head, "bridge_" + "b" * 32, BridgeLimits())


def delta_for(sent, **changes):
    return build_delta(sent.manifest.model_dump(mode="json"), **changes)


def test_too_many_files_is_refused(broker, candidate, staging):
    sent = sent_bundle(broker, candidate)
    data = delta_for(sent, added={f"n{i}.txt": b"x" for i in range(3)})
    with pytest.raises(BridgeValidationError, match="too many"):
        validate_output_bundle(data, sent, BridgeLimits(max_files=2), staging)
    assert list(staging.iterdir()) == []


def test_single_file_and_total_size_limits(broker, candidate, staging):
    sent = sent_bundle(broker, candidate)
    data = delta_for(sent, added={"a.bin": b"x" * 2000, "b.bin": b"y" * 2000})
    with pytest.raises(BridgeValidationError, match="per-file"):
        validate_output_bundle(data, sent, BridgeLimits(max_file_bytes=1000), staging)
    with pytest.raises(BridgeValidationError, match="total-size"):
        validate_output_bundle(data, sent, BridgeLimits(max_total_bytes=3000), staging)


def test_decompression_bomb_is_bounded(broker, candidate, staging):
    sent = sent_bundle(broker, candidate)
    bomb = delta_for(sent, added={"zeros.bin": b"\0" * 5_000_000})
    assert len(bomb) < 20_000
    limits = BridgeLimits(max_file_bytes=10_000_000, max_total_bytes=100_000)
    with pytest.raises(BridgeValidationError):
        validate_output_bundle(bomb, sent, limits, staging)


# --- Candidate drift (optimistic concurrency) ---


def _modify_untouched(root):
    (root / "src/app.py").write_text("print('changed locally')\n")


def _add_local(root):
    (root / "local_new.txt").write_text("created locally during the run\n")


def _delete_local(root):
    (root / "src/app.py").unlink()


def _chmod_local(root):
    os.chmod(root / "src/app.py", 0o755)


def _modify_remote_deleted(root):
    (root / "docs/old.md").write_text("locally revived while remote deleted it\n")


def _modify_remote_changed(root):
    (root / "README.md").write_text("newer local change\n")


def _create_remote_added(root):
    (root / "tools.sh").write_text("#!/bin/sh\necho created locally\n")


DRIFT = {
    "modified_existing_file": _modify_untouched,
    "added_local_file": _add_local,
    "deleted_local_file": _delete_local,
    "executable_bit_change": _chmod_local,
    "local_edit_of_remotely_deleted_file": _modify_remote_deleted,
    "local_edit_of_remotely_changed_file": _modify_remote_changed,
    "local_create_of_remotely_added_path": _create_remote_added,
}


@pytest.mark.parametrize("name", list(DRIFT))
async def test_candidate_drift_during_run_applies_nothing(
    repo, broker, candidate, staging, tmp_path, name
):
    seen = {}

    def work(ws):
        standard_work(ws)
        DRIFT[name](candidate.local_path)  # the local change races the remote episode
        seen["after_local_change"] = snapshot(repo, candidate)

    server = FakeHarnessRouter(tmp_path, work=work)
    result = await run_bridge(broker, candidate, server, staging)
    assert result.outcome.status == "completed"
    assert result.workspace_sync_status == "failed"
    assert result.error.code == "candidate_changed_during_execution", result.error
    # Zero remote changes: the candidate is exactly as the local change left it.
    assert snapshot(repo, candidate) == seen["after_local_change"]
    assert result.added_paths == result.changed_paths == result.deleted_paths == ()


async def test_ignored_local_change_is_not_drift(broker, candidate, staging, tmp_path):
    def work(ws):
        standard_work(ws)
        (candidate.local_path / ".env").write_text("SECRET=rotated-locally\n")

    server = FakeHarnessRouter(tmp_path, work=work)
    result = await run_bridge(broker, candidate, server, staging)
    assert result.workspace_sync_status == "synced"
    assert (candidate.local_path / ".env").read_text() == "SECRET=rotated-locally\n"


async def test_symlinked_parent_created_during_run_applies_nothing(
    repo, broker, candidate, staging, tmp_path
):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "app.py").write_text("print('app')\n")  # same content: reads look unchanged
    seen = {}

    def work(ws):
        (ws / "src/app.py").write_text("print('remote change')\n")
        root = candidate.local_path
        (root / "src/app.py").unlink()
        (root / "src").rmdir()
        (root / "src").symlink_to(outside, target_is_directory=True)
        seen["after"] = snapshot(repo, candidate)

    server = FakeHarnessRouter(tmp_path, work=work)
    result = await run_bridge(broker, candidate, server, staging)
    assert (result.workspace_sync_status, result.error.code) == (
        "failed",
        "candidate_changed_during_execution",
    )
    # Deterministic: Git lists the new untracked `src` link, which sorts before
    # the tracked `src/app.py`, so the symlink rule for `src` itself fires.
    assert result.error.message.endswith("symbolic links are not supported yet: 'src'")
    assert (outside / "app.py").read_text() == "print('app')\n"
    assert snapshot(repo, candidate) == seen["after"]


def test_apply_refuses_symlinked_parent_before_any_mutation(
    broker, candidate, staging, tmp_path, monkeypatch
):
    """Even with the drift check bypassed, no write passes through a local symlink."""

    def git_must_not_be_queried(*args, **kwargs):
        raise AssertionError("git check-ignore ran before path safety")

    monkeypatch.setattr(bundle_module, "_ignored", git_must_not_be_queried)
    sent = sent_bundle(broker, candidate)
    outside = tmp_path / "outside"
    outside.mkdir()
    (candidate.local_path / "lib").symlink_to(outside, target_is_directory=True)
    delta = validate_output_bundle(
        delta_for(sent, added={"lib/evil.txt": b"x", "zz_first.txt": b"y"}),
        sent,
        BridgeLimits(),
        staging,
    )
    before = tree(candidate.local_path)
    with pytest.raises(BridgeError) as caught:
        bundle_module.apply_delta(candidate.local_path, delta, sent.manifest)
    assert caught.value.code == "unsafe_local_path"
    assert list(outside.iterdir()) == []
    assert tree(candidate.local_path) == before


@pytest.mark.parametrize("path", [".git", ".git/config", ".GIT/hooks/x"])
def test_apply_never_targets_git(candidate, path):
    with pytest.raises(BridgeError) as caught:
        bundle_module._target(candidate.local_path.resolve(), path)
    assert caught.value.code == "unsafe_local_path"
    assert (candidate.local_path / ".git").is_file()  # a worktree's .git is a file


# --- Runtime gating ---


async def test_incomplete_with_valid_delta_syncs_but_stays_incomplete(
    repo, broker, candidate, staging, tmp_path
):
    a = accepted(repo)
    server = FakeHarnessRouter(tmp_path, work=standard_work, status="incomplete")
    result = await run_bridge(broker, candidate, server, staging)
    assert result.outcome.status == "incomplete"
    assert result.workspace_sync_status == "synced"
    assert not hasattr(result, "verified")
    assert accepted(repo) == a


# --- One UHP deployment ---


def test_bridge_refuses_a_dispatcher_on_another_uhp_client(broker, tmp_path):
    server = FakeHarnessRouter(tmp_path)
    files_client = UHPClient("http://uhp.test/api/harness", transport=httpx.MockTransport(server))
    task_client = UHPClient("http://uhp.test/api/harness", transport=httpx.MockTransport(server))
    dispatcher = ExecutionDispatcher(harness_task=UHPHarnessTaskBackend(task_client))
    with pytest.raises(ValueError, match="different UHPClient"):
        UHPWorkspaceBridge(broker, files_client, dispatcher)
    assert server.requests == []


def test_bridge_refuses_a_non_uhp_harness_backend(broker, tmp_path):
    class OtherBackend:
        async def execute(self, request):
            raise AssertionError("never called")

    client = UHPClient("http://uhp.test/api/harness", transport=httpx.MockTransport(lambda r: None))
    with pytest.raises(TypeError, match="not a UHP backend"):
        UHPWorkspaceBridge(broker, client, ExecutionDispatcher(harness_task=OtherBackend()))
    with pytest.raises(ValueError, match="no harness-task backend"):
        UHPWorkspaceBridge(broker, client, ExecutionDispatcher())


async def test_filesystem_failure_mid_apply_rolls_back(
    repo, broker, candidate, staging, tmp_path, monkeypatch
):
    before = snapshot(repo, candidate)
    real_replace = os.replace
    calls = []

    def flaky_replace(src, dst):
        calls.append(dst)
        if len(calls) == 4:
            raise OSError("disk full")
        return real_replace(src, dst)

    monkeypatch.setattr(bundle_module.os, "replace", flaky_replace)
    server = FakeHarnessRouter(tmp_path, work=standard_work)
    result = await run_bridge(broker, candidate, server, staging)
    monkeypatch.setattr(bundle_module.os, "replace", real_replace)
    assert (result.workspace_sync_status, result.error.code) == ("failed", "apply_failed")
    assert "disk full" in result.error.message
    assert snapshot(repo, candidate) == before


async def test_failed_rollback_raises_original_error_with_evidence(
    repo, broker, candidate, staging, tmp_path, monkeypatch
):
    real_replace = os.replace
    calls = []

    def replace_then_fail(src, dst):
        calls.append(dst)
        if len(calls) >= 2:
            raise OSError(f"write failed #{len(calls)}")
        return real_replace(src, dst)

    monkeypatch.setattr(bundle_module.os, "replace", replace_then_fail)
    server = FakeHarnessRouter(tmp_path, work=standard_work)
    with pytest.raises(OSError, match="write failed #2") as caught:
        await run_bridge(broker, candidate, server, staging)
    assert any("Rollback also failed" in note for note in caught.value.__notes__)


# --- Guard rails ---


def test_capabilities():
    assert UHPWorkspaceBridge.supports_workspace_sync is True


def test_base_longhorizon_adapter_still_has_no_workspace_sync():
    adapter_module = pytest.importorskip("cloudeo.longhorizon.adapter", exc_type=ImportError)
    assert adapter_module.UHPHarnessAgentAdapter.supports_workspace_sync is False


def test_bridge_git_runner_allows_only_read_only_queries(tmp_path):
    with pytest.raises(BridgeError, match="not permitted"):
        bundle_module.git(tmp_path, "status")
    assert bundle_module.ALLOWED_GIT_SUBCOMMANDS == {"ls-files", "check-ignore"}


def test_helper_is_python38_compatible_and_stdlib_only():
    module = ast.parse(HELPER_SOURCE.decode(), feature_version=(3, 8))
    imported = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}


async def test_bridge_makes_no_real_network_calls(
    broker, candidate, staging, tmp_path, monkeypatch
):
    async def no_network(self, request):
        raise AssertionError("real network transport used")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", no_network)
    server = FakeHarnessRouter(tmp_path, work=standard_work)
    result = await run_bridge(broker, candidate, server, staging)
    assert result.workspace_sync_status == "synced"
