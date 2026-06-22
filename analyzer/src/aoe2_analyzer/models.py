"""Data models for a parsed AoE2 DE replay.

We use stdlib dataclasses (no third-party dependency) to keep the scaffold light.
These model the *intended* output shape of the analyzer — the parser does not yet
populate them from real replay data.
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
    click_time: Optional[float] = None  # when the "advance" was clicked
    arrival_time: Optional[float] = None  # when the age was actually reached

    @property
    def transition_seconds(self) -> Optional[float]:
        """How long the up-time took (arrival - click)."""
        if self.click_time is None or self.arrival_time is None:
            return None
        return self.arrival_time - self.click_time


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

    age_timings: list[AgeTiming] = field(default_factory=list)
    economy_timeline: list[EconomySnapshot] = field(default_factory=list)

    # Convenience headline stats (reconstructed from the timeline).
    final_villagers: Optional[int] = None
    peak_town_centers: Optional[int] = None
    total_idle_tc_seconds: Optional[float] = None
    total_housed_seconds: Optional[float] = None
    military_units_produced: Optional[int] = None

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

    # Flag so downstream code / users know this isn't real data yet.
    is_mock: bool = False

    # Human-readable caveats about what could / couldn't be extracted.
    notes: list[str] = field(default_factory=list)

    def player_by_name(self, name: str) -> Optional[PlayerSummary]:
        for p in self.players:
            if p.name == name:
                return p
        return None
