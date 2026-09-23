"""Upstream LongHorizon manager run, then Cloudeo normalization and the promotion gate.

A thin wrapper around the pinned, unmodified lh_harness.manager.run(). The
authority chain is:

    LongHorizon manager:  "the objective appears complete"
    Cloudeo normalizer:   "the final audit is / is not authoritative"
    Promotion gate:       "this exact audited state may / may not become accepted"

The wrapper decides nothing about promotion itself. Upstream `complete` only
permits an attempt; checkpoint_and_promote_verified() alone decides. It never
calls broker.promote(), never touches refs, and never reads auditor prose.

Upstream behavior is kept as-is: an auditor episode with status "error" still
ends the upstream run as failed/provider_*. The wrapper records every auditor
and format-repair EpisodeResult unchanged, so the final audit is always
normalized afterwards (AUDITOR_ERROR, BLOCKED, ...) and never promoted.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Literal

try:
    from lh_harness import manager as lh_manager
    from lh_harness.environment.base import Environment
    from lh_harness.types import (
        DEFAULT_WORKSPACE_PATH,
        EpisodeBudget,
        EpisodeResult,
        HarnessConfig,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - depends on the install
    raise ImportError(
        "cloudeo.longhorizon requires the optional 'longhorizon' extra "
        "(LongHorizon-Harness pinned at v0.1.7)."
    ) from exc

from pydantic import BaseModel, ConfigDict

from cloudeo.longhorizon.adapter import UHPHarnessAgentAdapter
from cloudeo.longhorizon.audit_result import AuditorVerification, normalize_auditor_result
from cloudeo.longhorizon.promotion_gate import (
    GatedPromotionResult,
    checkpoint_and_promote_verified,
)
from cloudeo.longhorizon.roles import bind_longhorizon_roles
from cloudeo.longhorizon.workspace_auditor import UHPWorkspaceAuditorAdapter
from cloudeo.longhorizon.workspace_executor import UHPWorkspaceExecutorAdapter
from cloudeo.workspace.broker import WorkspaceBroker
from cloudeo.workspace.models import CandidateWorkspace

NotAttemptedReason = Literal[
    "objective_not_complete",
    "auditor_missing",
    "manager_failed_before_audit",
]


class ManagedPromotionResult(BaseModel):
    """Both worlds: the upstream run report and Cloudeo's structured decision.

    promotion_attempted is True exactly when checkpoint_and_promote_verified()
    was called; its GatedPromotionResult is then authoritative. Otherwise
    promotion_result is None and promotion_not_attempted_reason says why. A
    refusal is never fabricated for a gate that was not invoked.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    upstream_report: dict[str, Any]
    # The final audit, normalized; None only when no auditor episode ran.
    verification: AuditorVerification | None
    promotion_attempted: bool
    promotion_not_attempted_reason: NotAttemptedReason | None = None
    promotion_result: GatedPromotionResult | None = None
    workspace_id: str
    candidate_id: str
    base_commit: str
    checkpoint_commit: str | None = None
    # How many auditor episodes the run produced; only the last is authority.
    auditor_episodes: int = 0
    format_repair_used: bool = False

    @property
    def promoted(self) -> bool:
        return self.promotion_result is not None and self.promotion_result.promoted


class _Recorder:
    """Records each EpisodeResult of an already-validated adapter, unchanged."""

    def __init__(self, inner: Any, role: str, log: list[tuple[str, EpisodeResult]]):
        self._inner = inner
        self._role = role
        self._log = log

    async def run_episode(
        self,
        prompt: str,
        env: Environment,
        budget: EpisodeBudget,
        live_trajectory_path: str | None = None,
    ) -> EpisodeResult:
        result = await self._inner.run_episode(
            prompt, env, budget, live_trajectory_path=live_trajectory_path
        )
        self._log.append((self._role, result))
        return result


class _UnboundRole:
    """Stands in for a role Cloudeo does not bind (GUI), so upstream never falls
    back to another adapter for it. Using it fails the episode explicitly."""

    def __init__(self, role: str):
        self._role = role

    async def run_episode(
        self,
        prompt: str,
        env: Environment,
        budget: EpisodeBudget,
        live_trajectory_path: str | None = None,
    ) -> EpisodeResult:
        return EpisodeResult(
            status="error",
            error=f"role_not_bound: no Cloudeo adapter is eligible for {self._role}",
            metadata={"assistant_visible_output": "", "actions_log_diagnostics_only": True},
        )


