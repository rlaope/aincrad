from __future__ import annotations

import copy
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TypeGuard, cast


class LifeEventType(StrEnum):
    COMPANION_RECRUITMENT = "companion_recruitment"
    COMPANION_DEPARTURE = "companion_departure"
    PERMANENT_CHARACTER_DEATH = "permanent_character_death"
    QUEST_OFFER = "quest_offer"
    QUEST_COMPLETION = "quest_completion"
    BOSS_ROOM_CLEAR = "boss_room_clear"
    NEXT_FLOOR_TRANSITION = "next_floor_transition"


def _deep_freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_deep_freeze(item) for item in value)
    return copy.deepcopy(value)


@dataclass(frozen=True, slots=True)
class LifeEventTemplate:
    id: str
    event_type: LifeEventType
    triggers: Mapping[str, object]
    display_text_ko: str
    effects: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "triggers", _deep_freeze(self.triggers))
        object.__setattr__(self, "effects", _deep_freeze(self.effects))


class LifeEventCatalogError(ValueError):
    """Raised when life-event template data violates the catalog contract."""


def _has_control(value: str) -> bool:
    return any(unicodedata.category(character).startswith("C") for character in value)


def _validate_id(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or _has_control(value)
    ):
        raise LifeEventCatalogError(f"{field} must be a safe non-empty id")
    return value


def _validate_display_text(value: object, field: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or _has_control(value)
        or not any("가" <= character <= "힣" for character in value)
    ):
        raise LifeEventCatalogError(f"{field} must be non-empty control-free Korean text")


