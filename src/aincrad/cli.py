from __future__ import annotations

import argparse
import hashlib
import inspect
import os
import shutil
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TextIO

from aincrad.agents import (
    BaselinePolicy,
    BaselineStoryDirector,
    Observation,
    Perception,
    StoryDirector,
    perceive,
)
from aincrad.commentary import (
    DestinationCandidate,
    MovementCommentaryRequest,
    MovementCommentaryResult,
    deterministic_commentary,
)
from aincrad.content import (
    available_action_intents,
    contextual_action_for_intent,
    resident_npc_for_location,
)
from aincrad.content.events import LIFE_EVENT_CATALOG
from aincrad.domain import (
    ActionIntent,
    ActionKind,
    ActionRejected,
    ActionSucceeded,
    Adventurer,
    CharacterClass,
    DomainEvent,
    PartyState,
    Stats,
    WorldState,
)
from aincrad.domain.identity import (
    HERO_ID,
    CharacterIdentityError,
    CharacterIdentityProfile,
    HeroNameError,
    validate_hero_name,
)
from aincrad.domain.rules import apply_intent
from aincrad.domain.story import (
    StoryIntent,
    StoryIntentKind,
    StoryRecentEventView,
    StoryResolution,
    StoryState,
)
from aincrad.history import HistoryArchive
from aincrad.persistence import MAX_RECORDS, EventLog, StoredEvent, canonical_json, to_json_value
from aincrad.simulation import (
    SimulationResult as EngineSimulationResult,
)
from aincrad.simulation import (
    SimulationScheduler,
    create_initial_world,
)
from aincrad.simulation.runtime import (
    apply_action_progression,
    apply_legacy_life_events,
)
from aincrad.simulation.story import (
    build_story_perception,
    generate_story_candidates,
    resolve_story_intent,
)
from aincrad.storytelling import (
    HermesKimiTurnStoryAdapter,
    ResolvedAction,
    ResolvedStoryEvent,
    TurnPartyMember,
    TurnStoryRequest,
    TurnStoryResult,
    local_turn_story,
)
from aincrad.tui import (
    AdventurerView,
    EventView,
    RunSummary,
    render_simulation,
    sanitize_terminal_text,
)
from aincrad.tui.keys import Key, KeyReader, PosixKeyReader
from aincrad.tui.layout import wrap_display
from aincrad.tui.localization import (
    location_description_ko,
    location_direction_ko,
    location_name_ko,
)
from aincrad.tui.menu import MenuController, MenuOutcome
from aincrad.tui.narrative import (
    NO_STORY_EVENT_TEXT,
    detail_non_negative_int,
    event_detail_map,
    render_turn_story,
)
from aincrad.tui.screens import (
    MenuChoice,
    render_menu,
    render_status_context,
    render_text_screen,
    text_screen_body_capacity,
)
from aincrad.tui.textual_app import AincradTextualApp, MenuOption, TextualInteraction


@dataclass(frozen=True)
class SimulationResult:
    events: tuple[EventView, ...]
    adventurers: tuple[AdventurerView, ...]
    summary: RunSummary


Runner = Callable[..., SimulationResult]
ReplayRunner = Callable[..., SimulationResult]
CommentaryProvider = Callable[[MovementCommentaryRequest], MovementCommentaryResult]
StoryProvider = Callable[[TurnStoryRequest], TurnStoryResult]
_CURRENT_SCHEMA_VERSION = 5
_CURRENT_RULES_VERSION = 4
_VERSIONED_RULES_VERSIONS = {2: 1, 3: 2, 4: 3, 5: 4}
_VERSIONED_CONTENT_REVISIONS = {
    2: "rules-v2",
    3: "rules-v2",
    4: "rules-v3",
    5: "current",
}


class _ResizeGeneration:
    """Coalesce resize signals without erasing a newer notification."""

    def __init__(self) -> None:
        self._generation = 0
        self._consumed_generation = 0

    def notify(self, *_signal_args: object) -> None:
        self._generation += 1

    def consume(self) -> bool:
        generation = self._generation
        if generation == self._consumed_generation:
            return False
        self._consumed_generation = generation
        return True


@dataclass(frozen=True, slots=True)
class ControlledAction:
    intent: ActionIntent
    controller: str
    reason_code: str

    def __post_init__(self) -> None:
        if self.controller not in {"user", "baseline_policy", "test", "legacy"}:
            raise ValueError("unsupported action controller")
        if not self.reason_code or len(self.reason_code) > 64:
            raise ValueError("reason_code must contain at most 64 characters")

    @property
    def actor_id(self) -> str:
        return self.intent.adventurer_id


@dataclass(frozen=True, slots=True)
class TickTrace:
    proposals: tuple[ControlledAction, ...]
    action_events: tuple[DomainEvent, ...]
    story_intent: StoryIntent
    story_resolution: StoryResolution
    facts: tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True, slots=True)
class CollaborativeResult:
    final_state: WorldState
    events: tuple[DomainEvent, ...]
    proposals: tuple[ControlledAction, ...]
    traces: tuple[TickTrace, ...]


Chooser = Callable[[WorldState, str], ActionIntent | ControlledAction]
HourObserver = Callable[[int, EngineSimulationResult], None]
ContinueDecider = Callable[[WorldState], bool]
TraceObserver = Callable[[int, TickTrace], None]
TraceContinueDecider = Callable[[WorldState, TickTrace], bool]
_BASE_TIME = datetime(2025, 12, 31, 15, tzinfo=UTC)  # 2026-01-01 00:00 KST
_INITIAL_RHEA_RELATIONSHIP = 55
_OBJECTIVE_RELATIONSHIP_DELTA = 5
_AI_CHOICE = object()
_MOVE_CHOICE = object()
_OTHER_DESTINATIONS = object()
_ACTION_LABELS = {
    "move": "이동",
    "rest": "휴식",
    "gather": "채집",
    "trade": "거래",
    "wait": "대기",
}
_ACTIVITY_LABELS = {
    "idle": "대기",
    "moving": "이동 중",
    "resting": "휴식 중",
    "gathering": "채집 중",
    "trading": "거래 중",
    "waiting": "대기",
}
_CHARACTER_OPTIONS = (
    (CharacterClass.WARRIOR, "전사", "레아 베일", Stats(24, 24, 8, 8)),
    (CharacterClass.ARCHER, "궁수", "토빈 리드", Stats(18, 18, 12, 12)),
    (CharacterClass.MAGE, "마법사", "세이블 퀼", Stats(14, 14, 20, 20)),
    (CharacterClass.TANK, "탱커", "브란 실드", Stats(30, 30, 6, 6)),
)
_CLASS_LABELS = {
    character_class: label for character_class, label, _, _ in _CHARACTER_OPTIONS
}
_DEFAULT_IDENTITY_PROFILE = CharacterIdentityProfile(
    personality_description="낯선 것을 호기심 있게 살피되 위험 앞에서는 신중하게 판단한다.",
    traits_description="동료의 의견을 존중하고 작은 단서도 놓치지 않으려 한다.",
)
_CHARACTER_DESCRIPTIONS = {
    CharacterClass.WARRIOR: "근접 전투와 생존의 균형이 좋습니다",
    CharacterClass.ARCHER: "민첩하게 거리를 유지하며 기회를 노립니다",
    CharacterClass.MAGE: "높은 MP로 강력한 선택지를 준비합니다",
    CharacterClass.TANK: "높은 HP로 파티의 위험을 받아냅니다",
}


def _prompt_identity_textual(interaction: TextualInteraction) -> CharacterIdentityProfile:
    def validate_personality(raw: str) -> str:
        return CharacterIdentityProfile(
            personality_description=raw,
            traits_description=_DEFAULT_IDENTITY_PROFILE.traits_description,
        ).personality_description

    def validate_traits(raw: str) -> str:
        return CharacterIdentityProfile(
            personality_description=_DEFAULT_IDENTITY_PROFILE.personality_description,
            traits_description=raw,
        ).traits_description

    personality = interaction.input_text(
        "주인공의 성격",
        subtitle="이 인물이 어떤 마음가짐으로 사람과 낯선 상황을 대하는지 자유롭게 적어 주세요",
        validate=validate_personality,
    )
    if personality is None:
        return _DEFAULT_IDENTITY_PROFILE
    traits = interaction.input_text(
        "주인공의 특징",
        subtitle="말투, 습관, 장점, 약점처럼 이야기에서 드러날 특징을 자유롭게 적어 주세요",
        validate=validate_traits,
    )
    if traits is None:
        return _DEFAULT_IDENTITY_PROFILE
    return CharacterIdentityProfile(
        personality_description=personality,
        traits_description=traits,
    )


def _prompt_for_character(*, stdin: TextIO, stdout: TextIO) -> CharacterClass:
    stdout.write("\n══ 캐릭터 선택 ══\n")
    for index, (_, label, name, stats) in enumerate(_CHARACTER_OPTIONS, start=1):
        stdout.write(
            f"{index}. {label} · {name} "
            f"(HP {stats.max_hp}, MP {stats.max_mp})\n"
        )
    while True:
        stdout.write("선택> ")
        stdout.flush()
        answer = stdin.readline()
        if answer == "":
            raise EOFError("캐릭터 선택 입력이 종료되었습니다")
        try:
            selected = int(answer.strip())
        except ValueError:
            selected = 0
        if 1 <= selected <= len(_CHARACTER_OPTIONS):
            return _CHARACTER_OPTIONS[selected - 1][0]
        stdout.write(f"1~{len(_CHARACTER_OPTIONS)} 사이의 번호를 입력하세요.\n")


def _screen_width() -> int:
    return min(100, max(40, shutil.get_terminal_size((80, 24)).columns))


def _screen_height() -> int:
    return max(1, shutil.get_terminal_size((80, 24)).lines)


def _show_text_screen(
    title: str,
    body_lines: Sequence[str],
    *,
    key_reader: KeyReader,
    stdout: TextIO,
    frame_writer: Callable[[str], None] | None,
) -> None:
    offset = 0
    while True:
        width = _screen_width()
        height = _screen_height()
        wrapped = tuple(
            wrapped_line
            for source_line in body_lines
            for wrapped_line in wrap_display(
                sanitize_terminal_text(source_line), width - 4
            )
        )
        scroll_hint = "↑↓ / W S 스크롤 · Enter / Esc 뒤로"
        viewport_size = max(
            1,
            text_screen_body_capacity(
                title,
                scroll_hint,
                width=width,
                height=height,
            ),
        )
        max_offset = max(0, len(wrapped) - viewport_size)
        offset = min(offset, max_offset)
        visible = wrapped[offset : offset + viewport_size]
        scrollable = len(wrapped) > viewport_size
        hint = (
            scroll_hint
            if scrollable
            else "Enter 또는 Esc로 뒤로"
        )
        viewport_size = max(
            1,
            text_screen_body_capacity(
                title,
                hint,
                width=width,
                height=height,
            ),
        )
        max_offset = max(0, len(wrapped) - viewport_size)
        offset = min(offset, max_offset)
        visible = wrapped[offset : offset + viewport_size]
        frame = render_text_screen(
            title,
            visible,
            hint=hint,
            width=width,
            height=height,
        )
        if frame_writer is None:
            stdout.write(frame)
            stdout.flush()
        else:
            frame_writer(frame)
        key = key_reader.read_key()
        if key is Key.INTERRUPT:
            raise KeyboardInterrupt
        if key in {Key.ENTER, Key.BACK, Key.EOF, Key.QUIT}:
            return
        if key is Key.UP:
            offset = max(0, offset - 1)
        elif key is Key.DOWN:
            offset = min(max_offset, offset + 1)


def _select_menu(
    title: str,
    choices: Sequence[MenuChoice],
    values: Sequence[object],
    *,
    key_reader: KeyReader,
    stdout: TextIO,
    allow_back: bool = False,
    frame_writer: Callable[[str], None] | None = None,
    subtitle: str = "",
    context: Sequence[str] = (),
    width: int | None = None,
) -> object | None:
    controller = MenuController(tuple(zip(choices, values, strict=True)))
    while True:
        frame_width = width if width is not None else _screen_width()
        frame_height = _screen_height()
        frame = render_menu(
            title,
            choices,
            controller.selected_index,
            subtitle=subtitle,
            context=context,
            allow_back=allow_back,
            width=frame_width,
            height=frame_height,
        )
        if frame_writer is None:
            stdout.write(frame)
            stdout.flush()
        else:
            frame_writer(frame)
        key = key_reader.read_key()
        if key is Key.INTERRUPT:
            raise KeyboardInterrupt
        if key in {Key.EOF, Key.QUIT}:
            return None
        if frame_height < 8:
            if key is Key.BACK and allow_back:
                return None
            continue
        result = controller.handle_key(key)
        if result is None:
            continue
        if result.outcome is MenuOutcome.BACK:
            return None
        assert result.value is not None
        return result.value[1]