async def run_managed_with_promotion_gate(
    *,
    task: str,
    env: Environment,
    config: HarnessConfig,
    broker: WorkspaceBroker,
    candidate: CandidateWorkspace,
    manager: UHPHarnessAgentAdapter,
    executor: UHPWorkspaceExecutorAdapter,
    auditor: UHPWorkspaceAuditorAdapter,
    format_repair: UHPHarnessAgentAdapter | None = None,
    final_response: UHPHarnessAgentAdapter | None = None,
    checkpoint_message: str = "Verified LongHorizon objective",
) -> ManagedPromotionResult:
    format_repair = format_repair or manager
    final_response = final_response or manager
    # 1. Validate before anything runs; every check fails closed.
    roles = bind_longhorizon_roles(
        {
            "manager": manager,
            "cli_executor": executor,
            "cli_auditor": auditor,
            "auditor_format_repair": format_repair,
            "final_response": final_response,
        }
    )
    _require_same_candidate(broker, candidate, executor, auditor)
    config = _candidate_config(config, candidate)

    # 2. Record the auditor and format-repair episodes; nothing else changes.
    log: list[tuple[str, EpisodeResult]] = []
    roles["cli_auditor_agent"] = _Recorder(auditor, "auditor", log)
    roles["auditor_format_repair_agent"] = _Recorder(format_repair, "repair", log)

    # 3. The upstream round loop, unmodified.
    report = await lh_manager.run(
        task=task,
        env=env,
        config=config,
        gui_executor_agent=_UnboundRole("gui_executor"),
        gui_auditor_agent=_UnboundRole("gui_auditor"),
        **roles,
    )

    # 4. Normalize the final audit, whatever the run's outcome.
    primary, repair = _final_audit(log)
    verification = normalize_auditor_result(primary, repair=repair) if primary else None
    identity = {
        "upstream_report": report,
        "verification": verification,
        "workspace_id": candidate.workspace_id,
        "candidate_id": candidate.candidate_id,
        "base_commit": candidate.base_commit,
        "auditor_episodes": sum(1 for role, _ in log if role == "auditor"),
        "format_repair_used": repair is not None,
    }

    def not_attempted(reason: NotAttemptedReason) -> ManagedPromotionResult:
        return ManagedPromotionResult(
            promotion_attempted=False, promotion_not_attempted_reason=reason, **identity
        )

    if verification is None:
        failed = report.get("status") == "failed"
        return not_attempted("manager_failed_before_audit" if failed else "auditor_missing")
    # Upstream completion only permits an attempt; it never implies promotion.
    if report.get("status") != "complete" or report.get("completion_satisfied") is not True:
        return not_attempted("objective_not_complete")

    # 5. The promotion gate is the only authority.
    gated = checkpoint_and_promote_verified(
        broker, candidate, verification, message=checkpoint_message
    )
    return ManagedPromotionResult(
        promotion_attempted=True,
        promotion_result=gated,
        checkpoint_commit=gated.checkpoint.commit if gated.checkpoint else None,
        **identity,
    )


def _require_same_candidate(
    broker: WorkspaceBroker,
    candidate: CandidateWorkspace,
    executor: UHPWorkspaceExecutorAdapter,
    auditor: UHPWorkspaceAuditorAdapter,
) -> None:
    """The executor, the auditor, and the gate must all act on one candidate."""
    for name, bound in (("executor", executor.candidate), ("auditor", auditor.candidate)):
        if bound != candidate:
            raise ValueError(
                f"The {name} is bound to candidate {bound.candidate_id}, "
                f"not {candidate.candidate_id}."
            )
    if executor.bridge.broker is not broker or auditor.transport.broker is not broker:
        raise ValueError("The executor and auditor must use the gate's Workspace Broker.")


def _candidate_config(config: HarnessConfig, candidate: CandidateWorkspace) -> HarnessConfig:
    """Name the candidate as the workspace; keep upstream's own files out of it."""
    root = Path(candidate.local_path).resolve()
    if config.workspace_path not in (DEFAULT_WORKSPACE_PATH, str(candidate.local_path)):
        raise ValueError(
            f"config.workspace_path {config.workspace_path!r} is not the candidate "
            f"{candidate.local_path}; refusing to substitute another workspace."
        )
    for key in ("harness_dir", "log_dir"):
        path = Path(getattr(config, key)).expanduser().resolve()
        if path == root or root in path.parents:
            raise ValueError(
                f"config.{key} {path} is inside the candidate; upstream's own files "
                "would change the audited state."
            )
    return dataclasses.replace(config, workspace_path=str(candidate.local_path))


def _final_audit(
    log: list[tuple[str, EpisodeResult]],
) -> tuple[EpisodeResult | None, EpisodeResult | None]:
    """The last auditor episode and the repair that immediately followed it."""
    for index in range(len(log) - 1, -1, -1):
        role, result = log[index]
        if role == "auditor":
            following = log[index + 1] if index + 1 < len(log) else None
            repair = following[1] if following and following[0] == "repair" else None
            return result, repair
    return None, None
