"""Independent LongHorizon CLI auditor over a frozen CandidateWorkspace snapshot.

Real GitWorkspaceBroker, CandidateWorkspace, UHPWorkspaceBridge,
UHPWorkspaceAuditTransport, UHPClient, ExecutionDispatcher,
UHPHarnessTaskBackend, bridge helper, and the pinned LongHorizon types, prompt
builder, and audit parser; the HarnessRouter side is the offline fake from
test_uhp_workspace_bridge.
"""

# Pytest fixtures imported from test_uhp_workspace_bridge are requested by
# parameter name, which ruff reports as redefinitions.
# ruff: noqa: F811

import hashlib
import inspect
import io
import json
import os
import tarfile

import httpx
import pytest

pytest.importorskip("lh_harness", reason="requires the optional 'longhorizon' extra")

from lh_harness import manager as lh_manager
from lh_harness.adapters.base import AgentAdapter
from lh_harness.auditor_agent import (
    audit_report_from_episode_result,
    auditor_report_text_from_episode_result,
    parse_audit_report,
)
from lh_harness.environment.base import Environment
from lh_harness.role_prompts import MANAGER_NEXT_CLI, build_role_auditor_prompt
from lh_harness.types import EpisodeBudget, EpisodeResult
from test_uhp_workspace_bridge import (  # noqa: F401 - fixtures are used by name
    FakeHarnessRouter,
    accepted,
    broker,
    candidate,
    git,
    isolated_git,
    make_bridge,
    project_with,
    repo,
    snapshot,
    staging,
    standard_work,
    tree,
)

from cloudeo.bridge import remote_helper as helper
from cloudeo.bridge.audit import UHPWorkspaceAuditTransport, snapshot_content_sha256
from cloudeo.bridge.bundle import build_input_bundle
from cloudeo.bridge.models import BridgeLimits
from cloudeo.execution.dispatch import ExecutionDispatcher
from cloudeo.execution.uhp_backend import UHPHarnessTaskBackend
from cloudeo.longhorizon.adapter import HarnessExecutionProfile, UHPHarnessAgentAdapter
from cloudeo.longhorizon.roles import (
    LONGHORIZON_ROLES,
    RoleEligibilityError,
    bind_longhorizon_roles,
    eligible_roles,
    require_role_eligible,
)
from cloudeo.longhorizon.workspace_auditor import UHPWorkspaceAuditorAdapter
from cloudeo.longhorizon.workspace_executor import UHPWorkspaceExecutorAdapter
from cloudeo.uhp.client import UHPClient

EXECUTOR_PROFILE = HarnessExecutionProfile(
    harness_id="chrn_claude", model="claude-opus-5", max_step=12
)
AUDITOR_PROFILE = HarnessExecutionProfile(harness_id="chrn_codex", model="audit-model", max_step=7)
EXECUTOR_BUDGET = EpisodeBudget(max_duration_seconds=900)
AUDIT_BUDGET = EpisodeBudget(max_duration_seconds=300)
# The real pinned LongHorizon auditor prompt, naming a local workspace path.
AUDIT_PROMPT = build_role_auditor_prompt(
    task="Refactor the app and update the docs.",
    plan_text="CLI subtask: update README.md and add src/pkg/new_module.py.",
    executor_output="Updated README.md and added src/pkg/new_module.py.",
    next_step=MANAGER_NEXT_CLI,
    workspace_path="/workspace",
)
VALID_REPORT = """\
Status: complete
Integrity: clean
Contract audit: aligned

Audit facts: README.md reads "updated readme" and src/pkg/new_module.py defines VALUE = 1.
Evidence: inspected both files directly in the extracted snapshot.
Acceptance-constraint backcheck: every constraint of the subtask is satisfied.
Blocking constraints: none
State update for manager: the CLI subtask is complete and trustworthy."""


def reply(text, response_id="resp_audit"):
    return {
        "id": response_id,
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
    }


