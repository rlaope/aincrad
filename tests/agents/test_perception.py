from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from aincrad.agents import Observation, Perception, perceive


def test_perception_exposes_only_observed_fields_and_is_deeply_read_only() -> None:
    world_payload = {
        "tick": 12,
        "actor": {
            "id": "rhea",
            "location_id": "emberfall",
            "hp": 18,
            "secret_quest": "the sealed crown",
        },
        "visible_entities": (
            {
                "id": "mira",
                "kind": "adventurer",
                "display_name": "Mira",
                "hidden_ai_goal": "betray rhea",
            },
        ),
        "server_rng_seed": 991,
    }
    observation = Observation(
        tick=world_payload["tick"],
        actor_id=world_payload["actor"]["id"],
        location_id=world_payload["actor"]["location_id"],
        self_state={"hp": world_payload["actor"]["hp"]},
        visible_entities=world_payload["visible_entities"],
        visible_entity_fields=("id", "kind", "display_name"),
    )

    perception = perceive(observation)

    assert perception == Perception(
        tick=12,
        actor_id="rhea",
        location_id="emberfall",
        self_state=(("hp", 18),),
        visible_entities=((('display_name', 'Mira'), ('id', 'mira'), ('kind', 'adventurer')),),
    )
    assert "secret_quest" not in repr(perception)
    assert "hidden_ai_goal" not in repr(perception)
    assert "server_rng_seed" not in repr(perception)
    with pytest.raises(FrozenInstanceError):
        perception.tick = 13  # type: ignore[misc]


def test_perception_never_retains_a_reference_to_mutable_observation_data() -> None:
    self_state = {"hp": 9}
    entity = {"id": "slime", "kind": "monster"}
    perception = perceive(
        Observation(
            tick=1,
            actor_id="rhea",
            location_id="mossreach",
            self_state=self_state,
            visible_entities=(entity,),
            visible_entity_fields=("id", "kind"),
        )
    )

    self_state["hp"] = 0
    entity["kind"] = "hidden-boss"

    assert perception.self_state == (("hp", 9),)
    assert dict(perception.visible_entities[0]) == {"id": "slime", "kind": "monster"}
