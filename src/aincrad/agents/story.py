from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar, Protocol, runtime_checkable

from aincrad.domain.story import StoryIntent, StoryIntentKind, StoryPerception


@runtime_checkable
class StoryDirector(Protocol):
    """Select one supplied story proposal without executing it."""

    def choose(
        self, perception: StoryPerception, candidates: Sequence[StoryIntent]
    ) -> StoryIntent: ...


class NoAllowedStoryIntent(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class BaselineStoryDirector:
    """Stateless deterministic baseline over a trusted candidate set."""

    kind_priority: ClassVar[tuple[StoryIntentKind, ...]] = (
        StoryIntentKind.COMPLETE_QUEST,
        StoryIntentKind.DEPART_COMPANION,
        StoryIntentKind.RECRUIT_COMPANION,
        StoryIntentKind.OFFER_QUEST,
        StoryIntentKind.NO_OP,
    )

    def choose(
        self, perception: StoryPerception, candidates: Sequence[StoryIntent]
    ) -> StoryIntent:
        if not isinstance(perception, StoryPerception):
            raise TypeError("story directors accept only StoryPerception")
        if not candidates:
            raise NoAllowedStoryIntent("the rules engine supplied no story candidates")
        if any(not isinstance(candidate, StoryIntent) for candidate in candidates):
            raise TypeError("every candidate must be a StoryIntent")
        if any(candidate.tick != perception.tick for candidate in candidates):
            raise ValueError("every candidate tick must match the perception tick")
        if any(candidate.hero_id != perception.hero_id for candidate in candidates):
            raise ValueError("every candidate hero must match the perceived hero")

        rank = {kind: index for index, kind in enumerate(self.kind_priority)}
        return min(candidates, key=lambda candidate: (rank[candidate.kind], candidate.candidate_id))
