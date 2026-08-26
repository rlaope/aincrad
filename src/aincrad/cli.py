from __future__ import annotations

import argparse
import inspect
import os
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TextIO

from aincrad.agents import BaselinePolicy, Observation, Perception, perceive
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
from aincrad.domain.rules import apply_intent
from aincrad.history import HistoryArchive
from aincrad.persistence import MAX_RECORDS, EventLog, StoredEvent, to_json_value
from aincrad.simulation import (
    SimulationResult as EngineSimulationResult,
)
from aincrad.simulation import (
    SimulationScheduler,
    create_initial_world,
)
from aincrad.simulation.runtime import apply_action_progression, apply_life_events
from aincrad.tui import (
    AdventurerView,
    EventView,
    RunSummary,
    render_simulation,
    sanitize_terminal_text,
)


@dataclass(frozen=True)
class SimulationResult:
    events: tuple[EventView, ...]
    adventurers: tuple[AdventurerView, ...]
    summary: RunSummary


Runner = Callable[..., SimulationResult]
ReplayRunner = Callable[..., SimulationResult]
Chooser = Callable[[WorldState, str], ActionIntent]
HourObserver = Callable[[int, EngineSimulationResult], None]
_BASE_TIME = datetime(2025, 12, 31, 15, tzinfo=UTC)  # 2026-01-01 00:00 KST
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


def _starting_world(character_class: CharacterClass) -> WorldState:
    base = create_initial_world()
    _, _, name, stats = next(
        option for option in _CHARACTER_OPTIONS if option[0] is character_class
    )
    hero_id = f"hero-{character_class.value}"
    hero = Adventurer(
        id=hero_id,
        name=name,
        location_id="emberfall",
        stats=stats,
        gold=5,
        character_class=character_class,
    )
    return WorldState(
        base.tick,
        base.locations,
        {hero_id: hero},
        PartyState(hero_id, (hero_id,), cap=3),
    )


def _available_intents(world: WorldState, actor_id: str) -> tuple[ActionIntent, ...]:
    adventurer = world.adventurers[actor_id]
    location = world.locations[adventurer.location_id]
    intents = [
        ActionIntent(actor_id, ActionKind.MOVE, target_location_id=destination)
        for destination in sorted(location.connections)
    ]
    if location.kind.value == "hunting_ground":
        intents.append(ActionIntent(actor_id, ActionKind.GATHER))
    if location.kind.value == "town" and adventurer.resources > 0:
        intents.append(
            ActionIntent(actor_id, ActionKind.TRADE, quantity=adventurer.resources)
        )
    intents.extend(
        (
            ActionIntent(actor_id, ActionKind.REST),
            ActionIntent(actor_id, ActionKind.WAIT),
        )
    )
    return tuple(intents)


def _perception(world: WorldState, actor_id: str) -> Perception:
    adventurer = world.adventurers[actor_id]
    visible_entities = tuple(
        {"id": other.id, "kind": "adventurer", "display_name": other.name}
        for other in sorted(world.adventurers.values(), key=lambda item: item.id)
        if other.id != actor_id and other.location_id == adventurer.location_id
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
        )
    )


def _intent_label(intent: ActionIntent, world: WorldState) -> str:
    action = intent.action.value if isinstance(intent.action, ActionKind) else str(intent.action)
    if action == ActionKind.MOVE.value and intent.target_location_id is not None:
        return f"이동 → {world.locations[intent.target_location_id].name}"
    if action == ActionKind.TRADE.value:
        return f"거래 (자원 {intent.quantity}개 판매)"
    return _ACTION_LABELS.get(action, action)


def _choose_ai_intent(world: WorldState, actor_id: str) -> ActionIntent:
    adventurer = world.adventurers[actor_id]
    location = world.locations[adventurer.location_id]
    allowed = _available_intents(world, actor_id)

    def matching(
        action: ActionKind, target: str | None = None
    ) -> ActionIntent | None:
        return next(
            (
                intent
                for intent in allowed
                if intent.action is action
                and (target is None or intent.target_location_id == target)
            ),
            None,
        )

    if adventurer.resources > 0:
        trade = matching(ActionKind.TRADE)
        if trade is not None:
            return trade
    if adventurer.location_id == "mossreach":
        if adventurer.resources < 3:
            gather = matching(ActionKind.GATHER)
            if gather is not None:
                return gather
        return matching(ActionKind.MOVE, "emberfall") or BaselinePolicy().choose(
            _perception(world, actor_id), allowed
        )
    if location.kind.value == "town":
        destination = "mossreach" if adventurer.location_id == "emberfall" else "emberfall"
        move = matching(ActionKind.MOVE, destination)
        if move is not None:
            return move
    if location.stage is not None and not location.is_boss_room:
        forward = matching(ActionKind.MOVE, f"vault-{location.stage + 1}")
        if forward is not None:
            return forward
    return BaselinePolicy().choose(_perception(world, actor_id), allowed)


