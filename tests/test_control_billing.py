"""Provider-neutral profile fields and the project billing policy (ADR-035 slice 3, PN-05).

The forbidden case throughout: a subscription profile must never turn into
metered use without the project having approved exactly that.
"""

from typing import get_args

import pytest
from control_helpers import (
    OPUS,
    PROFILES,
    SUBSCRIPTION_ONLY,
    E,
    project_profile,
    register_all,
    writer,
)
from pydantic import ValidationError

from cloudeo.control.model import (
    BillingMode,
    BillingPolicy,
    DirectToolProfile,
    FallbackCondition,
    Limits,
    Permissions,
    Role,
    observed_billing,
)
from cloudeo.control.store import ControlStoreError, SqliteControlStore
from cloudeo.execution import contracts
from cloudeo.execution.contracts import RuntimeIdentity

SUB = BillingMode.SUBSCRIPTION_INCLUDED
METERED = BillingMode.METERED_API
METERED_CODER = writer("metered-coder", E, billing_mode=METERED).evolve(
    limits=Limits(max_cost_usd=5)
)


def metered_policy(*, fallback=False, cap=10.0, modes=(SUB, METERED)):
    return BillingPolicy(
        allowed_modes=frozenset(modes), allow_metered_fallback=fallback, max_metered_cost_usd=cap
    )


def with_profiles(policy, *, executor=OPUS, fallbacks=(), extra=()):
    """The helper project profile with its executor binding and billing policy replaced."""
    base = project_profile(fallbacks=())
    known = {**PROFILES, **{p.ref: p for p in extra}}
    conditions = frozenset({FallbackCondition.MODEL_UNAVAILABLE}) if fallbacks else frozenset()
    bindings = tuple(
        b.evolve(primary=executor, fallbacks=fallbacks, fallback_conditions=conditions)
        if b.role == E
        else b
        for b in base.bindings
    )
    bound = dict.fromkeys(r for b in bindings for r in (b.primary, *b.fallbacks))
    return base.evolve(
        bindings=bindings, profiles=tuple(known[r] for r in bound), billing_policy=policy
    )


# --- Profile fields ---


@pytest.mark.negative
def test_a_profile_must_declare_its_billing_mode():
    data = PROFILES[OPUS].model_dump()
    del data["billing_mode"]
    with pytest.raises(ValidationError, match="billing_mode"):
        type(PROFILES[OPUS]).model_validate(data)
    with pytest.raises(ValidationError):
        PROFILES[OPUS].evolve(billing_mode="free_forever")


def test_new_fields_are_optional_routing_data_and_default_to_none():
    opus = PROFILES[OPUS]
    assert (opus.execution_plane, opus.adapter_id, opus.auth_profile_ref) == (None, None, None)
    routed = opus.evolve(
        execution_plane="native_agent_cli", adapter_id="cli-a", auth_profile_ref="team-plan"
    )
    assert routed.adapter_id == "cli-a"


@pytest.mark.negative
@pytest.mark.parametrize(
    "field,value",
    [
        ("billing_mode", METERED),
        ("execution_plane", "uhp_harness"),
        ("adapter_id", "other-adapter"),
        ("auth_profile_ref", "other-account"),
    ],
)
def test_every_new_field_is_part_of_the_fingerprint(field, value):
    opus = PROFILES[OPUS]
    changed = opus.evolve(**{field: value})
    assert changed.ref.version == opus.ref.version
    assert changed.ref.fingerprint != opus.ref.fingerprint


@pytest.mark.negative
@pytest.mark.parametrize(
    "value",
    [
        "sk-" + "a1B2" * 25,  # an API-key-shaped value: mixed case and long
        "ghp_" + "Ab1" * 12,  # a token-shaped value: mixed case
        "x" * 65,
        "Team-Plan",
        "team plan",
    ],
)
def test_auth_profile_ref_refuses_secret_shaped_values(value):
    with pytest.raises(ValidationError, match="auth_profile_ref"):
        PROFILES[OPUS].evolve(auth_profile_ref=value)


@pytest.mark.negative
def test_a_direct_tool_runs_only_on_the_direct_tool_plane():
    tool = {
        "profile_id": "lint-tool",
        "version": 1,
        "permissions": Permissions(workspace="read_only"),
        "eligible_roles": (Role.CODE_AUDITOR,),
        "capability": "lint",
        "provider": "local",
        "billing_mode": BillingMode.SELF_HOSTED,
    }
    assert DirectToolProfile(**tool, execution_plane="direct_tool").execution_plane
    with pytest.raises(ValidationError, match="direct_tool plane"):
        DirectToolProfile(**tool, execution_plane="native_agent_cli")


# --- Registered versions are immutable ---


@pytest.mark.negative
def test_a_registered_version_cannot_change_its_billing_mode(tmp_path):
    store = SqliteControlStore(tmp_path / "control.db")
    register_all(store)
    opus = PROFILES[OPUS]
    with pytest.raises(ControlStoreError):
        store.register_profile(opus.evolve(billing_mode=METERED))
    assert store.registered_profile(opus.profile_id, opus.version).billing_mode == SUB
    # A changed billing mode is a new version, never an edit.
    store.register_profile(opus.evolve(version=2, billing_mode=BillingMode.PREPAID_CREDIT))


@pytest.mark.negative
def test_a_project_profile_cannot_embed_an_edited_billing_mode(tmp_path):
    store = SqliteControlStore(tmp_path / "control.db")
    register_all(store)
    edited = PROFILES[OPUS].evolve(billing_mode=BillingMode.PREPAID_CREDIT)
    policy = BillingPolicy(allowed_modes=frozenset({SUB, BillingMode.PREPAID_CREDIT}))
    project = with_profiles(policy, executor=edited.ref, extra=(edited,))
    with pytest.raises(ControlStoreError, match="not the registered profile version"):
        store.save_profile(project)


