from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum, nonmember
from typing import TypeAlias

from .models import WorldState

STORY_INTENT_VERSION = 1
_SAFE_TOKEN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
StoryValue: TypeAlias = (
    str
    | int
    | float
    | bool
    | None
    | tuple["StoryValue", ...]
    | tuple[tuple[str, "StoryValue"], ...]
)
StoryFields: TypeAlias = tuple[tuple[str, StoryValue], ...]


class StoryIntentKind(StrEnum):
    """Closed set of story changes understood by version one directors."""

    VERSION = nonmember(STORY_INTENT_VERSION)
    NO_OP = "no_op"
    OFFER_QUEST = "offer_quest"
    COMPLETE_QUEST = "complete_quest"
    RECRUIT_COMPANION = "recruit_companion"
    DEPART_COMPANION = "depart_companion"


class QuestState(StrEnum):
    OFFERED = "offered"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True, init=False)
class StoryState:
    """Canonical story-owned facts, detached from caller-owned mappings."""

    quest_states: tuple[tuple[str, QuestState], ...]
    relationship_scores: tuple[tuple[str, str, int], ...]
    resolved_candidate_ids: tuple[str, ...]
    resolved_template_ids: tuple[str, ...]

    def __init__(
        self,
        *,
        quest_states: Mapping[str, QuestState] | tuple[tuple[str, QuestState], ...] = (),
        relationship_scores: (
            Mapping[tuple[str, str], int] | tuple[tuple[str, str, int], ...]
        ) = (),
        resolved_candidate_ids: Iterable[str] = (),
        resolved_template_ids: Iterable[str] = (),
    ) -> None:
        if isinstance(quest_states, tuple):
            quest_items = list(quest_states)
        else:
            quest_items = list(quest_states.items())
        if isinstance(relationship_scores, tuple):
            relationship_items = list(relationship_scores)
        else:
            relationship_items = [
                (source, target, score) for (source, target), score in relationship_scores.items()
            ]
        frozen_quests = tuple(sorted(quest_items, key=lambda item: item[0]))
        frozen_relationships = tuple(sorted(relationship_items))
        candidate_ids = tuple(resolved_candidate_ids)
        template_ids = tuple(resolved_template_ids)
        for quest_id, state in frozen_quests:
            _require_safe_token(quest_id, "quest_id")
            if not isinstance(state, QuestState):
                raise TypeError("quest state must be QuestState")
        if len({quest_id for quest_id, _ in frozen_quests}) != len(frozen_quests):
            raise ValueError("quest states must have unique quest ids")
        for source_id, target_id, score in frozen_relationships:
            _require_safe_token(source_id, "relationship source_id")
            _require_safe_token(target_id, "relationship target_id")
            if type(score) is not int or not 0 <= score <= 100:
                raise ValueError("relationship score must be an integer from 0 through 100")
        relationship_keys = {(source, target) for source, target, _ in frozen_relationships}
        if len(relationship_keys) != len(frozen_relationships):
            raise ValueError("relationship scores must have unique character pairs")
        if any(_SHA256_HEX.fullmatch(candidate_id) is None for candidate_id in candidate_ids):
            raise ValueError("resolved candidate ids must be canonical lowercase SHA-256 hex")
        for template_id in template_ids:
            _require_safe_token(template_id, "resolved template id")
        if len(set(candidate_ids)) != len(candidate_ids) or len(set(template_ids)) != len(
            template_ids
        ):
            raise ValueError("resolved ids must be unique")
        object.__setattr__(self, "quest_states", frozen_quests)
        object.__setattr__(self, "relationship_scores", frozen_relationships)
        object.__setattr__(self, "resolved_candidate_ids", candidate_ids)
        object.__setattr__(self, "resolved_template_ids", template_ids)

    def quest_state(self, quest_id: str) -> QuestState | None:
        return dict(self.quest_states).get(quest_id)

    def relationship_score(self, source_id: str, target_id: str) -> int | None:
        return next(
            (
                score
                for source, target, score in self.relationship_scores
                if source == source_id and target == target_id
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class StoryResolutionEvent:
    tick: int
    candidate_id: str
    template_id: str | None
    kind: StoryIntentKind
    hero_id: str
    reason_code: str
    quest_id: str | None = None
    companion_id: str | None = None


@dataclass(frozen=True, slots=True)
class StoryResolution:
    world: WorldState
    story: StoryState
    event: StoryResolutionEvent


def _require_safe_token(value: str, field_name: str) -> None:
    if not isinstance(value, str) or _SAFE_TOKEN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a safe canonical token")


def story_candidate_id(
    *,
    kind: StoryIntentKind,
    tick: int,
    hero_id: str,
    reason_code: str,
    quest_id: str | None = None,
    companion_id: str | None = None,
    version: int = STORY_INTENT_VERSION,
) -> str:
    """Return the SHA-256 ID of canonical, explicitly versioned candidate fields."""

    _validate_controls(version=version, kind=kind, tick=tick)
    _require_safe_token(hero_id, "hero_id")
    _require_safe_token(reason_code, "reason_code")
    _validate_kind_fields(kind, quest_id, companion_id)
    payload = {
        "companion_id": companion_id,
        "hero_id": hero_id,
        "kind": kind.value,
        "quest_id": quest_id,
        "reason_code": reason_code,
        "tick": tick,
        "version": version,
    }
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class StoryIntent:
    """A validated proposal; only the trusted rules engine may apply it."""

    version: int
    candidate_id: str
    kind: StoryIntentKind
    tick: int
    hero_id: str
    reason_code: str
    quest_id: str | None = None
    companion_id: str | None = None

    def __post_init__(self) -> None:
        _validate_controls(version=self.version, kind=self.kind, tick=self.tick)
        _require_safe_token(self.hero_id, "hero_id")
        _require_safe_token(self.reason_code, "reason_code")
        _validate_kind_fields(self.kind, self.quest_id, self.companion_id)
        if _SHA256_HEX.fullmatch(self.candidate_id) is None:
            raise ValueError("candidate_id must be canonical lowercase SHA-256 hex")
        expected = story_candidate_id(
            version=self.version,
            kind=self.kind,
            tick=self.tick,
            hero_id=self.hero_id,
            reason_code=self.reason_code,
            quest_id=self.quest_id,
            companion_id=self.companion_id,
        )
        if self.candidate_id != expected:
            raise ValueError("candidate_id does not match the canonical intent fields")


@dataclass(frozen=True, slots=True)
class StoryCharacterView:
    character_id: str
    fields: StoryFields = ()

    def __post_init__(self) -> None:
        _require_safe_token(self.character_id, "character_id")
        _validate_fields(self.fields)


@dataclass(frozen=True, slots=True)
class StoryQuestView:
    quest_id: str
    fields: StoryFields = ()

    def __post_init__(self) -> None:
        _require_safe_token(self.quest_id, "quest_id")
        _validate_fields(self.fields)


@dataclass(frozen=True, slots=True)
class StoryRelationshipView:
    source_id: str
    target_id: str
    fields: StoryFields = ()

    def __post_init__(self) -> None:
        _require_safe_token(self.source_id, "source_id")
        _require_safe_token(self.target_id, "target_id")
        _validate_fields(self.fields)


@dataclass(frozen=True, slots=True)
class StoryRecentEventView:
    event_id: str
    tick: int
    kind: str
    fields: StoryFields = ()

    def __post_init__(self) -> None:
        _require_safe_token(self.event_id, "event_id")
        _require_safe_token(self.kind, "kind")
        if type(self.tick) is not int or self.tick < 0:
            raise ValueError("event tick must be a non-negative integer")
        _validate_fields(self.fields)


@dataclass(frozen=True, slots=True)
class StoryPerception:
    """Detached story-only observations. It contains no world-state reference."""

    version: int
    tick: int
    hero_id: str
    characters: tuple[StoryCharacterView, ...] = ()
    quests: tuple[StoryQuestView, ...] = ()
    relationships: tuple[StoryRelationshipView, ...] = ()
    recent_events: tuple[StoryRecentEventView, ...] = ()

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != STORY_INTENT_VERSION:
            raise ValueError(f"version must be {STORY_INTENT_VERSION}")
        if type(self.tick) is not int or self.tick < 0:
            raise ValueError("tick must be a non-negative integer")
        _require_safe_token(self.hero_id, "hero_id")
        collections = (
            self.characters,
            self.quests,
            self.relationships,
            self.recent_events,
        )
        if any(type(items) is not tuple for items in collections):
            raise TypeError("story perception collections must be tuples")


def build_story_perception(
    *,
    version: int,
    tick: int,
    hero_id: str,
    characters: Iterable[Mapping[str, object]] = (),
    quests: Iterable[Mapping[str, object]] = (),
    relationships: Iterable[Mapping[str, object]] = (),
    recent_events: Iterable[Mapping[str, object]] = (),
) -> StoryPerception:
    """Copy JSON-like source mappings into tuple-only story views."""

    return StoryPerception(
        version=version,
        tick=tick,
        hero_id=hero_id,
        characters=tuple(
            StoryCharacterView(_mapping_token(item, "id"), _mapping_fields(item, {"id"}))
            for item in characters
        ),
        quests=tuple(
            StoryQuestView(_mapping_token(item, "id"), _mapping_fields(item, {"id"}))
            for item in quests
        ),
        relationships=tuple(
            StoryRelationshipView(
                _mapping_token(item, "source_id"),
                _mapping_token(item, "target_id"),
                _mapping_fields(item, {"source_id", "target_id"}),
            )
            for item in relationships
        ),
        recent_events=tuple(
            StoryRecentEventView(
                _mapping_token(item, "id"),
                _mapping_int(item, "tick"),
                _mapping_token(item, "kind"),
                _mapping_fields(item, {"id", "tick", "kind"}),
            )
            for item in recent_events
        ),
    )


def _freeze_story_value(value: object) -> StoryValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _freeze_story_value(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_story_value(item) for item in value)
    raise TypeError(f"story observations must be JSON-compatible, got {type(value).__name__}")


def _mapping_fields(item: Mapping[str, object], excluded: set[str]) -> StoryFields:
    return tuple(
        sorted(
            (str(key), _freeze_story_value(value))
            for key, value in item.items()
            if key not in excluded
        )
    )


def _mapping_token(item: Mapping[str, object], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    _require_safe_token(value, key)
    return value


def _mapping_int(item: Mapping[str, object], key: str) -> int:
    value = item.get(key)
    if type(value) is not int:
        raise TypeError(f"{key} must be an integer")
    return value


def _validate_fields(fields: StoryFields) -> None:
    if type(fields) is not tuple:
        raise TypeError("story view fields must be tuples")
    if tuple(sorted(fields, key=lambda item: item[0])) != fields:
        raise ValueError("story view fields must be canonically sorted")
    for key, value in fields:
        _require_safe_token(key, "field name")
        _validate_story_value(value)


def _validate_story_value(value: StoryValue) -> None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return
    if type(value) is not tuple:
        raise TypeError("story values must use tuples only")
    for item in value:
        if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str):
            _validate_story_value(item[1])
        else:
            _validate_story_value(item)


def _validate_controls(*, version: int, kind: StoryIntentKind, tick: int) -> None:
    if type(version) is not int or version != STORY_INTENT_VERSION:
        raise ValueError(f"version must be {STORY_INTENT_VERSION}")
    if not isinstance(kind, StoryIntentKind):
        raise TypeError("kind must be StoryIntentKind")
    if type(tick) is not int or tick < 0:
        raise ValueError("tick must be a non-negative integer")


def _validate_kind_fields(
    kind: StoryIntentKind, quest_id: str | None, companion_id: str | None
) -> None:
    requires_quest = kind in {StoryIntentKind.OFFER_QUEST, StoryIntentKind.COMPLETE_QUEST}
    requires_companion = kind in {
        StoryIntentKind.RECRUIT_COMPANION,
        StoryIntentKind.DEPART_COMPANION,
    }
    if (quest_id is not None) != requires_quest:
        qualifier = "requires" if requires_quest else "forbids"
        raise ValueError(f"{kind.value} {qualifier} quest_id")
    if (companion_id is not None) != requires_companion:
        qualifier = "requires" if requires_companion else "forbids"
        raise ValueError(f"{kind.value} {qualifier} companion_id")
    if quest_id is not None:
        _require_safe_token(quest_id, "quest_id")
    if companion_id is not None:
        _require_safe_token(companion_id, "companion_id")