def _require_keys(value: Mapping[str, object], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise LifeEventCatalogError(f"{field} schema requires exactly {sorted(expected)}")


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_template_schema(template: LifeEventTemplate) -> None:
    triggers = template.triggers
    effects = template.effects
    event_type = template.event_type
    schemas = {
        LifeEventType.COMPANION_RECRUITMENT: (
            {"quest_id", "relationship_at_least"},
            {"companion_id", "party_action"},
        ),
        LifeEventType.COMPANION_DEPARTURE: (
            {"companion_id", "relationship_below"},
            {"companion_id", "party_action"},
        ),
        LifeEventType.PERMANENT_CHARACTER_DEATH: (
            {"character_hp_at_most", "permadeath_enabled"},
            {"character_status", "story_state"},
        ),
        LifeEventType.QUEST_OFFER: (
            {"location_id", "quest_available"},
            {"quest_id", "quest_state"},
        ),
        LifeEventType.QUEST_COMPLETION: (
            {"quest_id", "objectives_complete"},
            {"quest_id", "quest_state"},
        ),
        LifeEventType.BOSS_ROOM_CLEAR: (
            {"boss_id", "boss_hp_at_most"},
            {"boss_room_id", "boss_cleared"},
        ),
        LifeEventType.NEXT_FLOOR_TRANSITION: (
            {"boss_clear_event_id"},
            {"transition_id", "next_world_floor"},
        ),
    }
    trigger_keys, effect_keys = schemas[event_type]
    trigger_field = (
        f"event {template.id} boss clear trigger"
        if event_type is LifeEventType.NEXT_FLOOR_TRANSITION
        else f"event {template.id} trigger"
    )
    _require_keys(triggers, trigger_keys, trigger_field)
    _require_keys(effects, effect_keys, f"event {template.id} effect")

    id_fields = {
        "quest_id",
        "companion_id",
        "location_id",
        "boss_id",
        "boss_room_id",
        "boss_clear_event_id",
        "transition_id",
    }
    for field in id_fields & set(triggers):
        _validate_id(triggers[field], f"event {template.id} trigger {field}")
    for field in id_fields & set(effects):
        _validate_id(effects[field], f"event {template.id} effect {field}")

    if event_type is LifeEventType.COMPANION_RECRUITMENT:
        relationship = triggers["relationship_at_least"]
        if not _is_int(relationship) or not 0 <= relationship <= 100:
            raise LifeEventCatalogError("recruitment trigger relationship must be 0 through 100")
        if effects["party_action"] != "add":
            raise LifeEventCatalogError("recruitment effect party_action must be add")
    elif event_type is LifeEventType.COMPANION_DEPARTURE:
        relationship = triggers["relationship_below"]
        if not _is_int(relationship) or not 0 <= relationship <= 100:
            raise LifeEventCatalogError("departure trigger relationship must be 0 through 100")
        if effects["party_action"] != "remove":
            raise LifeEventCatalogError("departure effect party_action must be remove")
    elif event_type is LifeEventType.PERMANENT_CHARACTER_DEATH:
        hp = triggers["character_hp_at_most"]
        if not _is_int(hp) or hp > 0:
            raise LifeEventCatalogError(
                "death trigger character_hp_at_most must be an integer at most 0"
            )
        if triggers["permadeath_enabled"] is not True:
            raise LifeEventCatalogError("death trigger permadeath_enabled must be true")
        if effects != {"character_status": "dead", "story_state": "ended"}:
            raise LifeEventCatalogError("death effect must end the dead character's story")
    elif event_type is LifeEventType.QUEST_OFFER:
        if triggers["quest_available"] is not True or effects["quest_state"] != "offered":
            raise LifeEventCatalogError("quest offer trigger/effect values are invalid")
    elif event_type is LifeEventType.QUEST_COMPLETION:
        if triggers["objectives_complete"] is not True or effects["quest_state"] != "completed":
            raise LifeEventCatalogError("quest completion trigger/effect values are invalid")
    elif event_type is LifeEventType.BOSS_ROOM_CLEAR:
        hp = triggers["boss_hp_at_most"]
        if not _is_int(hp) or hp > 0:
            raise LifeEventCatalogError("boss trigger boss_hp_at_most must be an integer at most 0")
        if effects["boss_cleared"] is not True:
            raise LifeEventCatalogError("boss effect boss_cleared must be true")
    elif event_type is LifeEventType.NEXT_FLOOR_TRANSITION:
        floor = effects["next_world_floor"]
        if not _is_int(floor) or floor <= 1:
            raise LifeEventCatalogError("transition effect next_world_floor must exceed 1")


def _validate_world_references(
    templates: Sequence[LifeEventTemplate], world: Mapping[str, object]
) -> None:
    dungeons = cast(Sequence[Mapping[str, object]], world["dungeons"])
    floors = [
        floor
        for dungeon in dungeons
        for floor in cast(Sequence[Mapping[str, object]], dungeon["floors"])
    ]
    boss_room = next(floor for floor in floors if floor["kind"] == "boss_room")
    completion = cast(Mapping[str, object], boss_room["completion"])
    boss_clear = next(
        template for template in templates if template.event_type is LifeEventType.BOSS_ROOM_CLEAR
    )
    transition = next(
        template
        for template in templates
        if template.event_type is LifeEventType.NEXT_FLOOR_TRANSITION
    )
    if (
        boss_clear.triggers["boss_id"] != completion["boss_id"]
        or boss_clear.effects["boss_room_id"] != boss_room["id"]
        or transition.effects["transition_id"] != completion["transition_id"]
        or transition.effects["next_world_floor"] != completion["next_world_floor"]
    ):
        raise LifeEventCatalogError("boss and transition metadata must match world fixture")


def validate_life_event_catalog(
    templates: Sequence[LifeEventTemplate],
    *,
    world: Mapping[str, object] | None = None,
) -> tuple[LifeEventTemplate, ...]:
    for template in templates:
        _validate_id(template.id, "event id")
        _validate_display_text(template.display_text_ko, f"event {template.id}.display_text_ko")
    ids = [template.id for template in templates]
    if len(ids) != len(set(ids)):
        raise LifeEventCatalogError("duplicate event id")
    boss_clear_ids = {
        template.id
        for template in templates
        if template.event_type is LifeEventType.BOSS_ROOM_CLEAR
    }
    for template in templates:
        if not isinstance(template.event_type, LifeEventType):
            raise LifeEventCatalogError(f"unsupported event type: {template.event_type}")
        if not template.triggers:
            raise LifeEventCatalogError(f"event {template.id} requires triggers")
        if not template.effects:
            raise LifeEventCatalogError(f"event {template.id} requires effects")
        _validate_template_schema(template)
        if (
            template.event_type is LifeEventType.NEXT_FLOOR_TRANSITION
            and template.triggers.get("boss_clear_event_id") not in boss_clear_ids
        ):
            raise LifeEventCatalogError(
                f"next-floor transition {template.id} requires a catalog boss clear"
            )

    offered_quest_ids = {
        template.effects["quest_id"]
        for template in templates
        if template.event_type is LifeEventType.QUEST_OFFER
    }
    completed_quest_ids = {
        template.effects["quest_id"]
        for template in templates
        if template.event_type is LifeEventType.QUEST_COMPLETION
        and template.triggers["quest_id"] == template.effects["quest_id"]
    }
    if offered_quest_ids != completed_quest_ids:
        raise LifeEventCatalogError(
            "quest reference must have coherent offer and completion events"
        )
    for template in templates:
        if (
            template.event_type is LifeEventType.COMPANION_RECRUITMENT
            and template.triggers["quest_id"] not in completed_quest_ids
        ):
            raise LifeEventCatalogError(
                "recruitment quest reference must be a completed catalog quest"
            )

    recruited_companion_ids = {
        template.effects["companion_id"]
        for template in templates
        if template.event_type is LifeEventType.COMPANION_RECRUITMENT
    }
    for template in templates:
        if template.event_type is LifeEventType.COMPANION_DEPARTURE and (
            template.triggers["companion_id"] != template.effects["companion_id"]
            or template.effects["companion_id"] not in recruited_companion_ids
        ):
            raise LifeEventCatalogError("departure companion reference must match a recruitment")
    if world is not None:
        _validate_world_references(templates, world)
    return tuple(templates)


LIFE_EVENT_CATALOG: tuple[LifeEventTemplate, ...] = (
    LifeEventTemplate(
        id="companion-recruit-rhea",
        event_type=LifeEventType.COMPANION_RECRUITMENT,
        triggers={"quest_id": "echoes-at-emberfall", "relationship_at_least": 60},
        display_text_ko="레아가 당신의 동료로 합류했습니다.",
        effects={"companion_id": "rhea-vale", "party_action": "add"},
    ),
    LifeEventTemplate(
        id="companion-depart-rhea",
        event_type=LifeEventType.COMPANION_DEPARTURE,
        triggers={"companion_id": "rhea-vale", "relationship_below": 20},
        display_text_ko="레아가 결별을 선언하고 파티를 떠났습니다.",
        effects={"companion_id": "rhea-vale", "party_action": "remove"},
    ),
    LifeEventTemplate(
        id="story-end-permanent-death",
        event_type=LifeEventType.PERMANENT_CHARACTER_DEATH,
        triggers={"character_hp_at_most": 0, "permadeath_enabled": True},
        display_text_ko="모험가는 영원히 쓰러졌고, 이 이야기는 여기서 끝납니다.",
        effects={"character_status": "dead", "story_state": "ended"},
    ),
    LifeEventTemplate(
        id="quest-offer-echoes-at-emberfall",
        event_type=LifeEventType.QUEST_OFFER,
        triggers={"location_id": "emberfall-quest-hall", "quest_available": True},
        display_text_ko="길드 게시판에 '잿불 마을의 메아리' 의뢰가 나타났습니다.",
        effects={"quest_id": "echoes-at-emberfall", "quest_state": "offered"},
    ),
    LifeEventTemplate(
        id="quest-complete-echoes-at-emberfall",
        event_type=LifeEventType.QUEST_COMPLETION,
        triggers={"quest_id": "echoes-at-emberfall", "objectives_complete": True},
        display_text_ko="'잿불 마을의 메아리' 의뢰를 완료했습니다.",
        effects={"quest_id": "echoes-at-emberfall", "quest_state": "completed"},
    ),
    LifeEventTemplate(
        id="boss-clear-starless-vault",
        event_type=LifeEventType.BOSS_ROOM_CLEAR,
        triggers={"boss_id": "null-cartographer", "boss_hp_at_most": 0},
        display_text_ko="별 없는 금고의 수호자가 쓰러지고 보스 방이 정복되었습니다.",
        effects={"boss_room_id": "vault-10", "boss_cleared": True},
    ),
    LifeEventTemplate(
        id="transition-aurora-lift-floor-2",
        event_type=LifeEventType.NEXT_FLOOR_TRANSITION,
        triggers={"boss_clear_event_id": "boss-clear-starless-vault"},
        display_text_ko="오로라 승강기가 열리며 세계 제2층으로 향하는 길이 이어집니다.",
        effects={"transition_id": "aurora-lift-floor-2", "next_world_floor": 2},
    ),
)
