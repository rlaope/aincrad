from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

MAX_LEVEL = 100
XP_CURVE: tuple[int, ...] = tuple(100 + 25 * level * level for level in range(1, 101))


class LocationKind(StrEnum):
    TOWN = "town"
    HUNTING_GROUND = "hunting_ground"
    DUNGEON = "dungeon"


class CharacterClass(StrEnum):
    WARRIOR = "warrior"
    ARCHER = "archer"
    MAGE = "mage"
    TANK = "tank"


class Activity(StrEnum):
    IDLE = "idle"
    MOVING = "moving"
    RESTING = "resting"
    GATHERING = "gathering"
    TRADING = "trading"
    WAITING = "waiting"
    OBSERVING = "observing"
    SCOUTING = "scouting"
    SEARCHING = "searching"
    FIGHTING = "fighting"
    CAMPING = "camping"
    SERVICING = "servicing"


class ActionKind(StrEnum):
    MOVE = "move"
    REST = "rest"
    GATHER = "gather"
    TRADE = "trade"
    WAIT = "wait"
    OBSERVE = "observe"
    BUY_SUPPLIES = "buy_supplies"
    SELL_SALVAGE = "sell_salvage"
    LODGE = "lodge"
    STORE_BELONGINGS = "store_belongings"
    LIST_CONTRACTS = "list_contracts"
    TURN_IN_CONTRACT = "turn_in_contract"
    READ_NOTICES = "read_notices"
    REQUEST_DIRECTIONS = "request_directions"
    BUY_MEAL = "buy_meal"
    HEAR_RUMOR = "hear_rumor"
    BROWSE_GOODS = "browse_goods"
    VIEW_TAVERN_MENU = "view_tavern_menu"
    EAT_INN_MEAL = "eat_inn_meal"
    ORDER_DRINK = "order_drink"
    TALK_ORRIN = "talk_orrin"
    TALK_BRANN = "talk_brann"
    ASK_VELA_ADVICE = "ask_vela_advice"
    TALK_PELL = "talk_pell"
    TALK_SENA = "talk_sena"
    HUNT = "hunt"
    SCOUT = "scout"
    CAMP = "camp"
    SEARCH = "search"
    FIGHT = "fight"
    CHALLENGE = "challenge"


@dataclass(frozen=True, slots=True)
class Stats:
    hp: int
    max_hp: int
    mp: int
    max_mp: int

    def __post_init__(self) -> None:
        if self.max_hp < 0 or self.max_mp < 0:
            raise ValueError("maximum stats cannot be negative")
        if not 0 <= self.hp <= self.max_hp:
            raise ValueError("hp must be between zero and max_hp")
        if not 0 <= self.mp <= self.max_mp:
            raise ValueError("mp must be between zero and max_mp")


@dataclass(frozen=True, slots=True)
class ContextualAction:
    """Fixture-backed local action metadata with only state the domain can represent."""

    id: str
    kind: ActionKind
    label_ko: str
    description_ko: str
    service: str | None = None
    clue_code: str | None = None
    encounter_code: str | None = None
    outcome_code: str | None = None
    requires_completed_contract: bool = False
    gold_delta: int = 0
    gold_per_resource: int = 0
    resource_delta: int = 0
    restore_hp: int = 0
    restore_mp: int = 0

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("contextual action id cannot be empty")
        if not self.label_ko.strip() or not self.description_ko.strip():
            raise ValueError("contextual actions require Korean display metadata")
        if self.restore_hp < 0 or self.restore_mp < 0:
            raise ValueError("contextual restoration cannot be negative")


@dataclass(frozen=True, slots=True)
class Location:
    id: str
    name: str
    kind: LocationKind
    connections: tuple[str, ...] = ()
    stage: int | None = None
    is_boss_room: bool = False
    boss_id: str | None = None
    transition_id: str | None = None
    next_world_floor: int | None = None
    description: str = ""
    services: tuple[str, ...] = ()
    contextual_actions: tuple[ContextualAction, ...] = ()

    def __post_init__(self) -> None:
        if self.stage is not None and self.stage <= 0:
            raise ValueError("location stage must be positive")
        if self.is_boss_room and self.stage is None:
            raise ValueError("boss rooms require a stage")
        if (self.boss_id is not None or self.transition_id is not None) and not self.is_boss_room:
            raise ValueError("boss metadata requires a boss room")
        if self.next_world_floor is not None and (
            not self.is_boss_room or self.next_world_floor <= 0
        ):
            raise ValueError("world-floor transitions require a valid boss room")
        if len({action.id for action in self.contextual_actions}) != len(self.contextual_actions):
            raise ValueError("location contextual action ids must be unique")
        if len({action.kind for action in self.contextual_actions}) != len(self.contextual_actions):
            raise ValueError("location contextual action kinds must be unique")


