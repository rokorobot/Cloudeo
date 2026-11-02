"""EVAL-01 PR 6a: the deterministic regression gate.

Exit criteria (docs/EVAL-01_PLAN.md §5, PR 6): a seeded critical regression
blocks; missing required evidence blocks; only "pass" lets a change advance.
"""

import json

from cloudeo.core.controller import Controller
from cloudeo.evaluation import scenarios
from cloudeo.evaluation.__main__ import main as cli
from cloudeo.evaluation.runner import capabilities
from cloudeo.models import ToolCandidate

CORPUS = "corpus-v3"


def gate(tmp_path):
    code = cli(["gate", "--suite", CORPUS, "--out", str(tmp_path)])
    (report,) = tmp_path.glob("gate-*.json")
    data = json.loads(report.read_text())
    assert data["exit_code"] == code
    assert (tmp_path / f"gate-{data['run_id']}.md").is_file()
    return code, data


def test_clean_main_passes_and_capability_gaps_do_not_gate(tmp_path):
    code, report = gate(tmp_path)
    assert report["capability"]["fail"] > 0  # open gaps stay visible, never gate
    if capabilities()["longhorizon"]:
        assert (code, report["verdict"]) == (0, "pass"), report["blocked_reasons"]
        assert report["regression"]["pass"] == 22 and report["regression"]["fail"] == 0
        assert not report["fail_reasons"] and not report["blocked_reasons"]
    else:
        # Without the pinned integration, regression cases that need it cannot pass.
        assert (code, report["verdict"]) == (2, "blocked")
        assert all("unsupported" in r for r in report["blocked_reasons"])


def test_forbidden_billing_fallback_fails_the_gate(tmp_path, monkeypatch):
    # Seeded defect: a runtime reporting metered use where the profile declared a
    # subscription is silently accepted (ADR-035 forbids it).
    from cloudeo.control import model

    real = model.observed_billing

    def accepts_metered(profile, observed):
        if observed == model.BillingMode.METERED_API:
            return "conforms"
        return real(profile, observed)

    monkeypatch.setattr(model, "observed_billing", accepts_metered)
    code, report = gate(tmp_path)
    assert (code, report["verdict"]) == (1, "fail")
    assert any(
        r.startswith("prohibited-billing-transition#1: regression failed")
        and "billing.observed_metered_api" in r
        for r in report["fail_reasons"]
    ), report["fail_reasons"]


def test_correct_answer_through_an_unauthorized_action_fails_the_gate(tmp_path, monkeypatch):
    real = Controller._execute_direct_tool
    rogue = ToolCandidate(id="rogue", description="unapproved", treg_tool_id="rogue.email")

    async def also_calls_rogue(self, candidate, *, dry_run):
        await real(self, rogue, dry_run=dry_run)  # seeded defect: an unapproved call
        return await real(self, candidate, dry_run=dry_run)

    monkeypatch.setattr(Controller, "_execute_direct_tool", also_calls_rogue)
    code, report = gate(tmp_path)
    assert (code, report["verdict"]) == (1, "fail")
    trial = next(t for t in report["trials"] if t["case_id"] == "direct-tool-verified-success")
    assert trial["verdict"] == "fail" and "rogue.email" in trial["reasons"]


def test_missing_evidence_blocks_never_passes(tmp_path, monkeypatch):
    # The scenario still returns its observations, but no boundary event is recorded.
    real = scenarios.SCENARIOS["core.controller.run"]

    async def unobserved(fixture, workdir, record):
        return await real(fixture, workdir, scenarios.Recorder())

    monkeypatch.setitem(scenarios.SCENARIOS, "core.controller.run", unobserved)
    code, report = gate(tmp_path)
    assert (code, report["verdict"]) == (2, "blocked")
    assert not report["fail_reasons"]
    assert any(
        "direct-tool-verified-success#1: regression unknown" in r and "evidence_missing" in r
        for r in report["blocked_reasons"]
    ), report["blocked_reasons"]


def test_infrastructure_error_blocks_never_passes(tmp_path, monkeypatch):
    async def broken(fixture, workdir, record):
        raise RuntimeError("fake boundary down")

    monkeypatch.setitem(scenarios.SCENARIOS, "core.controller.run", broken)
    code, report = gate(tmp_path)
    assert (code, report["verdict"]) == (2, "blocked")
    assert any("error: RuntimeError: fake boundary down" in r for r in report["blocked_reasons"])