def _prompt_for_character_menu(
    *,
    key_reader: KeyReader,
    stdout: TextIO,
    frame_writer: Callable[[str], None] | None = None,
) -> CharacterClass | None:
    choices = tuple(
        MenuChoice(
            label,
            f"HP {stats.max_hp} · MP {stats.max_mp} · {_CHARACTER_DESCRIPTIONS[character_class]}",
        )
        for character_class, label, _, stats in _CHARACTER_OPTIONS
    )
    selected = _select_menu(
        "직업 선택",
        choices,
        tuple(item[0] for item in _CHARACTER_OPTIONS),
        key_reader=key_reader,
        stdout=stdout,
        allow_back=True,
        frame_writer=frame_writer,
        subtitle="주인공의 역할을 선택하세요",
    )
    return selected if isinstance(selected, CharacterClass) else None


def _starting_world(
    character_class: CharacterClass,
    hero_name: str | None = None,
    *,
    content_revision: str = "current",
) -> WorldState:
    base = create_initial_world(content_revision=content_revision)
    _, _, default_name, stats = next(
        option for option in _CHARACTER_OPTIONS if option[0] is character_class
    )
    name = validate_hero_name(default_name if hero_name is None else hero_name)
    hero = Adventurer(
        id=HERO_ID,
        name=name,
        location_id="emberfall",
        stats=stats,
        gold=5,
        character_class=character_class,
    )
    return WorldState(
        base.tick,
        base.locations,
        {**base.adventurers, HERO_ID: hero},
        PartyState(HERO_ID, (HERO_ID,), cap=3),
    )


def _available_intents(world: WorldState, actor_id: str) -> tuple[ActionIntent, ...]:
    return available_action_intents(world, actor_id)


def _perception(world: WorldState, actor_id: str) -> Perception:
    adventurer = world.adventurers[actor_id]
    resident = resident_npc_for_location(adventurer.location_id)
    visible_entities = tuple(
        {"id": other.id, "kind": "adventurer", "display_name": other.name}
        for other in sorted(world.adventurers.values(), key=lambda item: item.id)
        if other.id != actor_id and other.location_id == adventurer.location_id
    ) + (
        (
            {
                "id": resident.id,
                "kind": "npc",
                "display_name": resident.display_name,
                "service": resident.service,
            },
        )
        if resident is not None
        else ()
    )
    return perceive(
        Observation(
            tick=world.tick,
            actor_id=actor_id,
            location_id=adventurer.location_id,
            self_state={
                "hp": adventurer.stats.hp,
                "mp": adventurer.stats.mp,
                "gold": adventurer.gold,
                "resources": adventurer.resources,
            },
            visible_entities=visible_entities,
            visible_entity_fields=("id", "kind", "display_name", "service"),
        )
    )


def _intent_label(intent: ActionIntent, world: WorldState) -> str:
    action = intent.action.value if isinstance(intent.action, ActionKind) else str(intent.action)
    if action == ActionKind.MOVE.value and intent.target_location_id is not None:
        return f"이동 → {location_name_ko(intent.target_location_id)}"
    contextual = contextual_action_for_intent(world, intent)
    if contextual is not None:
        return contextual.label_ko
    if action == ActionKind.TRADE.value:
        return f"거래 (자원 {intent.quantity}개 판매)"
    return _ACTION_LABELS.get(action, action)


def _intent_description(intent: ActionIntent, world: WorldState) -> str:
    action = intent.action.value if isinstance(intent.action, ActionKind) else str(intent.action)
    if action == ActionKind.MOVE.value and intent.target_location_id is not None:
        return f"{location_name_ko(intent.target_location_id)}에서 다음 한 시간을 보냅니다"
    contextual = contextual_action_for_intent(world, intent)
    if contextual is not None:
        return contextual.description_ko
    descriptions = {
        ActionKind.GATHER.value: "현재 지역에서 자원과 단서를 찾습니다",
        ActionKind.TRADE.value: "보유 자원을 판매해 여정을 준비합니다",
        ActionKind.REST.value: "안전한 곳에서 HP와 MP를 회복합니다",
        ActionKind.WAIT.value: "이동하지 않고 주변의 변화를 지켜봅니다",
    }
    return descriptions.get(action, "이 행동을 다음 한 시간 동안 수행합니다")


def _choose_ai_intent(world: WorldState, actor_id: str) -> ActionIntent:
    """Delegate one actor using only that actor's detached perception."""

    return BaselinePolicy().choose(
        _perception(world, actor_id), _available_intents(world, actor_id)
    )


def _identity_labels_ko(profile: CharacterIdentityProfile) -> tuple[str, ...]:
    return (
        f"성격: {profile.personality_description}",
        f"특징: {profile.traits_description}",
    )


def _movement_commentary_request(
    world: WorldState,
    actor_id: str,
    identity_profile: CharacterIdentityProfile,
    destination_ids: tuple[str, ...] | None = None,
) -> MovementCommentaryRequest:
    adventurer = world.adventurers[actor_id]
    location = world.locations[adventurer.location_id]
    destinations = tuple(
        DestinationCandidate(
            destination_id=destination_id,
            name_ko=location_name_ko(destination_id),
            description_ko=location_description_ko(destination_id),
            order=index,
        )
        for index, destination_id in enumerate(
            sorted(destination_ids if destination_ids is not None else location.connections)
        )
    )
    return MovementCommentaryRequest(
        current_location_name_ko=location_name_ko(location.id),
        current_location_description_ko=location_description_ko(location.id),
        hp_summary_ko=f"HP {adventurer.stats.hp}/{adventurer.stats.max_hp}",
        mp_summary_ko=f"MP {adventurer.stats.mp}/{adventurer.stats.max_mp}",
        identity_labels_ko=_identity_labels_ko(identity_profile),
        destinations=destinations,
    )


def _prompt_for_movement_textual(
    world: WorldState,
    actor_id: str,
    *,
    interaction: TextualInteraction,
    identity_profile: CharacterIdentityProfile,
    commentary_provider: Callable[
        [MovementCommentaryRequest], MovementCommentaryResult
    ] = deterministic_commentary,
    move_intents: tuple[ActionIntent, ...] | None = None,
) -> ControlledAction:
    if move_intents is None:
        move_intents = tuple(
            intent
            for intent in _available_intents(world, actor_id)
            if intent.action is ActionKind.MOVE
        )
    by_destination = {
        intent.target_location_id: intent
        for intent in move_intents
        if intent.target_location_id is not None
    }
    commentary = commentary_provider(
        _movement_commentary_request(
            world,
            actor_id,
            identity_profile,
            tuple(
                intent.target_location_id
                for intent in move_intents
                if intent.target_location_id is not None
            ),
        )
    )
    recommendation_options: tuple[MenuOption[object], ...] = tuple(
        MenuOption[object](
            location_name_ko(recommendation.destination_id),
            recommendation.commentary_ko,
            by_destination[recommendation.destination_id],
        )
        for recommendation in commentary.recommendations
    )
    selected = interaction.choose(
        "이동할 곳",
        recommendation_options
        + (
            MenuOption[object](
                "기타 목적지",
                "연결된 모든 목적지를 확인합니다",
                _OTHER_DESTINATIONS,
            ),
        ),
        subtitle="해설을 읽고 다음 한 시간을 보낼 목적지를 고르세요",
        allow_back=True,
    )
    if selected is None:
        raise EOFError("이동 선택이 취소되었습니다")
    if selected is _OTHER_DESTINATIONS:
        selected = interaction.choose(
            "기타 목적지",
            tuple(
                MenuOption[object](
                    location_name_ko(intent.target_location_id or ""),
                    location_description_ko(intent.target_location_id or ""),
                    intent,
                )
                for intent in move_intents
            ),
            subtitle="현재 위치와 직접 이어진 길만 표시합니다",
            allow_back=True,
        )
        if selected is None:
            raise EOFError("이동 선택이 취소되었습니다")
    assert isinstance(selected, ActionIntent)
    return ControlledAction(selected, "user", "user.selected")


def _prompt_for_intent(
    world: WorldState, actor_id: str, *, stdin: TextIO, stdout: TextIO
) -> ActionIntent:
    adventurer = world.adventurers[actor_id]
    allowed = _available_intents(world, actor_id)
    day, hour = divmod(world.tick, 24)
    stdout.write(
        f"\n[{day + 1}일차 {hour:02d}:00] {adventurer.name} @ "
        f"{location_name_ko(adventurer.location_id)}\n"
    )
    for index, intent in enumerate(allowed, start=1):
        stdout.write(f"{index}. {_intent_label(intent, world)}\n")
    ai_index = len(allowed) + 1
    stdout.write(f"{ai_index}. AI 판단에 맡긴다\n")
    while True:
        stdout.write("선택> ")
        stdout.flush()
        answer = stdin.readline()
        if answer == "":
            raise EOFError("행동 선택 입력이 종료되었습니다")
        try:
            selected_index = int(answer.strip())
        except ValueError:
            selected_index = 0
        if 1 <= selected_index <= len(allowed):
            return allowed[selected_index - 1]
        if selected_index == ai_index:
            selected = _choose_ai_intent(world, actor_id)
            stdout.write(
                f"AI 선택: {_intent_label(selected, world)} "
                "(reason_code=world_state_rule)\n"
            )
            return selected
        stdout.write(f"1~{ai_index} 사이의 번호를 입력하세요.\n")


def _prompt_for_facility_intent_menu(
    world: WorldState,
    actor_id: str,
    facility_id: str,
    facility_intents: tuple[ActionIntent, ...],
    *,
    key_reader: KeyReader,
    stdout: TextIO,
    frame_writer: Callable[[str], None] | None,
) -> ActionIntent | None:
    """Choose a facility action before the scheduler sees an intent."""

    adventurer = world.adventurers[actor_id]
    resident = resident_npc_for_location(facility_id)
    day, hour = divmod(world.tick, 24)
    context = render_status_context(
        day=day + 1,
        hour=hour,
        location=location_name_ko(facility_id),
        hp=adventurer.stats.hp,
        max_hp=adventurer.stats.max_hp,
        mp=adventurer.stats.mp,
        max_mp=adventurer.stats.max_mp,
        level=adventurer.level,
        party_size=sum(
            world.adventurers[member_id].alive
            for member_id in (world.party.member_ids if world.party is not None else (actor_id,))
        ),
        gold=adventurer.gold,
        resources=adventurer.resources,
        resident_name=resident.display_name if resident is not None else None,
        resident_role_ko=resident.role_ko if resident is not None else None,
        width=_screen_width(),
    )
    selected = _select_menu(
        location_name_ko(facility_id),
        tuple(
            MenuChoice(_intent_label(intent, world), _intent_description(intent, world))
            for intent in facility_intents
        ),
        facility_intents,
        key_reader=key_reader,
        stdout=stdout,
        allow_back=True,
        frame_writer=frame_writer,
        subtitle="이 시설에서 보낼 다음 한 시간의 행동을 고르세요",
        context=context,
        width=_screen_width(),
    )
    if selected is None:
        return None
    assert isinstance(selected, ActionIntent)
    assert selected.target_location_id == facility_id
    return selected


def _prompt_for_movement_menu(
    world: WorldState,
    actor_id: str,
    *,
    key_reader: KeyReader,
    stdout: TextIO,
    frame_writer: Callable[[str], None] | None,
    move_intents: tuple[ActionIntent, ...],
) -> ControlledAction:
    selected = _select_menu(
        "이동할 곳",
        tuple(
            MenuChoice(
                location_name_ko(intent.target_location_id or ""),
                location_description_ko(intent.target_location_id or ""),
            )
            for intent in move_intents
        ),
        move_intents,
        key_reader=key_reader,
        stdout=stdout,
        allow_back=True,
        frame_writer=frame_writer,
        subtitle="현재 위치와 직접 이어진 길만 표시합니다",
        width=_screen_width(),
    )
    if selected is None:
        return _prompt_for_intent_menu(
            world,
            actor_id,
            key_reader=key_reader,
            stdout=stdout,
            frame_writer=frame_writer,
        )
    assert isinstance(selected, ActionIntent)
    return ControlledAction(selected, "user", "user.selected")