@dataclass(frozen=True, slots=True)
class Adventurer:
    id: str
    name: str
    location_id: str
    stats: Stats
    activity: Activity = Activity.IDLE
    gold: int = 0
    resources: int = 0
    character_class: CharacterClass = CharacterClass.WARRIOR
    level: int = 1
    exp: int = 0
    alive: bool = True
    death_tick: int | None = None
    death_cause: str | None = None

    def __post_init__(self) -> None:
        if self.gold < 0 or self.resources < 0:
            raise ValueError("wealth cannot be negative")
        if not 1 <= self.level <= MAX_LEVEL:
            raise ValueError(f"level must be between 1 and {MAX_LEVEL}")
        if self.exp < 0:
            raise ValueError("experience cannot be negative")
        if self.level == MAX_LEVEL and self.exp != 0:
            raise ValueError("experience must be zero at the level cap")
        if self.level < MAX_LEVEL and self.exp >= XP_CURVE[self.level - 1]:
            raise ValueError("experience must be below the next-level requirement")
        if self.alive and (self.death_tick is not None or self.death_cause is not None):
            raise ValueError("living adventurers cannot have death metadata")
        if not self.alive and self.death_tick is None:
            raise ValueError("dead adventurers require a death tick")
        if self.death_tick is not None and self.death_tick < 0:
            raise ValueError("death tick cannot be negative")
        if not self.alive and self.stats.hp != 0:
            raise ValueError("dead adventurers must have zero hp")
        if not self.alive and self.activity is not Activity.IDLE:
            raise ValueError("dead adventurers cannot act")

    @property
    def can_act(self) -> bool:
        return self.alive


@dataclass(frozen=True, slots=True)
class ActionIntent:
    adventurer_id: str
    action: ActionKind | str
    target_location_id: str | None = None
    quantity: int = 1


@dataclass(frozen=True, slots=True)
class PartyState:
    selected_hero_id: str
    member_ids: tuple[str, ...]
    cap: int

    def __post_init__(self) -> None:
        if self.cap <= 0:
            raise ValueError("party cap must be positive")
        if not self.selected_hero_id:
            raise ValueError("selected hero id cannot be empty")
        if self.selected_hero_id not in self.member_ids:
            raise ValueError("selected hero must remain in the party")
        if len(set(self.member_ids)) != len(self.member_ids):
            raise ValueError("party members must be unique")
        if len(self.member_ids) > self.cap:
            raise ValueError("party cannot exceed its cap")

    @property
    def leader_id(self) -> str:
        """Backward-compatible name for the selected story hero."""
        return self.selected_hero_id


@dataclass(frozen=True, slots=True)
class WorldState:
    tick: int
    locations: Mapping[str, Location] = field(default_factory=dict)
    adventurers: Mapping[str, Adventurer] = field(default_factory=dict)
    party: PartyState | None = None

    def __post_init__(self) -> None:
        if self.tick < 0:
            raise ValueError("tick cannot be negative")
        locations = dict(self.locations)
        adventurers = dict(self.adventurers)
        if any(key != value.id for key, value in locations.items()):
            raise ValueError("location keys must match ids")
        if any(key != value.id for key, value in adventurers.items()):
            raise ValueError("adventurer keys must match ids")
        if any(a.location_id not in locations for a in adventurers.values()):
            raise ValueError("every adventurer must occupy an existing location")
        party = self.party
        if party is None:
            member_ids = tuple(sorted(adventurers))
            if not member_ids:
                raise ValueError("world requires at least one party member")
            party = PartyState(member_ids[0], member_ids, len(member_ids))
        if any(member_id not in adventurers for member_id in party.member_ids):
            raise ValueError("every party member must exist in the world")
        object.__setattr__(self, "locations", MappingProxyType(locations))
        object.__setattr__(self, "adventurers", MappingProxyType(adventurers))
        object.__setattr__(self, "party", party)
