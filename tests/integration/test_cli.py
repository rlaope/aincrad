from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pytest

import aincrad.cli as cli_module
from aincrad.cli import (
    SimulationResult,
    _available_intents,
    _default_replay,
    _default_run,
    _event_fields,
    _prompt_for_intent,
    _prompt_for_intent_menu,
    _render_history_details,
    _run_hours,
    _starting_world,
    build_parser,
    main,
)
from aincrad.domain import ActionIntent, ActionKind, CharacterClass
from aincrad.domain.identity import CharacterIdentityProfile
from aincrad.history import HistoryArchive
from aincrad.persistence import GENESIS_HASH, EventLog, StoredEvent, to_json_value
from aincrad.simulation import SimulationScheduler, create_initial_world
from aincrad.simulation.scheduler import SimulationResult as EngineSimulationResult
from aincrad.tui import AdventurerView, EventView, RunSummary
from aincrad.tui.keys import Key


class Keys:
    def __init__(self, *keys: Key) -> None:
        self._keys = iter(keys)

    def read_key(self) -> Key:
        return next(self._keys)


def _write_rehashed_v2_log(
    target: Path,
    records: tuple[StoredEvent, ...],
    ticks: list[dict[str, object]],
) -> None:
    log = EventLog(target)
    log.append(records[0].event)
    last_tick = None
    for tick in ticks:
        last_tick = log.append(tick)
    assert last_tick is not None
    terminator = dict(records[-1].event)
    terminator["last_tick_event_hash"] = last_tick.event_hash
    log.append(terminator)


def sample_result() -> SimulationResult:
    return SimulationResult(
        events=(EventView(datetime(2026, 8, 26, tzinfo=UTC), "이동", "도시에 도착"),),
        adventurers=(AdventurerView("Rhea Vale", "Emberfall", 100, 25, "대기"),),
        summary=RunSummary(seed=9, days=3, event_count=1, status="완료"),
    )


@pytest.mark.parametrize(
    ("fixture_name", "event_count"),
    (
        ("v2_events_warrior.jsonl", 2),
        ("v3_events_warrior.jsonl", 2),
        ("v4_events_warrior.jsonl", 1),
        ("v5_events_warrior.jsonl", 1),
    ),
)
def test_committed_v2_to_v5_logs_remain_hash_verified_replayable(
    fixture_name: str, event_count: int
) -> None:
    event_log = Path(__file__).parents[1] / "fixtures" / fixture_name

    replayed = _default_replay(event_log=event_log, verify_hash=True)

    assert replayed.summary.status == "해시 검증 완료"
    assert replayed.summary.event_count == event_count


def test_movement_awards_zero_xp_and_round_trips_through_hash_replay(
    tmp_path: Path,
) -> None:
    event_log = tmp_path / "events.jsonl"

    _default_run(
        seed=7,
        hours=1,
        headless=True,
        output=event_log,
        force=False,
        character_class=CharacterClass.WARRIOR,
        hero_name="별",
        stdin=StringIO(),
        stdout=StringIO(),
    )

    records = EventLog(event_log).verify()
    assert records[0].event["schema_version"] == 7
    assert records[0].event["rules_version"] == 6
    tick = records[1].event
    hero_event = next(
        event
        for event in tick["action_events"]
        if event["adventurer_id"] == "hero"
    )
    assert hero_event["action"] == ActionKind.MOVE.value
    assert dict(hero_event["details"])["xp_awarded"] == "0"
    assert _default_replay(event_log=event_log, verify_hash=True).summary.status == "해시 검증 완료"


def test_identity_profile_round_trips_through_v3_log_and_history(tmp_path: Path) -> None:
    event_log = tmp_path / "events.jsonl"
    history_root = tmp_path / "history"
    identity = CharacterIdentityProfile(
        personality_description="차분히 분석하고 관찰한 뒤 신중하게 행동한다.",
        traits_description="동료와 조화를 이루며 약속을 끝까지 지킨다.",
    )

    simulated = _default_run(
        seed=7,
        hours=1,
        headless=True,
        output=event_log,
        force=False,
        character_class=CharacterClass.WARRIOR,
        hero_name="별",
        identity_profile=identity,
        history_root=history_root,
        stdin=StringIO(),
        stdout=StringIO(),
    )
    replayed = _default_replay(event_log=event_log, verify_hash=True)

    init = EventLog(event_log).verify()[0].event
    assert init["version"] == 7
    assert init["schema_version"] == 7
    assert init["rules_version"] == 6
    assert init["identity"] == identity.to_json()
    assert replayed.adventurers == simulated.adventurers
    assert HistoryArchive(history_root).load_run(1).metadata["identity"] == identity.to_json()
    history_text = _render_history_details(HistoryArchive(history_root), 1)
    assert "성격: 차분히 분석하고 관찰한 뒤 신중하게 행동한다." in history_text
    assert "특징: 동료와 조화를 이루며 약속을 끝까지 지킨다." in history_text