def _prompt_for_intent_menu(
    world: WorldState,
    actor_id: str,
    *,
    key_reader: KeyReader,
    stdout: TextIO,
    frame_writer: Callable[[str], None] | None = None,
) -> ControlledAction:
    allowed = _available_intents(world, actor_id)
    move_intents = tuple(intent for intent in allowed if intent.action is ActionKind.MOVE)
    frame_width = _screen_width()
    adventurer = world.adventurers[actor_id]
    resident = resident_npc_for_location(adventurer.location_id)
    party_size = sum(
        world.adventurers[member_id].alive
        for member_id in (world.party.member_ids if world.party is not None else (actor_id,))
    )
    day, hour = divmod(world.tick, 24)
    context = render_status_context(
        day=day + 1,
        hour=hour,
        location=location_name_ko(adventurer.location_id),
        hp=adventurer.stats.hp,
        max_hp=adventurer.stats.max_hp,
        mp=adventurer.stats.mp,
        max_mp=adventurer.stats.max_mp,
        level=adventurer.level,
        party_size=party_size,
        gold=adventurer.gold,
        resources=adventurer.resources,
        resident_name=resident.display_name if resident is not None else None,
        resident_role_ko=resident.role_ko if resident is not None else None,
        width=frame_width,
    )
    facility_labels = {
        "emberfall-shop": "상점",
        "emberfall-inn": "여관",
        "emberfall-quest-hall": "의뢰소",
        "emberfall-plaza": "광장",
        "emberfall-tavern": "주점",
    }
    facility_ids = tuple(
        facility_id
        for facility_id in facility_labels
        if any(intent.target_location_id == facility_id for intent in allowed)
    )
    facility_actions = {
        facility_id: tuple(
            intent for intent in allowed if intent.target_location_id == facility_id
        )
        for facility_id in facility_ids
    }
    local_intents = tuple(intent for intent in allowed if intent.target_location_id is None)
    choices = tuple(
        MenuChoice(
            f"{facility_labels[facility_id]} · {location_name_ko(facility_id)}",
            location_description_ko(facility_id),
        )
        for facility_id in facility_ids
    ) + (
        (
            MenuChoice("마을 밖으로 이동", "마을 경계 밖으로 이어진 길을 살펴봅니다"),
        )
        if facility_ids
        else (
            MenuChoice("이동하기", f"연결된 길 {len(move_intents)}곳을 살펴봅니다"),
        )
    ) + tuple(
        MenuChoice(_intent_label(intent, world), _intent_description(intent, world))
        for intent in local_intents
    ) + (
        MenuChoice(
            "AI 판단에 맡기기",
            "현재 HP·MP·위치·자원·갈 수 있는 길을 비교해 행동 선택",
        ),
    )
    choice_values: tuple[object, ...] = (
        *facility_ids,
        _MOVE_CHOICE,
        *local_intents,
        _AI_CHOICE,
    )
    selected = _select_menu(
        f"{world.adventurers[actor_id].name}의 행동",
        choices,
        choice_values,
        key_reader=key_reader,
        stdout=stdout,
        allow_back=False,
        frame_writer=frame_writer,
        subtitle="다음 한 시간의 행동을 고르세요",
        context=context,
        width=frame_width,
    )
    if selected is None:
        raise EOFError("행동 선택이 취소되었습니다")
    if selected is _AI_CHOICE:
        return ControlledAction(
            _choose_ai_intent(world, actor_id), "baseline_policy", "policy.baseline"
        )
    if selected is _MOVE_CHOICE:
        return _prompt_for_movement_menu(
            world,
            actor_id,
            key_reader=key_reader,
            stdout=stdout,
            frame_writer=frame_writer,
            move_intents=move_intents,
        )
    if isinstance(selected, str) and selected in facility_actions:
        facility_intent = _prompt_for_facility_intent_menu(
            world,
            actor_id,
            selected,
            facility_actions[selected],
            key_reader=key_reader,
            stdout=stdout,
            frame_writer=frame_writer,
        )
        if facility_intent is None:
            return _prompt_for_intent_menu(
                world,
                actor_id,
                key_reader=key_reader,
                stdout=stdout,
                frame_writer=frame_writer,
            )
        return ControlledAction(facility_intent, "user", "user.selected")
    assert isinstance(selected, ActionIntent)
    return ControlledAction(selected, "user", "user.selected")


def _prompt_for_facility_intent_textual(
    world: WorldState,
    actor_id: str,
    facility_id: str,
    facility_intents: tuple[ActionIntent, ...],
    *,
    interaction: TextualInteraction,
) -> ActionIntent | None:
    """Choose one facility service without mutating or scheduling the world."""

    adventurer = world.adventurers[actor_id]
    resident = resident_npc_for_location(facility_id)
    day, hour = divmod(world.tick, 24)
    context = render_status_context(
        day=day + 1,
        hour=hour,
        location=location_name_ko(facility_id),
        hp=adventurer.stats.hp,
        max_hp=adventurer.stats.max_hp,
        mp=adventurer.stats.mp,
        max_mp=adventurer.stats.max_mp,
        level=adventurer.level,
        party_size=sum(
            world.adventurers[member_id].alive
            for member_id in (world.party.member_ids if world.party is not None else (actor_id,))
        ),
        gold=adventurer.gold,
        resources=adventurer.resources,
        resident_name=resident.display_name if resident is not None else None,
        resident_role_ko=resident.role_ko if resident is not None else None,
        width=80,
    )
    selected = interaction.choose(
        location_name_ko(facility_id),
        tuple(
            MenuOption[object](
                _intent_label(intent, world), _intent_description(intent, world), intent
            )
            for intent in facility_intents
        ),
        subtitle="이 시설에서 보낼 다음 한 시간의 행동을 고르세요",
        context=context,
        allow_back=True,
    )
    if selected is None:
        return None
    assert isinstance(selected, ActionIntent)
    assert selected.target_location_id == facility_id
    return selected


def _prompt_for_intent_textual(
    world: WorldState,
    actor_id: str,
    *,
    interaction: TextualInteraction,
    identity_profile: CharacterIdentityProfile = _DEFAULT_IDENTITY_PROFILE,
    commentary_provider: Callable[
        [MovementCommentaryRequest], MovementCommentaryResult
    ] = deterministic_commentary,
) -> ControlledAction:
    allowed = _available_intents(world, actor_id)
    move_intents = tuple(intent for intent in allowed if intent.action is ActionKind.MOVE)
    local_intents = tuple(
        intent
        for intent in allowed
        if intent.action is not ActionKind.MOVE and intent.target_location_id is None
    )
    adventurer = world.adventurers[actor_id]
    resident = resident_npc_for_location(adventurer.location_id)
    party_size = sum(
        world.adventurers[member_id].alive
        for member_id in (world.party.member_ids if world.party is not None else (actor_id,))
    )
    day, hour = divmod(world.tick, 24)
    context = render_status_context(
        day=day + 1,
        hour=hour,
        location=location_name_ko(adventurer.location_id),
        hp=adventurer.stats.hp,
        max_hp=adventurer.stats.max_hp,
        mp=adventurer.stats.mp,
        max_mp=adventurer.stats.max_mp,
        level=adventurer.level,
        party_size=party_size,
        gold=adventurer.gold,
        resources=adventurer.resources,
        resident_name=resident.display_name if resident is not None else None,
        resident_role_ko=resident.role_ko if resident is not None else None,
        width=80,
    )
    facility_labels = {
        "emberfall-shop": "상점",
        "emberfall-inn": "여관",
        "emberfall-quest-hall": "의뢰소",
        "emberfall-plaza": "광장",
        "emberfall-tavern": "주점",
    }
    facility_ids = tuple(
        facility_id
        for facility_id in facility_labels
        if any(intent.target_location_id == facility_id for intent in allowed)
    )
    facility_actions = {
        facility_id: tuple(
            intent for intent in allowed if intent.target_location_id == facility_id
        )
        for facility_id in facility_ids
    }
    route_intents = move_intents
    if facility_ids:
        movement_options: tuple[MenuOption[object], ...] = tuple(
            MenuOption[object](
                f"{facility_labels[facility_id]} · {location_name_ko(facility_id)}",
                location_description_ko(facility_id),
                facility_id,
            )
            for facility_id in facility_ids
        ) + (
            MenuOption[object](
                "마을 밖으로 이동",
                "마을 경계 밖으로 이어진 길을 살펴봅니다",
                _MOVE_CHOICE,
            ),
        )
    else:
        movement_options = (
            MenuOption[object](
                "이동하기",
                f"연결된 길 {len(move_intents)}곳을 물리적·사회적 맥락과 함께 살펴봅니다",
                _MOVE_CHOICE,
            ),
        )
    options: tuple[MenuOption[object], ...] = movement_options + tuple(
        MenuOption[object](
            _intent_label(intent, world),
            _intent_description(intent, world),
            intent,
        )
        for intent in local_intents
    ) + (
        MenuOption[object](
            "AI 판단에 맡기기",
            "현재 HP·MP·위치·자원·갈 수 있는 길을 비교해 행동 선택",
            _AI_CHOICE,
        ),
    )
    selected = interaction.choose(
        f"{adventurer.name}의 행동",
        options,
        subtitle="다음 한 시간의 행동을 고르세요",
        context=context,
    )
    if selected is None:
        raise EOFError("행동 선택이 취소되었습니다")
    if selected is _AI_CHOICE:
        return ControlledAction(
            _choose_ai_intent(world, actor_id), "baseline_policy", "policy.baseline"
        )
    if selected is _MOVE_CHOICE:
        return _prompt_for_movement_textual(
            world,
            actor_id,
            interaction=interaction,
            identity_profile=identity_profile,
            commentary_provider=commentary_provider,
            move_intents=route_intents,
        )
    if isinstance(selected, str) and selected in facility_actions:
        facility_intent = _prompt_for_facility_intent_textual(
            world,
            actor_id,
            selected,
            facility_actions[selected],
            interaction=interaction,
        )
        if facility_intent is None:
            return _prompt_for_intent_textual(
                world,
                actor_id,
                interaction=interaction,
                identity_profile=identity_profile,
                commentary_provider=commentary_provider,
            )
        return ControlledAction(facility_intent, "user", "user.selected")
    assert isinstance(selected, ActionIntent)
    return ControlledAction(selected, "user", "user.selected")


def _apply_objective_relationship(story: StoryState, objective_complete: bool) -> StoryState:
    """Apply the explicit +5 objective delta, bounded to the 0..100 domain."""

    if not objective_complete:
        return story
    score = story.relationship_score(HERO_ID, "rhea-vale")
    if score is None:
        raise ValueError("missing canonical Rhea relationship")
    relationships = {
        (source_id, target_id): relationship_score
        for source_id, target_id, relationship_score in story.relationship_scores
    }
    relationships[(HERO_ID, "rhea-vale")] = min(
        100, score + _OBJECTIVE_RELATIONSHIP_DELTA
    )
    return StoryState(
        quest_states=story.quest_states,
        relationship_scores=relationships,
        resolved_candidate_ids=story.resolved_candidate_ids,
        resolved_template_ids=story.resolved_template_ids,
    )


def _run_hours(
    initial: WorldState,
    *,
    seed: int,
    hours: int,
    chooser: Chooser,
    observer: HourObserver | None = None,
    direct_hero_only: bool = False,
    story_director: StoryDirector | None = None,
    continue_decider: ContinueDecider | None = None,
    trace_continue_decider: TraceContinueDecider | None = None,
    trace_observer: TraceObserver | None = None,
) -> CollaborativeResult:
    """Run canonical hourly action batches followed by exactly one story decision."""

    world = initial
    events: list[DomainEvent] = []
    proposals: list[ControlledAction] = []
    traces: list[TickTrace] = []
    scheduler = SimulationScheduler(seed=seed)
    director = story_director or BaselineStoryDirector()
    story = StoryState(relationship_scores={(HERO_ID, "rhea-vale"): _INITIAL_RHEA_RELATIONSHIP})
    for completed_hours in range(1, hours + 1):
        party = world.party
        if party is None:
            raise ValueError("world has no runtime party")
        actor_ids = tuple(
            actor_id
            for actor_id in party.member_ids
            if world.adventurers[actor_id].alive
        )
        controlled: list[ControlledAction] = []
        for actor_id in actor_ids:
            if direct_hero_only and actor_id != party.selected_hero_id:
                selected = ControlledAction(
                    _choose_ai_intent(world, actor_id),
                    "baseline_policy",
                    "policy.baseline",
                )
            else:
                raw = chooser(world, actor_id)
                selected = (
                    raw
                    if isinstance(raw, ControlledAction)
                    else ControlledAction(raw, "legacy", "legacy.chooser")
                )
            if selected.actor_id != actor_id:
                raise ValueError("chooser returned an action for another actor")
            controlled.append(selected)
        hourly = scheduler.run_hour(world, (item.intent for item in controlled))
        action_world = hourly.final_state
        hero = action_world.adventurers[party.selected_hero_id]
        available_locations = (hero.location_id,)
        available_quests = (
            ("echoes-at-emberfall",)
            if hero.location_id == "emberfall-quest-hall"
            else ()
        )
        # Observable objective rule: a successful hero GATHER action while the
        # resulting location is Mossreach completes echoes-at-emberfall.
        objective_complete = any(
            isinstance(event, ActionSucceeded)
            and event.adventurer_id == party.selected_hero_id
            and event.action is ActionKind.GATHER
            and action_world.adventurers[event.adventurer_id].location_id == "mossreach"
            for event in hourly.events
        )
        completed_objectives = (
            ("echoes-at-emberfall",) if objective_complete else ()
        )
        story = _apply_objective_relationship(story, objective_complete)
        recent = tuple(
            StoryRecentEventView(
                f"action-{event.tick}-{event.adventurer_id}",
                event.tick,
                "action_succeeded"
                if isinstance(event, ActionSucceeded)
                else "action_rejected",
                (
                    (
                        "action",
                        str(
                            event.action.value
                            if isinstance(event.action, ActionKind)
                            else event.action
                        ),
                    ),
                ),
            )
            for event in hourly.events
        )
        perception = build_story_perception(action_world, story, recent_events=recent)
        candidates = generate_story_candidates(
            action_world,
            story,
            LIFE_EVENT_CATALOG,
            available_location_ids=available_locations,
            available_quest_ids=available_quests,
            completed_objective_quest_ids=completed_objectives,
        )
        selected_story = director.choose(perception, candidates)
        resolution = resolve_story_intent(
            action_world,
            story,
            selected_story,
            LIFE_EVENT_CATALOG,
            available_location_ids=available_locations,
            available_quest_ids=available_quests,
            completed_objective_quest_ids=completed_objectives,
        )
        world = resolution.world
        story = resolution.story
        facts = (
            ("available_location_ids", available_locations),
            ("available_quest_ids", available_quests),
            ("completed_objective_quest_ids", completed_objectives),
            (
                "relationship_score",
                (str(story.relationship_score(HERO_ID, "rhea-vale")),),
            ),
        )
        trace = TickTrace(
            tuple(controlled), hourly.events, selected_story, resolution, facts
        )
        traces.append(trace)
        if trace_observer is not None:
            trace_observer(completed_hours, trace)
        proposals.extend(controlled)
        events.extend(hourly.events)
        observed = EngineSimulationResult(world, hourly.events)
        if observer is not None:
            observer(completed_hours, observed)
        current_party = world.party
        if current_party is None:
            raise ValueError("world has no runtime party")
        if trace_continue_decider is not None and not trace_continue_decider(world, trace):
            break
        if not world.adventurers[current_party.selected_hero_id].alive:
            break
        if continue_decider is not None and not continue_decider(world):
            break
    return CollaborativeResult(world, tuple(events), tuple(proposals), tuple(traces))


