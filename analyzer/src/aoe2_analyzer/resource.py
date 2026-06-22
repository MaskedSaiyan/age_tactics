"""Heuristic resource inference for villager orders.

The replay records *where* a villager was sent (map x/y) but not *what* it was
sent to gather. We infer the resource by proximity to the player's drop-off
buildings, which DO carry a type and position:

  - Lumber Camp  -> wood
  - Mining Camp  -> gold/stone  (one building serves both — can't disambiguate)
  - Mill / Farm  -> food

This is a best-effort guess, not ground truth:
  * early game (before any camp exists) there is nothing to match against;
  * a drop-off only counts once it has been built (we respect build time);
  * orders far from every camp are reported as "elsewhere".
"""

from __future__ import annotations

import math
from typing import Optional

# building_id -> resource category for drop-off buildings.
DROPOFF_RESOURCE = {
    562: "wood",        # Lumber Camp
    584: "gold/stone",  # Mining Camp
    68: "food",         # Mill
    50: "food",         # Farm
}

# Max distance (tiles) from a drop-off for the match to be trusted.
MAX_MATCH_DISTANCE = 16.0

# Players often send a villager to a resource and drop the camp moments later,
# so a camp built shortly AFTER the order still indicates what it gathered.
LOOKAHEAD_SECONDS = 90.0


def dropoff_resource(building_id: object) -> Optional[str]:
    """Resource category a drop-off building collects, or None if not a drop-off."""
    if isinstance(building_id, int):
        return DROPOFF_RESOURCE.get(building_id)
    return None


def infer_resource(
    x: Optional[float],
    y: Optional[float],
    dropoffs: list[tuple],
    at_time: Optional[float] = None,
) -> Optional[str]:
    """Best-effort resource for an order at (x, y), given a player's drop-offs.

    `dropoffs` is a list of (build_time, x, y, resource). Only drop-offs already
    built by `at_time` are considered. Returns "wood" / "gold/stone" / "food",
    "elsewhere" if the nearest is too far, or None if position/data is missing.
    """
    if x is None or y is None or not dropoffs:
        return None
    best_res: Optional[str] = None
    best_dist = math.inf
    for build_time, bx, by, res in dropoffs:
        if (
            at_time is not None
            and build_time is not None
            and build_time > at_time + LOOKAHEAD_SECONDS
        ):
            continue
        if bx is None or by is None:
            continue
        dist = math.hypot(x - bx, y - by)
        if dist < best_dist:
            best_dist = dist
            best_res = res
    if best_res is None:
        return None
    return best_res if best_dist <= MAX_MATCH_DISTANCE else "elsewhere"
