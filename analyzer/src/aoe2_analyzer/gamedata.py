"""Static AoE2 DE game-data lookups: unit and building ids -> readable names.

Only high-confidence, common ids are mapped. Anything not listed renders as
"Unit #<id>" / "Building #<id>" so a build order stays readable without risking
a wrong label. Extend these as more ids are confirmed from real replays.
"""

from __future__ import annotations

# The villager unit id (used for build-order numbering of "Villager #N").
VILLAGER_ID = 83

UNIT_NAMES = {
    83: "Villager",
    293: "Villager",  # female base variant
    # Infantry
    74: "Militia",
    75: "Man-at-Arms",
    77: "Long Swordsman",
    93: "Spearman",
    358: "Pikeman",
    # Archers
    4: "Archer",
    24: "Crossbowman",
    7: "Skirmisher",
    39: "Cavalry Archer",
    # Cavalry
    448: "Scout Cavalry",
    546: "Light Cavalry",
    38: "Knight",
    329: "Camel Rider",
    # Siege / monks / trade / naval
    125: "Monk",
    128: "Trade Cart",
    13: "Fishing Ship",
    17: "Trade Cog",
    35: "Battering Ram",
}

BUILDING_NAMES = {
    70: "House",
    68: "Mill",
    562: "Lumber Camp",
    584: "Mining Camp",
    50: "Farm",
    109: "Town Center",
    12: "Barracks",
    87: "Archery Range",
    101: "Stable",
    49: "Siege Workshop",
    84: "Market",
    104: "Monastery",
    103: "Blacksmith",
    79: "Watch Tower",
    45: "Dock",
    82: "Castle",
    72: "Palisade Wall",
    117: "Stone Wall",
    199: "Fish Trap",
}


def unit_name(unit_id: object) -> str:
    if isinstance(unit_id, int) and unit_id in UNIT_NAMES:
        return UNIT_NAMES[unit_id]
    return f"Unit #{unit_id}"


def building_name(building_id: object) -> str:
    if isinstance(building_id, int) and building_id in BUILDING_NAMES:
        return BUILDING_NAMES[building_id]
    return f"Building #{building_id}"