def _non_negative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return number


def _positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aincrad")
    commands = parser.add_subparsers(dest="command", required=True)

    simulate = commands.add_parser("simulate", help="결정론적 모험 시뮬레이션 실행")
    simulate.add_argument("--seed", type=_non_negative_int, required=True)
    duration = simulate.add_mutually_exclusive_group(required=True)
    duration.add_argument("--days", type=_positive_int)
    duration.add_argument("--hours", type=_positive_int)
    simulate.add_argument("--headless", action="store_true")
    simulate.add_argument(
        "--class",
        dest="character_class",
        choices=tuple(character_class.value for character_class in CharacterClass),
        help="시작 직업: warrior, archer, mage, tank",
    )
    simulate.add_argument(
        "--name", "--hero-name", dest="hero_name", help="주인공 표시 이름"
    )
    simulate.add_argument("--output", type=Path)
    simulate.add_argument("--history-root", type=Path)
    simulate.add_argument(
        "--force", action="store_true", help="기존 events.jsonl을 명시적으로 교체"
    )

    replay_parser = commands.add_parser("replay", help="저장된 이벤트 로그 재생")
    replay_parser.add_argument("event_log", type=Path)
    replay_parser.add_argument("--verify-hash", action="store_true")
    history_parser = commands.add_parser("history", help="회차별 히스토리 조회")
    history_commands = history_parser.add_subparsers(dest="history_command", required=True)
    history_list = history_commands.add_parser("list", help="회차 목록")
    history_list.add_argument("--history-root", type=Path, required=True)
    history_show = history_commands.add_parser("show", help="회차 상세")
    history_show.add_argument("run_number", type=_positive_int)
    history_show.add_argument("--history-root", type=Path, required=True)
    return parser



def _event_message(event: DomainEvent, world: WorldState) -> str:
    actor = world.adventurers.get(event.adventurer_id)
    actor_name = actor.name if actor is not None else event.adventurer_id
    action = event.action.value if isinstance(event.action, ActionKind) else str(event.action)
    if isinstance(event, ActionRejected):
        reasons = {
            "unknown_adventurer": "그 모험가를 찾을 수 없었다",
            "adventurer_dead": "이미 쓰러져 행동할 수 없었다",
            "unknown_location": "목적지를 찾을 수 없었다",
            "location_not_connected": "이어진 길이 없었다",
            "gather_not_allowed": "이곳에서는 채집할 수 없었다",
            "invalid_gather_yield": "채집 결과가 올바르지 않았다",
            "trade_not_allowed": "이곳에서는 거래할 수 없었다",
            "invalid_quantity": "거래 수량이 올바르지 않았다",
            "insufficient_resources": "팔 자원이 부족했다",
            "invalid_action": "세계 규칙에 맞지 않는 행동이었다",
        }
        return f"{actor_name}: {reasons.get(event.reason, '행동을 실행할 수 없었다')}."
    if not isinstance(event, ActionSucceeded):
        return f"{actor_name}: {_ACTION_LABELS.get(action, action)} 판정이 끝났다."

    details = event_detail_map(event)
    if event.action is ActionKind.MOVE:
        activity = f"{location_direction_ko(event.target_location_id or '')} 이동했다."
    elif event.action is ActionKind.REST:
        activity = "안전한 곳에서 쉬며 몸과 마음을 추슬렀다."
    elif event.action is ActionKind.GATHER:
        activity = f"자원 {details.get('resources_gathered', '0')}개를 모았다."
    elif event.action is ActionKind.TRADE:
        activity = f"자원 {details.get('resources_sold', str(event.quantity))}개를 팔았다."
    else:
        activity = "자리를 지키며 주변을 살폈다."

    results: list[str] = []
    damage = detail_non_negative_int(details, "damage")
    if damage:
        results.append(f"피해 {damage}")
    hp_restored = detail_non_negative_int(details, "hp_restored")
    mp_restored = detail_non_negative_int(details, "mp_restored")
    if hp_restored or mp_restored:
        results.append(f"HP {hp_restored}, MP {mp_restored} 회복")
    xp = detail_non_negative_int(details, "xp_awarded")
    if xp:
        results.append(f"경험치 {xp} 획득")
    hp = details.get("hp")
    mp = details.get("mp")
    if hp is not None and mp is not None:
        results.append(f"현재 HP {hp}, MP {mp}")
    suffix = f" 결과: {' · '.join(results)}." if results else ""
    return f"{actor_name}: {activity}{suffix}"


def _event_view(event: DomainEvent, world: WorldState) -> EventView:
    action = event.action.value if isinstance(event.action, ActionKind) else str(event.action)
    return EventView(
        occurred_at=_BASE_TIME + timedelta(hours=event.tick),
        kind=_ACTION_LABELS.get(action, action),
        message=_event_message(event, world),
    )


def _continue_context(
    world: WorldState, trace: TickTrace, *, width: int
) -> tuple[str, ...]:
    party = world.party
    if party is None:
        raise ValueError("world has no runtime party")
    hero = world.adventurers[party.selected_hero_id]
    resident = resident_npc_for_location(hero.location_id)
    day, hour = divmod(world.tick, 24)
    status = render_status_context(
        day=day + 1,
        hour=hour,
        location=location_name_ko(hero.location_id),
        hp=hero.stats.hp,
        max_hp=hero.stats.max_hp,
        mp=hero.stats.mp,
        max_mp=hero.stats.max_mp,
        level=hero.level,
        party_size=sum(world.adventurers[item].alive for item in party.member_ids),
        gold=hero.gold,
        resources=hero.resources,
        resident_name=resident.display_name if resident is not None else None,
        resident_role_ko=resident.role_ko if resident is not None else None,
        width=width,
    )
    return (*status, "", "방금 끝난 한 시간의 기록을 확인했습니다.")


def _story_event_text(trace: TickTrace) -> str | None:
    template_id = trace.story_resolution.event.template_id
    template = next((item for item in LIFE_EVENT_CATALOG if item.id == template_id), None)
    return template.display_text_ko if template is not None else None


def _turn_story_request(
    world: WorldState,
    trace: TickTrace,
    identity_profile: CharacterIdentityProfile,
    recent_scene_summaries_ko: tuple[str, ...],
) -> TurnStoryRequest:
    party = world.party
    if party is None:
        raise ValueError("world has no runtime party")
    hero = world.adventurers[party.selected_hero_id]
    location = world.locations[hero.location_id]
    controllers = {proposal.actor_id: proposal.controller for proposal in trace.proposals}
    proposals = {proposal.actor_id: proposal for proposal in trace.proposals}
    resolved_actions: list[ResolvedAction] = []
    for event in trace.action_events:
        proposal = proposals[event.adventurer_id]
        actor = world.adventurers[event.adventurer_id]
        action_story = render_turn_story(
            world,
            (event,),
            controllers={event.adventurer_id: proposal.controller},
            story_event_text=None,
        )
        resolved_actions.append(
            ResolvedAction(
                actor_name_ko=actor.name,
                action_ko=_intent_label(proposal.intent, world),
                controller_ko={
                    "user": "사용자",
                    "baseline_policy": "규칙 기반 동료",
                    "legacy": "기존 선택기",
                    "test": "테스트 선택기",
                }[controllers[event.adventurer_id]],
                outcome_ko="성공" if isinstance(event, ActionSucceeded) else "실패",
                details_ko=tuple(line for line in action_story[1:] if line),
            )
        )
    relationship_score = dict(trace.facts).get("relationship_score", ("알 수 없음",))[0]
    party_view = tuple(
        TurnPartyMember(
            name_ko=member.name,
            public_stats_ko=(
                f"Lv.{member.level} · HP {member.stats.hp}/{member.stats.max_hp} · "
                f"MP {member.stats.mp}/{member.stats.max_mp} · EXP {member.exp}"
            ),
            roles_ko=(_CLASS_LABELS[member.character_class],),
            relationships_ko=(
                (f"레아 베일과의 관계 {relationship_score}/100",)
                if member.id == party.selected_hero_id
                else ()
            ),
        )
        for member in (world.adventurers[member_id] for member_id in party.member_ids)
    )
    event_text = _story_event_text(trace)
    completed_tick = min(event.tick for event in trace.action_events)
    day, hour = divmod(completed_tick, 24)
    return TurnStoryRequest(
        world_title="The Glass Frontier",
        world_lore_summary_ko=(
            "유리 파편과 오래된 장치가 남은 세계에서 모험가들이 생존하고 관계를 쌓는다."
        ),
        day=day + 1,
        hour=hour,
        tick=completed_tick,
        current_location_id=location.id,
        current_location_name_ko=location_name_ko(location.id),
        current_location_kind_ko={
            "town": "마을 또는 마을 내부 시설",
            "hunting_ground": "사냥터",
            "dungeon": "던전",
        }[location.kind.value],
        current_location_description_ko=location_description_ko(location.id),
        identity_labels_ko=_identity_labels_ko(identity_profile),
        party=party_view,
        selected_actions=tuple(resolved_actions),
        resolved_story_event=(
            ResolvedStoryEvent("시간 사건", (event_text,)) if event_text is not None else None
        ),
        recent_scene_summaries_ko=recent_scene_summaries_ko,
    )


def _adventurer_views(world: WorldState) -> tuple[AdventurerView, ...]:
    party = world.party
    visible_ids = party.member_ids if party is not None else tuple(world.adventurers)
    return tuple(
        AdventurerView(
            name=adventurer.name,
            location=location_name_ko(adventurer.location_id),
            hp=adventurer.stats.hp,
            mp=adventurer.stats.mp,
            activity=_ACTIVITY_LABELS.get(adventurer.activity.value, adventurer.activity.value),
            level=adventurer.level,
            exp=adventurer.exp,
            character_class=next(
                label
                for character_class, label, _, _ in _CHARACTER_OPTIONS
                if character_class is adventurer.character_class
            ),
        )
        for adventurer in (world.adventurers[actor_id] for actor_id in visible_ids)
    )


def _output_log_path(output: Path) -> Path:
    if output.suffix == ".jsonl":
        output.parent.mkdir(parents=True, exist_ok=True)
        return output
    output.mkdir(parents=True, exist_ok=True)
    return output / "events.jsonl"


def _next_home_log_path(log_root: Path) -> Path:
    """Return the first unused monotonic home-playthrough path without creating it."""

    for run_number in range(1, MAX_RECORDS + 1):
        candidate = log_root / f"playthrough-{run_number:06d}.jsonl"
        if not candidate.exists():
            return candidate
    raise ValueError("home playthrough log limit reached")


def _world_digest(world: WorldState) -> str:
    return hashlib.sha256(canonical_json(world).encode("utf-8")).hexdigest()