def test_simulate_parser_accepts_explicit_hero_name_option() -> None:
    args = build_parser().parse_args(
        [
            "simulate",
            "--seed",
            "7",
            "--hours",
            "1",
            "--headless",
            "--class",
            "warrior",
            "--hero-name",
            "한별",
        ]
    )

    assert args.hero_name == "한별"


def test_no_arguments_non_tty_fails_fast_with_headless_guidance(tmp_path: Path) -> None:
    stdout = StringIO()

    exit_code = main(
        [],
        stdin=StringIO(),
        stdout=stdout,
        home_history_root=tmp_path / "history",
    )

    assert exit_code == 2
    assert "aincrad simulate --headless" in stdout.getvalue()
    assert not any(prefix in stdout.getvalue() for prefix in ("1.", "2.", "3."))


def test_home_start_reuses_interactive_simulation_path(tmp_path: Path) -> None:
    calls: list[tuple[int | None, int | None, bool, Path | None]] = []

    def runner(
        *,
        seed: int,
        days: int | None,
        hours: int | None,
        headless: bool,
        history_root: Path | None,
        **_: object,
    ) -> SimulationResult:
        del seed
        calls.append((days, hours, headless, history_root))
        return sample_result()

    stdout = StringIO()
    history_root = tmp_path / "history"
    exit_code = main(
        [],
        runner=runner,
        key_reader=Keys(Key.ENTER, Key.DOWN, Key.DOWN, Key.ENTER),
        stdin=StringIO(),
        stdout=stdout,
        home_history_root=history_root,
    )

    assert exit_code == 0
    assert calls == [(None, 1, False, history_root)]
    assert "실행 요약" in stdout.getvalue()


def test_home_history_lists_and_opens_a_saved_run(tmp_path: Path) -> None:
    history_root = tmp_path / "history"
    archive = HistoryArchive(history_root)
    archive.create_run(
        {
            "seed": 42,
            "character_class": "warrior",
            "character_class_ko": "전사",
            "hero_id": "hero-warrior",
            "hero_name": "레아 베일",
        }
    )
    stdout = StringIO()

    exit_code = main(
        [],
        key_reader=Keys(
            Key.DOWN,
            Key.ENTER,
            Key.ENTER,
            Key.ENTER,
            Key.DOWN,
            Key.DOWN,
            Key.ENTER,
        ),
        stdin=StringIO(),
        stdout=stdout,
        home_history_root=history_root,
    )

    assert exit_code == 0
    rendered = stdout.getvalue()
    assert "히스토리 선택" in rendered
    assert "1회차 · 레아 베일" in rendered
    assert "1회차 기록" in rendered
    assert "══" not in rendered


def test_interactive_projection_counts_dynamic_party_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_counts: list[int] = []

    def capture_projection(events, adventurers, summary, *, width: int) -> str:
        del events, adventurers, width
        event_counts.append(summary.event_count)
        return ""

    def dynamic_run(initial, *, seed, hours, chooser, observer=None, **_):
        del seed, hours, chooser
        scheduler = SimulationScheduler(seed=7)
        world = initial
        assert world.party is not None
        hero_id = world.party.selected_hero_id
        batches = tuple((ActionIntent(hero_id, ActionKind.WAIT),) for _ in range(4))
        all_events = []
        for completed_hours, intents in enumerate(batches, start=1):
            hourly = scheduler.run_hour(world, intents)
            world = hourly.final_state
            all_events.extend(hourly.events)
            if observer is not None:
                observer(completed_hours, hourly)
        return EngineSimulationResult(world, tuple(all_events))

    monkeypatch.setattr(cli_module, "render_simulation", capture_projection)
    monkeypatch.setattr(cli_module, "_run_hours", dynamic_run)

    _default_run(
        seed=7,
        hours=4,
        headless=False,
        output=None,
        force=False,
        character_class=CharacterClass.WARRIOR,
        hero_name="별",
        stdin=StringIO(),
        stdout=StringIO(),
    )

    assert event_counts == [1, 2, 3, 4]


