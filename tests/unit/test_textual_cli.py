from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from aincrad.cli import (
    _AI_CHOICE,
    _MOVE_CHOICE,
    _available_intents,
    _default_replay,
    _default_run,
    _prompt_for_intent_textual,
    _run_home_textual,
    _starting_world,
)
from aincrad.domain import ActionIntent, ActionKind, CharacterClass
from aincrad.domain.identity import (
    CharacterIdentityProfile,
    CoreValue,
    InquiryStance,
    RelationshipStance,
    RiskAttitude,
)
from aincrad.history import HistoryArchive
from aincrad.persistence import EventLog
from aincrad.storytelling import TurnStoryRequest, TurnStoryResult
from aincrad.tui.textual_app import MenuOption


@pytest.fixture(autouse=True)
def _offline_story_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AINCRAD_STORY_MODE", "local")


class FakeInteraction:
    def __init__(self, *answers: object, name: str = "유리별") -> None:
        self.answers = iter(answers)
        self.name = name
        self.menus: list[tuple[str, tuple[MenuOption[Any], ...]]] = []
        self.text_screens: list[tuple[str, tuple[str, ...]]] = []
        self.story_screens: list[tuple[str, tuple[str, ...]]] = []
        self.timeline: list[str] = []

    def choose(
        self,
        title: str,
        options: Sequence[MenuOption[Any]],
        *,
        subtitle: str = "",
        context: Sequence[str] = (),
        allow_back: bool = False,
    ) -> object | None:
        self.timeline.append(title)
        self.menus.append((title, tuple(options)))
        return next(self.answers)

    def input_text(
        self,
        title: str,
        *,
        subtitle: str,
        validate: Callable[[str], str],
    ) -> str | None:
        return validate(self.name)

    def show_text(self, title: str, body_lines: Sequence[str]) -> None:
        self.timeline.append(title)
        self.text_screens.append((title, tuple(body_lines)))

    def show_story(self, title: str, body_lines: Sequence[str]) -> None:
        self.timeline.append(title)
        self.story_screens.append((title, tuple(body_lines)))


_IDENTITY_ANSWERS = (
    InquiryStance.CURIOUS,
    RiskAttitude.BALANCED,
    CoreValue.GROWTH,
    RelationshipStance.COOPERATIVE,
)


def test_textual_home_uses_widget_menu_without_plain_output(tmp_path: Path) -> None:
    interaction = FakeInteraction("exit")
    output = StringIO()

    result = _run_home_textual(
        runner=None,
        stdin=StringIO(),
        stdout=output,
        history_root=tmp_path / "history",
        interaction=interaction,
    )

    assert result == 0
    assert output.getvalue() == ""
    assert interaction.menus[0][0] == "메인 메뉴"
    assert [option.label for option in interaction.menus[0][1]] == [
        "새 모험",
        "스토리 AI",
        "히스토리",
        "종료",
    ]


def test_textual_home_can_select_authenticated_kimi_storyteller(tmp_path: Path) -> None:
    interaction = FakeInteraction("commentator", "kimi", "exit")

    assert _run_home_textual(
        runner=None,
        stdin=StringIO(),
        stdout=StringIO(),
        history_root=tmp_path / "history",
        interaction=interaction,  # type: ignore[arg-type]
    ) == 0

    assert [title for title, _ in interaction.menus] == [
        "메인 메뉴",
        "스토리 AI 설정",
        "메인 메뉴",
    ]
    assert [option.label for option in interaction.menus[1][1]] == [
        "Kimi ultrafast",
        "로컬 스토리",
        "뒤로",
    ]


def test_default_run_routes_character_name_and_action_through_textual_widgets() -> None:
    world = _starting_world(CharacterClass.WARRIOR, "유리별")
    observe = next(
        intent
        for intent in _available_intents(world, "hero")
        if intent.action is ActionKind.OBSERVE
    )
    interaction = FakeInteraction(CharacterClass.WARRIOR, *_IDENTITY_ANSWERS, observe)
    output = StringIO()

    result = _default_run(
        seed=42,
        hours=1,
        headless=False,
        output=None,
        force=False,
        stdin=StringIO(),
        stdout=output,
        interaction=interaction,
    )

    assert any(adventurer.name == "유리별" for adventurer in result.adventurers)
    assert output.getvalue() == ""
    assert [title for title, _ in interaction.menus] == [
        "직업 선택",
        "탐구 성향",
        "위험 태도",
        "핵심 가치",
        "관계 성향",
        "유리별의 행동",
    ]
    assert interaction.menus[-1][1][-1].label == "AI 판단에 맡기기"