class UntouchableEnvironment:
    """Satisfies LongHorizon's Environment protocol; fails if the adapter uses it."""

    async def exec(self, command, timeout=30, tee_path=None):
        raise AssertionError("the auditor must not execute in the Environment")

    async def screenshot(self):
        raise AssertionError("screenshot must not be called")

    async def upload(self, local_path, remote_path):
        raise AssertionError("upload must not be called")

    async def download(self, remote_path, local_path):
        raise AssertionError("download must not be called")


def env():
    environment = UntouchableEnvironment()
    assert isinstance(environment, Environment)
    return environment


def make_transport(broker, server, staging, limits=None):
    client = UHPClient(
        "http://uhp.test/api/harness", "test-not-a-real-key", transport=httpx.MockTransport(server)
    )
    dispatcher = ExecutionDispatcher(harness_task=UHPHarnessTaskBackend(client))
    transport = UHPWorkspaceAuditTransport(
        broker, client, dispatcher, limits=limits, staging_root=staging
    )
    return transport, client


async def run_auditor(broker, candidate, server, staging, **episode):
    transport, client = make_transport(broker, server, staging)
    auditor = UHPWorkspaceAuditorAdapter(AUDITOR_PROFILE, transport, candidate)
    async with client:
        return await auditor.run_episode(
            AUDIT_PROMPT, env(), episode.pop("budget", AUDIT_BUDGET), **episode
        )


def audit_server(tmp_path, work=None, text=VALID_REPORT, **kwargs):
    """A fake HarnessRouter whose single task is the audit."""
    return FakeHarnessRouter(
        tmp_path, work=work, response_overrides=kwargs.pop("overrides", reply(text)), **kwargs
    )


def cloudeo_refs(repo):
    return git(repo, "for-each-ref", "--format=%(refname)", "refs/cloudeo").splitlines()


def no_checkpoint_or_decision(repo):
    return not any(r.split("/")[-1] in ("promoted", "rejected") for r in cloudeo_refs(repo)) and (
        not any("/checkpoints/" in r for r in cloudeo_refs(repo))
    )


def uploaded_snapshot(server):
    """(manifest, member names) of the latest uploaded input archive."""
    upload = [u for u in server.uploads.values() if u["filename"].endswith(".tar.gz")][-1]
    with tarfile.open(fileobj=io.BytesIO(upload["content"]), mode="r:gz") as tar:
        names = tar.getnames()
        manifest_bytes = tar.extractfile(helper.MANIFEST_MEMBER).read()
    return json.loads(manifest_bytes), manifest_bytes, names


# --- A-I. Executor then independent auditor, end to end ---


