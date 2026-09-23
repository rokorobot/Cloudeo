"""Cloudeo-owned LongHorizon role eligibility. Fails closed.

LongHorizon's manager (pinned v0.1.7, `_run_impl`) takes one adapter per role
and silently falls back to a default `agent` or `auditor_agent` for any role
left unbound. Cloudeo therefore binds roles explicitly through this module and
never relies on those defaults. LongHorizon itself is not patched.

Eligibility is an explicit table keyed by exact adapter type: a subclass or an
unknown adapter is eligible for nothing. It is not inferred from class names.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from cloudeo.longhorizon.adapter import UHPHarnessAgentAdapter
from cloudeo.longhorizon.workspace_auditor import UHPWorkspaceAuditorAdapter
from cloudeo.longhorizon.workspace_executor import UHPWorkspaceExecutorAdapter

LONGHORIZON_ROLES = (
    "manager",
    "gui_executor",
    "cli_executor",
    "gui_auditor",
    "cli_auditor",
    "auditor_format_repair",
    "final_response",
)
# The pinned manager's keyword argument for each role.
MANAGER_ROLE_KEYWORDS = {role: f"{role}_agent" for role in LONGHORIZON_ROLES}

ROLE_ELIGIBILITY: Mapping[type, frozenset[str]] = {
    # Text-only roles: it cannot see a synchronized workspace.
    UHPHarnessAgentAdapter: frozenset({"manager", "final_response", "auditor_format_repair"}),
    # Mutates candidate files; not an independent auditor; no GUI/screenshot
    # contract; manager and final-response roles need no mutation.
    UHPWorkspaceExecutorAdapter: frozenset({"cli_executor"}),
    # Read-only snapshot in a fresh session; no GUI/screenshot contract; it is
    # not an executor, and format repair stays with the text-only adapter.
    UHPWorkspaceAuditorAdapter: frozenset({"cli_auditor"}),
}


class RoleEligibilityError(ValueError):
    """The adapter is not eligible for the LongHorizon role; nothing was bound."""


def eligible_roles(adapter: Any) -> frozenset[str]:
    return ROLE_ELIGIBILITY.get(type(adapter), frozenset())


def require_role_eligible(adapter: Any, role: str) -> None:
    if role not in LONGHORIZON_ROLES:
        raise RoleEligibilityError(f"Unknown LongHorizon role {role!r}.")
    if role not in eligible_roles(adapter):
        raise RoleEligibilityError(
            f"{type(adapter).__name__} is not eligible for the {role!r} role "
            f"(eligible: {sorted(eligible_roles(adapter)) or 'none'})."
        )


def bind_longhorizon_roles(bindings: Mapping[str, Any]) -> dict[str, Any]:
    """Validate every binding and return the manager's role keyword arguments.

    Every binding must be eligible, or nothing is returned. Only explicit role
    keywords are produced, never the manager's default `agent`/`auditor_agent`.
    """
    for role, adapter in bindings.items():
        require_role_eligible(adapter, role)
    return {MANAGER_ROLE_KEYWORDS[role]: adapter for role, adapter in bindings.items()}
