from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest

from aincrad.agents import BaselineStoryDirector
from aincrad.cli import (
    ControlledAction,
    _apply_objective_relationship,
    _continue_context,
    _default_replay,
    _default_run,
    _next_home_log_path,
    _prompt_for_intent_menu,
    _ResizeGeneration,
    _run_hours,
    _select_menu,
    _show_text_screen,
    _starting_world,
    main,
)
from aincrad.domain import ActionIntent, ActionKind, CharacterClass
from aincrad.domain.identity import HERO_ID, HeroNameError
from aincrad.domain.story import StoryPerception, StoryState
from aincrad.persistence import EventLog
from aincrad.tui.keys import Key, PosixKeyReader
from aincrad.tui.layout import display_width
from aincrad.tui.screens import MenuChoice


class Keys:
    def __init__(self, *keys: Key) -> None:
        self.keys = iter(keys)

    def read_key(self) -> Key:
        return next(self.keys)


def test_resize_generation_preserves_signals_after_each_consumption() -> None:
    resize = _ResizeGeneration()

    resize.notify()
    assert resize.consume() is True
    resize.notify()
    assert resize.consume() is True
    assert resize.consume() is False


def test_injected_home_uses_korean_non_numeric_keyboard_menu(tmp_path: Path) -> None:
    output = StringIO()
    assert main(
        [],
        key_reader=Keys(Key.DOWN, Key.DOWN, Key.ENTER),
        stdin=StringIO(),
        stdout=output,
        home_history_root=tmp_path / "history",
    ) == 0
    rendered = output.getvalue()
    assert all(label in rendered for label in ("새 모험", "히스토리", "종료"))
    assert not any(prefix in rendered for prefix in ("1.", "2.", "3."))


def test_menu_remeasures_terminal_width_without_losing_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widths = iter((80, 40))
    frames: list[str] = []
    monkeypatch.setattr("aincrad.cli._screen_width", lambda: next(widths))

    selected = _select_menu(
        "크기 변경",
        (MenuChoice("첫 항목"), MenuChoice("둘째 항목")),
        ("first", "second"),
        key_reader=Keys(Key.DOWN, Key.ENTER),
        stdout=StringIO(),
        frame_writer=frames.append,
    )

    assert selected == "second"
    assert all(display_width(line) == 80 for line in frames[0].splitlines())
    assert all(display_width(line) == 40 for line in frames[1].splitlines())
    assert "◆ 둘째 항목" in frames[1]


def test_menu_ignores_hidden_navigation_and_selection_below_eight_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames: list[str] = []
    monkeypatch.setattr("aincrad.cli._screen_width", lambda: 40)
    monkeypatch.setattr("aincrad.cli._screen_height", lambda: 7)

    selected = _select_menu(
        "위험한 선택",
        (MenuChoice("안전"), MenuChoice("파괴")),
        ("safe", "destructive"),
        key_reader=Keys(Key.DOWN, Key.ENTER, Key.QUIT),
        stdout=StringIO(),
        frame_writer=frames.append,
    )

    assert selected is None
    assert len(frames) == 3
    assert all("안전" not in frame and "파괴" not in frame for frame in frames)