def test_simulate_injects_arguments_and_prints_projection(tmp_path: Path) -> None:
    calls: list[tuple[int | None, int | None, bool, Path | None, bool]] = []

    def runner(
        *,
        seed: int,
        days: int | None,
        hours: int | None,
        headless: bool,
        output: Path | None,
        force: bool,
    ) -> SimulationResult:
        del seed
        calls.append((days, hours, headless, output, force))
        return sample_result()

    stdout = StringIO()
    event_log = tmp_path / "events.jsonl"
    exit_code = main(
        ["simulate", "--seed", "9", "--days", "3", "--headless", "--output", str(event_log)],
        runner=runner,
        stdout=stdout,
    )

    assert exit_code == 0
    assert calls == [(3, None, True, event_log, False)]
    assert "2026-08-26" in stdout.getvalue()
    assert "Rhea Vale" in stdout.getvalue()
    assert "실행 요약" in stdout.getvalue()


def test_replay_injects_event_log_and_hash_verification(tmp_path: Path) -> None:
    event_log = tmp_path / "events.jsonl"
    event_log.write_text("", encoding="utf-8")
    calls: list[tuple[Path, bool]] = []

    def replayer(*, event_log: Path, verify_hash: bool) -> SimulationResult:
        calls.append((event_log, verify_hash))
        return sample_result()

    stdout = StringIO()
    exit_code = main(
        ["replay", str(event_log), "--verify-hash"],
        replayer=replayer,
        stdout=stdout,
    )

    assert exit_code == 0
    assert calls == [(event_log, True)]
    assert "이동" in stdout.getvalue()