def _legacy_v2_world(world: WorldState) -> WorldState:
    """Remove post-v2 location affordances before replaying rules version 1."""

    locations = {
        location_id: replace(
            location,
            description="",
            services=(),
            contextual_actions=(),
        )
        for location_id, location in world.locations.items()
    }
    adventurers = dict(world.adventurers)
    for candidate_id in ("rhea-vale", "tovin-reed", "sable-quill"):
        candidate = adventurers[candidate_id]
        adventurers[candidate_id] = replace(
            candidate,
            location_id="emberfall",
            character_class=CharacterClass.WARRIOR,
        )
    return replace(world, locations=locations, adventurers=adventurers)


def _legacy_v2_world_digest(world: WorldState) -> str:
    """Hash a world through the exact Location field set committed by v2."""

    payload = to_json_value(world)
    locations = payload.get("locations")
    if not isinstance(locations, dict):
        raise ValueError("legacy v2 world locations must be an object")
    for raw_location in locations.values():
        if not isinstance(raw_location, dict):
            raise ValueError("legacy v2 location must be an object")
        raw_location.pop("description", None)
        raw_location.pop("services", None)
        raw_location.pop("contextual_actions", None)
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _default_run(
    *,
    seed: int,
    days: int | None = None,
    hours: int | None = None,
    headless: bool,
    output: Path | None,
    force: bool,
    character_class: CharacterClass | None = None,
    hero_name: str | None = None,
    identity_profile: CharacterIdentityProfile | None = None,
    commentary_provider: CommentaryProvider = deterministic_commentary,
    story_provider: StoryProvider = local_turn_story,
    history_root: Path | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    key_reader: KeyReader | None = None,
    story_director: StoryDirector | None = None,
    continue_decider: ContinueDecider | None = None,
    trace_continue_decider: TraceContinueDecider | None = None,
    frame_writer: Callable[[str], None] | None = None,
    interaction: TextualInteraction | None = None,
) -> SimulationResult:
    total_hours = hours if hours is not None else (days or 0) * 24
    if total_hours <= 0:
        raise ValueError("simulation duration must be positive")
    input_stream = stdin if stdin is not None else sys.stdin
    output_stream = stdout if stdout is not None else sys.stdout
    selected_class = character_class
    if selected_class is None:
        if headless:
            selected_class = CharacterClass.WARRIOR
        elif interaction is not None:
            selected_class = interaction.choose(
                "직업 선택",
                tuple(
                    MenuOption(
                        label,
                        f"HP {stats.max_hp} · MP {stats.max_mp} · "
                        f"{_CHARACTER_DESCRIPTIONS[candidate]}",
                        candidate,
                    )
                    for candidate, label, _, stats in _CHARACTER_OPTIONS
                ),
                subtitle="주인공의 역할을 선택하세요",
                allow_back=True,
            )
            if selected_class is None:
                raise EOFError("직업 선택이 취소되었습니다")
        elif key_reader is not None:
            selected_class = _prompt_for_character_menu(
                key_reader=key_reader,
                stdout=output_stream,
                frame_writer=frame_writer,
            )
            if selected_class is None:
                raise EOFError("직업 선택이 취소되었습니다")
        else:
            selected_class = _prompt_for_character(
                stdin=input_stream, stdout=output_stream
            )
    if hero_name is None:
        if headless:
            hero_name = next(
                default_name
                for candidate, _, default_name, _ in _CHARACTER_OPTIONS
                if candidate is selected_class
            )
        elif interaction is not None:
            class_label = next(
                label
                for candidate, label, _, _ in _CHARACTER_OPTIONS
                if candidate is selected_class
            )
            hero_name = interaction.input_text(
                "주인공 이름",
                subtitle=f"{class_label} · 모험 중 표시할 이름을 정하세요",
                validate=validate_hero_name,
            )
            if hero_name is None:
                raise EOFError("주인공 이름 입력이 취소되었습니다")
        elif isinstance(key_reader, PosixKeyReader):
            if frame_writer is None:
                hero_name = key_reader.read_text_line(output_stream, "주인공 이름: ")
            else:
                class_label = next(
                    label
                    for candidate, label, _, _ in _CHARACTER_OPTIONS
                    if candidate is selected_class
                )

                def redraw_name(value: str) -> None:
                    shown_value = sanitize_terminal_text(value) if value else ""
                    frame_writer(
                        render_text_screen(
                            "주인공 이름",
                            (
                                f"이름 › {shown_value}▌",
                                f"{class_label} · 모험 중 표시할 이름을 정하세요",
                            ),
                            hint="한글·영문 최대 24칸 · Enter 확정 · Esc 뒤로",
                            width=_screen_width(),
                            height=_screen_height(),
                        )
                    )

                hero_name = key_reader.read_text_line(
                    output_stream,
                    "",
                    redraw=redraw_name,
                    accept_input=lambda: _screen_height() >= 8,
                )
        else:
            output_stream.write("주인공 이름: ")
            output_stream.flush()
            raw_name = input_stream.readline()
            if raw_name == "":
                raise EOFError("주인공 이름 입력이 종료되었습니다")
            hero_name = raw_name
    if hero_name is None:
        raise AssertionError("hero name selection did not produce a name")
    validated_name = validate_hero_name(hero_name)
    if identity_profile is None and interaction is not None and not headless:
        identity_profile = _prompt_identity_textual(interaction)
    selected_identity = identity_profile or _DEFAULT_IDENTITY_PROFILE
    initial = _starting_world(selected_class, validated_name)
    archive = HistoryArchive(history_root) if history_root is not None else None
    run_number: int | None = None

    def ensure_history_run() -> int:
        nonlocal run_number
        if archive is None:
            raise AssertionError("history archive is unavailable")
        if run_number is None:
            run_number = archive.create_run(
                {
                    "seed": seed,
                    "character_class": selected_class.value,
                    "character_class_ko": next(
                        label
                        for candidate, label, _, _ in _CHARACTER_OPTIONS
                        if candidate is selected_class
                    ),
                    "hero_id": HERO_ID,
                    "hero_name": validated_name,
                    "identity": selected_identity.to_json(),
                    "event_log": str(output) if output is not None else "",
                }
            )
        return run_number

    def ai_chooser(world: WorldState, actor_id: str) -> ControlledAction:
        return ControlledAction(
            _choose_ai_intent(world, actor_id),
            "baseline_policy",
            "policy.baseline",
        )

    chooser: Chooser
    observers: list[HourObserver] = []
    hourly_traces: dict[int, TickTrace] = {}

    def remember_trace(completed_hours: int, trace: TickTrace) -> None:
        hourly_traces[completed_hours] = trace

    if archive is not None:

        def record_hour(
            completed_hours: int, hourly: EngineSimulationResult
        ) -> None:
            current_run_number = ensure_history_run()
            trace = hourly_traces[completed_hours]
            template = next(
                (
                    item
                    for item in LIFE_EVENT_CATALOG
                    if item.id == trace.story_resolution.event.template_id
                ),
                None,
            )
            story_projections = (
                (
                    {
                        "kind": "story_resolution",
                        "scene": template.display_text_ko,
                        "opportunity": trace.story_intent.kind.value,
                        "evidence_ids": [
                            value
                            for value in (
                                trace.story_intent.candidate_id,
                                trace.story_resolution.event.template_id,
                            )
                            if value is not None
                        ],
                    },
                )
                if template is not None
                else ()
            )
            archive.append_hourly(
                current_run_number,
                {
                    "day": (completed_hours - 1) // 24 + 1,
                    "hour": (completed_hours - 1) % 24,
                    "tick": completed_hours - 1,
                    "events": [
                        *(to_json_value(event) for event in hourly.events),
                        *story_projections,
                    ],
                    "party": [
                        {
                            "id": adventurer.id,
                            "name": adventurer.name,
                            "level": adventurer.level,
                            "exp": adventurer.exp,
                            "hp": adventurer.stats.hp,
                            "mp": adventurer.stats.mp,
                            "alive": adventurer.alive,
                        }
                        for adventurer in (
                            hourly.final_state.adventurers[actor_id]
                            for actor_id in (
                                hourly.final_state.party.member_ids
                                if hourly.final_state.party is not None
                                else ()
                            )
                        )
                    ],
                },
            )
            if completed_hours % 24 == 0:
                archive.append_daily_summary(
                    current_run_number,
                    {
                        "day": completed_hours // 24,
                        "survivors": sum(
                            adventurer.alive
                            for adventurer in (
                                hourly.final_state.adventurers[actor_id]
                                for actor_id in (
                                    hourly.final_state.party.member_ids
                                    if hourly.final_state.party is not None
                                    else ()
                                )
                            )
                        ),
                    },
                )

        observers.append(record_hour)
    if headless:
        chooser = ai_chooser
    else:
        rendered_event_count = 0

        def interactive_chooser(world: WorldState, actor_id: str) -> ControlledAction:
            if interaction is not None:
                return _prompt_for_intent_textual(
                    world,
                    actor_id,
                    interaction=interaction,
                    identity_profile=selected_identity,
                    commentary_provider=commentary_provider,
                )
            if key_reader is not None:
                return _prompt_for_intent_menu(
                    world,
                    actor_id,
                    key_reader=key_reader,
                    stdout=output_stream,
                    frame_writer=frame_writer,
                )
            return ControlledAction(
                _prompt_for_intent(
                    world, actor_id, stdin=input_stream, stdout=output_stream
                ),
                "user",
                "user.selected",
            )

        chooser = interactive_chooser

        def render_hour(completed_hours: int, hourly: EngineSimulationResult) -> None:
            nonlocal rendered_event_count
            rendered_event_count += len(hourly.events)
            if frame_writer is not None or interaction is not None:
                return
            status = "완료" if completed_hours == total_hours else "진행 중"
            output_stream.write(
                render_simulation(
                    tuple(_event_view(event, hourly.final_state) for event in hourly.events),
                    _adventurer_views(hourly.final_state),
                    RunSummary(
                        seed,
                        max(1, (completed_hours + 23) // 24),
                        rendered_event_count,
                        f"{status} ({completed_hours}/{total_hours}시간)",
                    ),
                    width=80,
                )
            )

        observers.append(render_hour)

    def observe_hour(
        completed_hours: int, hourly: EngineSimulationResult
    ) -> None:
        for observer in observers:
            observer(completed_hours, hourly)

    recent_scene_summaries_ko: list[str] = []

    def present_story_then_continue(world: WorldState, trace: TickTrace) -> bool:
        canonical_story = render_turn_story(
            world,
            trace.action_events,
            controllers={
                proposal.actor_id: proposal.controller for proposal in trace.proposals
            },
            story_event_text=_story_event_text(trace),
        )
        if interaction is not None and not headless:
            request = _turn_story_request(
                world,
                trace,
                selected_identity,
                tuple(recent_scene_summaries_ko[-8:]),
            )

            def produce_story_lines() -> tuple[str, ...]:
                try:
                    projected = story_provider(request)
                except Exception:
                    projected = local_turn_story(request)
                return (
                    *projected.story_ko.splitlines(),
                    "",
                    "── 이번 시간 ──",
                    *canonical_story[1:],
                )

            interaction.show_story_from(
                f"{canonical_story[0]} · 한 시간의 이야기",
                produce_story_lines,
            )
            recent_scene_summaries_ko.append(
                sanitize_terminal_text(" ".join(canonical_story[1:]))[:800]
            )
        if trace_continue_decider is None:
            return True
        return trace_continue_decider(world, trace)

    result = _run_hours(
        initial,
        seed=seed,
        hours=total_hours,
        chooser=chooser,
        observer=observe_hour if observers else None,
        direct_hero_only=not headless,
        story_director=story_director,
        continue_decider=continue_decider,
        trace_continue_decider=present_story_then_continue,
        trace_observer=remember_trace,
    )
    party = result.final_state.party
    if party is None:
        raise ValueError("world has no runtime party")
    selected_hero = result.final_state.adventurers[party.selected_hero_id]
    completed_hours = result.final_state.tick - initial.tick
    final_world_digest = _world_digest(result.final_state)
    if archive is not None and run_number is not None and not selected_hero.alive:
        if selected_hero.death_cause == "dungeon_hazard":
            ending_story = (
                f"{selected_hero.name}은 던전의 위험으로 쓰러졌다. "
                "그 죽음은 되돌릴 수 없으며, 이 이야기는 여기서 끝난다."
            )
        else:
            ending_story = (
                f"{selected_hero.name}은 모험 도중 영원히 쓰러졌다. "
                "그 죽음은 되돌릴 수 없으며, 이 이야기는 여기서 끝난다."
            )
        archive.record_character_end(
            run_number,
            {
                "character_id": selected_hero.id,
                "ending": "death",
                "story": ending_story,
            },
        )
    if output is not None:
        event_path = _output_log_path(output)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=event_path.parent, prefix=f".{event_path.name}.", suffix=".tmp"
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        try:
            log = EventLog(temporary_path)
            log.append(
                {
                    "record_type": "run_init",
                    "version": _CURRENT_SCHEMA_VERSION,
                    "schema_version": _CURRENT_SCHEMA_VERSION,
                    "rules_version": _CURRENT_RULES_VERSION,
                    "world_id": "glassfrontier",
                    "seed": seed,
                    "hero_id": HERO_ID,
                    "hero_name": validated_name,
                    "identity": selected_identity.to_json(),
                    "character_class": selected_class.value,
                    "hero_control": "delegated" if headless else "interactive",
                    "expected_tick_count": completed_hours,
                    "final_tick": result.final_state.tick,
                    "final_world_digest": final_world_digest,
                }
            )
            last_tick_hash: str | None = None
            for trace in result.traces:
                stored_tick = log.append(
                    {
                        "record_type": "tick",
                        "version": _CURRENT_SCHEMA_VERSION,
                        "tick": trace.story_intent.tick - 1,
                        "proposals": [
                            {
                                "actor_id": proposal.actor_id,
                                "action": proposal.intent.action.value
                                if isinstance(proposal.intent.action, ActionKind)
                                else str(proposal.intent.action),
                                "target_location_id": proposal.intent.target_location_id,
                                "quantity": proposal.intent.quantity,
                                "controller": proposal.controller,
                                "reason_code": proposal.reason_code,
                            }
                            for proposal in trace.proposals
                        ],
                        "action_events": [
                            to_json_value(event) for event in trace.action_events
                        ],
                        "story_facts": {key: list(values) for key, values in trace.facts},
                        "story_intent": to_json_value(trace.story_intent),
                        "story_resolution": {
                            "event": to_json_value(trace.story_resolution.event),
                            "story": to_json_value(trace.story_resolution.story),
                            "party_member_ids": list(
                                trace.story_resolution.world.party.member_ids
                                if trace.story_resolution.world.party is not None
                                else ()
                            ),
                        },
                    }
                )
                last_tick_hash = stored_tick.event_hash
            if last_tick_hash is None:
                raise ValueError("versioned runs require at least one completed tick")
            log.append(
                {
                    "record_type": "run_end",
                    "version": _CURRENT_SCHEMA_VERSION,
                    "expected_tick_count": completed_hours,
                    "final_tick": result.final_state.tick,
                    "final_world_digest": final_world_digest,
                    "last_tick_event_hash": last_tick_hash,
                }
            )
            with temporary_path.open("rb") as stream:
                os.fsync(stream.fileno())
            if force:
                os.replace(temporary_path, event_path)
            else:
                os.link(temporary_path, event_path)
        finally:
            temporary_path.unlink(missing_ok=True)
    final_status = "완료" if completed_hours == total_hours else "홈으로 종료"
    return SimulationResult(
        events=tuple(_event_view(event, result.final_state) for event in result.events),
        adventurers=_adventurer_views(result.final_state),
        summary=RunSummary(
            seed,
            max(1, (completed_hours + 23) // 24),
            len(result.events),
            final_status,
        ),
    )


def _event_fields(
    record: StoredEvent,
) -> tuple[int, int, str, str, str | None, int, dict[str, str], str | None]:
    event = record.event
    if not isinstance(event, dict):
        raise ValueError(f"event {record.seq} payload must be an object")
    tick = event.get("tick")
    next_tick = event.get("next_tick")
    action = event.get("action")
    actor = event.get("adventurer_id")
    target = event.get("target_location_id")
    quantity = event.get("quantity")
    if type(tick) is int and (tick < 0 or tick >= MAX_RECORDS):
        raise ValueError(f"event {record.seq} tick exceeds the supported limit")
    if type(tick) is not int:
        raise ValueError(f"event {record.seq} tick must be an integer")
    if type(next_tick) is not int or next_tick != tick + 1:
        raise ValueError(f"event {record.seq} next_tick must equal tick + 1")
    if not isinstance(actor, str) or not actor:
        raise ValueError(f"event {record.seq} must have a non-empty adventurer_id")
    if not isinstance(action, str):
        raise ValueError(f"event {record.seq} has an invalid action")
    if target is not None and not isinstance(target, str):
        raise ValueError(f"event {record.seq} has an invalid target_location_id")
    if type(quantity) is not int:
        raise ValueError(f"event {record.seq} has an invalid quantity")
    reason = event.get("reason")
    raw_details = event.get("details", [])
    if reason is not None and (not isinstance(reason, str) or not reason):
        raise ValueError(f"event {record.seq} has an invalid rejection reason")
    if not isinstance(raw_details, list):
        raise ValueError(f"event {record.seq} details must be a list")
    details: dict[str, str] = {}
    for item in raw_details:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not all(isinstance(value, str) for value in item)
        ):
            raise ValueError(f"event {record.seq} has invalid details")
        key, value = item
        if key in details:
            raise ValueError(f"event {record.seq} has duplicate detail keys")
        details[key] = value
    return tick, next_tick, actor, action, target, quantity, details, reason


def _positive_detail(record: StoredEvent, details: dict[str, str], key: str) -> int:
    value = details.get(key)
    if value is None or not value.isdecimal() or int(value) <= 0:
        raise ValueError(f"event {record.seq} has invalid {key}")
    return int(value)


def _reduce_stored_event(
    world: WorldState, record: StoredEvent, *, advance_tick: bool = True
) -> WorldState:
    tick, next_tick, actor, action, target, quantity, details, reason = _event_fields(
        record
    )
    if world.tick != tick:
        raise ValueError(f"event {record.seq} does not follow world tick {world.tick}")
    gather_yield = (
        _positive_detail(record, details, "resources_gathered")
        if action == ActionKind.GATHER.value and reason is None
        else 1
    )
    try:
        action_value: ActionKind | str = ActionKind(action)
    except ValueError:
        action_value = action
    intent = ActionIntent(actor, action_value, target_location_id=target, quantity=quantity)
    next_world, emitted = apply_intent(world, intent, gather_yield=gather_yield)
    if len(emitted) != 1 or to_json_value(emitted[0]) != record.event:
        raise ValueError(f"event {record.seq} does not match the engine result")
    return replace(next_world, tick=next_tick) if advance_tick else next_world


def _replay_action(
    world: WorldState, record: StoredEvent
) -> tuple[WorldState, DomainEvent]:
    tick, _, actor, action, target, quantity, details, reason = _event_fields(record)
    if world.tick != tick:
        raise ValueError(f"event {record.seq} does not follow world tick {world.tick}")
    gather_yield = (
        _positive_detail(record, details, "resources_gathered")
        if action == ActionKind.GATHER.value and reason is None
        else 1
    )
    try:
        action_value: ActionKind | str = ActionKind(action)
    except ValueError:
        action_value = action
    intent = ActionIntent(actor, action_value, target_location_id=target, quantity=quantity)
    before = world
    world, emitted = apply_intent(world, intent, gather_yield=gather_yield)
    if len(emitted) != 1:
        raise ValueError(f"event {record.seq} does not match the engine result")
    event = emitted[0]
    if isinstance(event, ActionSucceeded):
        raw_xp = details.get("xp_awarded")
        if raw_xp is None or not raw_xp.isdecimal() or int(raw_xp) > 25:
            raise ValueError(f"event {record.seq} has invalid xp_awarded")
        raw_damage = details.get("damage", "0")
        if not raw_damage.isdecimal():
            raise ValueError(f"event {record.seq} has invalid damage")
        world, event = apply_action_progression(
            before,
            world,
            event,
            xp_award=max(1, int(raw_xp)),
            hazard_damage=int(raw_damage),
        )
    return world, event


def _strict_replay_versioned(
    records: tuple[StoredEvent, ...], *, hash_verified: bool, expected_version: int
) -> SimulationResult:
    if len(records) < 3:
        raise ValueError("versioned replay requires run initialization, ticks, and run terminator")
    init = records[0].event
    init_keys = {
        "record_type",
        "version",
        "schema_version",
        "rules_version",
        "world_id",
        "seed",
        "hero_id",
        "hero_name",
        "character_class",
        "hero_control",
        "expected_tick_count",
        "final_tick",
        "final_world_digest",
    }
    if expected_version in {3, 4, 5}:
        init_keys.add("identity")
    if not isinstance(init, dict) or set(init) != init_keys:
        raise ValueError("invalid versioned run initialization")
    expected_rules_version = _VERSIONED_RULES_VERSIONS[expected_version]
    if (
        init["record_type"] != "run_init"
        or init["version"] != expected_version
        or init["schema_version"] != expected_version
        or init["rules_version"] != expected_rules_version
        or init["world_id"] != "glassfrontier"
        or init["hero_id"] != HERO_ID
        or type(init["seed"]) is not int
        or init["seed"] < 0
        or init["hero_control"] not in {"delegated", "interactive"}
        or type(init["expected_tick_count"]) is not int
        or init["expected_tick_count"] < 1
        or type(init["final_tick"]) is not int
        or not isinstance(init["final_world_digest"], str)
        or len(init["final_world_digest"]) != 64
    ):
        raise ValueError("unsupported versioned run initialization")
    if expected_version in {3, 4, 5}:
        identity = init["identity"]
        if not isinstance(identity, dict):
            raise ValueError("versioned run identity must be an object")
        CharacterIdentityProfile.from_json(identity)
    terminator = records[-1].event
    if (
        not isinstance(terminator, dict)
        or set(terminator)
        != {
            "record_type",
            "version",
            "expected_tick_count",
            "final_tick",
            "final_world_digest",
            "last_tick_event_hash",
        }
        or type(terminator["record_type"]) is not str
        or type(terminator["version"]) is not int
        or type(terminator["expected_tick_count"]) is not int
        or type(terminator["final_tick"]) is not int
        or type(terminator["final_world_digest"]) is not str
        or type(terminator["last_tick_event_hash"]) is not str
    ):
        raise ValueError("versioned replay requires a canonical run terminator")
    tick_records = records[1:-1]
    if (
        terminator["record_type"] != "run_end"
        or terminator["version"] != expected_version
        or terminator["expected_tick_count"] != init["expected_tick_count"]
        or terminator["final_tick"] != init["final_tick"]
        or terminator["final_world_digest"] != init["final_world_digest"]
        or terminator["last_tick_event_hash"] != tick_records[-1].event_hash
        or len(tick_records) != init["expected_tick_count"]
    ):
        raise ValueError("versioned replay run terminator or tick count does not match")
    hero_name = validate_hero_name(init["hero_name"])
    character_class = CharacterClass(init["character_class"])
    seed = init["seed"]
    world = _starting_world(
        character_class,
        hero_name,
        content_revision=_VERSIONED_CONTENT_REVISIONS[expected_version],
    )
    if expected_version == 2:
        world = _legacy_v2_world(world)
    story = StoryState(relationship_scores={(HERO_ID, "rhea-vale"): _INITIAL_RHEA_RELATIONSHIP})
    scheduler = SimulationScheduler(
        seed=seed,
        legacy_all_actions_award_xp=expected_version == 2,
    )
    all_events: list[DomainEvent] = []
    for record in tick_records:
        payload = record.event
        if not isinstance(payload, dict) or set(payload) != {
            "record_type",
            "version",
            "tick",
            "proposals",
            "action_events",
            "story_facts",
            "story_intent",
            "story_resolution",
        }:
            raise ValueError(f"record {record.seq} must be a canonical tick")
        if (
            payload.get("version") != expected_version
            or type(payload["tick"]) is not int
            or payload["tick"] != world.tick
        ):
            raise ValueError(f"record {record.seq} has an invalid tick envelope")
        raw_proposals = payload.get("proposals")
        if not isinstance(raw_proposals, list):
            raise ValueError(f"record {record.seq} proposals must be a list")
        intents: list[ActionIntent] = []
        party_before = world.party
        if party_before is None:
            raise ValueError("strict replay world has no party")
        for raw in raw_proposals:
            if not isinstance(raw, dict) or set(raw) != {
                "actor_id",
                "action",
                "target_location_id",
                "quantity",
                "controller",
                "reason_code",
            }:
                raise ValueError(f"record {record.seq} has an invalid proposal")
            controlled = ControlledAction(
                ActionIntent(
                    raw["actor_id"],
                    ActionKind(raw["action"]),
                    target_location_id=raw["target_location_id"],
                    quantity=raw["quantity"],
                ),
                raw["controller"],
                raw["reason_code"],
            )
            is_hero = controlled.actor_id == party_before.selected_hero_id
            if is_hero and init["hero_control"] == "interactive":
                allowed_provenance = {
                    ("user", "user.selected"),
                    ("baseline_policy", "policy.baseline"),
                }
            else:
                allowed_provenance = {("baseline_policy", "policy.baseline")}
            if (
                controlled.controller,
                controlled.reason_code,
            ) not in allowed_provenance:
                raise ValueError(f"record {record.seq} has invalid controller provenance")
            intents.append(
                ActionIntent(
                    raw["actor_id"],
                    ActionKind(raw["action"]),
                    target_location_id=raw["target_location_id"],
                    quantity=raw["quantity"],
                )
            )
        expected_actor_order = tuple(
            actor_id
            for actor_id in party_before.member_ids
            if world.adventurers[actor_id].alive
        )
        if tuple(intent.adventurer_id for intent in intents) != expected_actor_order:
            raise ValueError(
                f"record {record.seq} proposals are not in canonical party order"
            )
        hourly = scheduler.run_hour(world, intents)
        if [to_json_value(event) for event in hourly.events] != payload.get("action_events"):
            raise ValueError(f"record {record.seq} action events do not match the engine result")
        action_world = hourly.final_state
        party = action_world.party
        if party is None:
            raise ValueError("strict replay world has no party")
        hero = action_world.adventurers[party.selected_hero_id]
        available_locations = (hero.location_id,)
        available_quests = (
            ("echoes-at-emberfall",)
            if hero.location_id == "emberfall-quest-hall"
            else ()
        )
        completed_objectives = (
            ("echoes-at-emberfall",)
            if any(
                isinstance(event, ActionSucceeded)
                and event.adventurer_id == HERO_ID
                and event.action is ActionKind.GATHER
                and hero.location_id == "mossreach"
                for event in hourly.events
            )
            else ()
        )
        story = _apply_objective_relationship(story, bool(completed_objectives))
        facts = {
            "available_location_ids": list(available_locations),
            "available_quest_ids": list(available_quests),
            "completed_objective_quest_ids": list(completed_objectives),
            "relationship_score": [
                str(story.relationship_score(HERO_ID, "rhea-vale"))
            ],
        }
        if payload.get("story_facts") != facts:
            raise ValueError(f"record {record.seq} story facts do not match observed facts")
        raw_intent = payload.get("story_intent")
        if not isinstance(raw_intent, dict) or set(raw_intent) != {
            "version",
            "candidate_id",
            "kind",
            "tick",
            "hero_id",
            "reason_code",
            "quest_id",
            "companion_id",
        }:
            raise ValueError(f"record {record.seq} has a noncanonical story intent")
        selected = StoryIntent(
            version=raw_intent["version"],
            candidate_id=raw_intent["candidate_id"],
            kind=StoryIntentKind(raw_intent["kind"]),
            tick=raw_intent["tick"],
            hero_id=raw_intent["hero_id"],
            reason_code=raw_intent["reason_code"],
            quest_id=raw_intent["quest_id"],
            companion_id=raw_intent["companion_id"],
        )
        resolution = resolve_story_intent(
            action_world,
            story,
            selected,
            LIFE_EVENT_CATALOG,
            available_location_ids=available_locations,
            available_quest_ids=available_quests,
            completed_objective_quest_ids=completed_objectives,
        )
        expected_resolution = {
            "event": to_json_value(resolution.event),
            "story": to_json_value(resolution.story),
            "party_member_ids": list(
                resolution.world.party.member_ids
                if resolution.world.party is not None
                else ()
            ),
        }
        if payload.get("story_resolution") != expected_resolution:
            raise ValueError(
                f"record {record.seq} story resolution does not match the engine result"
            )
        expected_tick = {
            "record_type": "tick",
            "version": expected_version,
            "tick": world.tick,
            "proposals": raw_proposals,
            "action_events": [to_json_value(event) for event in hourly.events],
            "story_facts": facts,
            "story_intent": to_json_value(selected),
            "story_resolution": expected_resolution,
        }
        if payload != expected_tick:
            raise ValueError(f"record {record.seq} does not match the canonical tick payload")
        world = resolution.world
        story = resolution.story
        all_events.extend(hourly.events)
        if not world.adventurers[HERO_ID].alive and record is not tick_records[-1]:
            raise ValueError("replay contains records after selected hero became dead")
    digest = (
        _legacy_v2_world_digest(world)
        if expected_version == 2
        else _world_digest(world)
    )
    if world.tick != init["final_tick"] or digest != init["final_world_digest"]:
        raise ValueError("versioned replay final world commitment does not match")
    replay_status = "해시 검증 완료" if hash_verified else "스키마 검증 완료"
    return SimulationResult(
        tuple(_event_view(event, world) for event in all_events),
        _adventurer_views(world),
        RunSummary(seed, max(1, (world.tick + 23) // 24), len(all_events), replay_status),
    )


def _default_replay(*, event_log: Path, verify_hash: bool) -> SimulationResult:
    log = EventLog(event_log)
    records = log.verify() if verify_hash else log.read()
    if (
        records
        and isinstance(records[0].event, dict)
        and records[0].event.get("record_type") == "run_init"
    ):
        schema_version = records[0].event.get("schema_version")
        if type(schema_version) is not int or schema_version not in {2, 3, 4, 5}:
            raise ValueError("unsupported versioned run initialization")
        return _strict_replay_versioned(
            records,
            hash_verified=verify_hash,
            expected_version=schema_version,
        )
    world = create_initial_world()
    if records:
        first_actor = _event_fields(records[0])[2]
        if first_actor.startswith("hero-"):
            try:
                character_class = CharacterClass(first_actor.removeprefix("hero-"))
            except ValueError as error:
                raise ValueError(f"unknown starting hero {first_actor}") from error
            world = _starting_world(character_class)
    index = 0
    display_events: list[DomainEvent] = []
    while index < len(records):
        tick = _event_fields(records[index])[0]
        if tick != world.tick:
            raise ValueError(f"expected replay tick {world.tick}, got {tick}")
        tick_records: list[StoredEvent] = []
        while index < len(records) and _event_fields(records[index])[0] == tick:
            tick_records.append(records[index])
            index += 1
        party = world.party
        if party is None:
            raise ValueError("replay world has no runtime party")
        expected_actor_ids = {
            actor_id
            for actor_id in party.member_ids
            if world.adventurers[actor_id].alive
        }
        actor_ids = tuple(_event_fields(record)[2] for record in tick_records)
        if len(actor_ids) != len(set(actor_ids)):
            duplicate = next(actor for actor in actor_ids if actor_ids.count(actor) > 1)
            raise ValueError(f"duplicate action for {duplicate} at tick {tick}")
        if set(actor_ids) != expected_actor_ids or len(actor_ids) != len(expected_actor_ids):
            raise ValueError(
                "replay hourly batch requires exactly one action from every living current "
                "party member"
            )
        replayed_events: list[DomainEvent] = []
        for record in tick_records:
            world, event = _replay_action(world, record)
            replayed_events.append(event)
        world, finalized_events = apply_legacy_life_events(world, tuple(replayed_events))
        for record, event in zip(tick_records, finalized_events, strict=True):
            if to_json_value(event) != record.event:
                raise ValueError(f"event {record.seq} does not match the engine result")
        display_events.extend(finalized_events)
        world = replace(world, tick=tick + 1)
        party = world.party
        if party is None:
            raise ValueError("replay world has no runtime party")
        if not world.adventurers[party.selected_hero_id].alive and index < len(records):
            raise ValueError("replay contains records after selected hero became dead")
    events = tuple(_event_view(event, world) for event in display_events)
    days = max(1, (world.tick + 23) // 24)
    status = "해시 검증 완료" if verify_hash else "미검증 재생 완료"
    return SimulationResult(
        events,
        _adventurer_views(world),
        RunSummary(0, days, len(events), status),
    )


def _history_text(value: object) -> str:
    return sanitize_terminal_text(str(value))


def _render_history_list(archive: HistoryArchive) -> str:
    lines = ["══ 회차 목록 ══"]
    runs = archive.list_runs()
    if not runs:
        lines.append("(저장된 회차 없음)")
    for run in runs:
        hero_name = _history_text(run.metadata.get("hero_name", "알 수 없음"))
        character_class = _history_text(
            run.metadata.get("character_class_ko", "알 수 없음")
        )
        lines.append(
            f"{run.run_number}회차 | {hero_name} · {character_class} | "
            f"기록 {run.record_count}건"
        )
    return "\n".join(lines) + "\n"


def _render_history_details(archive: HistoryArchive, run_number: int) -> str:
    run = archive.load_run(run_number)
    hero_name = _history_text(run.metadata.get("hero_name", "알 수 없음"))
    character_class = _history_text(
        run.metadata.get("character_class_ko", "알 수 없음")
    )
    lines = [
        f"══ {run.run_number}회차 히스토리 ══",
        f"주인공: {hero_name} · {character_class}",
    ]
    raw_identity = run.metadata.get("identity")
    if isinstance(raw_identity, Mapping):
        try:
            profile = CharacterIdentityProfile.from_json(raw_identity)
        except CharacterIdentityError:
            lines.append("조사 관점: 확인할 수 없는 기록")
        else:
            lines.append("조사 관점")
            lines.extend(_identity_labels_ko(profile))
    if not run.timeline:
        lines.append("(기록 없음)")
    for record in run.timeline:
        if record.kind == "hourly":
            day = record.payload.get("day", "?")
            hour = record.payload.get("hour", "?")
            hour_label = f"{hour:02d}" if type(hour) is int else "?"
            lines.append(f"\n── {day}일차 {hour_label}:00 ──")
            party = record.payload.get("party", [])
            actor_names = (
                {
                    raw_member.get("id"): _history_text(
                        raw_member.get("name", "알 수 없음")
                    )
                    for raw_member in party
                    if isinstance(raw_member, dict) and isinstance(raw_member.get("id"), str)
                }
                if isinstance(party, list)
                else {}
            )
            raw_events = record.payload.get("events", [])
            if isinstance(raw_events, list):
                for raw_event in raw_events:
                    if not isinstance(raw_event, dict):
                        continue
                    if raw_event.get("kind") != "story_resolution":
                        action = raw_event.get("action")
                        if not isinstance(action, str):
                            continue
                        actor_id = raw_event.get("adventurer_id")
                        actor_name = (
                            actor_names.get(actor_id, hero_name)
                            if isinstance(actor_id, str)
                            else hero_name
                        )
                        target = raw_event.get("target_location_id")
                        if action == ActionKind.MOVE.value and isinstance(target, str):
                            action_text = f"{location_direction_ko(target)} 이동했다."
                        else:
                            action_label = _ACTION_LABELS.get(action, _history_text(action))
                            action_text = f"‘{action_label}’에 나섰다."
                        lines.append(f"[행동] {actor_name} — {action_text}")
                        continue
                    scene = _history_text(raw_event.get("scene", NO_STORY_EVENT_TEXT))
                    opportunity_value = raw_event.get("opportunity", "no_op")
                    opportunity = {
                        "no_op": "새 사건 없음",
                        "offer_quest": "새 의뢰",
                        "complete_quest": "의뢰 완료",
                        "recruit_companion": "동료 합류",
                        "depart_companion": "동료 이탈",
                    }.get(
                        opportunity_value
                        if isinstance(opportunity_value, str)
                        else "",
                        "알 수 없는 사건",
                    )
                    evidence = raw_event.get("evidence_ids", [])
                    evidence_text = ", ".join(
                        _history_text(item) for item in evidence if isinstance(item, str)
                    ) if isinstance(evidence, list) else ""
                    lines.append(f"[이야기] {scene} · {opportunity}")
                    if evidence_text:
                        lines.append(f"근거 ID: {evidence_text}")
            if isinstance(party, list):
                for raw_member in party:
                    if not isinstance(raw_member, dict):
                        continue
                    lines.append(
                        f"{_history_text(raw_member.get('name', '알 수 없음'))} | "
                        f"Lv.{raw_member.get('level', '?')} "
                        f"EXP {raw_member.get('exp', '?')} | "
                        f"HP {raw_member.get('hp', '?')} | "
                        f"MP {raw_member.get('mp', '?')}"
                    )
        elif record.kind == "daily_summary":
            lines.append(
                f"\n[일일 요약] {record.payload.get('day', '?')}일차 · "
                f"생존 {record.payload.get('survivors', '?')}명"
            )
        elif record.kind == "character_end":
            lines.append(
                f"\n[이야기 종료] {_history_text(record.payload.get('story', '기록 없음'))}"
            )
    return "\n".join(lines) + "\n"


def _run_home(
    *,
    runner: Runner | None,
    replayer: ReplayRunner | None,
    stdin: TextIO,
    stdout: TextIO,
    history_root: Path,
    key_reader: KeyReader | None = None,
    frame_writer: Callable[[str], None] | None = None,
) -> int:
    if key_reader is not None:
        return _run_home_keyboard(
            runner=runner,
            stdin=stdin,
            stdout=stdout,
            history_root=history_root,
            key_reader=key_reader,
            frame_writer=frame_writer,
        )
    while True:
        stdout.write(
            "\n══ The Glass Frontier ══\n"
            "1. 시작하기\n"
            "2. 히스토리\n"
            "3. 종료\n"
            "선택: "
        )
        stdout.flush()
        choice = stdin.readline()
        if choice == "":
            return 0
        choice = choice.strip()
        if choice == "1":
            main(
                [
                    "simulate",
                    "--seed",
                    "42",
                    "--hours",
                    "1",
                    "--history-root",
                    str(history_root),
                ],
                runner=runner,
                replayer=replayer,
                stdin=stdin,
                stdout=stdout,
                home_history_root=history_root,
            )
            continue
        if choice == "2":
            archive = HistoryArchive(history_root)
            stdout.write(_render_history_list(archive))
            if not archive.list_runs():
                continue
            stdout.write("볼 회차 번호 (Enter: 뒤로): ")
            stdout.flush()
            raw_run_number = stdin.readline()
            if raw_run_number == "" or not raw_run_number.strip():
                continue
            try:
                run_number = int(raw_run_number)
                stdout.write(_render_history_details(archive, run_number))
            except (ValueError, OSError):
                stdout.write("회차 번호를 확인하세요.\n")
            continue
        if choice == "3":
            return 0
        stdout.write("1, 2, 3 중에서 선택하세요.\n")


def _run_home_keyboard(
    *,
    runner: Runner | None,
    stdin: TextIO,
    stdout: TextIO,
    history_root: Path,
    key_reader: KeyReader,
    frame_writer: Callable[[str], None] | None = None,
) -> int:
    home_choices = (
        MenuChoice("새 모험", "직업과 이름을 정해 첫 시간을 시작합니다"),
        MenuChoice("히스토리", "저장된 여정의 시간별 기록을 엽니다"),
        MenuChoice("종료", "터미널로 돌아갑니다"),
    )
    while True:
        selected = _select_menu(
            "메인 메뉴",
            home_choices,
            ("start", "history", "exit"),
            key_reader=key_reader,
            stdout=stdout,
            frame_writer=frame_writer,
            subtitle="새로운 여정을 시작하거나 기록된 모험을 열람합니다",
        )
        if selected in {None, "exit"}:
            return 0
        if selected == "history":
            archive = HistoryArchive(history_root)
            runs = archive.list_runs()
            if not runs:
                _show_text_screen(
                    "히스토리",
                    ("기록된 회차가 없습니다",),
                    key_reader=key_reader,
                    stdout=stdout,
                    frame_writer=frame_writer,
                )
                continue
            run_choices = tuple(
                MenuChoice(
                    f"{run.run_number}회차 · "
                    f"{_history_text(run.metadata.get('hero_name', '알 수 없음'))}",
                    f"{_history_text(run.metadata.get('character_class_ko', '직업 미상'))} · "
                    f"시드 {run.metadata.get('seed', '?')}",
                )
                for run in runs
            ) + (MenuChoice("홈으로"),)
            run_number = _select_menu(
                "히스토리 선택",
                run_choices,
                tuple(run.run_number for run in runs) + (None,),
                key_reader=key_reader,
                stdout=stdout,
                allow_back=True,
                frame_writer=frame_writer,
                subtitle="열어볼 여정을 선택하세요",
            )
            if isinstance(run_number, int):
                detail_lines = _render_history_details(archive, run_number).splitlines()
                if detail_lines and detail_lines[0].startswith("══"):
                    detail_lines = detail_lines[1:]
                _show_text_screen(
                    f"{run_number}회차 기록",
                    tuple(detail_lines),
                    key_reader=key_reader,
                    stdout=stdout,
                    frame_writer=frame_writer,
                )
            continue
        if runner is not None:
            result = runner(
                seed=42,
                days=None,
                hours=1,
                headless=False,
                output=None,
                force=False,
                character_class=None,
                history_root=history_root,
                stdin=stdin,
                stdout=stdout,
            )
            stdout.write(
                render_simulation(result.events, result.adventurers, result.summary, width=80)
            )
            continue

        def continue_after_hour(world: WorldState, trace: TickTrace) -> bool:
            context = _continue_context(world, trace, width=_screen_width())
            choice = _select_menu(
                "여정 계속",
                (
                    MenuChoice("다음 시간 진행", "파티가 각자의 다음 행동을 선택합니다"),
                    MenuChoice("여정 저장 후 홈으로", "현재 기록을 보존하고 홈으로 돌아갑니다"),
                ),
                (True, False),
                key_reader=key_reader,
                stdout=stdout,
                frame_writer=frame_writer,
                subtitle="다음 시간을 진행할까요?",
                context=context,
            )
            return choice is True

        output_path = _next_home_log_path(history_root.parent / "playthroughs")
        try:
            _default_run(
                seed=42,
                hours=MAX_RECORDS - 1,
                headless=False,
                output=output_path,
                force=False,
                history_root=history_root,
                stdin=stdin,
                stdout=stdout,
                key_reader=key_reader,
                trace_continue_decider=continue_after_hour,
                frame_writer=frame_writer,
            )
        except (EOFError, HeroNameError):
            continue


def _run_home_textual(
    *,
    runner: Runner | None,
    stdin: TextIO,
    stdout: TextIO,
    history_root: Path,
    interaction: TextualInteraction,
    story_provider: StoryProvider | None = None,
) -> int:
    commentary_provider: CommentaryProvider = deterministic_commentary
    rich_story_provider: StoryProvider = (
        HermesKimiTurnStoryAdapter().story if story_provider is None else story_provider
    )
    use_rich_story = not (
        story_provider is None and os.environ.get("AINCRAD_STORY_MODE") == "local"
    )
    selected_story_provider = rich_story_provider if use_rich_story else local_turn_story
    home_options = (
        MenuOption("새 모험", "직업과 이름을 정해 첫 시간을 시작합니다", "start"),
        MenuOption("설정", "이야기가 펼쳐지는 방식을 정합니다", "settings"),
        MenuOption("지난 이야기", "저장된 여정을 다시 읽습니다", "history"),
        MenuOption("종료", "터미널로 돌아갑니다", "exit"),
    )
    while True:
        selected = interaction.choose(
            "메인 메뉴",
            home_options,
            subtitle="새로운 여정을 시작하거나 기록된 모험을 열람합니다",
        )
        if selected in {None, "exit"}:
            return 0
        if selected == "settings":
            setting = interaction.choose(
                "설정",
                (
                    MenuOption[str | None](
                        "이야기 방식",
                        (
                            "현재: 풍부한 이야기"
                            if use_rich_story
                            else "현재: 간결한 이야기"
                        ),
                        "story-mode",
                    ),
                    MenuOption[str | None]("뒤로", "메인 메뉴로 돌아갑니다", None),
                ),
                subtitle="읽고 싶은 이야기의 분위기와 진행 방식을 정하세요",
                allow_back=True,
            )
            if setting == "story-mode":
                mode = interaction.choose(
                    "이야기 방식",
                    (
                        MenuOption[str | None](
                            "풍부한 이야기",
                            "장소와 인물의 분위기를 살린 긴 장면으로 읽습니다",
                            "rich",
                        ),
                        MenuOption[str | None](
                            "간결한 이야기",
                            "확정된 일을 중심으로 짧게 읽습니다",
                            "concise",
                        ),
                        MenuOption[str | None]("뒤로", "현재 방식을 유지합니다", None),
                    ),
                    subtitle="세계의 결과는 같고 표현 방식만 달라집니다",
                    allow_back=True,
                )
                if mode == "rich":
                    use_rich_story = True
                    selected_story_provider = rich_story_provider
                elif mode == "concise":
                    use_rich_story = False
                    selected_story_provider = local_turn_story
            continue
        if selected == "history":
            archive = HistoryArchive(history_root)
            runs = archive.list_runs()
            if not runs:
                interaction.show_text("히스토리", ("기록된 회차가 없습니다",))
                continue
            history_options: tuple[MenuOption[int | None], ...] = tuple(
                MenuOption[int | None](
                    f"{run.run_number}회차 · "
                    f"{_history_text(run.metadata.get('hero_name', '알 수 없음'))}",
                    f"{_history_text(run.metadata.get('character_class_ko', '직업 미상'))} · "
                    f"시드 {run.metadata.get('seed', '?')}",
                    run.run_number,
                )
                for run in runs
            ) + (MenuOption[int | None]("홈으로", "메인 메뉴로 돌아갑니다", None),)
            run_number = interaction.choose(
                "히스토리 선택",
                history_options,
                subtitle="열어볼 여정을 선택하세요",
                allow_back=True,
            )
            if isinstance(run_number, int):
                detail_lines = _render_history_details(archive, run_number).splitlines()
                if detail_lines and detail_lines[0].startswith("══"):
                    detail_lines = detail_lines[1:]
                interaction.show_text(f"{run_number}회차 기록", detail_lines)
            continue
        if runner is not None:
            result = runner(
                seed=42,
                days=None,
                hours=1,
                headless=False,
                output=None,
                force=False,
                character_class=None,
                history_root=history_root,
                stdin=stdin,
                stdout=stdout,
            )
            interaction.show_text(
                "모험 결과",
                render_simulation(
                    result.events,
                    result.adventurers,
                    result.summary,
                    width=80,
                ).splitlines(),
            )
            continue

        def continue_after_hour(world: WorldState, trace: TickTrace) -> bool:
            party = world.party
            if party is None:
                raise ValueError("world has no runtime party")
            if not world.adventurers[party.selected_hero_id].alive:
                return False
            choice = interaction.choose(
                "여정 계속",
                (
                    MenuOption(
                        "다음 시간 진행",
                        "파티가 각자의 다음 행동을 선택합니다",
                        True,
                    ),
                    MenuOption(
                        "여정 저장 후 홈으로",
                        "현재 기록을 보존하고 홈으로 돌아갑니다",
                        False,
                    ),
                ),
                subtitle="다음 시간을 진행할까요?",
                context=_continue_context(world, trace, width=80),
            )
            return choice is True

        output_path = _next_home_log_path(history_root.parent / "playthroughs")
        try:
            _default_run(
                seed=42,
                hours=MAX_RECORDS - 1,
                headless=False,
                output=output_path,
                force=False,
                history_root=history_root,
                commentary_provider=commentary_provider,
                story_provider=selected_story_provider,
                stdin=stdin,
                stdout=stdout,
                trace_continue_decider=continue_after_hour,
                interaction=interaction,
            )
        except (EOFError, HeroNameError):
            continue


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner | None = None,
    replayer: ReplayRunner | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    home_history_root: Path = Path("runs/history"),
    key_reader: KeyReader | None = None,
) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    input_stream = stdin if stdin is not None else sys.stdin
    stream = stdout if stdout is not None else sys.stdout
    if not arguments:
        try:
            if key_reader is not None:
                return _run_home(
                    runner=runner,
                    replayer=replayer,
                    stdin=input_stream,
                    stdout=stream,
                    history_root=home_history_root,
                    key_reader=key_reader,
                )
            if input_stream.isatty() and stream.isatty():
                app_result = AincradTextualApp(
                    lambda interaction: _run_home_textual(
                        runner=runner,
                        stdin=input_stream,
                        stdout=stream,
                        history_root=home_history_root,
                        interaction=interaction,
                    )
                ).run()
                return 0 if app_result is None else app_result
            stream.write(
                "대화형 화면에는 TTY가 필요합니다. "
                "자동 실행은 `aincrad simulate --headless`를 사용하세요.\n"
            )
            stream.flush()
            return 2
        except KeyboardInterrupt:
            return 130
    parser = build_parser()
    args = parser.parse_args(arguments)

    if args.command == "history":
        archive = HistoryArchive(args.history_root)
        if args.history_command == "list":
            stream.write(_render_history_list(archive))
            return 0
        stream.write(_render_history_details(archive, args.run_number))
        return 0

    if args.command == "simulate":
        if runner is not None:
            runner_arguments = {
                "seed": args.seed,
                "days": args.days,
                "hours": args.hours,
                "headless": args.headless,
                "output": args.output,
                "force": args.force,
                "character_class": (
                    CharacterClass(args.character_class)
                    if args.character_class is not None
                    else None
                ),
                "hero_name": args.hero_name,
                "history_root": args.history_root,
                "stdin": stdin,
                "stdout": stream,
            }
            signature = inspect.signature(runner)
            accepts_keywords = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            )
            if (
                args.hours is not None
                and not accepts_keywords
                and "hours" not in signature.parameters
            ):
                if args.hours % 24 != 0:
                    parser.error("legacy runner does not support sub-day --hours")
                if "days" not in signature.parameters:
                    parser.error("injected runner does not support --hours")
                runner_arguments["days"] = args.hours // 24
            accepted_arguments = (
                runner_arguments
                if accepts_keywords
                else {
                    key: value
                    for key, value in runner_arguments.items()
                    if key in signature.parameters
                }
            )
            result = runner(**accepted_arguments)
        else:
            result = _default_run(
                seed=args.seed,
                days=args.days,
                hours=args.hours,
                headless=args.headless,
                output=args.output,
                force=args.force,
                character_class=(
                    CharacterClass(args.character_class)
                    if args.character_class is not None
                    else None
                ),
                hero_name=args.hero_name,
                history_root=args.history_root,
                stdin=stdin,
                stdout=stream,
                key_reader=key_reader,
            )
    else:
        result = (replayer or _default_replay)(
            event_log=args.event_log,
            verify_hash=args.verify_hash,
        )
    if args.command != "simulate" or args.headless or runner is not None:
        stream.write(
            render_simulation(result.events, result.adventurers, result.summary, width=80)
        )
    return 0
