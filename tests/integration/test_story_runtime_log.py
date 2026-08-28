from __future__ import annotations

from pathlib import Path

import pytest

from aincrad.cli import ControlledAction, _default_replay, _default_run, _run_hours, _starting_world
from aincrad.domain import ActionIntent, ActionKind, CharacterClass
from aincrad.domain.identity import HERO_ID
from aincrad.domain.story import StoryIntentKind
from aincrad.persistence import EventLog, StoredEvent


def _write_rehashed_single_tick_log(
    target: Path, records: tuple[StoredEvent, ...], tick: dict[str, object]
) -> None:
    out = EventLog(target)
    out.append(records[0].event)
    stored_tick = out.append(tick)
    terminator = dict(records[-1].event)
    terminator["last_tick_event_hash"] = stored_tick.event_hash
    out.append(terminator)


def test_observed_quest_path_recruits_existing_fixture_candidate() -> None:
    route = {
        0: ActionIntent(
            HERO_ID, ActionKind.LIST_CONTRACTS, target_location_id="emberfall-quest-hall"
        ),
        1: ActionIntent(HERO_ID, ActionKind.MOVE, target_location_id="emberfall"),
        2: ActionIntent(HERO_ID, ActionKind.MOVE, target_location_id="mossreach-terraces"),
        3: ActionIntent(HERO_ID, ActionKind.MOVE, target_location_id="mossreach"),
        4: ActionIntent(HERO_ID, ActionKind.GATHER),
        5: ActionIntent(HERO_ID, ActionKind.WAIT),
    }

    def choose(world, actor_id: str) -> ControlledAction:
        return ControlledAction(route[world.tick], "test", "test.route")

    result = _run_hours(
        _starting_world(CharacterClass.WARRIOR, "별"),
        seed=8,
        hours=6,
        chooser=choose,
        direct_hero_only=True,
    )
    kinds = [trace.story_intent.kind for trace in result.traces]
    assert StoryIntentKind.OFFER_QUEST in kinds
    assert StoryIntentKind.COMPLETE_QUEST in kinds
    assert StoryIntentKind.RECRUIT_COMPANION in kinds
    assert result.final_state.party is not None
    assert result.final_state.party.member_ids == (HERO_ID, "rhea-vale")
    assert result.final_state.adventurers["rhea-vale"].id == "rhea-vale"


def test_validly_rehashed_tampered_proposal_fails_engine_replay(tmp_path: Path) -> None:
    original = tmp_path / "original.jsonl"
    _default_run(
        seed=4,
        hours=1,
        headless=True,
        output=original,
        force=False,
        character_class=CharacterClass.WARRIOR,
        hero_name="별",
    )
    records = EventLog(original).verify()
    tampered = tmp_path / "tampered.jsonl"
    tick = dict(records[1].event)
    proposals = [dict(item) for item in tick["proposals"]]
    proposals[0]["action"] = "rest"
    proposals[0]["target_location_id"] = None
    tick["proposals"] = proposals
    _write_rehashed_single_tick_log(tampered, records, tick)

    with pytest.raises(ValueError, match="engine result"):
        _default_replay(event_log=tampered, verify_hash=True)


def test_validly_rehashed_tampered_story_resolution_fails_replay(tmp_path: Path) -> None:
    original = tmp_path / "original.jsonl"
    _default_run(
        seed=4,
        hours=1,
        headless=True,
        output=original,
        force=False,
        character_class=CharacterClass.WARRIOR,
        hero_name="별",
    )
    records = EventLog(original).verify()
    tampered = tmp_path / "tampered.jsonl"
    tick = dict(records[1].event)
    resolution = dict(tick["story_resolution"])
    resolution["party_member_ids"] = [HERO_ID, "rhea-vale"]
    tick["story_resolution"] = resolution
    _write_rehashed_single_tick_log(tampered, records, tick)

    with pytest.raises(ValueError, match="story resolution"):
        _default_replay(event_log=tampered, verify_hash=True)


@pytest.mark.parametrize("removed_records", [1, 2])
def test_v2_replay_rejects_complete_line_tail_truncation(
    tmp_path: Path, removed_records: int
) -> None:
    original = tmp_path / "original.jsonl"
    _default_run(
        seed=4,
        hours=2,
        headless=True,
        output=original,
        force=False,
        character_class=CharacterClass.WARRIOR,
        hero_name="별",
    )
    records = EventLog(original).verify()
    truncated = EventLog(tmp_path / f"truncated-{removed_records}.jsonl")
    for record in records[:-removed_records]:
        truncated.append(record.event)

    with pytest.raises(ValueError, match="run terminator|tick count"):
        _default_replay(event_log=truncated.path, verify_hash=True)


@pytest.mark.parametrize("mutation", ["extra_tick_field", "missing_nullable_intent_field"])
def test_v2_replay_rejects_validly_rehashed_noncanonical_tick_payload(
    tmp_path: Path, mutation: str
) -> None:
    original = tmp_path / "original.jsonl"
    _default_run(
        seed=4,
        hours=1,
        headless=True,
        output=original,
        force=False,
        character_class=CharacterClass.WARRIOR,
        hero_name="별",
    )
    records = EventLog(original).verify()
    tick = dict(records[1].event)
    if mutation == "extra_tick_field":
        tick["unexpected"] = True
    else:
        story_intent = dict(tick["story_intent"])
        story_intent.pop("quest_id")
        tick["story_intent"] = story_intent
    tampered_path = tmp_path / f"{mutation}.jsonl"
    _write_rehashed_single_tick_log(tampered_path, records, tick)

    with pytest.raises(ValueError, match="canonical tick|story intent"):
        _default_replay(event_log=tampered_path, verify_hash=True)


def test_v2_schema_only_replay_does_not_claim_hash_verification(tmp_path: Path) -> None:
    event_log = tmp_path / "events.jsonl"
    _default_run(
        seed=4,
        hours=1,
        headless=True,
        output=event_log,
        force=False,
        character_class=CharacterClass.WARRIOR,
        hero_name="별",
    )

    replayed = _default_replay(event_log=event_log, verify_hash=False)

    assert replayed.summary.status == "스키마 검증 완료"


@pytest.mark.parametrize(("tick_index", "boolean_tick"), [(0, False), (1, True)])
def test_v2_replay_rejects_validly_rehashed_boolean_tick(
    tmp_path: Path, tick_index: int, boolean_tick: bool
) -> None:
    original = tmp_path / "original.jsonl"
    _default_run(
        seed=4,
        hours=2,
        headless=True,
        output=original,
        force=False,
        character_class=CharacterClass.WARRIOR,
        hero_name="별",
    )
    records = EventLog(original).verify()
    ticks = [dict(record.event) for record in records[1:-1]]
    ticks[tick_index]["tick"] = boolean_tick
    tampered = EventLog(tmp_path / f"boolean-{tick_index}.jsonl")
    tampered.append(records[0].event)
    last_tick = None
    for tick in ticks:
        last_tick = tampered.append(tick)
    assert last_tick is not None
    terminator = dict(records[-1].event)
    terminator["last_tick_event_hash"] = last_tick.event_hash
    tampered.append(terminator)

    with pytest.raises(ValueError, match="invalid tick envelope"):
        _default_replay(event_log=tampered.path, verify_hash=True)
