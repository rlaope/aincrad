from __future__ import annotations

import pytest

from aincrad.cli import (
    _continue_context,
    _event_view,
    _intent_description,
    _intent_label,
    _run_hours,
    _starting_world,
)
from aincrad.domain import ActionIntent, ActionKind, ActionSucceeded, CharacterClass
from aincrad.domain.identity import HERO_ID
from aincrad.domain.rules import apply_intent
from aincrad.simulation import create_initial_world
from aincrad.tui.localization import location_description_ko, location_name_ko


def test_every_runtime_location_has_a_korean_display_name() -> None:
    world = create_initial_world()

    displayed = {
        location_id: location_name_ko(location_id)
        for location_id in world.locations
    }

    assert displayed == {
        "emberfall": "잿불마을",
        "emberfall-shop": "잿불창고 교역소",
        "emberfall-inn": "고요한 심지 여관",
        "emberfall-quest-hall": "길잡이 회관",
        "emberfall-plaza": "빛결 광장",
        "emberfall-tavern": "구리 혜성 주점",
        "mossreach-terraces": "이끼자락 층계",
        "mossreach": "이끼자락 황야",
        "mossreach-vaultgate": "금고 어귀 절벽",
        "vault-1": "메아리 회랑",
        "vault-2": "물에 잠긴 기록보관소",
        "vault-3": "밤유리 둑길",
        "vault-4": "고요한 저수조",
        "vault-5": "흑단 천구의실",
        "vault-6": "황혼 작업장",
        "vault-7": "잿빛 온실",
        "vault-8": "거꾸로 선 종탑",
        "vault-9": "왕관 없는 대기실",
        "vault-10": "공허 지도제작자의 방",
    }


def test_every_runtime_location_has_public_korean_physical_context() -> None:
    world = create_initial_world()

    descriptions = {
        location_id: location_description_ko(location_id)
        for location_id in world.locations
    }

    assert all(description.endswith(".") for description in descriptions.values())
    assert all(
        any("가" <= char <= "힣" for char in description)
        for description in descriptions.values()
    )
    assert all(
        location_id not in description
        for location_id, description in descriptions.items()
    )
    assert location_description_ko("unknown-place") == "확인된 지형 정보가 없습니다."


def test_action_and_status_projection_use_korean_location_names() -> None:
    world = _starting_world(CharacterClass.WARRIOR, "유리별")
    move = ActionIntent(HERO_ID, ActionKind.MOVE, target_location_id="mossreach-terraces")

    result = _run_hours(
        world,
        seed=7,
        hours=1,
        chooser=lambda _world, actor_id: ActionIntent(actor_id, ActionKind.WAIT),
        direct_hero_only=True,
    )
    context = _continue_context(result.final_state, result.traces[-1], width=80)

    assert _intent_label(move, world) == "이동 → 이끼자락 층계"
    assert _intent_description(move, world).startswith("이끼자락 층계에서")
    assert context[0].startswith("1일차 01:00 · 잿불마을")
    assert not any("Emberfall" in line or "Mossreach" in line for line in context)


def test_headless_event_projection_hides_internal_location_and_detail_keys() -> None:
    world = _starting_world(CharacterClass.WARRIOR, "한별")
    result, events = apply_intent(
        world,
        ActionIntent(
            HERO_ID,
            ActionKind.BROWSE_GOODS,
            target_location_id="emberfall-shop",
        ),
    )

    message = _event_view(events[0], result).message

    assert "한별: 자리를 지키며 주변을 살폈다." in message
    assert "경험치" not in message
    assert "destination=" not in message
    assert "emberfall-shop" not in message
    assert "xp_awarded" not in message


@pytest.mark.parametrize(
    "key",
    (
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
    ),
)
@pytest.mark.parametrize("value", ("not-an-int", "-1", "1000001"))
def test_headless_projection_rejects_every_malformed_numeric_detail(
    key: str,
    value: str,
) -> None:
    world = _starting_world(CharacterClass.WARRIOR, "한별")
    event = ActionSucceeded(
        tick=0,
        adventurer_id=HERO_ID,
        action=ActionKind.WAIT,
        next_tick=1,
        target_location_id=None,
        quantity=1,
        details=((key, value),),
    )

    with pytest.raises(ValueError, match=rf"{key}.*non-negative decimal"):
        _event_view(event, world)


@pytest.mark.parametrize("value", ("0", "1000000"))
def test_headless_projection_accepts_numeric_detail_boundaries(value: str) -> None:
    world = _starting_world(CharacterClass.WARRIOR, "한별")
    numeric_keys = (
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
    event = ActionSucceeded(
        tick=0,
        adventurer_id=HERO_ID,
        action=ActionKind.WAIT,
        next_tick=1,
        target_location_id=None,
        quantity=1,
        details=tuple((key, value) for key in numeric_keys),
    )

    assert _event_view(event, world).message
