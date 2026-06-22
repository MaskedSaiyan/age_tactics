"""Replay parsing for AoE2 DE .aoe2record files.

#############################################################################
# STATUS: partial real parsing 🎉
#
# `.aoe2record` is a compressed header (raw DEFLATE) followed by an
# uncompressed body that is the recorded *command stream* (every action each
# player took). We use the `mgz` library to walk the body, which is robust
# across game versions.
#
# WHAT WORKS NOW (real data, read straight from the file):
#   - game version string (e.g. "VER 9.4")
#   - real game duration (summed from SYNC operations / postgame world_time)
#   - per-player activity: total actions, BUILD count, MAKE (unit) count
#   - player names (scraped from the header's DE string table)
#
# WHAT IS STILL TODO (needs simulating the command stream / full header parse):
#   - civilizations per player  (mgz's full header parser does not yet support
#     this exact DE sub-version, so civ is reported as "unknown")
#   - Feudal/Castle/Imperial click & arrival times
#   - villager count by age, resource distribution over time
#   - Town Center idle time, farm count, housed time, build-order timeline
#
# If `mgz` is not installed, or the file can't be read, we fall back to the
# old MOCK summary (flagged with is_mock=True) so the CLI/tests still run.
#############################################################################
"""

from __future__ import annotations

import io
import re
import struct
import zlib
from typing import Optional

from .models import AgeTiming, EconomySnapshot, PlayerSummary, ReplaySummary


def parse_replay(path: str) -> ReplaySummary:
    """Parse an .aoe2record file into a ReplaySummary.

    Tries real parsing first; falls back to a mock summary if anything goes
    wrong (missing file, mgz not installed, unsupported format, etc.).
    """
    try:
        return _parse_real(path)
    except Exception as exc:  # noqa: BLE001 - any failure -> graceful mock fallback
        summary = _mock_summary(path)
        summary.notes.insert(
            0,
            f"Real parsing failed ({type(exc).__name__}: {exc}); showing MOCK data.",
        )
        return summary


# --------------------------------------------------------------------------- #
# Real parsing
# --------------------------------------------------------------------------- #

# Action types we count as a meaningful "player action" with a player_id.
def _parse_real(path: str) -> ReplaySummary:
    from mgz import fast  # imported lazily so the mock path works without mgz
    from mgz.fast import Operation

    with open(path, "rb") as handle:
        data = handle.read()

    if len(data) < 8:
        raise ValueError("file too small to be an .aoe2record")

    header_len = struct.unpack("<I", data[0:4])[0]
    if not (8 < header_len < len(data)):
        raise ValueError(f"implausible header length: {header_len}")

    version = _read_version(data)
    names = _scrape_player_names(data)

    # --- Walk the body (command stream) -----------------------------------
    body = io.BytesIO(data[header_len:])
    fast.meta(body)  # consume body meta (log version + first header offset)

    total_ms = 0
    postgame_world_time: Optional[int] = None
    actions: dict[int, int] = {}
    builds: dict[int, int] = {}
    makes: dict[int, int] = {}

    while True:
        try:
            op_type, op_data = fast.operation(body)
        except EOFError:
            break
        except Exception:
            # Trailing/garbage op — stop cleanly with whatever we have.
            break

        if op_type == Operation.SYNC:
            inc = op_data[0] if isinstance(op_data, (list, tuple)) else op_data
            if isinstance(inc, int):
                total_ms += inc
        elif op_type == Operation.POSTGAME and isinstance(op_data, dict):
            wt = op_data.get("world_time")
            if isinstance(wt, int):
                postgame_world_time = wt
        elif op_type == Operation.ACTION and isinstance(op_data, tuple):
            action, payload = op_data[0], op_data[1]
            pid = payload.get("player_id") if isinstance(payload, dict) else None
            if isinstance(pid, int):
                actions[pid] = actions.get(pid, 0) + 1
                name = getattr(action, "name", "")
                if name == "BUILD":
                    builds[pid] = builds.get(pid, 0) + 1
                elif name == "MAKE":
                    makes[pid] = makes.get(pid, 0) + 1

    duration_ms = postgame_world_time or total_ms
    duration_seconds = duration_ms / 1000.0 if duration_ms else None

    # --- Build player summaries -------------------------------------------
    players: list[PlayerSummary] = []
    for idx, pid in enumerate(sorted(actions)):
        # Best-effort name: header string table, in slot order. Falls back to id.
        name = names[idx] if idx < len(names) else f"Player {pid}"
        players.append(
            PlayerSummary(
                player_id=pid,
                name=name,
                civ="unknown",  # TODO: full header parse for civ (see module docstring)
                action_count=actions.get(pid),
                build_count=builds.get(pid),
                make_count=makes.get(pid),
                military_units_produced=makes.get(pid),  # MAKE orders as a proxy
            )
        )

    summary = ReplaySummary(
        source_file=path,
        map_name=None,  # TODO: requires full header parse
        game_duration_seconds=duration_seconds,
        game_version=version,
        players=players,
        is_mock=False,
        notes=[
            "Civilizations, ages, and economy stats are not extracted yet "
            "(this DE sub-version isn't supported by mgz's full header parser).",
            "Player names are scraped in slot order and may not align perfectly "
            "with the action player_ids.",
            "'Military produced' = count of MAKE orders, a proxy (queued != built).",
        ],
    )
    return summary


