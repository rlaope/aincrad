from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, TypeVar, runtime_checkable

from .perception import FrozenFields, Perception

IntentT = TypeVar("IntentT")


@dataclass(frozen=True, slots=True)
class ActionIntent:
    """A proposed action DTO. The world engine remains the sole executor."""

    actor_id: str
    action: str
    target_id: str | None = None
    parameters: FrozenFields = ()

    def __post_init__(self) -> None:
        if not self.actor_id or not self.action:
            raise ValueError("actor_id and action must be non-empty")


@runtime_checkable
class Policy(Protocol):
    """Policies may choose, but cannot execute or mutate world state."""

    def choose(
        self, perception: Perception, allowed_actions: Sequence[IntentT]
    ) -> IntentT: ...


class NoAllowedAction(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class BaselinePolicy:
    """A deterministic, stateless policy suitable for replay baselines."""

    action_priority: tuple[str, ...] = (
        "attack",
        "gather",
        "interact",
        "move",
        "rest",
        "wait",
    )

    def choose(
        self, perception: Perception, allowed_actions: Sequence[IntentT]
    ) -> IntentT:
        if not allowed_actions:
            raise NoAllowedAction("the world supplied no allowed actions")
        if any(_actor_id(intent) != perception.actor_id for intent in allowed_actions):
            raise ValueError("every allowed action must belong to the perceived actor")

        rank = {action: index for index, action in enumerate(self.action_priority)}
        return min(
            allowed_actions,
            key=lambda intent: (
                rank.get(_action_name(intent), len(rank)),
                _action_name(intent),
                _target_id(intent),
                _details_key(intent),
            ),
        )


def _actor_id(intent: Any) -> str:
    actor_id = getattr(intent, "actor_id", None)
    if actor_id is None:
        actor_id = getattr(intent, "adventurer_id", None)
    if not isinstance(actor_id, str):
        raise TypeError("action intent must expose actor_id or adventurer_id")
    return actor_id


def _action_name(intent: Any) -> str:
    action = getattr(intent, "action", None)
    if isinstance(action, Enum):
        action = action.value
    if not isinstance(action, str):
        raise TypeError("action intent must expose a string-like action")
    return action


def _target_id(intent: Any) -> str:
    target = getattr(intent, "target_id", None)
    if target is None:
        target = getattr(intent, "target_location_id", None)
    return target if isinstance(target, str) else ""


def _details_key(intent: Any) -> str:
    if hasattr(intent, "parameters"):
        return repr(intent.parameters)
    return repr(getattr(intent, "quantity", None))
