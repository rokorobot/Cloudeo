"""V2C-22: the accepted baseline observed from a real GitWorkspaceBroker (ADR-030).

Proves orchestration reads the broker's accepted state, not the repository's
HEAD, and that the control layer's drift checks act on it. It does not prove
that a broker belongs to a WorkOrder's project (no ProjectTarget yet).
"""

# Pytest fixtures imported from the broker tests are requested by parameter
# name, which ruff reports as redefinitions.
# ruff: noqa: F811

import pytest
from control_helpers import NOW, new_work_order, plan
from test_workspace_broker import (  # noqa: F401 - fixtures are used by name
    broker,
    commit_file,
    git,
    isolated_git,
    repo,
    root,
)

from cloudeo.control import machine as m
from cloudeo.control.model import AttentionCode, Candidate, WorkOrderStatus
from cloudeo.orchestration.baseline import (
    BaselineWorkspaceMismatch,
    observe_accepted_baseline,
)
from cloudeo.workspace.git import GitWorkspaceBroker

S = WorkOrderStatus


def promote_change(broker, name):
    """Move accepted state through the broker, as a concurrent WorkOrder would."""
    candidate = broker.create_candidate(broker.accepted_state())
    (candidate.local_path / name).write_text("x\n")
    return broker.promote(broker.checkpoint_candidate(candidate, name)).accepted_commit


def test_v2c_22_records_real_broker_accepted_state_without_claiming_project_binding(
    repo, root, broker
):
    accepted = git(repo, "rev-parse", "HEAD")
    observed = observe_accepted_baseline(broker)
    assert (observed.workspace_id, observed.accepted_commit) == ("demo", accepted)
    assert observed.evidence.kind == "broker_accepted_state"
    assert observed.evidence.ref == f"demo@{accepted}"
    # HEAD moves without a promotion: the accepted baseline does not.
    head = commit_file(repo, "unaccepted.txt", "x\n", "not promoted")
    assert head != accepted
    assert observe_accepted_baseline(broker).accepted_commit == accepted
    # A promotion through the broker does move it.
    promoted = promote_change(broker, "feature.txt")
    assert observe_accepted_baseline(broker).accepted_commit == promoted != head
    # Limitation: any broker is observed; nothing binds it to the WorkOrder's
    # project "demo" before a candidate exists.
    other = GitWorkspaceBroker.initialize(repo, "other", accepted, root)
    assert observe_accepted_baseline(other, new_work_order()).workspace_id == "other"


def test_v2c_22_observed_baseline_drives_the_control_drift_checks(broker):
    planned = observe_accepted_baseline(broker)
    wo = m.start_intake(new_work_order(), accepted_baseline=planned.accepted_commit)
    wo = m.propose_plan(wo, plan())
    wo = m.approve_plan(wo, plan_version=1, approved_by="robert", approved_at=NOW)
    wo = m.attach_candidate(
        wo,
        Candidate(workspace_id="demo", candidate_id="cand1", base_commit=planned.accepted_commit),
        accepted_baseline=observe_accepted_baseline(broker, wo).accepted_commit,
    )
    moved = promote_change(broker, "concurrent.txt")
    current = observe_accepted_baseline(broker, wo)
    wo = m.start_execution(wo, accepted_baseline=current.accepted_commit)
    assert wo.status == S.USER_ATTENTION_REQUIRED
    (reason,) = wo.open_attention.reasons
    assert reason.code == AttentionCode.BASELINE_DRIFT
    assert reason.evidence[0].ref == moved
    assert wo.planned_baseline == planned.accepted_commit  # never rebased


@pytest.mark.negative
def test_v2c_22_a_broker_for_another_workspace_is_refused_once_a_candidate_exists(
    repo, root, broker
):
    base = observe_accepted_baseline(broker).accepted_commit
    wo = m.start_intake(new_work_order(), accepted_baseline=base)
    wo = m.approve_plan(
        m.propose_plan(wo, plan()), plan_version=1, approved_by="robert", approved_at=NOW
    )
    wo = m.attach_candidate(
        wo,
        Candidate(workspace_id="demo", candidate_id="cand1", base_commit=base),
        accepted_baseline=base,
    )
    other = GitWorkspaceBroker.initialize(repo, "other", base, root)
    with pytest.raises(BaselineWorkspaceMismatch):
        observe_accepted_baseline(other, wo)
