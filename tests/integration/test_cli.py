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
    _run_hours,
    _starting_world,
    main,
)
from aincrad.domain import ActionIntent, ActionKind, CharacterClass
from aincrad.history import HistoryArchive
from aincrad.persistence import GENESIS_HASH, EventLog, StoredEvent
from aincrad.simulation import SimulationScheduler, create_initial_world
from aincrad.simulation.scheduler import SimulationResult as EngineSimulationResult
from aincrad.tui import AdventurerView, EventView, RunSummary


def sample_result() -> SimulationResult:
    return SimulationResult(
        events=(EventView(datetime(2026, 8, 26, tzinfo=UTC), "이동", "도시에 도착"),),
        adventurers=(AdventurerView("Rhea Vale", "Emberfall", 100, 25, "대기"),),
        summary=RunSummary(seed=9, days=3, event_count=1, status="완료"),
    )


def test_no_arguments_opens_home_menu_and_can_exit(tmp_path: Path) -> None:
    stdout = StringIO()

    exit_code = main(
        [],
        stdin=StringIO("3\n"),
        stdout=stdout,
        home_history_root=tmp_path / "history",
    )

    assert exit_code == 0
    assert "The Glass Frontier" in stdout.getvalue()
    assert "1. 시작하기" in stdout.getvalue()
    assert "2. 히스토리" in stdout.getvalue()
    assert "3. 종료" in stdout.getvalue()


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
        stdin=StringIO("1\n3\n"),
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
        stdin=StringIO("2\n1\n3\n"),
        stdout=stdout,
        home_history_root=history_root,
    )

    assert exit_code == 0
    assert "══ 회차 목록 ══" in stdout.getvalue()
    assert "1회차 | 레아 베일 · 전사" in stdout.getvalue()
    assert "══ 1회차 히스토리 ══" in stdout.getvalue()


def test_interactive_projection_counts_dynamic_party_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_counts: list[int] = []

    def capture_projection(events, adventurers, summary, *, width: int) -> str:
        del events, adventurers, width
        event_counts.append(summary.event_count)
        return ""

    def dynamic_run(initial, *, seed, hours, chooser, observer=None):
        del seed, hours, chooser
        scheduler = SimulationScheduler(seed=7)
        world = initial
        assert world.party is not None
        hero_id = world.party.selected_hero_id
        batches = (
            (ActionIntent(hero_id, ActionKind.MOVE, target_location_id="mossreach"),),
            (
                ActionIntent(hero_id, ActionKind.WAIT),
                ActionIntent("rhea-companion", ActionKind.WAIT),
            ),
            (
                ActionIntent(hero_id, ActionKind.MOVE, target_location_id="emberfall"),
                ActionIntent("rhea-companion", ActionKind.WAIT),
            ),
            (ActionIntent(hero_id, ActionKind.WAIT),),
        )
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
        stdin=StringIO(),
        stdout=StringIO(),
    )

    assert event_counts == [1, 3, 5, 6]


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
    event = dict(EventLog(valid_log).verify()[0].event)
    details = [list(item) for item in event["details"]]
    exp_index = next(index for index, item in enumerate(details) if item[0] == "exp")
    details[exp_index][1] = "999"
    event["details"] = details
    event_log = tmp_path / "events.jsonl"
    EventLog(event_log).append(event)

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
    assert selected.target_location_id == "mossreach"
    lines = stdout.getvalue().splitlines()
    ai_option = next(line for line in lines if "AI 판단에 맡긴다" in line)
    assert ai_option.startswith(f"{len(allowed) + 1}.")
    assert "AI 선택" in stdout.getvalue()


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
    stdin = StringIO("1\n9\n")
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

    assert world.party.selected_hero_id == "hero-mage"
    assert world.party.member_ids == ("hero-mage",)


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
    assert "EXP 0" in rendered
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
    hero = world.adventurers["hero-mage"]
    fragile = replace(hero, location_id="mossreach", stats=replace(hero.stats, hp=1))
    world = replace(world, adventurers={fragile.id: fragile})
    calls: list[int] = []

    def chooser(current, actor_id: str) -> ActionIntent:
        calls.append(current.tick)
        return ActionIntent(actor_id, ActionKind.MOVE, target_location_id="vault-1")

    result = _run_hours(world, seed=1, hours=10, chooser=chooser)

    assert result.final_state.tick == 1
    assert result.final_state.adventurers[fragile.id].alive is False
    assert calls == [0]


def test_dead_hero_history_records_character_end_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_starting_world = _starting_world

    def fragile_world(character_class: CharacterClass):
        world = original_starting_world(character_class)
        hero = next(iter(world.adventurers.values()))
        fragile = replace(hero, location_id="mossreach", stats=replace(hero.stats, hp=1))
        return replace(world, adventurers={fragile.id: fragile})

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
    assert endings[0].payload["character_id"] == "hero-mage"
    assert endings[0].payload["ending"] == "death"


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
    life_events = {
        value
        for record in records
        if isinstance(record.event, dict)
        for key, value in record.event.get("details", [])
        if key == "life_event"
    }
    replayed = _default_replay(event_log=event_log, verify_hash=True)

    assert life_events >= {"companion-recruit-rhea", "companion-depart-rhea"}
    assert replayed.adventurers == simulated.adventurers


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
    incomplete = EventLog(incomplete_log)
    for record in records:
        event = record.event
        if isinstance(event, dict) and not (
            event.get("tick") == 1 and event.get("adventurer_id") == "rhea-companion"
        ):
            incomplete.append(event)

    with pytest.raises(ValueError, match="exactly one action"):
        _default_replay(event_log=incomplete_log, verify_hash=True)


def test_strict_replay_rejects_records_after_selected_hero_dies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_starting_world = _starting_world

    def fragile_world(character_class: CharacterClass):
        world = original_starting_world(character_class)
        hero = next(iter(world.adventurers.values()))
        fragile = replace(hero, stats=replace(hero.stats, hp=1))
        return replace(world, adventurers={fragile.id: fragile})

    monkeypatch.setattr("aincrad.cli._starting_world", fragile_world)
    scheduler = SimulationScheduler(seed=1)
    world = fragile_world(CharacterClass.MAGE)
    recruited = scheduler.run_hour(
        world,
        (
            ActionIntent(
                "hero-mage", ActionKind.MOVE, target_location_id="mossreach"
            ),
        ),
    )
    death_batch = scheduler.run_hour(
        recruited.final_state,
        (
            ActionIntent("hero-mage", ActionKind.MOVE, target_location_id="vault-1"),
            ActionIntent("rhea-companion", ActionKind.WAIT),
        ),
    )
    assert death_batch.final_state.adventurers["hero-mage"].alive is False
    assert death_batch.final_state.adventurers["rhea-companion"].alive is True
    trailing_batch = scheduler.run_hour(
        death_batch.final_state,
        (ActionIntent("rhea-companion", ActionKind.WAIT),),
    )
    event_log = tmp_path / "trailing-after-hero-death.jsonl"
    log = EventLog(event_log)
    for event in (*recruited.events, *death_batch.events, *trailing_batch.events):
        log.append(event)

    with pytest.raises(ValueError, match="selected hero.*dead"):
        _default_replay(event_log=event_log, verify_hash=True)


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