@pytest.mark.parametrize(
    "arguments",
    [
        ["simulate", "--seed", "1", "--days", "0"],
        ["simulate", "--seed", "-1", "--days", "1"],
        ["simulate", "--seed", "not-a-number", "--days", "1"],
        ["replay"],
    ],
)
def test_invalid_arguments_exit_abnormally(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(arguments)

    assert raised.value.code != 0


def test_module_cli_smoke_is_deterministic_and_offline() -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = "src"
    command = [
        sys.executable,
        "-m",
        "aincrad",
        "simulate",
        "--seed",
        "17",
        "--days",
        "2",
        "--headless",
    ]

    first = subprocess.run(
        command,
        cwd=Path(__file__).parents[2],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    second = subprocess.run(
        command,
        cwd=Path(__file__).parents[2],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert first.returncode == 0, first.stderr
    assert first.stdout == second.stdout
    assert "시드 17" in first.stdout
    assert "2일" in first.stdout


def test_replay_rejects_non_integer_or_out_of_sequence_tick(tmp_path: Path) -> None:
    event_log = tmp_path / "events.jsonl"
    EventLog(event_log).append(
        {
            "tick": True,
            "next_tick": 1,
            "adventurer_id": "rhea-vale",
            "action": "wait",
            "target_location_id": None,
            "quantity": 1,
            "details": [],
        }
    )

    with pytest.raises(ValueError, match="tick"):
        _default_replay(event_log=event_log, verify_hash=True)


def test_replay_hash_flag_controls_chain_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event_log = tmp_path / "events.jsonl"
    _default_run(
        seed=3,
        hours=1,
        headless=True,
        output=event_log,
        force=False,
        character_class=CharacterClass.WARRIOR,
    )
    calls: list[str] = []
    original_read = EventLog.read
    original_verify = EventLog.verify

    def read(log: EventLog):
        calls.append("read")
        return original_read(log)

    def verify(log: EventLog):
        calls.append("verify")
        return original_verify(log)

    monkeypatch.setattr(EventLog, "read", read)
    monkeypatch.setattr(EventLog, "verify", verify)

    _default_replay(event_log=event_log, verify_hash=False)
    assert calls == ["read"]
    calls.clear()
    _default_replay(event_log=event_log, verify_hash=True)
    assert calls == ["verify"]


def test_replay_reconstructs_the_simulated_final_world(tmp_path: Path) -> None:
    event_log = tmp_path / "events.jsonl"
    simulated = _default_run(
        seed=42, days=2, headless=True, output=event_log, force=False
    )

    replayed = _default_replay(event_log=event_log, verify_hash=True)

    assert replayed.adventurers == simulated.adventurers
    assert replayed.summary.days == simulated.summary.days
    assert len(replayed.events) == len(simulated.events)


def test_simulate_publish_is_atomic_when_destination_appears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event_log = tmp_path / "events.jsonl"

    def competing_link(source: Path, destination: Path) -> None:
        del source
        destination.write_text("competing evidence", encoding="utf-8")
        raise FileExistsError(destination)

    monkeypatch.setattr("aincrad.cli.os.link", competing_link)

    with pytest.raises(FileExistsError):
        _default_run(seed=1, days=1, headless=True, output=event_log, force=False)
    assert event_log.read_text(encoding="utf-8") == "competing evidence"


def test_replay_rejects_event_outcome_that_disagrees_with_engine(tmp_path: Path) -> None:
    valid_log = tmp_path / "valid.jsonl"
    _default_run(
        seed=3,
        hours=1,
        headless=True,
        output=valid_log,
        force=False,
        character_class=CharacterClass.WARRIOR,
    )
    records = EventLog(valid_log).verify()
    tick = dict(records[1].event)
    events = [dict(item) for item in tick["action_events"]]
    events[0]["quantity"] = 999
    tick["action_events"] = events
    event_log = tmp_path / "events.jsonl"
    _write_rehashed_v2_log(event_log, records, [tick])

    with pytest.raises(ValueError, match="engine result"):
        _default_replay(event_log=event_log, verify_hash=True)


def test_replay_rejects_tick_beyond_supported_limit() -> None:
    record = StoredEvent(
        seq=100_002,
        event={
            "tick": 100_001,
            "next_tick": 100_002,
            "adventurer_id": "rhea-vale",
            "action": "wait",
            "target_location_id": None,
            "quantity": 1,
            "details": [],
        },
        prev_event_hash=GENESIS_HASH,
        event_hash=GENESIS_HASH,
    )

    with pytest.raises(ValueError, match="supported limit"):
        _event_fields(record)


def test_prompt_always_lists_ai_delegation_last() -> None:
    world = create_initial_world()
    allowed = _available_intents(world, "rhea-vale")
    stdin = StringIO(f"{len(allowed) + 1}\n")
    stdout = StringIO()

    selected = _prompt_for_intent(world, "rhea-vale", stdin=stdin, stdout=stdout)

    assert selected in allowed
    assert selected.action is ActionKind.MOVE
    assert selected.target_location_id == "mossreach-terraces"
    lines = stdout.getvalue().splitlines()
    ai_option = next(line for line in lines if "AI 판단에 맡긴다" in line)
    assert ai_option.startswith(f"{len(allowed) + 1}.")
    assert "AI 선택" in stdout.getvalue()


def test_keyboard_facility_incident_walk_returns_one_interaction_selection() -> None:
    world = _starting_world(CharacterClass.WARRIOR, "유리별")
    stdout = StringIO()

    selected = _prompt_for_intent_menu(
        world,
        "hero",
        key_reader=Keys(
            Key.ENTER,
            Key.DOWN,
            Key.DOWN,
            Key.DOWN,
            Key.DOWN,
            Key.ENTER,
            Key.ENTER,
            Key.DOWN,
            Key.ENTER,
        ),
        stdout=stdout,
    )

    assert selected.reason_code == "user.selected"
    assert selected.intent.action is ActionKind.ENGAGE_INCIDENT
    assert selected.intent.target_location_id == "emberfall-shop"
    assert selected.intent.interaction is not None
    assert selected.intent.interaction.path == (
        ("crate-opening", "inspect-crate"),
        ("crate-findings", "buy-discounted"),
    )
    assert "금 간 화물 상자" in stdout.getvalue()


def test_keyboard_repeated_escape_abandons_incident_without_recursing_or_mutating_world() -> None:
    world = _starting_world(CharacterClass.WARRIOR, "유리별")
    escape_walk = (
        Key.ENTER,
        Key.DOWN,
        Key.DOWN,
        Key.DOWN,
        Key.DOWN,
        Key.ENTER,
        Key.BACK,
    )
    selected = _prompt_for_intent_menu(
        world,
        "hero",
        key_reader=Keys(
            *escape_walk,
            *escape_walk,
            *escape_walk,
            Key.DOWN,
            Key.DOWN,
            Key.DOWN,
            Key.DOWN,
            Key.DOWN,
            Key.DOWN,
            Key.ENTER,
        ),
        stdout=StringIO(),
    )

    assert selected.intent.action is ActionKind.OBSERVE
    assert world.tick == 0
    assert world.adventurers["hero"].location_id == "emberfall"


def test_two_hours_collect_one_action_from_each_adventurer() -> None:
    calls: list[tuple[int, str]] = []

    def chooser(world, actor_id: str) -> ActionIntent:
        calls.append((world.tick, actor_id))
        return ActionIntent(actor_id, ActionKind.WAIT)

    result = _run_hours(create_initial_world(), seed=3, hours=2, chooser=chooser)

    assert result.final_state.tick == 2
    assert len(result.events) == 6
    assert calls == [
        (0, "rhea-vale"),
        (0, "sable-quill"),
        (0, "tovin-reed"),
        (1, "rhea-vale"),
        (1, "sable-quill"),
        (1, "tovin-reed"),
    ]


def test_interactive_new_run_selects_one_hero_then_runs_one_hour() -> None:
    stdin = StringIO("1\n별\n22\n")
    stdout = StringIO()

    exit_code = main(
        ["simulate", "--seed", "7", "--hours", "1"],
        stdin=stdin,
        stdout=stdout,
    )

    rendered = stdout.getvalue()
    assert exit_code == 0
    assert "캐릭터 선택" in rendered
    assert all(role in rendered for role in ("전사", "궁수", "마법사", "탱커"))
    assert rendered.count("AI 판단에 맡긴다") == 1
    assert rendered.count("AI 선택:") == 1
    assert "1일차 00:00" in rendered
    assert "이벤트 1건" in rendered


def test_starting_world_runtime_party_contains_only_selected_hero() -> None:
    world = _starting_world(CharacterClass.MAGE)

    assert world.party.selected_hero_id == "hero"
    assert world.party.member_ids == ("hero",)


def test_history_list_shows_monotonic_playthroughs(tmp_path: Path) -> None:
    history_root = tmp_path / "history"
    for seed in (7, 8):
        assert (
            main(
                [
                    "simulate",
                    "--seed",
                    str(seed),
                    "--hours",
                    "1",
                    "--headless",
                    "--history-root",
                    str(history_root),
                ],
                stdout=StringIO(),
            )
            == 0
        )

    stdout = StringIO()
    assert (
        main(
            ["history", "list", "--history-root", str(history_root)], stdout=stdout
        )
        == 0
    )

    rendered = stdout.getvalue()
    assert "회차 목록" in rendered
    assert "1회차" in rendered
    assert "2회차" in rendered
    assert "전사" in rendered


def test_history_show_renders_hourly_character_state(tmp_path: Path) -> None:
    history_root = tmp_path / "history"
    assert (
        main(
            [
                "simulate",
                "--seed",
                "7",
                "--hours",
                "1",
                "--headless",
                "--class",
                "mage",
                "--history-root",
                str(history_root),
            ],
            stdout=StringIO(),
        )
        == 0
    )

    stdout = StringIO()
    assert (
        main(
            ["history", "show", "1", "--history-root", str(history_root)],
            stdout=stdout,
        )
        == 0
    )

    rendered = stdout.getvalue()
    assert "1회차 히스토리" in rendered
    assert "세이블 퀼 · 마법사" in rendered
    assert "1일차 00:00" in rendered
    assert "Lv.1" in rendered
    assert "EXP " in rendered
    assert "HP 14" in rendered
    assert "MP 20" in rendered


def test_history_cli_sanitizes_unicode_format_controls_from_metadata_and_payloads(
    tmp_path: Path,
) -> None:
    history_root = tmp_path / "history"
    archive = HistoryArchive(history_root)
    run_number = archive.create_run(
        {
            "hero_id": "hero",
            "hero_name": "Hero\u202eName",
            "character_class_ko": "Ma\u2066ge",
        }
    )
    archive.append_hourly(
        run_number,
        {
            "day": 1,
            "hour": 0,
            "tick": 0,
            "events": [{"message": "hidden\u200btext"}],
            "party": [
                {
                    "id": "hero",
                    "name": "Party\u202dName",
                    "level": 1,
                    "exp": 0,
                    "hp": 0,
                    "mp": 0,
                    "alive": False,
                }
            ],
        },
    )
    archive.record_character_end(
        run_number,
        {"character_id": "hero", "ending": "death", "story": "Story\u2069End"},
    )

    rendered = StringIO()
    assert main(
        ["history", "list", "--history-root", str(history_root)], stdout=rendered
    ) == 0
    assert main(
        ["history", "show", "1", "--history-root", str(history_root)], stdout=rendered
    ) == 0

    output = rendered.getvalue()
    assert all(control not in output for control in ("\u202e", "\u2066", "\u202d", "\u2069"))
    assert "Hero�Name" in output
    assert "Ma�ge" in output
    assert "Party�Name" in output
    assert "Story�End" in output


def test_full_day_appends_24_hours_and_one_daily_summary(tmp_path: Path) -> None:
    history_root = tmp_path / "history"

    _default_run(
        seed=7,
        days=1,
        headless=True,
        output=None,
        force=False,
        history_root=history_root,
    )

    timeline = HistoryArchive(history_root).load_run(1).timeline
    assert sum(record.kind == "hourly" for record in timeline) == 24
    assert sum(record.kind == "daily_summary" for record in timeline) == 1
    assert timeline[-1].payload == {"day": 1, "survivors": 1}


def test_run_hours_stops_immediately_after_selected_hero_dies() -> None:
    world = _starting_world(CharacterClass.MAGE)
    hero = world.adventurers["hero"]
    fragile = replace(hero, location_id="mossreach-vaultgate", stats=replace(hero.stats, hp=1))
    world = replace(world, adventurers={fragile.id: fragile})
    calls: list[int] = []
    story_calls: list[int] = []

    def chooser(current, actor_id: str) -> ActionIntent:
        calls.append(current.tick)
        return ActionIntent(actor_id, ActionKind.MOVE, target_location_id="vault-1")

    result = _run_hours(
        world,
        seed=1,
        hours=10,
        chooser=chooser,
        trace_continue_decider=lambda current, _trace: (
            story_calls.append(current.tick) or True
        ),
    )

    assert result.final_state.tick == 1
    assert result.final_state.adventurers[fragile.id].alive is False
    assert calls == [0]
    assert story_calls == [1]


def test_dead_hero_history_records_character_end_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_starting_world = _starting_world

    def fragile_world(
        character_class: CharacterClass,
        hero_name: str | None = None,
        *,
        content_revision: str = "current",
    ):
        world = original_starting_world(
            character_class, hero_name, content_revision=content_revision
        )
        hero = world.adventurers["hero"]
        fragile = replace(
            hero, location_id="mossreach-vaultgate", stats=replace(hero.stats, hp=1)
        )
        return replace(world, adventurers={**world.adventurers, fragile.id: fragile})

    def enter_dungeon(world, actor_id: str) -> ActionIntent:
        del world
        return ActionIntent(actor_id, ActionKind.MOVE, target_location_id="vault-1")

    monkeypatch.setattr("aincrad.cli._starting_world", fragile_world)
    monkeypatch.setattr("aincrad.cli._choose_ai_intent", enter_dungeon)
    history_root = tmp_path / "history"

    _default_run(
        seed=1,
        hours=8,
        headless=True,
        output=None,
        force=False,
        character_class=CharacterClass.MAGE,
        history_root=history_root,
    )

    timeline = HistoryArchive(history_root).load_run(1).timeline
    endings = [record for record in timeline if record.kind == "character_end"]
    assert len(endings) == 1
    assert endings[0].payload["character_id"] == "hero"
    assert endings[0].payload["ending"] == "death"
    ending_story = endings[0].payload["story"]
    assert isinstance(ending_story, str)
    assert "던전의 위험으로 쓰러졌다" in ending_story
    assert "tick=" not in ending_story
    assert "dungeon_hazard" not in ending_story


def test_legacy_replay_projects_korean_without_internal_detail_keys(tmp_path: Path) -> None:
    world = create_initial_world()
    result = _run_hours(
        world,
        seed=7,
        hours=1,
        chooser=lambda _world, actor_id: ActionIntent(
            actor_id,
            ActionKind.MOVE,
            target_location_id="mossreach-terraces",
        ),
    )
    event_log = tmp_path / "legacy.jsonl"
    log = EventLog(event_log)
    for event in result.traces[0].action_events:
        log.append(to_json_value(event))

    replayed = _default_replay(event_log=event_log, verify_hash=True)
    rendered = "\n".join(event.message for event in replayed.events)

    assert "이끼자락 층계로 이동했다" in rendered
    assert "mossreach-terraces" not in rendered
    assert "destination=" not in rendered
    assert "xp_awarded" not in rendered
    assert "character_class=" not in rendered


@pytest.mark.parametrize("character_class", tuple(CharacterClass))
def test_strict_replay_round_trips_all_four_classes(
    tmp_path: Path, character_class: CharacterClass
) -> None:
    event_log = tmp_path / f"{character_class.value}.jsonl"
    simulated = _default_run(
        seed=11,
        hours=4,
        headless=True,
        output=event_log,
        force=False,
        character_class=character_class,
    )

    records = EventLog(event_log).verify()
    replayed = _default_replay(event_log=event_log, verify_hash=True)

    assert records[0].event["record_type"] == "run_init"
    assert all(record.event["record_type"] == "tick" for record in records[1:-1])
    assert records[-1].event["record_type"] == "run_end"
    assert replayed.adventurers == simulated.adventurers


@pytest.mark.parametrize("version", (2, 3, 4))
@pytest.mark.parametrize("field", ("version", "expected_tick_count", "final_tick"))
def test_strict_replay_rejects_boolean_run_end_integer_commitments(
    tmp_path: Path, version: int, field: str
) -> None:
    if version == 2:
        source = Path(__file__).parents[1] / "fixtures" / "v2_events_warrior.jsonl"
    else:
        source = tmp_path / "v3.jsonl"
        _default_run(
            seed=11,
            hours=1,
            headless=True,
            output=source,
            force=False,
            character_class=CharacterClass.WARRIOR,
        )
    records = EventLog(source).verify()
    malformed = EventLog(tmp_path / f"v{version}-{field}.jsonl")
    for record in records[:-1]:
        malformed.append(record.event)
    terminator = dict(records[-1].event)
    terminator[field] = True
    terminator["last_tick_event_hash"] = malformed.verify()[-1].event_hash
    malformed.append(terminator)

    with pytest.raises(ValueError, match="canonical run terminator"):
        _default_replay(event_log=malformed.path, verify_hash=True)


def test_strict_replay_rejects_incomplete_recruited_party_batch(tmp_path: Path) -> None:
    complete_log = tmp_path / "complete.jsonl"
    _default_run(
        seed=11,
        hours=2,
        headless=True,
        output=complete_log,
        force=False,
        character_class=CharacterClass.WARRIOR,
    )
    records = EventLog(complete_log).verify()
    incomplete_log = tmp_path / "incomplete.jsonl"
    ticks = [dict(record.event) for record in records[1:-1]]
    ticks[0]["proposals"] = []
    _write_rehashed_v2_log(incomplete_log, records, ticks)

    with pytest.raises(ValueError, match="canonical party order"):
        _default_replay(event_log=incomplete_log, verify_hash=True)


def test_strict_replay_rejects_records_after_selected_hero_dies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_starting_world = _starting_world

    def fragile_world(
        character_class: CharacterClass,
        hero_name: str | None = None,
        *,
        content_revision: str = "current",
    ):
        world = original_starting_world(
            character_class, hero_name, content_revision=content_revision
        )
        hero = world.adventurers["hero"]
        fragile = replace(
            hero,
            location_id="mossreach-vaultgate",
            stats=replace(hero.stats, hp=1),
        )
        return replace(world, adventurers={**world.adventurers, "hero": fragile})

    monkeypatch.setattr("aincrad.cli._starting_world", fragile_world)
    monkeypatch.setattr(
        "aincrad.cli._choose_ai_intent",
        lambda world, actor_id: ActionIntent(
            actor_id, ActionKind.MOVE, target_location_id="vault-1"
        ),
    )
    valid = tmp_path / "death.jsonl"
    _default_run(
        seed=1,
        hours=3,
        headless=True,
        output=valid,
        force=False,
        character_class=CharacterClass.MAGE,
    )
    records = EventLog(valid).verify()
    assert len(records) == 3
    trailing = EventLog(tmp_path / "trailing.jsonl")
    init = dict(records[0].event)
    init["expected_tick_count"] = 2
    init["final_tick"] = 2
    trailing.append(init)
    trailing.append(records[1].event)
    extra = trailing.append({"record_type": "tick", "version": 2, "tick": 1})
    terminator = dict(records[-1].event)
    terminator["expected_tick_count"] = 2
    terminator["final_tick"] = 2
    terminator["last_tick_event_hash"] = extra.event_hash
    trailing.append(terminator)

    with pytest.raises(ValueError, match="selected hero.*dead"):
        _default_replay(event_log=trailing.path, verify_hash=True)


def test_injected_legacy_runner_adapts_whole_days_without_none() -> None:
    legacy_elapsed_hours: list[int] = []

    def legacy_runner(*, seed: int, days: int, headless: bool, output, force: bool):
        del seed, headless, output, force
        legacy_elapsed_hours.append(days * 24)
        return sample_result()

    assert (
        main(
            ["simulate", "--seed", "3", "--hours", "48", "--headless"],
            runner=legacy_runner,
            stdout=StringIO(),
        )
        == 0
    )
    assert legacy_elapsed_hours == [48]


def test_injected_legacy_runner_rejects_sub_day_hours(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def legacy_runner(*, seed: int, days: int, headless: bool, output, force: bool):
        del seed, headless, output, force
        return sample_result()

    with pytest.raises(SystemExit) as raised:
        main(
            ["simulate", "--seed", "3", "--hours", "1", "--headless"],
            runner=legacy_runner,
        )

    assert raised.value.code == 2
    assert "legacy runner does not support sub-day --hours" in capsys.readouterr().err


def test_injected_modern_runner_receives_hours_and_new_options(tmp_path: Path) -> None:
    received: dict[str, object] = {}

    def extended_runner(
        *,
        seed: int,
        days: int | None,
        hours: int | None,
        headless: bool,
        output: Path | None,
        force: bool,
        character_class: CharacterClass | None,
        history_root: Path | None,
        stdin,
        stdout,
    ) -> SimulationResult:
        received.update(
            seed=seed,
            days=days,
            hours=hours,
            headless=headless,
            output=output,
            force=force,
            character_class=character_class,
            history_root=history_root,
            stdin=stdin,
            stdout=stdout,
        )
        return sample_result()

    history_root = tmp_path / "history"
    main(
        [
            "simulate",
            "--seed",
            "4",
            "--hours",
            "1",
            "--headless",
            "--class",
            "tank",
            "--history-root",
            str(history_root),
        ],
        runner=extended_runner,
        stdout=StringIO(),
    )
    assert received["character_class"] is CharacterClass.TANK
    assert received["history_root"] == history_root
    assert received["hours"] == 1


def test_schema_v7_replay_rejects_raw_text_in_a_rehashed_interaction_proposal(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.jsonl"
    _default_run(
        seed=7,
        hours=1,
        headless=True,
        output=source,
        force=False,
        character_class=CharacterClass.WARRIOR,
    )
    records = EventLog(source).verify()
    tick = dict(records[1].event)
    proposal = dict(tick["proposals"][0])
    proposal["raw_text"] = "절대 기록되면 안 되는 입력"
    tick["proposals"] = [proposal]
    malformed = tmp_path / "raw-text.jsonl"
    _write_rehashed_v2_log(malformed, records, [tick])

    with pytest.raises(ValueError, match="invalid proposal"):
        _default_replay(event_log=malformed, verify_hash=True)


def test_schema_v7_replay_rejects_boolean_proposal_quantity(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.jsonl"
    _default_run(
        seed=7,
        hours=1,
        headless=True,
        output=source,
        force=False,
        character_class=CharacterClass.WARRIOR,
    )
    records = EventLog(source).verify()
    tick = dict(records[1].event)
    proposal = dict(tick["proposals"][0])
    proposal["quantity"] = True
    tick["proposals"] = [proposal]
    malformed = tmp_path / "boolean-quantity.jsonl"
    _write_rehashed_v2_log(malformed, records, [tick])

    with pytest.raises(ValueError, match="invalid proposal quantity"):
        _default_replay(event_log=malformed, verify_hash=True)
