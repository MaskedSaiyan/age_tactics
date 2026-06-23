"""Data models for a parsed AoE2 DE replay.

We use stdlib dataclasses (no third-party dependency) to keep the package light.
`AgeTiming`, `PlayerSummary`, and `ReplaySummary` are populated from real replay
data by the parser. `EconomySnapshot` models the per-tick economy view we are
building toward (idle TC time, vils-by-age); it is not populated yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AgeTiming:
    """When a player clicked up to an age and when they arrived.

    Times are in seconds from game start. `None` means the player never
    reached that age (or it could not be determined).
    """

    age: str  # "Feudal", "Castle", or "Imperial"
    click_time: Optional[float] = None  # when the "advance" was clicked (real)
    arrival_time: Optional[float] = None  # when the age was reached
    arrival_estimated: bool = False  # True when arrival = click + standard research time
    click_estimated: bool = False  # True when click_time is INFERRED (AI: no research
    #                                event, so estimated from the first age-locked building)

    @property
    def transition_seconds(self) -> Optional[float]:
        """How long the up-time took (arrival - click)."""
        if self.click_time is None or self.arrival_time is None:
            return None
        return self.arrival_time - self.click_time


@dataclass
class BuildOrderEvent:
    """One step in a reconstructed build order.

    `kind` is "unit" (trained/queued), "building" (foundation placed), or
    "age" (an age-up was clicked). `count` is how many were queued in a single
    action (DE_QUEUE can batch). Times are seconds from game start.
    """

    game_time: float
    kind: str  # "unit" | "building" | "age"
    name: str  # "Villager", "House", "Feudal Age", ...
    count: int = 1


@dataclass
class IdleGap:
    """A stretch where the main Town Center produced nothing.

    `start` and `seconds` are game-time seconds. Estimated by modelling the TC
    production line (training a villager occupies it ~25s; age-ups block it for
    the research duration).
    """

    start: float
    seconds: float


@dataclass
class NotableEvent:
    """A non-production event worth marking on a timeline.

    `kind` is the raw action name we surface as a 'what went wrong' signal:
    "RESIGN" (game decided), "DE_RETREAT" (army pulled back), "DELETE" (player
    removed their own unit/building). Times are seconds from game start.
    """

    game_time: float
    kind: str
    player_id: int


@dataclass
class TownCenter:
    """One Town Center that produced villagers, by its object id.

    `first`/`last` are the first and last villager-queue times from this building
    (seconds). The starting TC produces from ~00:00; extra TCs from when built —
    so this list shows a boom's whole TC ramp, not just the first one.
    """

    object_id: int
    first: float
    last: float
    idle_seconds: float = 0.0  # idle in THIS TC's own production line (first→last)


@dataclass
class UnitCommand:
    """One command issued to a specific unit (by its object id).

    Lets us follow an individual villager: every ORDER / MOVE / BUILD / etc it
    received, with the target object and map position. The replay does not carry
    the *type* of the target, so `target_id` and `x`/`y` are as far as we can go.
    """

    game_time: float
    action: str  # "ORDER", "MOVE", "BUILD", "WORK", "STOP", ...
    target_id: Optional[int] = None
    x: Optional[float] = None
    y: Optional[float] = None
    detail: Optional[str] = None  # e.g. building name for BUILD


@dataclass
class EconomySnapshot:
    """A point-in-time snapshot of a player's economy."""

    game_time: float  # seconds from game start
    villagers: int = 0
    on_food: int = 0
    on_wood: int = 0
    on_gold: int = 0
    on_stone: int = 0
    farms: int = 0
    town_centers: int = 1
    idle_tc_seconds: float = 0.0  # cumulative idle TC time up to this snapshot
    housed_seconds: float = 0.0  # cumulative population-blocked time up to this snapshot


@dataclass
class PlayerSummary:
    """Everything we (eventually) know about one player's game."""

    player_id: int
    name: str
    civ: str
    team: Optional[int] = None
    winner: Optional[bool] = None
    is_ai: bool = False  # AI players issue AI_ORDER actions and never RESEARCH ages

    age_timings: list[AgeTiming] = field(default_factory=list)
    build_order: list[BuildOrderEvent] = field(default_factory=list)
    economy_timeline: list[EconomySnapshot] = field(default_factory=list)

    # Convenience headline stats (reconstructed from the timeline).
    final_villagers: Optional[int] = None
    peak_town_centers: Optional[int] = None
    total_idle_tc_seconds: Optional[float] = None
    total_housed_seconds: Optional[float] = None
    military_units_produced: Optional[int] = None

    # Main Town Center (the first one) idle estimate.
    main_tc_id: Optional[int] = None
    main_tc_villagers: Optional[int] = None
    main_tc_first_seconds: Optional[float] = None  # first villager queued from it
    main_tc_last_seconds: Optional[float] = None  # last villager queued from it
    main_tc_idle_gaps: list[IdleGap] = field(default_factory=list)

    # ALL Town Centers that trained villagers — each (object_id, first, last) so a
    # boom's extra TCs are visible, not just the first one. Sorted by first time.
    town_centers: list["TownCenter"] = field(default_factory=list)

    # Drop-off buildings for resource inference: (build_time, x, y, resource).
    resource_dropoffs: list[tuple] = field(default_factory=list)

    # Real, robustly-extractable activity stats from the command stream.
    # (These come from counting operations in the body — see parser.py.)
    action_count: Optional[int] = None  # total player actions issued
    build_count: Optional[int] = None  # BUILD actions (foundations placed)
    make_count: Optional[int] = None  # MAKE actions (unit production orders)

    def age(self, name: str) -> Optional[AgeTiming]:
        """Return the AgeTiming for a given age name, if present."""
        for t in self.age_timings:
            if t.age.lower() == name.lower():
                return t
        return None


@dataclass
class ReplaySummary:
    """Top-level result of parsing one replay file."""

    source_file: str
    map_name: Optional[str] = None
    game_duration_seconds: Optional[float] = None
    game_version: Optional[str] = None  # e.g. "VER 9.4" (DE)
    players: list[PlayerSummary] = field(default_factory=list)

    # Per-unit command logs: object_id -> chronological commands, and the
    # player that owns each object. Populated for units that received commands.
    unit_commands: dict[int, list[UnitCommand]] = field(default_factory=dict)
    unit_owner: dict[int, int] = field(default_factory=dict)
    # Object ids that issued a BUILD command (builders == villagers).
    builder_ids: set[int] = field(default_factory=set)

    # Notable non-production events (resign / retreat / delete) on the timeline.
    notable_events: list["NotableEvent"] = field(default_factory=list)

    # Human-readable caveats about what could / couldn't be extracted.
    notes: list[str] = field(default_factory=list)

    def units_for_player(self, player_id: int) -> list[int]:
        """Object ids owned by a player that received at least one command."""
        return sorted(
            oid for oid, owner in self.unit_owner.items() if owner == player_id
        )

    def player_by_name(self, name: str) -> Optional[PlayerSummary]:
        for p in self.players:
            if p.name == name:
                return p
        return None
