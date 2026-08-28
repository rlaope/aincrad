from __future__ import annotations

from collections.abc import Mapping, Sequence

from aincrad.content import contextual_action_for_intent
from aincrad.domain import (
    ActionIntent,
    ActionKind,
    ActionRejected,
    ActionSucceeded,
    DomainEvent,
    WorldState,
)
from aincrad.domain.display import safe_terminal_text

from .localization import location_direction_ko, location_name_ko

NO_STORY_EVENT_TEXT = (
    "그 한 시간 동안 새로운 의뢰나 동료의 합류 같은 사건은 일어나지 않았다."
)

_REJECTION_TEXT = {
    "unknown_adventurer": "그 모험가를 찾을 수 없었기 때문에",
    "adventurer_dead": "이미 쓰러져 움직일 수 없었기 때문에",
    "unknown_location": "목적지를 확인할 수 없었기 때문에",
    "location_not_connected": "이어지는 길이 없었기 때문에",
    "gather_not_allowed": "이곳에서는 채집할 수 없었기 때문에",
    "invalid_gather_yield": "채집 결과가 잘못되었기 때문에",
    "trade_not_allowed": "이곳에서는 거래할 수 없었기 때문에",
    "invalid_quantity": "거래 수량이 올바르지 않았기 때문에",
    "insufficient_resources": "팔 자원이 부족했기 때문에",
    "insufficient_gold": "필요한 금화가 부족했기 때문에",
    "completed_contract_not_representable": "완료한 의뢰가 기록되어 있지 않았기 때문에",
    "action_not_available_at_location": "이 장소에서 할 수 있는 행동이 아니었기 때문에",
    "invalid_action": "세계의 규칙에 맞지 않는 행동이었기 때문에",
}

_ACTION_TEXT = {
    ActionKind.MOVE: "이동",
    ActionKind.REST: "휴식",
    ActionKind.GATHER: "채집",
    ActionKind.TRADE: "거래",
    ActionKind.WAIT: "대기",
}

_NUMERIC_DETAIL_KEYS = (
    "resources_gathered",
    "resources_sold",
    "damage",
    "hp_restored",
    "mp_restored",
    "mp_spent",
    "xp_awarded",
    "level",
    "exp",
    "hp",
    "mp",
)


def event_detail_map(event: ActionSucceeded) -> dict[str, str]:
    details = dict(event.details)
    if len(details) != len(event.details):
        raise ValueError("event details must not contain duplicate keys")
    for key in _NUMERIC_DETAIL_KEYS:
        if key in details:
            detail_non_negative_int(details, key)
    return details


def detail_non_negative_int(details: Mapping[str, str], key: str) -> int:
    value = details.get(key, "0")
    if not value.isdecimal() or len(value) > 7 or int(value) > 1_000_000:
        raise ValueError(f"event detail {key} must be a non-negative decimal integer")
    return int(value)


def _topic_particle(text: str) -> str:
    final = text[-1]
    if "가" <= final <= "힣":
        return "은" if (ord(final) - ord("가")) % 28 else "는"
    return "은"


def _action_sentence(
    world: WorldState,
    actor_name: str,
    location_id: str,
    event: DomainEvent,
    *,
    delegated: bool,
) -> str:
    subject = f"{actor_name}{_topic_particle(actor_name)}"
    lead = f"주변 상황을 살핀 {subject}" if delegated else subject
    location = location_name_ko(location_id)
    contextual = contextual_action_for_intent(
        world,
        ActionIntent(
            event.adventurer_id,
            event.action,
            target_location_id=event.target_location_id,
            quantity=event.quantity,
        ),
    )
    if isinstance(event, ActionRejected):
        reason = _REJECTION_TEXT.get(event.reason, "그 행동을 실행할 수 없었기 때문에")
        action = (
            contextual.label_ko
            if contextual is not None
            else _ACTION_TEXT.get(event.action, "행동")
            if isinstance(event.action, ActionKind)
            else "행동"
        )
        return f"{lead} {action}에 나서려 했지만, {reason} 뜻을 이루지 못했다."
    if not isinstance(event, ActionSucceeded):
        return f"{lead} {location}에서 한 시간을 보냈다."

    action = event.action
    details = event_detail_map(event)
    if action is ActionKind.MOVE:
        destination_id = event.target_location_id or location_id
        return f"{lead} 길을 골라 {location_direction_ko(destination_id)} 향했다."
    if action is ActionKind.REST:
        return f"{lead} {location}의 안전한 자리를 찾아 숨을 고르고 장비를 정돈했다."
    if action is ActionKind.GATHER:
        gathered = details.get("resources_gathered", "0")
        return f"{lead} {location}을 샅샅이 살펴 쓸 만한 자원 {gathered}개를 모았다."
    if action is ActionKind.TRADE:
        sold = details.get("resources_sold", str(event.quantity))
        return f"{lead} {location}의 상인과 흥정해 모아 둔 자원 {sold}개를 팔았다."
    if contextual is not None:
        return f"{lead} {location}에서 ‘{contextual.label_ko}’ 행동을 마쳤다."
    return f"{lead} {location}에 남아 서두르지 않고 주변의 움직임을 지켜보며 대기했다."


