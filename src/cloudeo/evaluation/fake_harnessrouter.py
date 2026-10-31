"""Offline fake of the pinned HarnessRouter CE 0.23.7 UHP server.

Shared by the test suite and the EVAL-01 deterministic scenarios: Cloudeo's
real UHP client, bridge and bridge helper run against it, while the agent
work is a supplied function instead of a model. It is not a HarnessRouter
implementation and is never used to run real tasks.
"""

from __future__ import annotations

import base64
import io
import json
import re
import subprocess
import sys
import tarfile
from email.parser import BytesParser
from email.policy import HTTP

import httpx

from cloudeo.bridge import remote_helper as helper
from cloudeo.uhp.models import UHP_VERSION

HEADERS = {"UHP-Version": UHP_VERSION}
SESSION = "hsess_bridge"


def parse_multipart(request: httpx.Request) -> dict:
    raw = f"Content-Type: {request.headers['Content-Type']}\r\n\r\n".encode() + request.read()
    message = BytesParser(policy=HTTP).parsebytes(raw)
    parts = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        parts[name] = {
            "filename": part.get_filename(),
            "content_type": part.get_content_type(),
            "payload": part.get_payload(decode=True),
        }
    return parts


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
