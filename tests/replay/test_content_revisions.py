from __future__ import annotations

from copy import deepcopy
from importlib.resources import files
from pathlib import Path

import pytest

import aincrad.content.fixtures as fixture_module
import aincrad.simulation.scenario as scenario_module
from aincrad.cli import _default_replay
from aincrad.content.actions import expected_action_kinds
from aincrad.content.fixtures import load_packaged_world_fixture
from aincrad.persistence import EventLog
from aincrad.simulation import create_initial_world


def test_packaged_loader_accepts_only_trusted_content_revisions() -> None:
    current = load_packaged_world_fixture()
    rules_v2 = load_packaged_world_fixture(revision="rules-v2")
    rules_v3 = load_packaged_world_fixture(revision="rules-v3")

    assert current["world_id"] == rules_v2["world_id"] == rules_v3["world_id"] == "glassfrontier"
    assert files("aincrad.content").joinpath(
        "data", "glassfrontier_world_rules_v2.json"
    ).is_file()
    assert files("aincrad.content").joinpath(
        "data", "glassfrontier_world_rules_v3.json"
    ).is_file()
    with pytest.raises(ValueError, match="unsupported content revision"):
        load_packaged_world_fixture(revision="rules-v3/../../outside")



def test_rules_v2_snapshot_validation_is_independent_of_evolved_current_action_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def evolved_action_kinds(location_id: str) -> tuple[str, ...]:
        expected = expected_action_kinds(location_id)
        return (*expected, "wait") if location_id == "emberfall-shop" else expected

    monkeypatch.setattr(fixture_module, "expected_action_kinds", evolved_action_kinds)

    frozen = fixture_module.load_packaged_world_fixture(revision="rules-v2")

    assert frozen["world_id"] == "glassfrontier"


def test_rules_v3_snapshot_validation_is_independent_of_evolved_current_action_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def evolved_action_kinds(location_id: str) -> tuple[str, ...]:
        expected = expected_action_kinds(location_id)
        return (*expected, "wait") if location_id == "emberfall-shop" else expected

    monkeypatch.setattr(fixture_module, "expected_action_kinds", evolved_action_kinds)

    frozen = fixture_module.load_packaged_world_fixture(revision="rules-v3")

    assert frozen["world_id"] == "glassfrontier"


def test_starting_world_explicitly_selects_a_trusted_content_revision() -> None:
    current = create_initial_world()
    frozen = create_initial_world(content_revision="rules-v2")

    assert set(frozen.locations).issubset(current.locations)
    with pytest.raises(ValueError, match="unsupported content revision"):
        create_initial_world(content_revision="rules-v2/../../outside")


def test_schema_v3_rules_v2_replay_uses_frozen_content_when_current_content_evolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_path = Path(__file__).parents[1] / "fixtures" / "v3_events_warrior.jsonl"
    frozen = load_packaged_world_fixture(revision="rules-v2")
    evolved = deepcopy(load_packaged_world_fixture())
    future_action = evolved["towns"][0]["facilities"][0]["actions"][0]
    future_action["id"] = "shop-buy-supplies-v2"
    future_action["outcome_code"] = "facility.supplies.v2"

    def evolved_loader(*, revision: str = "current"):
        if revision == "rules-v2":
            return frozen
        if revision == "current":
            return evolved
        raise ValueError("unsupported content revision")

    monkeypatch.setattr(scenario_module, "load_packaged_world_fixture", evolved_loader)

    replayed = _default_replay(event_log=fixture_path, verify_hash=True)

    assert replayed.summary.status == "해시 검증 완료"


def test_schema_v4_rules_v3_replay_uses_frozen_content_when_current_content_evolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_path = Path(__file__).parents[1] / "fixtures" / "v4_events_warrior.jsonl"
    frozen = load_packaged_world_fixture(revision="rules-v3")
    evolved = deepcopy(load_packaged_world_fixture())
    future_action = evolved["towns"][0]["facilities"][0]["actions"][0]
    future_action["id"] = "shop-browse-goods-v2"
    future_action["outcome_code"] = "facility.browse.v2"

    def evolved_loader(*, revision: str = "current"):
        if revision == "rules-v2":
            return load_packaged_world_fixture(revision="rules-v2")
        if revision == "rules-v3":
            return frozen
        if revision == "current":
            return evolved
        raise ValueError("unsupported content revision")

    monkeypatch.setattr(scenario_module, "load_packaged_world_fixture", evolved_loader)

    replayed = _default_replay(event_log=fixture_path, verify_hash=True)

    assert replayed.summary.status == "해시 검증 완료"


def test_schema_v6_rules_v5_replay_uses_frozen_current_content_when_current_evolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_path = Path(__file__).parents[1] / "fixtures" / "v6_events_warrior.jsonl"
    stored = EventLog(fixture_path).verify()
    assert stored[0].event["schema_version"] == 6
    assert stored[0].event["rules_version"] == 5
    frozen = load_packaged_world_fixture(revision="rules-v5")
    evolved = deepcopy(load_packaged_world_fixture())
    evolved["towns"][0]["actions"][0]["id"] = "emberfall-observe-evolved"

    def evolved_loader(*, revision: str = "current"):
        if revision == "rules-v5":
            return frozen
        if revision == "current":
            return evolved
        return load_packaged_world_fixture(revision=revision)

    monkeypatch.setattr(scenario_module, "load_packaged_world_fixture", evolved_loader)

    replayed = _default_replay(event_log=fixture_path, verify_hash=True)

    assert replayed.summary.status == "해시 검증 완료"


def test_schema_v5_rules_v4_replay_uses_frozen_pre_incident_content_when_current_evolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_path = Path(__file__).parents[1] / "fixtures" / "v5_events_warrior.jsonl"
    stored = EventLog(fixture_path).verify()
    assert stored[0].event["schema_version"] == 5
    assert all("interaction" not in proposal for proposal in stored[1].event["proposals"])
    frozen = load_packaged_world_fixture(revision="rules-v4")
    evolved = deepcopy(load_packaged_world_fixture())
    evolved["towns"][0]["facilities"][0]["interactions"] = [
        {
            "id": "future-incident",
            "npc_id": "npc-orrin",
            "title_ko": "미래 사건",
            "entry_prompt_id": "entry",
            "prompts": [
                {
                    "id": "entry",
                    "text_ko": "미래의 선택입니다.",
                    "responses": [
                        {
                            "id": "finish",
                            "label_ko": "끝낸다",
                            "terminal": {
                                "outcome_code": "future-finished",
                                "gold_delta": 0,
                                "resource_delta": 0,
                            },
                        }
                    ],
                }
            ],
        }
    ]

    def evolved_loader(*, revision: str = "current"):
        if revision == "rules-v4":
            return frozen
        if revision == "current":
            return evolved
        return load_packaged_world_fixture(revision=revision)

    monkeypatch.setattr(scenario_module, "load_packaged_world_fixture", evolved_loader)

    replayed = _default_replay(event_log=fixture_path, verify_hash=True)

    assert replayed.summary.status == "해시 검증 완료"