def _prompt_for_intent(
    world: WorldState, actor_id: str, *, stdin: TextIO, stdout: TextIO
) -> ActionIntent:
    adventurer = world.adventurers[actor_id]
    allowed = _available_intents(world, actor_id)
    day, hour = divmod(world.tick, 24)
    stdout.write(
        f"\n[{day + 1}일차 {hour:02d}:00] {adventurer.name} @ "
        f"{world.locations[adventurer.location_id].name}\n"
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


def _run_hours(
    initial: WorldState,
    *,
    seed: int,
    hours: int,
    chooser: Chooser,
    observer: HourObserver | None = None,
) -> EngineSimulationResult:
    world = initial
    events: list[DomainEvent] = []
    scheduler = SimulationScheduler(seed=seed)
    for completed_hours in range(1, hours + 1):
        party = world.party
        if party is None:
            raise ValueError("world has no runtime party")
        actor_ids = tuple(
            actor_id
            for actor_id in party.member_ids
            if world.adventurers[actor_id].alive
        )
        intents = tuple(chooser(world, actor_id) for actor_id in actor_ids)
        hourly = scheduler.run_hour(world, intents)
        world = hourly.final_state
        events.extend(hourly.events)
        if observer is not None:
            observer(completed_hours, hourly)
        party = world.party
        if party is None:
            raise ValueError("world has no runtime party")
        if not world.adventurers[party.selected_hero_id].alive:
            break
    return EngineSimulationResult(world, tuple(events))


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
    label = _ACTION_LABELS.get(action, action)
    if isinstance(event, ActionRejected):
        return f"{actor_name}: {label} 거부 ({event.reason})"
    if isinstance(event, ActionSucceeded) and event.details:
        detail = ", ".join(f"{key}={value}" for key, value in event.details)
        return f"{actor_name}: {label} 성공 ({detail})"
    return f"{actor_name}: {label} 성공"


def _event_view(event: DomainEvent, world: WorldState) -> EventView:
    action = event.action.value if isinstance(event.action, ActionKind) else str(event.action)
    return EventView(
        occurred_at=_BASE_TIME + timedelta(hours=event.tick),
        kind=_ACTION_LABELS.get(action, action),
        message=_event_message(event, world),
    )


def _adventurer_views(world: WorldState) -> tuple[AdventurerView, ...]:
    return tuple(
        AdventurerView(
            name=adventurer.name,
            location=world.locations[adventurer.location_id].name,
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
        for adventurer in sorted(world.adventurers.values(), key=lambda item: item.id)
    )


def _output_log_path(output: Path) -> Path:
    if output.suffix == ".jsonl":
        output.parent.mkdir(parents=True, exist_ok=True)
        return output
    output.mkdir(parents=True, exist_ok=True)
    return output / "events.jsonl"


def _default_run(
    *,
    seed: int,
    days: int | None = None,
    hours: int | None = None,
    headless: bool,
    output: Path | None,
    force: bool,
    character_class: CharacterClass | None = None,
    history_root: Path | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> SimulationResult:
    total_hours = hours if hours is not None else (days or 0) * 24
    if total_hours <= 0:
        raise ValueError("simulation duration must be positive")
    input_stream = stdin if stdin is not None else sys.stdin
    output_stream = stdout if stdout is not None else sys.stdout
    selected_class = character_class
    if selected_class is None:
        selected_class = (
            CharacterClass.WARRIOR
            if headless
            else _prompt_for_character(stdin=input_stream, stdout=output_stream)
        )
    initial = _starting_world(selected_class)
    archive = HistoryArchive(history_root) if history_root is not None else None
    run_number = (
        archive.create_run(
            {
                "seed": seed,
                "character_class": selected_class.value,
                "character_class_ko": next(
                    label
                    for candidate, label, _, _ in _CHARACTER_OPTIONS
                    if candidate is selected_class
                ),
                "hero_id": next(iter(initial.adventurers)),
                "hero_name": next(iter(initial.adventurers.values())).name,
            }
        )
        if archive is not None
        else None
    )

    def ai_chooser(world: WorldState, actor_id: str) -> ActionIntent:
        return _choose_ai_intent(world, actor_id)

    chooser: Chooser
    observers: list[HourObserver] = []
    if archive is not None and run_number is not None:

        def record_hour(
            completed_hours: int, hourly: EngineSimulationResult
        ) -> None:
            archive.append_hourly(
                run_number,
                {
                    "day": (completed_hours - 1) // 24 + 1,
                    "hour": (completed_hours - 1) % 24,
                    "tick": completed_hours - 1,
                    "events": [to_json_value(event) for event in hourly.events],
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
                        for adventurer in sorted(
                            hourly.final_state.adventurers.values(),
                            key=lambda item: item.id,
                        )
                    ],
                },
            )
            if completed_hours % 24 == 0:
                archive.append_daily_summary(
                    run_number,
                    {
                        "day": completed_hours // 24,
                        "survivors": sum(
                            adventurer.alive
                            for adventurer in hourly.final_state.adventurers.values()
                        ),
                    },
                )

        observers.append(record_hour)
    if headless:
        chooser = ai_chooser
    else:
        rendered_event_count = 0

        def interactive_chooser(world: WorldState, actor_id: str) -> ActionIntent:
            return _prompt_for_intent(
                world, actor_id, stdin=input_stream, stdout=output_stream
            )

        chooser = interactive_chooser

        def render_hour(completed_hours: int, hourly: EngineSimulationResult) -> None:
            nonlocal rendered_event_count
            rendered_event_count += len(hourly.events)
            status = "완료" if completed_hours == total_hours else "진행 중"
            output_stream.write(
                render_simulation(
                    tuple(_event_view(event, hourly.final_state) for event in hourly.events),
                    _adventurer_views(hourly.final_state),
                    RunSummary(
                        seed,
                        max(1, (total_hours + 23) // 24),
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

    result = _run_hours(
        initial,
        seed=seed,
        hours=total_hours,
        chooser=chooser,
        observer=observe_hour if observers else None,
    )
    party = result.final_state.party
    if party is None:
        raise ValueError("world has no runtime party")
    selected_hero = result.final_state.adventurers[party.selected_hero_id]
    if archive is not None and run_number is not None and not selected_hero.alive:
        archive.record_character_end(
            run_number,
            {
                "character_id": selected_hero.id,
                "ending": "death",
                "story": (
                    "모험가는 영원히 쓰러졌고, 이 이야기는 여기서 끝납니다. "
                    f"(tick={selected_hero.death_tick}, cause={selected_hero.death_cause})"
                ),
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
            for event in result.events:
                log.append(event)
            with temporary_path.open("rb") as stream:
                os.fsync(stream.fileno())
            if force:
                os.replace(temporary_path, event_path)
            else:
                os.link(temporary_path, event_path)
        finally:
            temporary_path.unlink(missing_ok=True)
    return SimulationResult(
        events=tuple(_event_view(event, result.final_state) for event in result.events),
        adventurers=_adventurer_views(result.final_state),
        summary=RunSummary(
            seed, max(1, (total_hours + 23) // 24), len(result.events), "완료"
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


def _stored_event_view(record: StoredEvent, world: WorldState) -> EventView:
    tick, _, actor, action, _, _, details, reason = _event_fields(record)
    label = _ACTION_LABELS.get(action, action)
    actor_state = world.adventurers.get(actor)
    actor_name = actor_state.name if actor_state is not None else actor
    if reason is not None:
        message = f"{actor_name}: {label} 거부 ({reason})"
    elif details:
        pairs = [f"{key}={value}" for key, value in details.items()]
        message = f"{actor_name}: {label} 성공 ({', '.join(pairs)})"
    else:
        message = f"{actor_name}: {label} 성공"
    return EventView(_BASE_TIME + timedelta(hours=tick), label, message)


def _default_replay(*, event_log: Path, verify_hash: bool) -> SimulationResult:
    log = EventLog(event_log)
    records = log.verify() if verify_hash else log.read()
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
        world, finalized_events = apply_life_events(world, tuple(replayed_events))
        for record, event in zip(tick_records, finalized_events, strict=True):
            if to_json_value(event) != record.event:
                raise ValueError(f"event {record.seq} does not match the engine result")
        world = replace(world, tick=tick + 1)
        party = world.party
        if party is None:
            raise ValueError("replay world has no runtime party")
        if not world.adventurers[party.selected_hero_id].alive and index < len(records):
            raise ValueError("replay contains records after selected hero became dead")
    events = tuple(_stored_event_view(record, world) for record in records)
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
    if not run.timeline:
        lines.append("(기록 없음)")
    for record in run.timeline:
        if record.kind == "hourly":
            day = record.payload.get("day", "?")
            hour = record.payload.get("hour", "?")
            hour_label = f"{hour:02d}" if type(hour) is int else "?"
            lines.append(f"\n── {day}일차 {hour_label}:00 ──")
            party = record.payload.get("party", [])
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
) -> int:
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


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner | None = None,
    replayer: ReplayRunner | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    home_history_root: Path = Path("runs/history"),
) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    input_stream = stdin if stdin is not None else sys.stdin
    stream = stdout if stdout is not None else sys.stdout
    if not arguments:
        return _run_home(
            runner=runner,
            replayer=replayer,
            stdin=input_stream,
            stdout=stream,
            history_root=home_history_root,
        )
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
                history_root=args.history_root,
                stdin=stdin,
                stdout=stream,
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
