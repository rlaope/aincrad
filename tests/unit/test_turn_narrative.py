from __future__ import annotations

from dataclasses import replace

import pytest

from aincrad.cli import _run_hours, _starting_world
from aincrad.domain import (
    ActionIntent,
    ActionKind,
    ActionRejected,
    ActionSucceeded,
    Activity,
    CharacterClass,
)
from aincrad.domain.identity import HERO_ID
from aincrad.tui.narrative import render_turn_story


def test_turn_story_explains_the_delegated_action_and_concrete_result() -> None:
    result = _run_hours(
        _starting_world(CharacterClass.WARRIOR, "테스트용사"),
        seed=7,
        hours=1,
        chooser=lambda _world, actor_id: ActionIntent(actor_id, ActionKind.WAIT),
        direct_hero_only=True,
    )
    trace = result.traces[-1]

    story = render_turn_story(
        result.final_state,
        trace.action_events,
        controllers={HERO_ID: "baseline_policy"},
        story_event_text=None,
    )
    rendered = "\n".join(story)

    assert story[0] == "1일차 00:00 · 잿불마을"
    assert "주변 상황을 살핀 테스트용사는 잿불마을에 남아" in rendered
    assert "대기" in rendered
    assert "경험치" in rendered
    assert "HP 24/24" in rendered
    assert "MP 8/8" in rendered
    assert "새로운 의뢰나 동료의 합류 같은 사건은 일어나지 않았다" in rendered
    assert "AI가 활동" not in rendered
    assert "xp_awarded" not in rendered
    assert "테스트용사은" not in rendered
    assert "경험치 1를" not in rendered
    assert "Lv.1였다" not in rendered


def test_turn_story_narrates_movement_destination_and_hazard_result() -> None:
    result = _run_hours(
        _starting_world(CharacterClass.WARRIOR, "유리별"),
        seed=11,
        hours=2,
        chooser=lambda world, actor_id: ActionIntent(
            actor_id,
            ActionKind.MOVE,
            target_location_id=("mossreach" if world.tick == 0 else "vault-1"),
        ),
        direct_hero_only=True,
    )
    trace = result.traces[-1]

    rendered = "\n".join(
        render_turn_story(
            result.final_state,
            trace.action_events,
            controllers={HERO_ID: "user"},
            story_event_text=None,
        )
    )

    assert "메아리 회랑으로 향했다" in rendered
    assert "위험을 헤치며" in rendered
    assert "피해" in rendered
    assert "HP" in rendered


def test_companion_death_does_not_claim_the_hero_journey_ended() -> None:
    world = _starting_world(CharacterClass.WARRIOR, "유리별")
    hero = world.adventurers[HERO_ID]
    companion = replace(
        hero,
        id="companion",
        name="리아",
        stats=replace(hero.stats, hp=0),
        activity=Activity.IDLE,
        alive=False,
        death_tick=0,
        death_cause="dungeon_hazard",
    )
    assert world.party is not None
    world = replace(
        world,
        adventurers={**world.adventurers, companion.id: companion},
        party=replace(world.party, member_ids=(HERO_ID, companion.id)),
    )
    event = ActionSucceeded(
        tick=0,
        adventurer_id=companion.id,
        action=ActionKind.MOVE,
        next_tick=1,
        target_location_id="vault-1",
        quantity=1,
        details=(("damage", "24"), ("xp_awarded", "1")),
    )

    rendered = "\n".join(
        render_turn_story(
            world,
            (event,),
            controllers={companion.id: "baseline_policy"},
            story_event_text=None,
        )
    )

    assert "리아는 영원히 쓰러졌지만, 남은 이들의 여정은 계속된다" in rendered
    assert "이 여정은 끝났다" not in rendered


@pytest.mark.parametrize(
    ("action", "reason", "expected_action", "expected_reason"),
    [
        (ActionKind.MOVE, "unknown_location", "이동", "목적지를 확인할 수 없었기 때문에"),
        (ActionKind.MOVE, "location_not_connected", "이동", "이어지는 길이 없었기 때문에"),
        (ActionKind.GATHER, "gather_not_allowed", "채집", "채집할 수 없었기 때문에"),
        (ActionKind.GATHER, "invalid_gather_yield", "채집", "채집 결과가 잘못되었기 때문에"),
        (ActionKind.TRADE, "trade_not_allowed", "거래", "거래할 수 없었기 때문에"),
        (ActionKind.TRADE, "invalid_quantity", "거래", "거래 수량이 올바르지 않았기 때문에"),
        (ActionKind.TRADE, "insufficient_resources", "거래", "팔 자원이 부족했기 때문에"),
        (ActionKind.WAIT, "adventurer_dead", "대기", "이미 쓰러져 움직일 수 없었기 때문에"),
    ],
)
def test_rejected_story_names_action_and_exact_engine_reason(
    action: ActionKind,
    reason: str,
    expected_action: str,
    expected_reason: str,
) -> None:
    world = _starting_world(CharacterClass.WARRIOR, "유리별")
    event = ActionRejected(
        tick=0,
        adventurer_id=HERO_ID,
        action=action,
        next_tick=1,
        target_location_id="missing" if action is ActionKind.MOVE else None,
        quantity=0 if reason == "invalid_quantity" else 1,
        reason=reason,
    )

    rendered = "\n".join(
        render_turn_story(
            world,
            (event,),
            controllers={HERO_ID: "baseline_policy"},
            story_event_text=None,
        )
    )

    assert expected_action in rendered
    assert expected_reason in rendered


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
def test_malformed_numeric_detail_fails_with_context(key: str, value: str) -> None:
    world = _starting_world(CharacterClass.WARRIOR, "유리별")
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
        render_turn_story(
            world,
            (event,),
            controllers={HERO_ID: "user"},
            story_event_text=None,
        )


def test_duplicate_numeric_detail_fails_closed() -> None:
    world = _starting_world(CharacterClass.WARRIOR, "유리별")
    event = ActionSucceeded(
        tick=0,
        adventurer_id=HERO_ID,
        action=ActionKind.WAIT,
        next_tick=1,
        target_location_id=None,
        quantity=1,
        details=(("xp_awarded", "1"), ("xp_awarded", "2")),
    )

    with pytest.raises(ValueError, match="duplicate keys"):
        render_turn_story(
            world,
            (event,),
            controllers={HERO_ID: "user"},
            story_event_text=None,
        )


@pytest.mark.parametrize("value", ("0", "1000000"))
def test_numeric_detail_boundaries_are_accepted(value: str) -> None:
    world = _starting_world(CharacterClass.WARRIOR, "유리별")
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

    assert render_turn_story(
        world,
        (event,),
        controllers={HERO_ID: "user"},
        story_event_text=None,
    )
