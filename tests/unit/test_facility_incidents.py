from __future__ import annotations

from dataclasses import replace

from aincrad.domain import (
    ActionIntent,
    ActionKind,
    ActionRejected,
    ActionSucceeded,
    InteractionSelection,
)
from aincrad.domain.rules import apply_intent
from aincrad.simulation import create_initial_world


def test_orrin_two_step_incident_is_engine_validated_and_atomic() -> None:
    world = create_initial_world()
    selection = InteractionSelection(
        incident_id="orrin-cracked-crate",
        path=(("crate-opening", "inspect-crate"), ("crate-findings", "report-flaw")),
    )

    resolved, events = apply_intent(
        world,
        ActionIntent(
            "rhea-vale",
            ActionKind.ENGAGE_INCIDENT,
            target_location_id="emberfall-shop",
            interaction=selection,
        ),
    )

    assert resolved.adventurers["rhea-vale"].location_id == "emberfall-shop"
    assert resolved.adventurers["rhea-vale"].gold == 7
    assert isinstance(events[0], ActionSucceeded)
    assert dict(events[0].details) == {
        "location_id": "emberfall-shop",
        "incident_id": "orrin-cracked-crate",
        "prompt_path": "crate-opening/crate-findings",
        "response_id": "report-flaw",
        "outcome_code": "orrin-crate-flaw-reported",
        "gold_delta": "2",
    }

    tampered = replace(
        selection,
        path=(("crate-opening", "inspect-crate"), ("crate-findings", "unknown-response")),
    )
    rejected, rejected_events = apply_intent(
        world,
        ActionIntent(
            "rhea-vale",
            ActionKind.ENGAGE_INCIDENT,
            target_location_id="emberfall-shop",
            interaction=tampered,
        ),
    )

    assert rejected.adventurers["rhea-vale"] == world.adventurers["rhea-vale"]
    assert isinstance(rejected_events[0], ActionRejected)
    assert rejected_events[0].reason == "invalid_interaction_path"
