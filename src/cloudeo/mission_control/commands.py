"""Owner commands from Mission Control (ADR-038).

The only writes Mission Control can make, and each is an existing control
transition run by cloudeo.control.machine; nothing here changes WorkOrder
semantics:

- approve_plan / reject_plan on a PLAN_PROPOSED WorkOrder
- a decision on the open attention request: abort, defer, replan, and resume
  where no baseline recheck is needed

Not offered: change_agent / change_budget (they need an envelope amendment the
UI cannot author yet) and resume back into PLAN_APPROVED, EXECUTING or
FINAL_VERIFICATION (it rechecks the accepted baseline, which needs the
Workspace Broker the API is not bound to). Waivers are never sent.

Every command names the record version the owner saw. It is applied to that
exact version or not at all (StaleWriteError), so a decision is never made
against a state the owner did not see. The actor comes from server config,
never from the request.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from cloudeo.control import machine as m
from cloudeo.control.model import UserAction, UserDecision, WorkOrder, WorkOrderStatus
from cloudeo.control.store import SqliteControlStore, StaleWriteError

S = WorkOrderStatus

CommandName = Literal["approve_plan", "reject_plan", "abort", "defer", "replan", "resume"]
COMMANDS: tuple[CommandName, ...] = (
    "approve_plan",
    "reject_plan",
    "resume",
    "replan",
    "defer",
    "abort",
)
DECISIONS: dict[str, UserAction] = {
    "resume": UserAction.RESUME,
    "replan": UserAction.REPLAN,
    "defer": UserAction.DEFER,
    "abort": UserAction.ABORT,
}
# resume back into these states rechecks the accepted baseline (machine.decide).
NEEDS_BASELINE = frozenset({S.PLAN_APPROVED, S.EXECUTING, S.FINAL_VERIFICATION})

NO_BROKER = "resume here rechecks the accepted baseline; the API is not bound to a Workspace Broker"


@dataclass(frozen=True)
class Availability:
    command: CommandName
    enabled: bool
    reason: str | None = None


def available_commands(wo: WorkOrder) -> list[Availability]:
    """Which owner commands apply to this WorkOrder now, and why not otherwise.

    Pure: the same record always yields the same answer. Commands that do not
    apply to the current state are omitted; ones that apply but cannot be sent
    from Mission Control yet are listed disabled with the reason.
    """
    if wo.status == S.PLAN_PROPOSED:
        return [Availability("approve_plan", True), Availability("reject_plan", True)]
    request = wo.open_attention
    if wo.status != S.USER_ATTENTION_REQUIRED or request is None:
        return []
    blocking = request.open_blocking()
    if request.raised_from in NEEDS_BASELINE:
        resume = Availability("resume", False, NO_BROKER)
    elif blocking:
        resume = Availability(
            "resume", False, f"blocking reasons still open: {', '.join(map(str, blocking))}"
        )
    else:
        resume = Availability("resume", True)
    return [
        resume,
        Availability("replan", True),
        Availability("defer", True),
        Availability("abort", True),
    ]


class CommandRefused(Exception):
    """The command does not apply to the WorkOrder as stored; nothing changed."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class CommandService:
    def __init__(
        self,
        store: SqliteControlStore,
        *,
        actor: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._store = store
        self._actor = actor
        self._clock = clock

    def run(
        self,
        work_order_id: str,
        command: CommandName,
        *,
        expected_version: int,
        message: str = "",
    ) -> WorkOrder:
        """Apply one owner command to exactly the version the owner saw.

        Raises NotFoundError, StaleWriteError, or CommandRefused (which wraps
        the state machine's own TransitionRejected).
        """
        wo = self._store.get(work_order_id)
        if wo.version != expected_version:
            raise StaleWriteError(work_order_id)
        offered = {a.command: a for a in available_commands(wo)}
        if command not in offered:
            raise CommandRefused("not_applicable", f"{command} does not apply to {wo.status}")
        if not offered[command].enabled:
            raise CommandRefused("not_available", offered[command].reason or command)
        try:
            updated = self._apply(wo, command, message)
        except m.TransitionRejected as exc:
            raise CommandRefused(exc.code, str(exc)) from exc
        return self._store.update(
            updated, expected_version=expected_version, event=f"owner_{command}"
        )

    def _apply(self, wo: WorkOrder, command: CommandName, message: str) -> WorkOrder:
        now = self._clock()
        if command == "approve_plan":
            return m.approve_plan(
                wo, plan_version=len(wo.plan_versions), approved_by=self._actor, approved_at=now
            )
        if command == "reject_plan":
            return m.reject_plan(wo)
        decision = UserDecision(
            action=DECISIONS[command], actor=self._actor, at=now, message=message
        )
        return m.decide(wo, decision)
