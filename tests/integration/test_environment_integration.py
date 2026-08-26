from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest

from aincrad.agents import BaselineStoryDirector
from aincrad.cli import (
    ControlledAction,
    _apply_objective_relationship,
    _default_replay,
    _default_run,
    _next_home_log_path,
    _run_hours,
    _starting_world,
    main,
)
from aincrad.domain import ActionIntent, ActionKind, CharacterClass
from aincrad.domain.identity import HERO_ID
from aincrad.domain.story import StoryPerception, StoryState
from aincrad.persistence import EventLog
from aincrad.tui.keys import Key


class Keys:
    def __init__(self, *keys: Key) -> None:
        self.keys = iter(keys)

    def read_key(self) -> Key:
        return next(self.keys)


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
    assert all(label in rendered for label in ("시작하기", "히스토리", "종료"))
    assert not any(prefix in rendered for prefix in ("1.", "2.", "3."))


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

    def two_member_start(character_class: CharacterClass, hero_name: str | None = None):
        world = original_start(character_class, hero_name)
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
