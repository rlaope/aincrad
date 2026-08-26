from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TextIO

from aincrad.domain import (
    ActionIntent,
    ActionKind,
    ActionRejected,
    ActionSucceeded,
    DomainEvent,
    WorldState,
)
from aincrad.domain.rules import apply_intent
from aincrad.persistence import MAX_RECORDS, EventLog, StoredEvent, to_json_value
from aincrad.simulation import SimulationScheduler, create_initial_world
from aincrad.tui import AdventurerView, EventView, RunSummary, render_simulation


@dataclass(frozen=True)
class SimulationResult:
    events: tuple[EventView, ...]
    adventurers: tuple[AdventurerView, ...]
    summary: RunSummary


Runner = Callable[..., SimulationResult]
ReplayRunner = Callable[..., SimulationResult]
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
    simulate.add_argument("--days", type=_positive_int, required=True)
    simulate.add_argument("--headless", action="store_true")
    simulate.add_argument("--output", type=Path)
    simulate.add_argument(
        "--force", action="store_true", help="기존 events.jsonl을 명시적으로 교체"
    )

    replay_parser = commands.add_parser("replay", help="저장된 이벤트 로그 재생")
    replay_parser.add_argument("event_log", type=Path)
    replay_parser.add_argument("--verify-hash", action="store_true")
    return parser


def _intents_for_days(days: int) -> tuple[ActionIntent, ...]:
    cycle = (
        ActionIntent("rhea-vale", ActionKind.MOVE, target_location_id="mossreach"),
        ActionIntent("rhea-vale", ActionKind.GATHER),
        ActionIntent("rhea-vale", ActionKind.MOVE, target_location_id="emberfall"),
        ActionIntent("rhea-vale", ActionKind.TRADE, quantity=1),
        ActionIntent("tovin-reed", ActionKind.MOVE, target_location_id="mossreach"),
        ActionIntent("tovin-reed", ActionKind.GATHER),
        ActionIntent("tovin-reed", ActionKind.MOVE, target_location_id="emberfall"),
        ActionIntent("tovin-reed", ActionKind.WAIT),
        ActionIntent("sable-quill", ActionKind.REST),
        ActionIntent("sable-quill", ActionKind.WAIT),
    )
    count = days * 24
    return tuple(cycle[index % len(cycle)] for index in range(count))


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
    *, seed: int, days: int, headless: bool, output: Path | None, force: bool
) -> SimulationResult:
    del headless
    initial = create_initial_world()
    result = SimulationScheduler(seed=seed).run(initial, _intents_for_days(days))
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
        summary=RunSummary(seed, days, len(result.events), "완료"),
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
    if type(tick) is int and tick >= MAX_RECORDS:
        raise ValueError(f"event {record.seq} tick exceeds the supported limit")
    if type(tick) is not int or tick != record.seq - 1:
        raise ValueError(f"event {record.seq} tick must equal {record.seq - 1}")
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


def _reduce_stored_event(world: WorldState, record: StoredEvent) -> WorldState:
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
    return replace(next_world, tick=next_tick)


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
    for record in records:
        world = _reduce_stored_event(world, record)
    events = tuple(_stored_event_view(record, world) for record in records)
    days = max(1, (world.tick + 23) // 24)
    status = "해시 검증 완료" if verify_hash else "미검증 재생 완료"
    return SimulationResult(
        events,
        _adventurer_views(world),
        RunSummary(0, days, len(events), status),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner | None = None,
    replayer: ReplayRunner | None = None,
    stdout: TextIO | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    stream = stdout if stdout is not None else sys.stdout

    if args.command == "simulate":
        result = (runner or _default_run)(
            seed=args.seed,
            days=args.days,
            headless=args.headless,
            output=args.output,
            force=args.force,
        )
    else:
        result = (replayer or _default_replay)(
            event_log=args.event_log,
            verify_hash=args.verify_hash,
        )
    stream.write(render_simulation(result.events, result.adventurers, result.summary, width=80))
    return 0
