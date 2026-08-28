from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .fixtures import FixtureSchemaError, LoadedWorldFixture, load_packaged_world_fixture

_SERVICE_ROLE_KO = {
    "shop": "상점 관리인",
    "inn": "여관지기",
    "quest_hall": "의뢰 안내인",
    "plaza": "광장 안내인",
    "tavern": "주점 주인",
}


@dataclass(frozen=True, slots=True)
class ResidentNPC:
    """Public, fixture-validated identity of one facility resident."""

    id: str
    display_name: str
    location_id: str
    service: str
    role_ko: str


def _required_text(record: Mapping[str, object], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise FixtureSchemaError(f"NPC.{field} must be a non-empty string")
    return value


def resident_npcs_from_fixture(fixture: LoadedWorldFixture) -> tuple[ResidentNPC, ...]:
    """Extract only public resident data after the fixture's fail-closed validation."""

    residents: list[ResidentNPC] = []
    for raw_npc in fixture["npcs"]:
        if not isinstance(raw_npc, Mapping):
            raise FixtureSchemaError("NPC entries must be objects")
        npc = raw_npc
        npc_id = _required_text(npc, "id")
        display_name = _required_text(npc, "name")
        location_id = _required_text(npc, "location_id")
        service = _required_text(npc, "service")
        if npc.get("controller") != "rules":
            raise FixtureSchemaError("general NPC controller must be rules")
        try:
            role_ko = _SERVICE_ROLE_KO[service]
        except KeyError as error:
            raise FixtureSchemaError(f"NPC {npc_id} has unsupported public service") from error
        residents.append(ResidentNPC(npc_id, display_name, location_id, service, role_ko))
    if len({resident.id for resident in residents}) != len(residents):
        raise FixtureSchemaError("NPC ids must be unique")
    if len({resident.location_id for resident in residents}) != len(residents):
        raise FixtureSchemaError("resident NPC locations must be unique")
    return tuple(sorted(residents, key=lambda resident: resident.location_id))


def resident_npc_for_location(location_id: str) -> ResidentNPC | None:
    """Return the single public resident for a facility, or none outside facilities."""

    residents = resident_npcs_from_fixture(load_packaged_world_fixture())
    return next((resident for resident in residents if resident.location_id == location_id), None)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ServiceRequest:
    actor_id: str
    operation: str
    item_id: str | None = None


@dataclass(frozen=True, slots=True)
class ServiceResponse:
    npc_id: str
    actor_id: str
    operation: str
    effects: tuple[tuple[str, Any], ...]


@dataclass(frozen=True, slots=True)
class RuleBasedNPCService:
    """Deterministic service table for ordinary NPCs; no AI policy is involved."""

    npc_id: str
    service: str
    rules: Mapping[str, Mapping[str, Any]]

    def handle(self, request: ServiceRequest) -> ServiceResponse:
        key = request.operation
        if request.item_id is not None:
            key = f"{key}:{request.item_id}"
        try:
            configured_effects = self.rules[key]
        except KeyError as error:
            raise LookupError(f"unsupported {self.service} operation: {key}") from error
        effects = tuple(
            sorted((str(name), _freeze(value)) for name, value in configured_effects.items())
        )
        return ServiceResponse(self.npc_id, request.actor_id, request.operation, effects)