def test_textual_onboarding_asks_four_human_identity_questions(tmp_path: Path) -> None:
    world = _starting_world(CharacterClass.WARRIOR, "유리별")
    observe = next(
        intent
        for intent in _available_intents(world, "hero")
        if intent.action is ActionKind.OBSERVE
    )
    interaction = FakeInteraction(
        CharacterClass.WARRIOR,
        InquiryStance.ANALYTICAL,
        RiskAttitude.CAREFUL,
        CoreValue.HARMONY,
        RelationshipStance.COOPERATIVE,
        observe,
    )

    _default_run(
        seed=42,
        hours=1,
        headless=False,
        output=tmp_path / "events.jsonl",
        force=False,
        history_root=tmp_path / "history",
        stdin=StringIO(),
        stdout=StringIO(),
        interaction=interaction,
    )

    assert [title for title, _ in interaction.menus] == [
        "직업 선택",
        "탐구 성향",
        "위험 태도",
        "핵심 가치",
        "관계 성향",
        "유리별의 행동",
    ]
    identity = HistoryArchive(tmp_path / "history").load_run(1).metadata["identity"]
    assert identity["inquiry_stance"] == "analytical"
    assert identity["risk_attitude"] == "careful"
    assert identity["core_value"] == "harmony"
    assert identity["relationship_stance"] == "cooperative"


def test_textual_movement_is_three_explained_destinations_plus_other() -> None:
    world = _starting_world(CharacterClass.WARRIOR, "유리별")
    outside_move = next(
        intent
        for intent in _available_intents(world, "hero")
        if intent.target_location_id == "mossreach"
    )
    interaction = FakeInteraction(_MOVE_CHOICE, outside_move)

    selected = _prompt_for_intent_textual(
        world,
        "hero",
        interaction=interaction,  # type: ignore[arg-type]
    )

    assert selected.intent == outside_move
    assert [title for title, _ in interaction.menus] == ["유리별의 행동", "이동할 곳"]
    movement_options = interaction.menus[1][1]
    assert len(movement_options) == 2
    assert movement_options[-1].label == "기타 목적지"
    assert all("물리적:" in option.description for option in movement_options[:-1])
    assert all("사회적:" in option.description for option in movement_options[:-1])


def test_emberfall_action_menu_exposes_town_facilities_instead_of_one_generic_move() -> None:
    world = _starting_world(CharacterClass.WARRIOR, "유리별")
    shop = next(
        intent
        for intent in _available_intents(world, "hero")
        if intent.target_location_id == "emberfall-shop"
    )
    interaction = FakeInteraction(shop)

    selected = _prompt_for_intent_textual(
        world,
        "hero",
        interaction=interaction,  # type: ignore[arg-type]
    )

    assert selected.intent == shop
    labels = [option.label for option in interaction.menus[0][1]]
    assert labels[:6] == [
        "상점 · 잿불창고 교역소",
        "여관 · 고요한 심지 여관",
        "의뢰소 · 길잡이 회관",
        "광장 · 빛결 광장",
        "주점 · 구리 혜성 주점",
        "마을 밖으로 이동",
    ]
    assert "이동하기" not in labels
    assert "온천 관찰" in labels


@pytest.mark.parametrize(
    ("location_id", "expected_local_labels"),
    (
        ("emberfall", ("온천 관찰",)),
        ("emberfall-shop", ("보급품 구입", "잔해 판매")),
        ("emberfall-inn", ("숙박", "물품 보관 문의")),
        ("emberfall-quest-hall", ("의뢰 목록 확인",)),
        ("emberfall-plaza", ("공지 읽기", "길 안내 요청")),
        ("emberfall-tavern", ("식사 구매", "검증된 소문 듣기")),
        ("mossreach", ("사냥", "채집", "정찰", "야영")),
        ("vault-1", ("정찰", "수색", "전투")),
        ("vault-10", ("정찰", "수색", "보스 도전")),
    ),
)
def test_textual_action_menu_uses_each_locations_contextual_catalog(
    location_id: str,
    expected_local_labels: tuple[str, ...],
) -> None:
    world = _starting_world(CharacterClass.WARRIOR, "유리별")
    hero = replace(world.adventurers["hero"], location_id=location_id)
    world = replace(world, adventurers={**world.adventurers, hero.id: hero})
    local_intents = tuple(
        intent
        for intent in _available_intents(world, hero.id)
        if intent.action is not ActionKind.MOVE
    )
    interaction = FakeInteraction(local_intents[0])

    selected = _prompt_for_intent_textual(
        world,
        hero.id,
        interaction=interaction,  # type: ignore[arg-type]
    )

    assert selected.intent == local_intents[0]
    action_options = interaction.menus[0][1]
    labels = tuple(option.label for option in action_options)
    assert all(label in labels for label in expected_local_labels)
    assert all(
        option.description for option in action_options if option.label in expected_local_labels
    )