def _read_version(data: bytes) -> Optional[str]:
    """Decompress the header and read the leading version string (e.g. 'VER 9.4')."""
    try:
        head = zlib.decompressobj(-15).decompress(data[8:], 64)
        return head[:8].split(b"\x00")[0].decode(errors="replace") or None
    except Exception:
        return None


def _scrape_player_names(data: bytes, limit: int = 50_000) -> list[str]:
    """Pull human-readable names from the header's DE string table.

    DE strings are encoded as the marker b'\\x60\\x0a' + uint16 length + text.
    We scan the start of the decompressed header and keep plausible names,
    skipping config-looking strings (those with ':' separators).
    """
    try:
        head = zlib.decompress(data[8:], -15)
    except Exception:
        return []

    names: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(b"\x60\x0a", head[:limit]):
        pos = match.start() + 2
        if pos + 2 > len(head):
            continue
        length = struct.unpack("<H", head[pos : pos + 2])[0]
        if not (1 <= length <= 40):
            continue
        raw = head[pos + 2 : pos + 2 + length]
        if not re.fullmatch(rb"[\x20-\x7e]+", raw):
            continue
        text = raw.decode()
        if ":" in text or text in seen:  # skip config strings / dupes
            continue
        seen.add(text)
        names.append(text)
    return names


# --------------------------------------------------------------------------- #
# Mock fallback (used when mgz is missing or the file can't be parsed)
# --------------------------------------------------------------------------- #


def _mock_summary(path: str) -> ReplaySummary:
    """Build a believable-but-fake ReplaySummary for development/testing."""
    goth_player = PlayerSummary(
        player_id=1,
        name="You (Goths)",
        civ="Goths",
        team=1,
        winner=True,
        age_timings=[
            AgeTiming(age="Feudal", click_time=600.0, arrival_time=640.0),
            AgeTiming(age="Castle", click_time=900.0, arrival_time=1060.0),
            AgeTiming(age="Imperial", click_time=1800.0, arrival_time=1980.0),
        ],
        economy_timeline=[
            EconomySnapshot(
                game_time=640.0, villagers=28, on_food=16, on_wood=8, on_gold=2,
                on_stone=2, farms=4, town_centers=1, idle_tc_seconds=5.0,
                housed_seconds=12.0,
            ),
            EconomySnapshot(
                game_time=1060.0, villagers=40, on_food=22, on_wood=10, on_gold=4,
                on_stone=4, farms=9, town_centers=1, idle_tc_seconds=18.0,
                housed_seconds=20.0,
            ),
            EconomySnapshot(
                game_time=1500.0, villagers=80, on_food=44, on_wood=20, on_gold=10,
                on_stone=6, farms=22, town_centers=3, idle_tc_seconds=35.0,
                housed_seconds=28.0,
            ),
            EconomySnapshot(
                game_time=1980.0, villagers=102, on_food=50, on_wood=28, on_gold=18,
                on_stone=6, farms=30, town_centers=3, idle_tc_seconds=52.0,
                housed_seconds=33.0,
            ),
        ],
        final_villagers=102,
        peak_town_centers=3,
        total_idle_tc_seconds=52.0,
        total_housed_seconds=33.0,
        military_units_produced=140,
    )

    ally_player = PlayerSummary(
        player_id=2,
        name="Pocket (Franks)",
        civ="Franks",
        team=1,
        winner=True,
        age_timings=[
            AgeTiming(age="Feudal", click_time=540.0, arrival_time=580.0),
            AgeTiming(age="Castle", click_time=820.0, arrival_time=970.0),
        ],
        final_villagers=95,
        peak_town_centers=3,
        military_units_produced=70,
    )

    return ReplaySummary(
        source_file=path,
        map_name="Arabia (mock)",
        game_duration_seconds=2400.0,
        players=[goth_player, ally_player],
        is_mock=True,
        notes=["This is MOCK data — real parsing was unavailable."],
    )