async def test_a_to_i_executor_then_independent_read_only_audit(
    repo, broker, candidate, staging, tmp_path
):
    a = accepted(repo)
    seen = {}

    def work(ws):
        if not seen:
            seen["executor"] = ws
            standard_work(ws)
        else:
            # The auditor sees exactly candidate A': the executor's changes.
            seen["auditor"] = ws
            seen["readme"] = (ws / "README.md").read_text()
            seen["new_module"] = (ws / "src/pkg/new_module.py").exists()
            seen["old_doc"] = (ws / "docs/old.md").exists()
            seen["claude_doc"] = (ws / "CLAUDE.md").exists()

    server = FakeHarnessRouter(
        tmp_path,
        work=work,
        response_overrides=lambda n: {} if n == 0 else reply(VALID_REPORT),
    )
    bridge, bridge_client = make_bridge(broker, server, staging)
    executor = UHPWorkspaceExecutorAdapter(EXECUTOR_PROFILE, bridge, candidate)
    async with bridge_client:
        executed = await executor.run_episode("Do the CLI subtask.", env(), EXECUTOR_BUDGET)
    assert executed.status == "done", executed.error
    # Candidate A': dirty and unverified.
    assert broker.inspect_candidate(candidate).dirty is True
    after_executor = snapshot(repo, candidate)

    audited = await run_auditor(broker, candidate, server, staging)

    # A. A successful read-only audit.
    assert isinstance(audited, EpisodeResult)
    assert audited.status == "done", audited.error
    m = audited.metadata
    assert m["cloudeo_runtime_status"] == "completed"
    assert m["workspace_access"] == "read_only_snapshot"
    assert m["auditor_remote_evidence"] == "unchanged"
    assert m["auditor_remote_workspace_unchanged"] is True
    assert m["auditor_workspace_mutations"] == {
        "added": [],
        "changed": [],
        "deleted": [],
        "mode_changed": [],
    }
    assert m["audit_snapshot_unchanged"] is True
    assert m["accepted_state_unchanged"] is True
    assert m["audit_invalid_reasons"] == []
    assert m["independently_verified"] is False
    assert m["verifier_workspace_mutation_detected"] is False
    # The auditor inspected exactly A', with HarnessRouter's bootstrap doc removed.
    assert seen["readme"] == "updated readme\n"
    assert seen["new_module"] is True and seen["old_doc"] is False
    assert seen["claude_doc"] is False
    # B. Candidate byte-for-byte A'; C. accepted still A; D. no checkpoint or decision.
    assert snapshot(repo, candidate) == after_executor
    assert accepted(repo) == a
    assert no_checkpoint_or_decision(repo)
    # E. A fresh session and remote workspace, not the executor's.
    assert executed.metadata["session_id"] != m["session_id"]
    assert executed.metadata["response_id"] != m["response_id"]
    assert seen["executor"] != seen["auditor"]
    # F. No previous_response_id; G. the auditor's own profile and budget.
    assert len(server.task_payloads) == 2
    audit_payload = server.task_payloads[1]
    assert "previous_response_id" not in audit_payload
    assert audit_payload["metadata"] == {"harness_id": "chrn_codex"}
    assert (
        audit_payload["model"],
        audit_payload["max_step"],
        audit_payload["timeout_seconds"],
    ) == ("audit-model", 7, 300)
    text = audit_payload["input"][0]["content"][0]["text"]
    assert text.split("=== AUDIT PROMPT ===\n")[1].strip() == AUDIT_PROMPT.strip()
    assert "Inspect only" in text and "pack-delta" in text
    # The snapshot sent is identified by exactly the recorded hashes.
    manifest, manifest_bytes, _ = uploaded_snapshot(server)
    assert m["audit_snapshot_manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    assert m["audit_snapshot_file_count"] == len(manifest["files"])
    assert m["audit_snapshot_head"] == a  # uncheckpointed: HEAD is still A
    assert m["audit_transport_run_id"] == manifest["bridge_run_id"]
    # H. The three-line report is preserved verbatim.
    assert m["assistant_visible_output"] == VALID_REPORT
    assert auditor_report_text_from_episode_result(audited) == VALID_REPORT
    # I. LongHorizon's own parser reads it as complete / clean / aligned.
    report = audit_report_from_episode_result(audited, 1)
    assert (report.status, report.integrity_status, report.contract_audit_status) == (
        "complete",
        "clean",
        "aligned",
    )
    parsed = parse_audit_report(auditor_report_text_from_episode_result(audited), 1)
    assert (parsed.status, parsed.integrity_status, parsed.contract_audit_status) == (
        "complete",
        "clean",
        "aligned",
    )
    # A complete audit still promotes nothing.
    assert accepted(repo) == a
    assert no_checkpoint_or_decision(repo)


async def test_auditor_uses_only_read_only_broker_calls(broker, candidate, staging, tmp_path):
    calls = []

    class SpyBroker:
        def __getattr__(self, name):
            calls.append(name)
            return getattr(broker, name)

    server = audit_server(tmp_path)
    transport, client = make_transport(SpyBroker(), server, staging)
    auditor = UHPWorkspaceAuditorAdapter(AUDITOR_PROFILE, transport, candidate)
    async with client:
        result = await auditor.run_episode(AUDIT_PROMPT, env(), AUDIT_BUDGET)
    assert result.status == "done", result.error
    assert set(calls) == {"inspect_candidate", "accepted_state"}


async def test_audit_snapshot_content_identity_for_the_next_gate(
    broker, candidate, staging, tmp_path
):
    result = await run_auditor(broker, candidate, audit_server(tmp_path), staging)
    assert result.status == "done"
    # Recomputed from the unchanged candidate with a different run ID: the
    # content identity matches, the run-specific manifest hash does not.
    head = broker.inspect_candidate(candidate).head_commit
    again = build_input_bundle(candidate, head, "bridge_" + "0" * 32, BridgeLimits())
    assert (
        snapshot_content_sha256(again.manifest.files)
        == (result.metadata["audit_snapshot_content_sha256"])
    )
    assert again.manifest_sha256 != result.metadata["audit_snapshot_manifest_sha256"]
    # Any change to the candidate changes the content identity.
    (candidate.local_path / "README.md").write_text("changed after the audit\n")
    changed = build_input_bundle(candidate, head, "bridge_" + "0" * 32, BridgeLimits())
    assert (
        snapshot_content_sha256(changed.manifest.files)
        != (result.metadata["audit_snapshot_content_sha256"])
    )


# --- J. A malformed report stays LongHorizon's format-repair concern ---


async def test_j_malformed_report_is_left_to_longhorizon(broker, candidate, staging, tmp_path):
    malformed = "Everything looks finished to me."
    result = await run_auditor(broker, candidate, audit_server(tmp_path, text=malformed), staging)
    # The read-only audit boundary held, so the episode is done; the adapter
    # neither repairs nor reinterprets the report.
    assert result.status == "done"
    assert result.metadata["assistant_visible_output"] == malformed
    raw = auditor_report_text_from_episode_result(result)
    assert lh_manager._should_repair_auditor_format(result, raw) is True
    report = audit_report_from_episode_result(result, 1)
    assert (report.status, report.integrity_status, report.contract_audit_status) == (
        "blocked",
        "suspect",
        "unknown",
    )


def test_j_source_finding_repaired_text_loses_to_primary_visible_output():
    """Pinned manager: a repaired report is put in actions_log but the primary
    metadata is kept, and assistant_visible_output takes precedence. With a UHP
    adapter the repair is therefore not used; the result stays blocked (fails closed)."""
    primary = EpisodeResult(
        status="done",
        actions_log="",
        duration_ms=0,
        metadata={"assistant_visible_output": "Everything looks finished to me."},
    )
    corrected = EpisodeResult(
        status=primary.status,
        actions_log=VALID_REPORT,
        duration_ms=0,
        metadata=primary.metadata,
    )
    assert audit_report_from_episode_result(corrected, 1).status == "blocked"


# --- K-N. Remote auditor writes are detected and never imported ---


def add_file(ws):
    (ws / "audit_notes.md").write_text("notes\n")


def modify_file(ws):
    (ws / "README.md").write_text("fixed by the auditor\n")


def delete_file(ws):
    (ws / "docs/old.md").unlink()


def chmod_file(ws):
    os.chmod(ws / "src/app.py", 0o755)


@pytest.mark.parametrize(
    "work,expected",
    [
        (add_file, {"added": ["audit_notes.md"], "changed": [], "deleted": [], "mode_changed": []}),
        (modify_file, {"added": [], "changed": ["README.md"], "deleted": [], "mode_changed": []}),
        (delete_file, {"added": [], "changed": [], "deleted": ["docs/old.md"], "mode_changed": []}),
        (
            chmod_file,
            {"added": [], "changed": ["src/app.py"], "deleted": [], "mode_changed": ["src/app.py"]},
        ),
    ],
    ids=["k_add", "l_modify", "m_delete", "n_executable_bit"],
)
async def test_k_to_n_remote_auditor_mutation_is_detected(
    repo, broker, candidate, staging, tmp_path, work, expected
):
    before = snapshot(repo, candidate)
    result = await run_auditor(broker, candidate, audit_server(tmp_path, work=work), staging)
    assert result.status == "error"
    assert result.error.startswith("auditor_workspace_mutation_detected")
    m = result.metadata
    assert m["auditor_workspace_mutations"] == expected
    assert m["auditor_remote_workspace_unchanged"] is False
    assert m["audit_invalid_reasons"] == ["auditor_workspace_mutation_detected"]
    # LongHorizon's own read-only guard keys, in the pinned shape.
    assert m["verifier_workspace_mutation_detected"] is True
    assert m["verifier_workspace_restored"] is True
    # The report is not trusted and is not the role's output.
    assert m["assistant_visible_output"] == ""
    assert m["untrusted_auditor_output"] == VALID_REPORT
    report = audit_report_from_episode_result(result, 1)
    assert report.status == "blocked"
    assert "Auditor also changed task workspace files" in report.report_text
    # Remote writes never reach the candidate.
    assert snapshot(repo, candidate) == before
    assert m["independently_verified"] is False


# --- O, P. Missing or invalid mutation evidence ---


@pytest.mark.parametrize(
    "server_kwargs,code",
    [
        ({"pack": False}, "output_artifact_missing"),
        ({"session_id": None}, "missing_session_id"),
    ],
    ids=["o_artifact_missing", "o_no_session"],
)
async def test_o_missing_evidence_is_error(
    repo, broker, candidate, staging, tmp_path, server_kwargs, code
):
    before = snapshot(repo, candidate)
    result = await run_auditor(broker, candidate, audit_server(tmp_path, **server_kwargs), staging)
    assert result.status == "error"
    assert result.error.startswith(f"audit_evidence_invalid: {code}")
    assert result.metadata["auditor_remote_evidence"] == "failed"
    assert result.metadata["auditor_remote_workspace_unchanged"] is False
    assert "verifier_workspace_mutation_detected" not in result.metadata
    assert result.metadata["assistant_visible_output"] == ""
    assert snapshot(repo, candidate) == before


def garbage_bundle(run_id, manifest):
    return b"not a gzip archive"


def other_snapshot_bundle(run_id, manifest):
    identity = {key: manifest[key] for key in ("workspace_id", "candidate_id", "base_commit")}
    delta = {
        "format": helper.FORMAT,
        "kind": "delta",
        "bridge_run_id": run_id,
        **identity,
        "input_manifest_sha256": "0" * 64,
        "added": [],
        "changed": [],
        "deleted": [],
    }
    return helper.build_archive(delta, {})


@pytest.mark.parametrize(
    "output,reason",
    [(garbage_bundle, "malformed"), (other_snapshot_bundle, "input_manifest_sha256")],
    ids=["p_garbage", "p_other_snapshot"],
)
async def test_p_invalid_evidence_bundle_is_error(
    repo, broker, candidate, staging, tmp_path, output, reason
):
    before = snapshot(repo, candidate)
    # The auditor itself behaves; the evidence artifact is replaced afterwards.
    server = audit_server(tmp_path, output=output)
    result = await run_auditor(broker, candidate, server, staging)
    assert result.status == "error"
    assert result.error.startswith("audit_evidence_invalid: invalid_bundle")
    assert reason in result.error
    assert snapshot(repo, candidate) == before
    assert list(staging.iterdir()) == []


# --- Q-T. Local candidate drift during the audit invalidates it ---


def local_modify(root):
    (root / "README.md").write_text("local edit during audit\n")


def local_add(root):
    (root / "local_new.txt").write_text("x\n")


def local_delete(root):
    (root / "src/app.py").unlink()


def local_chmod(root):
    os.chmod(root / "src/app.py", 0o755)


@pytest.mark.parametrize(
    "change,detail",
    [
        (local_modify, "modified README.md"),
        (local_add, "added local_new.txt"),
        (local_delete, "deleted src/app.py"),
        (local_chmod, "modified src/app.py"),
    ],
    ids=["q_modified", "r_added", "s_deleted", "t_executable_bit"],
)
async def test_q_to_t_local_drift_invalidates_audit(
    repo, broker, candidate, staging, tmp_path, change, detail
):
    server = audit_server(tmp_path, work=lambda ws: change(candidate.local_path))
    result = await run_auditor(broker, candidate, server, staging)
    assert result.status == "error"
    assert result.error.startswith("candidate_changed_during_audit")
    assert detail in result.error
    assert result.metadata["audit_snapshot_unchanged"] is False
    assert result.metadata["assistant_visible_output"] == ""
    # No auto-merge: the local change stays exactly as made.
    root = candidate.local_path
    if change is local_modify:
        assert (root / "README.md").read_text() == "local edit during audit\n"
    if change is local_chmod:
        assert os.access(root / "src/app.py", os.X_OK)


async def test_candidate_head_moving_during_audit_invalidates_it(
    repo, broker, candidate, staging, tmp_path
):
    # A checkpoint during the audit keeps the files but moves the candidate HEAD.
    server = audit_server(
        tmp_path, work=lambda ws: broker.checkpoint_candidate(candidate, "during audit")
    )
    result = await run_auditor(broker, candidate, server, staging)
    assert result.status == "error"
    assert result.error.startswith("candidate_changed_during_audit: candidate HEAD moved")


# --- U. Accepted state moving during the audit ---


async def test_u_accepted_state_moving_during_audit_invalidates_it(
    repo, broker, candidate, staging, tmp_path
):
    a = accepted(repo)

    def promote_other(ws):
        other = broker.create_candidate(broker.accepted_state())
        (other.local_path / "other.txt").write_text("x\n")
        broker.promote(broker.checkpoint_candidate(other, "moves accepted"))

    before_files = tree(candidate.local_path)
    result = await run_auditor(
        broker, candidate, audit_server(tmp_path, work=promote_other), staging
    )
    assert result.status == "error"
    assert result.error.startswith("candidate_stale_during_audit")
    assert result.metadata["accepted_state_unchanged"] is False
    assert accepted(repo) != a  # moved by the test, not by the audit
    assert tree(candidate.local_path) == before_files


async def test_stale_candidate_before_audit_makes_no_request(
    repo, broker, candidate, staging, tmp_path
):
    other = broker.create_candidate(broker.accepted_state())
    (other.local_path / "other.txt").write_text("x\n")
    broker.promote(broker.checkpoint_candidate(other, "moves accepted"))
    server = audit_server(tmp_path)
    result = await run_auditor(broker, candidate, server, staging)
    assert result.status == "error"
    assert result.error.startswith("candidate_stale")
    assert result.metadata["cloudeo_runtime_status"] is None
    assert server.requests == []


@pytest.mark.parametrize("problem", ["cleaned_up", "forged", "symlink"])
async def test_unavailable_candidate_makes_no_request(
    broker, candidate, staging, tmp_path, problem
):
    target = candidate
    if problem == "cleaned_up":
        broker.cleanup(candidate, discard=True)
    elif problem == "forged":
        target = candidate.model_copy(update={"candidate_id": "f" * 32})
    else:
        (candidate.local_path / "link").symlink_to("README.md")
    server = audit_server(tmp_path)
    result = await run_auditor(broker, target, server, staging)
    assert result.status == "error"
    assert result.error.startswith("candidate_unavailable")
    assert server.requests == []
    if problem == "cleaned_up":
        assert not candidate.local_path.exists()  # never recreated


# --- V-Y. Runtime states: no audit is accepted ---


async def test_v_unknown_runtime(repo, broker, candidate, staging, tmp_path):
    def timeout(request):
        raise httpx.ReadTimeout("timed out", request=request)

    before = snapshot(repo, candidate)
    result = await run_auditor(
        broker, candidate, audit_server(tmp_path, task_reply=timeout), staging
    )
    assert result.status == "error"
    assert result.error.startswith("runtime_state_unobserved")
    assert result.metadata["auditor_remote_evidence"] == "skipped"
    assert audit_report_from_episode_result(result, 1).status == "blocked"
    assert snapshot(repo, candidate) == before


@pytest.mark.parametrize(
    "runtime,expected",
    [("failed", "error"), ("cancelled", "cancelled"), ("in_progress", "error")],
    ids=["w_failed", "x_cancelled", "in_progress"],
)
async def test_w_x_non_completed_runtime(
    repo, broker, candidate, staging, tmp_path, runtime, expected
):
    before = snapshot(repo, candidate)
    result = await run_auditor(broker, candidate, audit_server(tmp_path, status=runtime), staging)
    assert result.status == expected
    assert result.metadata["cloudeo_runtime_status"] == runtime
    assert result.metadata["auditor_remote_evidence"] == "skipped"
    assert audit_report_from_episode_result(result, 1).status == "blocked"
    assert snapshot(repo, candidate) == before


@pytest.mark.parametrize("reason,expected", [("max_steps", "timeout"), ("interrupted", "error")])
async def test_y_incomplete_keeps_runtime_mapping_and_is_no_audit(
    broker, candidate, staging, tmp_path, reason, expected
):
    server = audit_server(
        tmp_path,
        status="incomplete",
        overrides={**reply(VALID_REPORT), "incomplete_details": {"reason": reason}},
    )
    result = await run_auditor(broker, candidate, server, staging)
    assert result.status == expected
    assert result.metadata["cloudeo_runtime_status"] == "incomplete"
    # Even with a well-formed "complete" report, an incomplete run is no audit.
    report = audit_report_from_episode_result(result, 1)
    assert report.status == "blocked"


# --- Z, AA. Environment and trajectory ---


async def test_z_aa_environment_untouched_and_no_trajectory(broker, candidate, staging, tmp_path):
    trajectory = tmp_path / "auditor_raw_trajectory.jsonl"
    result = await run_auditor(
        broker, candidate, audit_server(tmp_path), staging, live_trajectory_path=str(trajectory)
    )
    assert result.status == "done"  # UntouchableEnvironment raised on no call
    assert not trajectory.exists()


# --- AB-AE. Role eligibility ---

EXPECTED = {
    UHPHarnessAgentAdapter: {"manager", "final_response", "auditor_format_repair"},
    UHPWorkspaceExecutorAdapter: {"cli_executor"},
    UHPWorkspaceAuditorAdapter: {"cli_auditor"},
}


def _instances(broker, candidate, staging, tmp_path):
    server = FakeHarnessRouter(tmp_path)
    bridge, client = make_bridge(broker, server, staging)
    transport, _ = make_transport(broker, server, staging)
    return {
        UHPHarnessAgentAdapter: UHPHarnessAgentAdapter(
            EXECUTOR_PROFILE, ExecutionDispatcher(harness_task=UHPHarnessTaskBackend(client))
        ),
        UHPWorkspaceExecutorAdapter: UHPWorkspaceExecutorAdapter(
            EXECUTOR_PROFILE, bridge, candidate
        ),
        UHPWorkspaceAuditorAdapter: UHPWorkspaceAuditorAdapter(
            AUDITOR_PROFILE, transport, candidate
        ),
    }


@pytest.mark.parametrize("role", LONGHORIZON_ROLES)
def test_ab_ac_ad_role_matrix(broker, candidate, staging, tmp_path, role):
    for cls, adapter in _instances(broker, candidate, staging, tmp_path).items():
        assert eligible_roles(adapter) == EXPECTED[cls]
        if role in EXPECTED[cls]:
            require_role_eligible(adapter, role)
        else:
            with pytest.raises(RoleEligibilityError):
                require_role_eligible(adapter, role)


def test_ae_auditor_subclass_and_unknowns_fail_closed(broker, candidate, staging, tmp_path):
    adapters = _instances(broker, candidate, staging, tmp_path)
    auditor = adapters[UHPWorkspaceAuditorAdapter]
    executor = adapters[UHPWorkspaceExecutorAdapter]

    class LookalikeAuditor(UHPWorkspaceAuditorAdapter):
        pass

    lookalike = LookalikeAuditor(AUDITOR_PROFILE, auditor.transport, candidate)
    assert eligible_roles(lookalike) == frozenset()
    with pytest.raises(RoleEligibilityError):
        require_role_eligible(lookalike, "cli_auditor")
    for role in ("auditor", "agent", "auditor_agent"):
        with pytest.raises(RoleEligibilityError):
            require_role_eligible(auditor, role)
    # The auditor is not an executor, and the executor is not an auditor.
    with pytest.raises(RoleEligibilityError):
        bind_longhorizon_roles({"cli_executor": auditor})
    with pytest.raises(RoleEligibilityError):
        bind_longhorizon_roles({"cli_auditor": executor})
    bound = bind_longhorizon_roles(
        {
            "manager": adapters[UHPHarnessAgentAdapter],
            "cli_executor": executor,
            "cli_auditor": auditor,
            "auditor_format_repair": adapters[UHPHarnessAgentAdapter],
        }
    )
    assert set(bound) == {
        "manager_agent",
        "cli_executor_agent",
        "cli_auditor_agent",
        "auditor_format_repair_agent",
    }
    assert "agent" not in bound and "auditor_agent" not in bound
    # The pinned manager takes exactly this keyword for the CLI auditor.
    assert "cli_auditor_agent" in inspect.signature(lh_manager._run_impl).parameters


def test_capabilities_and_agent_adapter_conformance(broker, candidate, staging, tmp_path):
    auditor = _instances(broker, candidate, staging, tmp_path)[UHPWorkspaceAuditorAdapter]
    assert isinstance(auditor, AgentAdapter)
    assert UHPWorkspaceAuditorAdapter.supports_workspace_sync is True
    assert UHPWorkspaceAuditorAdapter.workspace_access == "read_only_snapshot"
    assert UHPWorkspaceExecutorAdapter.supports_workspace_sync is True
    assert UHPHarnessAgentAdapter.supports_workspace_sync is False
    assert inspect.signature(UHPWorkspaceAuditorAdapter.run_episode) == inspect.signature(
        UHPWorkspaceExecutorAdapter.run_episode
    )


def test_transport_requires_one_uhp_deployment(broker, staging, tmp_path):
    server = FakeHarnessRouter(tmp_path)
    _, other_client = make_transport(broker, server, staging)
    client = UHPClient(
        "http://uhp.test/api/harness", "test-not-a-real-key", transport=httpx.MockTransport(server)
    )
    dispatcher = ExecutionDispatcher(harness_task=UHPHarnessTaskBackend(other_client))
    with pytest.raises(ValueError, match="one UHP deployment"):
        UHPWorkspaceAuditTransport(broker, client, dispatcher)


# --- AF. HarnessRouter bootstrap docs still reconcile ---


async def test_af_tracked_project_doc_replaces_bootstrap_copy(tmp_path, staging):
    project_doc = b"# Project rules\nRun tests with pytest.\n"
    _, broker, candidate = project_with(tmp_path, {"CLAUDE.md": project_doc})
    seen = {}
    server = audit_server(
        tmp_path, work=lambda ws: seen.setdefault("doc", (ws / "CLAUDE.md").read_bytes())
    )
    result = await run_auditor(broker, candidate, server, staging)
    assert result.status == "done", result.error
    assert seen["doc"] == project_doc  # the auditor reads the project's own doc
    assert result.metadata["auditor_remote_workspace_unchanged"] is True


async def test_af_unknown_remote_doc_fails_closed(repo, broker, candidate, staging, tmp_path):
    server = audit_server(
        tmp_path, bootstrap_doc="AGENTS.md", bootstrap_content=b"unmarked instructions\n"
    )
    result = await run_auditor(broker, candidate, server, staging)
    assert server.helper_runs[0][0] == "unpack" and server.helper_runs[0][1] != 0
    assert result.status == "error"
    assert result.error.startswith("audit_evidence_invalid: output_artifact_missing")


# --- AG, AH. Ignored files and .git never enter the audit snapshot ---


async def test_ag_ah_snapshot_excludes_ignored_files_and_git(broker, candidate, staging, tmp_path):
    server = audit_server(tmp_path)
    result = await run_auditor(broker, candidate, server, staging)
    assert result.status == "done"
    manifest, _, names = uploaded_snapshot(server)
    paths = [entry["path"] for entry in manifest["files"]]
    assert "notes/new.txt" in paths  # untracked, not ignored
    for forbidden in (".env", "debug.log"):
        assert forbidden not in paths
        assert f"files/{forbidden}" not in names
    assert ".github/workflows/ci.yml" in paths  # a lookalike name is still sent
    assert not any(".git" in p.split("/") for p in paths)
    assert not any(".git" in n.split("/") for n in names)
    assert json.dumps(manifest).count("SECRET") == 0