def test_identity_changes_commentary_but_not_recommended_destinations() -> None:
    world = _starting_world(CharacterClass.WARRIOR, "유리별")
    first_move = next(
        intent
        for intent in _available_intents(world, "hero")
        if intent.action is ActionKind.MOVE
    )
    careful = CharacterIdentityProfile(
        inquiry_stance=InquiryStance.ANALYTICAL,
        risk_attitude=RiskAttitude.CAREFUL,
        core_value=CoreValue.HARMONY,
        relationship_stance=RelationshipStance.COOPERATIVE,
    )
    bold = CharacterIdentityProfile(
        inquiry_stance=InquiryStance.CURIOUS,
        risk_attitude=RiskAttitude.BOLD,
        core_value=CoreValue.FREEDOM,
        relationship_stance=RelationshipStance.INDEPENDENT,
    )
    careful_interaction = FakeInteraction(_MOVE_CHOICE, first_move)
    bold_interaction = FakeInteraction(_MOVE_CHOICE, first_move)

    _prompt_for_intent_textual(
        world,
        "hero",
        interaction=careful_interaction,  # type: ignore[arg-type]
        identity_profile=careful,
    )
    _prompt_for_intent_textual(
        world,
        "hero",
        interaction=bold_interaction,  # type: ignore[arg-type]
        identity_profile=bold,
    )

    careful_options = careful_interaction.menus[1][1][:3]
    bold_options = bold_interaction.menus[1][1][:3]
    assert [option.value for option in careful_options] == [
        option.value for option in bold_options
    ]
    assert [option.description for option in careful_options] != [
        option.description for option in bold_options
    ]


def test_cancel_before_first_action_does_not_create_phantom_history(tmp_path: Path) -> None:
    interaction = FakeInteraction(CharacterClass.WARRIOR, *_IDENTITY_ANSWERS, None)
    history_root = tmp_path / "history"

    with pytest.raises(EOFError, match="행동 선택"):
        _default_run(
            seed=42,
            hours=1,
            headless=False,
            output=tmp_path / "events.jsonl",
            force=False,
            history_root=history_root,
            stdin=StringIO(),
            stdout=StringIO(),
            interaction=interaction,
        )

    assert HistoryArchive(history_root).list_runs() == ()


def test_textual_home_shows_resolved_turn_story_before_continue_choice(tmp_path: Path) -> None:
    world = _starting_world(CharacterClass.WARRIOR, "유리별")
    observe = next(
        intent
        for intent in _available_intents(world, "hero")
        if intent.action is ActionKind.OBSERVE
    )
    interaction = FakeInteraction(
        "start",
        CharacterClass.WARRIOR,
        *_IDENTITY_ANSWERS,
        observe,
        False,
        "exit",
    )

    assert _run_home_textual(
        runner=None,
        stdin=StringIO(),
        stdout=StringIO(),
        history_root=tmp_path / "history",
        interaction=interaction,
    ) == 0

    story_index = next(
        index for index, title in enumerate(interaction.timeline) if title.endswith("시간의 이야기")
    )
    continue_index = interaction.timeline.index("여정 계속")
    assert story_index < continue_index
    assert interaction.text_screens == []
    title, lines = interaction.story_screens[0]
    rendered = "\n".join(lines)
    assert title == "1일차 00:00 · 잿불마을 · 한 시간의 이야기"
    assert lines[0] != "1일차 00:00 · 잿불마을"
    assert "유리별은 잿불마을에서 ‘온천 관찰’ 행동을 마쳤다" in rendered
    assert "경험치" not in rendered
    assert "HP 24/24" in rendered


