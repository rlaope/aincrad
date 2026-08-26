from __future__ import annotations

import pytest

from aincrad.agents import (
    ActionIntent,
    BaselinePolicy,
    NoAllowedAction,
    Perception,
    Policy,
)
from aincrad.domain import ActionIntent as DomainActionIntent
from aincrad.domain import ActionKind


def perception() -> Perception:
    return Perception(3, "rhea", "mossreach", (("hp", 10),))


def test_baseline_returns_one_of_the_exact_allowed_intents() -> None:
    allowed = (
        ActionIntent("rhea", "wait"),
        ActionIntent("rhea", "move", target_id="emberfall"),
    )

    chosen = BaselinePolicy().choose(perception(), allowed)

    assert chosen in allowed
    assert chosen == ActionIntent("rhea", "move", target_id="emberfall")


def test_baseline_is_deterministic_even_when_allowed_order_changes() -> None:
    attack_b = ActionIntent("rhea", "attack", target_id="wolf-b")
    attack_a = ActionIntent("rhea", "attack", target_id="wolf-a")
    policy = BaselinePolicy()

    first = policy.choose(perception(), (attack_b, attack_a))
    second = policy.choose(perception(), (attack_a, attack_b))

    assert first == second == attack_a


def test_baseline_rejects_empty_or_foreign_actor_action_lists() -> None:
    policy = BaselinePolicy()
    with pytest.raises(NoAllowedAction):
        policy.choose(perception(), ())
    with pytest.raises(ValueError, match="actor"):
        policy.choose(perception(), (ActionIntent("mira", "wait"),))


def test_policy_is_a_runtime_checkable_protocol() -> None:
    assert isinstance(BaselinePolicy(), Policy)


def test_policy_boundary_accepts_domain_intents_and_returns_the_exact_candidate() -> None:
    wait = DomainActionIntent("rhea", ActionKind.WAIT)
    move = DomainActionIntent("rhea", ActionKind.MOVE, target_location_id="emberfall")

    chosen = BaselinePolicy().choose(perception(), (wait, move))

    assert chosen is move


def test_baseline_sells_collected_resources_before_leaving_town() -> None:
    trade = DomainActionIntent("rhea", ActionKind.TRADE, quantity=3)
    move = DomainActionIntent("rhea", ActionKind.MOVE, target_location_id="mossreach")

    chosen = BaselinePolicy().choose(perception(), (move, trade))

    assert chosen is trade