def _result_sentence(world: WorldState, event: DomainEvent) -> str:
    if isinstance(event, ActionRejected):
        return "시간은 흘렀지만 상태는 달라지지 않았다."
    if not isinstance(event, ActionSucceeded):
        return "세계의 판정은 끝났지만 기록할 상태 변화는 없었다."

    actor = world.adventurers[event.adventurer_id]
    details = event_detail_map(event)
    changes: list[str] = []
    damage = detail_non_negative_int(details, "damage")
    if damage:
        damage_context = (
            "이동 도중 위험을 헤치며"
            if event.action is ActionKind.MOVE
            else "교전 중 적의 공격을 받아"
            if event.action in {ActionKind.FIGHT, ActionKind.CHALLENGE}
            else "위험을 헤치며"
        )
        changes.append(f"{damage_context} {damage}의 피해를 입었다")
    hp_restored = detail_non_negative_int(details, "hp_restored")
    mp_restored = detail_non_negative_int(details, "mp_restored")
    if hp_restored or mp_restored:
        changes.append(f"HP {hp_restored}, MP {mp_restored}를 회복했다")
    mp_spent = detail_non_negative_int(details, "mp_spent")
    if mp_spent:
        changes.append(f"집중력을 쓰느라 MP {mp_spent}를 소모했다")
    xp = detail_non_negative_int(details, "xp_awarded")
    if xp:
        changes.append(f"경험치가 {xp}만큼 늘었다")
    if not changes:
        changes.append("별다른 손실 없이 한 시간을 마쳤다")
    joined = ", ".join(changes)
    condition = (
        f"HP {actor.stats.hp}/{actor.stats.max_hp}, "
        f"MP {actor.stats.mp}/{actor.stats.max_mp}, 레벨 {actor.level}"
    )
    if not actor.alive:
        party = world.party
        if party is not None and actor.id == party.selected_hero_id:
            return f"그 결과 {joined}. {actor.name}의 HP는 0이 되었고, 이 여정은 끝났다."
        subject = f"{actor.name}{_topic_particle(actor.name)}"
        return f"그 결과 {joined}. {subject} 영원히 쓰러졌지만, 남은 이들의 여정은 계속된다."
    return f"그 결과 {joined}. 시간이 끝났을 때 {actor.name}의 현재 상태는 {condition}이다."


def render_turn_story(
    world: WorldState,
    events: Sequence[DomainEvent],
    *,
    controllers: Mapping[str, str],
    story_event_text: str | None,
) -> tuple[str, ...]:
    """Project one already-resolved deterministic hour as Korean narrative prose."""

    if not events:
        raise ValueError("turn narrative requires at least one resolved action event")
    tick = events[0].tick
    if any(event.tick != tick for event in events):
        raise ValueError("turn narrative events must belong to one tick")
    first_actor = world.adventurers[events[0].adventurer_id]
    day, hour = divmod(tick, 24)
    lines = [
        f"{day + 1}일차 {hour:02d}:00 · {location_name_ko(first_actor.location_id)}",
        "",
    ]
    for event in events:
        actor = world.adventurers[event.adventurer_id]
        lines.extend(
            (
                _action_sentence(
                    world,
                    safe_terminal_text(actor.name),
                    actor.location_id,
                    event,
                    delegated=controllers.get(event.adventurer_id) == "baseline_policy",
                ),
                _result_sentence(world, event),
                "",
            )
        )
    if story_event_text is None:
        lines.append(
            f"{NO_STORY_EVENT_TEXT} 세계는 다음 선택을 기다리며 조용히 숨을 골랐다."
        )
    else:
        lines.append(safe_terminal_text(story_event_text))
    return tuple(lines)