# --- The billing policy itself ---


@pytest.mark.negative
@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"allowed_modes": frozenset()}, "at least 1"),
        ({"allowed_modes": frozenset({SUB, BillingMode.UNKNOWN})}, "unknown billing mode"),
        (
            {"allowed_modes": frozenset({SUB}), "allow_metered_fallback": True},
            "metered fallback needs metered_api",
        ),
        ({"allowed_modes": frozenset({SUB, METERED})}, "needs a metered cost cap"),
        (
            {"allowed_modes": frozenset({SUB}), "max_metered_cost_usd": 10},
            "metered_api is not allowed",
        ),
        (
            {"allowed_modes": frozenset({METERED}), "max_metered_cost_usd": 0},
            "greater than 0",
        ),
    ],
)
def test_incoherent_billing_policies_are_refused(kwargs, message):
    with pytest.raises(ValidationError, match=message):
        BillingPolicy(**kwargs)


def test_billing_policy_serializes_independent_of_set_order():
    a = BillingPolicy(allowed_modes=frozenset([SUB, BillingMode.SELF_HOSTED]))
    b = BillingPolicy(allowed_modes=frozenset([BillingMode.SELF_HOSTED, SUB]))
    assert a.model_dump(mode="json")["allowed_modes"] == ["self_hosted", "subscription_included"]
    assert a.canonical_sha256() == b.canonical_sha256()


@pytest.mark.negative
def test_a_project_profile_needs_an_explicit_billing_policy():
    data = project_profile().model_dump()
    del data["billing_policy"]
    with pytest.raises(ValidationError, match="billing_policy"):
        type(project_profile()).model_validate(data)


# --- The approved envelope ---


@pytest.mark.negative
def test_a_bound_profile_outside_the_allowed_modes_is_refused():
    prepaid = writer("prepaid-coder", E, billing_mode=BillingMode.PREPAID_CREDIT)
    with pytest.raises(ValidationError, match="prepaid_credit is not approved"):
        with_profiles(SUBSCRIPTION_ONLY, executor=prepaid.ref, fallbacks=(), extra=(prepaid,))


@pytest.mark.negative
def test_a_profile_declaring_an_unknown_billing_mode_can_never_be_bound():
    unknown = writer("mystery-coder", E, billing_mode=BillingMode.UNKNOWN)
    for policy in (SUBSCRIPTION_ONLY, metered_policy(fallback=True)):
        with pytest.raises(ValidationError, match="unknown is not approved"):
            with_profiles(policy, executor=unknown.ref, fallbacks=(), extra=(unknown,))


@pytest.mark.negative
def test_a_subscription_primary_cannot_fall_back_to_metered_use_unless_approved():
    # Metered use is allowed and capped, but not as a fallback for a subscription.
    with pytest.raises(ValidationError, match="needs allow_metered_fallback"):
        with_profiles(metered_policy(), fallbacks=(METERED_CODER.ref,), extra=(METERED_CODER,))
    # Not allowed at all.
    with pytest.raises(ValidationError, match="metered_api is not approved"):
        with_profiles(SUBSCRIPTION_ONLY, fallbacks=(METERED_CODER.ref,), extra=(METERED_CODER,))
    # Explicitly approved, with a cap: accepted.
    approved = with_profiles(
        metered_policy(fallback=True), fallbacks=(METERED_CODER.ref,), extra=(METERED_CODER,)
    )
    assert approved.binding(E).fallbacks == (METERED_CODER.ref,)


def test_a_metered_primary_with_a_metered_fallback_is_not_a_transition():
    other = writer("metered-coder-2", E, billing_mode=METERED).evolve(limits=Limits(max_cost_usd=2))
    project = with_profiles(
        metered_policy(),
        executor=METERED_CODER.ref,
        fallbacks=(other.ref,),
        extra=(METERED_CODER, other),
    )
    assert project.billing_policy.allow_metered_fallback is False


@pytest.mark.negative
@pytest.mark.parametrize("limit", [None, 10.01])
def test_a_metered_profile_needs_a_cost_limit_within_the_cap(limit):
    coder = METERED_CODER.evolve(limits=Limits(max_cost_usd=limit))
    with pytest.raises(ValidationError, match="within the metered cost cap"):
        with_profiles(metered_policy(), executor=coder.ref, fallbacks=(), extra=(coder,))


# --- The observed billing mode at runtime ---


@pytest.mark.negative
def test_an_observed_billing_mode_other_than_the_declared_one_is_refused():
    opus = PROFILES[OPUS]
    assert observed_billing(opus, SUB) == "conforms"
    assert observed_billing(opus, METERED) == "refused"
    assert observed_billing(opus, BillingMode.PREPAID_CREDIT) == "refused"
    assert observed_billing(METERED_CODER, SUB) == "refused"


@pytest.mark.negative
def test_an_unreported_billing_mode_is_unverified_never_a_pass():
    opus = PROFILES[OPUS]
    assert observed_billing(opus, None) == "unverified"
    assert observed_billing(opus, BillingMode.UNKNOWN) == "unverified"


def test_runtime_identity_reports_billing_in_the_control_vocabulary():
    assert set(get_args(contracts.BillingMode)) == {str(m) for m in BillingMode}
    # Never inferred: a runtime that reports nothing has no billing mode.
    assert RuntimeIdentity(backend="uhp").billing_mode is None
    with pytest.raises(ValidationError):
        RuntimeIdentity(backend="uhp", billing_mode="subscription")