def test_textual_home_projects_free_ai_story_after_resolution_without_persisting_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _starting_world(CharacterClass.WARRIOR, "유리별")
    local_action = next(
        intent
        for intent in _available_intents(world, "hero")
        if intent.action is not ActionKind.MOVE
    )
    interaction = FakeInteraction(
        "start",
        CharacterClass.WARRIOR,
        *_IDENTITY_ANSWERS,
        local_action,
        False,
        "exit",
    )
    requests: list[TurnStoryRequest] = []
    ai_prose = "등불빛 아래서 유리별의 선택은 한 장면으로 길게 피어났다."

    def storyteller(request: TurnStoryRequest) -> TurnStoryResult:
        requests.append(request)
        return TurnStoryResult(ai_prose, "test")

    class FakeAdapter:
        story = staticmethod(storyteller)

    monkeypatch.setattr("aincrad.cli.HermesKimiTurnStoryAdapter", FakeAdapter)
    monkeypatch.delenv("AINCRAD_STORY_MODE")

    assert _run_home_textual(
        runner=None,
        stdin=StringIO(),
        stdout=StringIO(),
        history_root=tmp_path / "history",
        interaction=interaction,  # type: ignore[arg-type]
    ) == 0

    assert len(requests) == 1
    request = requests[0]
    assert request.selected_actions[0].outcome_ko
    assert all(request.selected_actions[0].details_ko)
    assert tuple(label.partition(":")[0] for label in request.identity_labels_ko) == (
        "탐구 성향",
        "위험 태도",
        "핵심 가치",
        "관계 성향",
    )
    story_index = next(
        index for index, (_, lines) in enumerate(interaction.story_screens) if ai_prose in lines
    )
    continue_index = interaction.timeline.index("여정 계속")
    assert interaction.timeline.index(interaction.story_screens[story_index][0]) < continue_index
    persisted = "".join(
        path.read_text(encoding="utf-8")
        for root in (tmp_path / "playthroughs", tmp_path / "history")
        if root.exists()
        for path in root.rglob("*")
        if path.is_file()
    )
    assert ai_prose not in persisted
    event_logs = list((tmp_path / "playthroughs").glob("*.jsonl"))
    assert len(event_logs) == 1
    replayed = _default_replay(event_log=event_logs[0], verify_hash=True)
    assert replayed.summary.status == "해시 검증 완료"
    records = EventLog(event_logs[0]).verify()
    assert records[0].event["rules_version"] == 2
    assert records[1].event["action_events"][0]["action"] == ActionKind.OBSERVE.value


def test_textual_ai_delegation_names_the_action_it_actually_resolved(tmp_path: Path) -> None:
    interaction = FakeInteraction(
        "start",
        CharacterClass.WARRIOR,
        *_IDENTITY_ANSWERS,
        _AI_CHOICE,
        False,
        "exit",
    )

    assert _run_home_textual(
        runner=None,
        stdin=StringIO(),
        stdout=StringIO(),
        history_root=tmp_path / "history",
        interaction=interaction,
    ) == 0

    rendered = "\n".join(interaction.story_screens[0][1])
    assert "주변 상황을 살핀 유리별은 길을 골라 고요한 심지 여관으로 향했다" in rendered
    assert "경험치" not in rendered
    assert "AI가 활동" not in rendered


def test_textual_fatal_hour_shows_story_without_continue_menu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_starting_world = _starting_world

    def fragile_world(character_class: CharacterClass, hero_name: str | None = None):
        world = original_starting_world(character_class, hero_name)
        hero = world.adventurers["hero"]
        fragile = replace(hero, location_id="mossreach", stats=replace(hero.stats, hp=1))
        return replace(world, adventurers={**world.adventurers, fragile.id: fragile})

    monkeypatch.setattr("aincrad.cli._starting_world", fragile_world)
    interaction = FakeInteraction(
        "start",
        CharacterClass.MAGE,
        *_IDENTITY_ANSWERS,
        ActionIntent("hero", ActionKind.MOVE, target_location_id="vault-1"),
        "exit",
        name="유리별",
    )

    assert _run_home_textual(
        runner=None,
        stdin=StringIO(),
        stdout=StringIO(),
        history_root=tmp_path / "history",
        interaction=interaction,  # type: ignore[arg-type]
    ) == 0

    rendered = "\n".join(interaction.story_screens[0][1])
    assert "유리별의 HP는 0이 되었고, 이 여정은 끝났다" in rendered
    assert interaction.timeline.count("1일차 00:00 · 메아리 회랑 · 한 시간의 이야기") == 1
    assert "여정 계속" not in interaction.timeline