def test_text_screen_scrolls_within_terminal_height(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames: list[str] = []
    monkeypatch.setattr("aincrad.cli._screen_width", lambda: 40)
    monkeypatch.setattr("aincrad.cli._screen_height", lambda: 12)

    _show_text_screen(
        "긴 기록",
        tuple(f"기록 {index}" for index in range(10)),
        key_reader=Keys(Key.DOWN, Key.DOWN, Key.ENTER),
        stdout=StringIO(),
        frame_writer=frames.append,
    )

    assert len(frames) == 3
    assert "기록 0" in frames[0]
    assert "기록 0" not in frames[-1]
    assert "기록 5" in frames[-1]
    assert all(len(frame.splitlines()) <= 12 for frame in frames)
    assert all(
        display_width(line) == 40
        for frame in frames
        for line in frame.splitlines()
    )


def test_text_screen_accounts_for_wrapped_title_below_twelve_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames: list[str] = []
    monkeypatch.setattr("aincrad.cli._screen_width", lambda: 40)
    monkeypatch.setattr("aincrad.cli._screen_height", lambda: 8)

    _show_text_screen(
        "아주 긴 히스토리 상세 제목 " * 4,
        tuple(f"기록 {index}" for index in range(5)),
        key_reader=Keys(Key.ENTER),
        stdout=StringIO(),
        frame_writer=frames.append,
    )

    assert len(frames[-1].splitlines()) <= 8
    assert "기록 0" in frames[-1]


def test_action_menu_shows_decision_context_and_keeps_ai_last() -> None:
    world = _starting_world(CharacterClass.WARRIOR, "유리별")
    frames: list[str] = []

    selected = _prompt_for_intent_menu(
        world,
        HERO_ID,
        key_reader=Keys(Key.ENTER),
        stdout=StringIO(),
        frame_writer=frames.append,
    )

    assert selected.controller == "user"
    frame = frames[-1]
    assert "유리별의 행동" in frame
    assert "1일차 00:00" in frame
    assert "잿불마을" in frame
    assert "Emberfall" not in frame
    assert "HP 24/24" in frame
    assert "MP 8/8" in frame
    assert "Lv.1" in frame
    assert "파티 1명" in frame
    assert frame.rindex("AI 판단에 맡기기") > frame.rindex("온천 관찰")


def test_continue_context_keeps_korean_status_after_story() -> None:
    result = _run_hours(
        _starting_world(CharacterClass.WARRIOR, "유리별"),
        seed=7,
        hours=1,
        chooser=lambda _world, actor_id: ActionIntent(actor_id, ActionKind.WAIT),
        direct_hero_only=True,
    )

    context = _continue_context(result.final_state, result.traces[-1], width=80)

    assert context[0].startswith("1일차 01:00 · 잿불마을")
    assert "방금 끝난 한 시간의 기록을 확인했습니다." in context
    assert not any("xp_awarded" in line for line in context)


def test_interactive_hourly_projection_uses_only_owned_frame_writer() -> None:
    output = StringIO()
    frames: list[str] = []

    _default_run(
        seed=42,
        hours=1,
        headless=False,
        output=None,
        force=False,
        character_class=CharacterClass.WARRIOR,
        hero_name="유리별",
        key_reader=Keys(Key.ENTER),
        stdin=StringIO(),
        stdout=output,
        continue_decider=lambda _world: False,
        frame_writer=frames.append,
    )

    assert frames
    assert output.getvalue() == ""


def test_owned_name_input_frame_respects_live_terminal_height(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded = iter("별\r\r".encode())
    frames: list[str] = []
    monkeypatch.setattr("aincrad.cli._screen_width", lambda: 40)
    monkeypatch.setattr("aincrad.cli._screen_height", lambda: 8)

    _default_run(
        seed=42,
        hours=1,
        headless=False,
        output=None,
        force=False,
        character_class=CharacterClass.WARRIOR,
        hero_name=None,
        key_reader=PosixKeyReader(
            read_bytes=lambda _size: bytes((next(encoded),)),
        ),
        stdin=StringIO(),
        stdout=StringIO(),
        continue_decider=lambda _world: False,
        frame_writer=frames.append,
    )

    name_frames = [frame for frame in frames if "주인공 이름" in frame]
    assert name_frames
    assert all(len(frame.splitlines()) <= 8 for frame in name_frames)
    assert all("이름 ›" in frame for frame in name_frames)


def test_owned_name_input_rejects_hidden_text_and_enter_below_eight_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded = iter("숨김\r\r\x1b".encode())
    monkeypatch.setattr("aincrad.cli._screen_width", lambda: 40)
    monkeypatch.setattr("aincrad.cli._screen_height", lambda: 6)

    with pytest.raises(EOFError, match="cancelled"):
        _default_run(
            seed=42,
            hours=1,
            headless=False,
            output=None,
            force=False,
            character_class=CharacterClass.WARRIOR,
            hero_name=None,
            key_reader=PosixKeyReader(
                read_bytes=lambda _size: bytes((next(encoded),)),
            ),
            stdin=StringIO(),
            stdout=StringIO(),
            continue_decider=lambda _world: False,
            frame_writer=lambda _frame: None,
        )


def test_owned_name_input_rejects_zwj_sequence() -> None:
    encoded = iter("👩‍💻".encode())

    with pytest.raises(ValueError, match="control or format"):
        _default_run(
            seed=42,
            hours=1,
            headless=False,
            output=None,
            force=False,
            character_class=CharacterClass.WARRIOR,
            hero_name=None,
            key_reader=PosixKeyReader(
                read_bytes=lambda _size: bytes((next(encoded),)),
            ),
            stdin=StringIO(),
            stdout=StringIO(),
            continue_decider=lambda _world: False,
            frame_writer=lambda _frame: None,
        )


@pytest.mark.parametrize("raw", ["👍🏽🏽", "🚗🏽", "🇰🏽"])
def test_owned_name_input_rejects_invalid_modifier_sequence(raw: str) -> None:
    encoded = iter((raw + "\r").encode())

    with pytest.raises(HeroNameError, match="unsupported Unicode sequence"):
        _default_run(
            seed=42,
            hours=1,
            headless=False,
            output=None,
            force=False,
            character_class=CharacterClass.WARRIOR,
            hero_name=None,
            key_reader=PosixKeyReader(
                read_bytes=lambda _size: bytes((next(encoded),)),
            ),
            stdin=StringIO(),
            stdout=StringIO(),
            continue_decider=lambda _world: False,
            frame_writer=lambda _frame: None,
        )


def test_starting_world_uses_stable_hero_and_keeps_candidates_outside_party() -> None:
    world = _starting_world(CharacterClass.MAGE, "나의 영웅")
    assert world.party is not None
    assert world.party.selected_hero_id == HERO_ID
    assert world.party.member_ids == (HERO_ID,)
    assert world.adventurers[HERO_ID].name == "나의 영웅"
    assert "rhea-vale" in world.adventurers
    assert "rhea-vale" not in world.party.member_ids


def test_direct_mode_asks_only_hero_and_companion_uses_policy() -> None:
    world = _starting_world(CharacterClass.WARRIOR, "용사")
    world = replace(world, party=replace(world.party, member_ids=(HERO_ID, "rhea-vale")))
    asked: list[str] = []

    def choose(current, actor_id: str) -> ControlledAction:
        asked.append(actor_id)
        return ControlledAction(ActionIntent(actor_id, ActionKind.WAIT), "user", "user.selected")

    result = _run_hours(world, seed=5, hours=1, chooser=choose, direct_hero_only=True)
    assert asked == [HERO_ID]
    assert [proposal.actor_id for proposal in result.proposals] == [HERO_ID, "rhea-vale"]
    assert result.proposals[1].controller == "baseline_policy"


def test_director_receives_story_perception_exactly_once_per_hour() -> None:
    received: list[object] = []

    class Director(BaselineStoryDirector):
        def choose(self, perception, candidates):
            received.append(perception)
            return super().choose(perception, candidates)

    _run_hours(
        _starting_world(CharacterClass.WARRIOR, "용사"),
        seed=3,
        hours=1,
        chooser=lambda world, actor_id: ControlledAction(
            ActionIntent(actor_id, ActionKind.WAIT), "test", "test.wait"
        ),
        story_director=Director(),
    )
    assert len(received) == 1
    assert isinstance(received[0], StoryPerception)


def test_scheduler_result_is_identical_under_intent_arrival_permutation() -> None:
    world = _starting_world(CharacterClass.WARRIOR, "용사")
    world = replace(world, party=replace(world.party, member_ids=(HERO_ID, "rhea-vale")))
    intents = (
        ActionIntent(HERO_ID, ActionKind.WAIT),
        ActionIntent("rhea-vale", ActionKind.WAIT),
    )
    from aincrad.simulation import SimulationScheduler

    assert SimulationScheduler(77).run_hour(world, intents) == SimulationScheduler(77).run_hour(
        world, reversed(intents)
    )


def test_new_log_round_trips_name_seed_and_replay_uses_no_controllers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "events.jsonl"
    simulated = _default_run(
        seed=9182,
        hours=2,
        headless=True,
        output=path,
        force=False,
        character_class=CharacterClass.TANK,
        hero_name="한별",
    )
    records = EventLog(path).verify()
    assert records[0].event["record_type"] == "run_init"
    assert records[0].event["seed"] == 9182
    assert records[0].event["hero_name"] == "한별"
    tick = records[1].event
    assert tick["record_type"] == "tick"
    assert tick["proposals"][0]["actor_id"] == HERO_ID
    assert "story_intent" in tick and "story_resolution" in tick

    def forbidden_policy(*args):
        raise AssertionError("policy called")

    def forbidden_director(*args):
        raise AssertionError("director called")

    monkeypatch.setattr("aincrad.cli.BaselinePolicy.choose", forbidden_policy)
    monkeypatch.setattr("aincrad.cli.BaselineStoryDirector.choose", forbidden_director)
    replayed = _default_replay(event_log=path, verify_hash=True)
    assert replayed.adventurers == simulated.adventurers
    assert replayed.summary.seed == 9182
    assert any(view.name == "한별" for view in replayed.adventurers)


def test_invalid_custom_name_creates_no_output_or_history(tmp_path: Path) -> None:
    output = tmp_path / "events.jsonl"
    history = tmp_path / "history"
    with pytest.raises(ValueError):
        _default_run(
            seed=1,
            hours=1,
            headless=True,
            output=output,
            force=False,
            character_class=CharacterClass.WARRIOR,
            hero_name="bad\x00name",
            history_root=history,
        )
    assert not output.exists()
    assert not history.exists()


def test_home_log_paths_are_monotonic_and_never_reuse_an_existing_log(tmp_path: Path) -> None:
    log_root = tmp_path / "logs"
    first = _next_home_log_path(log_root)
    first.parent.mkdir(parents=True)
    first.write_text("occupied", encoding="utf-8")

    second = _next_home_log_path(log_root)

    assert first.name == "playthrough-000001.jsonl"
    assert second.name == "playthrough-000002.jsonl"
    assert second != first


def test_v2_replay_rejects_rehashed_controller_provenance_tampering(tmp_path: Path) -> None:
    original = tmp_path / "original.jsonl"
    tampered = tmp_path / "tampered.jsonl"
    _default_run(
        seed=7,
        hours=1,
        headless=True,
        output=original,
        force=False,
        character_class=CharacterClass.WARRIOR,
        hero_name="별빛",
    )
    events = [record.event for record in EventLog(original).verify()]
    events[1]["proposals"][0]["controller"] = "user"
    out = EventLog(tampered)
    out.append(events[0])
    stored_tick = out.append(events[1])
    terminator = dict(events[-1])
    terminator["last_tick_event_hash"] = stored_tick.event_hash
    out.append(terminator)

    with pytest.raises(ValueError, match="controller provenance"):
        _default_replay(event_log=tampered, verify_hash=True)


def test_v2_replay_rejects_rehashed_negative_seed(tmp_path: Path) -> None:
    original = tmp_path / "original.jsonl"
    tampered = tmp_path / "tampered.jsonl"
    _default_run(
        seed=7,
        hours=1,
        headless=True,
        output=original,
        force=False,
        character_class=CharacterClass.WARRIOR,
        hero_name="별빛",
    )
    events = [record.event for record in EventLog(original).verify()]
    events[0]["seed"] = -1
    for event in events:
        EventLog(tampered).append(event)

    with pytest.raises(ValueError, match="initialization"):
        _default_replay(event_log=tampered, verify_hash=True)


def test_v2_replay_rejects_rehashed_noncanonical_proposal_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_start = _starting_world

    def two_member_start(
        character_class: CharacterClass,
        hero_name: str | None = None,
        *,
        content_revision: str = "current",
    ):
        world = original_start(
            character_class, hero_name, content_revision=content_revision
        )
        assert world.party is not None
        return replace(
            world,
            party=replace(world.party, member_ids=(HERO_ID, "rhea-vale")),
        )

    monkeypatch.setattr("aincrad.cli._starting_world", two_member_start)
    original = tmp_path / "original.jsonl"
    _default_run(
        seed=7,
        hours=1,
        headless=True,
        output=original,
        force=False,
        character_class=CharacterClass.WARRIOR,
        hero_name="별빛",
    )
    records = EventLog(original).verify()
    tick = dict(records[1].event)
    tick["proposals"] = list(reversed(tick["proposals"]))
    tampered = EventLog(tmp_path / "reordered.jsonl")
    tampered.append(records[0].event)
    stored_tick = tampered.append(tick)
    terminator = dict(records[-1].event)
    terminator["last_tick_event_hash"] = stored_tick.event_hash
    tampered.append(terminator)

    with pytest.raises(ValueError, match="canonical party order"):
        _default_replay(event_log=tampered.path, verify_hash=True)


def test_objective_relationship_update_preserves_unrelated_relationships() -> None:
    story = StoryState(
        relationship_scores={(HERO_ID, "rhea-vale"): 55, (HERO_ID, "tovin-reed"): 33}
    )

    updated = _apply_objective_relationship(story, True)

    assert updated.relationship_score(HERO_ID, "rhea-vale") == 60
    assert updated.relationship_score(HERO_ID, "tovin-reed") == 33


def test_interactive_summary_uses_completed_hours_not_the_session_ceiling() -> None:
    output = StringIO()

    result = _default_run(
        seed=42,
        hours=99_999,
        headless=False,
        output=None,
        force=False,
        key_reader=Keys(Key.ENTER, Key.ENTER),
        stdin=StringIO("한별\n"),
        stdout=output,
        continue_decider=lambda _world: False,
    )

    assert result.summary.days == 1
    assert "4167일" not in output.getvalue()
