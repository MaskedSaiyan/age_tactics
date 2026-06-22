"""Replay parsing for AoE2 DE .aoe2record files.

An `.aoe2record` is a compressed header (raw DEFLATE) followed by an
uncompressed body that is the recorded *command stream* (every action each
player took, interleaved with SYNC time ticks). We walk the body with the
`mgz` library, which is robust across game versions.

Extracted from real data:
  - game version string (e.g. "VER 9.4")
  - real game duration (postgame world_time, or summed SYNC ticks)
  - per-player age-up timings: when Feudal/Castle/Imperial were *clicked*
    (read straight from RESEARCH actions on the age technologies)
  - per-player build order: a chronological timeline of every unit queued
    (MAKE + DE_QUEUE) and building placed (BUILD), with age markers — enough
    to number "Villager #1..N" and the military up to each age
  - per-player activity: total actions, building count, units queued
  - player names (scraped from the header's DE string table)

Age *arrival* time is reported as click + the standard research duration; it
is flagged as an estimate because civ bonuses (e.g. Malay) are not applied.

Still on the roadmap (needs simulating the full command stream / header):
  - civilizations per player, maps
  - resource distribution over time, villagers actually alive (vs queued)
  - Town Center idle time, farm count, housed time

If `mgz` is not installed or the file can't be read, parsing raises a clear
error (no silent fallback) — see ReplayParseError.
"""

from __future__ import annotations

import io
import re
import struct
import zlib
from typing import Optional

from .gamedata import VILLAGER_ID, building_name, unit_name
from .models import AgeTiming, BuildOrderEvent, IdleGap, PlayerSummary, ReplaySummary

# Age advance technologies, keyed by mgz RESEARCH technology_id.
AGE_TECHS = {101: "Feudal", 102: "Castle", 103: "Imperial"}

# Standard age research durations (seconds) with no civ/tech modifiers applied.
# Used to estimate arrival time from the (real) click time.
AGE_RESEARCH_SECONDS = {"Feudal": 130.0, "Castle": 160.0, "Imperial": 190.0}

# Order ages should appear in, regardless of research order.
_AGE_ORDER = ["Feudal", "Castle", "Imperial"]

# Base time to train one villager (seconds), no civ/tech modifiers applied.
VILLAGER_TRAIN_SECONDS = 25.0

# Idle gaps shorter than this are normal click latency, not real idle TC time.
_MIN_IDLE_GAP_SECONDS = 3.0


class ReplayParseError(Exception):
    """Raised when an .aoe2record file cannot be parsed."""


def parse_replay(path: str) -> ReplaySummary:
    """Parse an .aoe2record file into a ReplaySummary.

    Raises ReplayParseError on any failure (missing file, mgz not installed,
    unsupported format, etc.) so callers can report it clearly.
    """
    try:
        return _parse_real(path)
    except ReplayParseError:
        raise
    except FileNotFoundError as exc:
        raise ReplayParseError(f"file not found: {path}") from exc
    except ImportError as exc:
        raise ReplayParseError(
            "the 'mgz' library is required to parse replays "
            "(install with: pip install mgz)"
        ) from exc
    except Exception as exc:  # noqa: BLE001 - surface anything else as a parse error
        raise ReplayParseError(f"{type(exc).__name__}: {exc}") from exc


# --------------------------------------------------------------------------- #
# Real parsing
# --------------------------------------------------------------------------- #


def _parse_real(path: str) -> ReplaySummary:
    from mgz import fast  # imported lazily so a clear ImportError is raised above
    from mgz.fast import Operation

    with open(path, "rb") as handle:
        data = handle.read()

    if len(data) < 8:
        raise ReplayParseError("file too small to be an .aoe2record")

    header_len = struct.unpack("<I", data[0:4])[0]
    if not (8 < header_len < len(data)):
        raise ReplayParseError(f"implausible header length: {header_len}")

    version = _read_version(data)
    names = _scrape_player_names(data)

    # --- Walk the body (command stream) -----------------------------------
    body = io.BytesIO(data[header_len:])
    fast.meta(body)  # consume body meta (log version + first header offset)

    total_ms = 0
    postgame_world_time: Optional[int] = None
    actions: dict[int, int] = {}
    builds: dict[int, int] = {}
    units: dict[int, int] = {}  # total units queued (MAKE + DE_QUEUE, amount-summed)
    # player_id -> {age_name -> click_time_seconds}
    age_clicks: dict[int, dict[str, float]] = {}
    # player_id -> chronological build-order events
    events: dict[int, list[BuildOrderEvent]] = {}
    # player_id -> list of (time, object_ids, kind, value) occupying a building.
    # kind "vil": value=count (train ~25s each); "age": value=research seconds.
    tc_events: dict[int, list[tuple]] = {}

    def add_event(pid: int, t_sec: float, kind: str, name: str, count: int = 1) -> None:
        events.setdefault(pid, []).append(BuildOrderEvent(t_sec, kind, name, count))

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
                t_sec = total_ms / 1000.0
                if name == "BUILD":
                    builds[pid] = builds.get(pid, 0) + 1
                    add_event(pid, t_sec, "building", building_name(payload.get("building_id")))
                elif name in ("MAKE", "DE_QUEUE"):
                    # MAKE = single unit (AI); DE_QUEUE = batch with `amount` (human).
                    amount = payload.get("amount")
                    count = amount if isinstance(amount, int) and amount > 0 else 1
                    unit_id = payload.get("unit_id")
                    units[pid] = units.get(pid, 0) + count
                    add_event(pid, t_sec, "unit", unit_name(unit_id), count)
                    if unit_id == VILLAGER_ID:
                        objs = payload.get("object_ids") or []
                        tc_events.setdefault(pid, []).append((t_sec, objs, "vil", count))
                elif name == "RESEARCH":
                    tech = payload.get("technology_id")
                    age = AGE_TECHS.get(tech)
                    if age is not None:
                        # First click wins (ignore any duplicate/cancelled re-issues).
                        age_clicks.setdefault(pid, {}).setdefault(age, t_sec)
                        add_event(pid, t_sec, "age", f"{age} Age")
                        objs = payload.get("object_ids") or []
                        tc_events.setdefault(pid, []).append(
                            (t_sec, objs, "age", AGE_RESEARCH_SECONDS[age])
                        )

    duration_ms = postgame_world_time or total_ms
    duration_seconds = duration_ms / 1000.0 if duration_ms else None

    # --- Build player summaries -------------------------------------------
    players: list[PlayerSummary] = []
    for idx, pid in enumerate(sorted(actions)):
        # Best-effort name: header string table, in slot order. Falls back to id.
        name = names[idx] if idx < len(names) else f"Player {pid}"
        tc = _estimate_main_tc_idle(tc_events.get(pid, []))
        players.append(
            PlayerSummary(
                player_id=pid,
                name=name,
                civ="unknown",  # TODO: full header parse for civ (see module docstring)
                age_timings=_build_age_timings(age_clicks.get(pid, {})),
                build_order=events.get(pid, []),
                action_count=actions.get(pid),
                build_count=builds.get(pid),
                make_count=units.get(pid),  # total units queued (MAKE + DE_QUEUE)
                military_units_produced=units.get(pid),  # queued units as a proxy
                main_tc_id=tc["tc_id"],
                main_tc_villagers=tc["villagers"],
                main_tc_first_seconds=tc["first"],
                main_tc_last_seconds=tc["last"],
                total_idle_tc_seconds=tc["idle_total"],
                main_tc_idle_gaps=tc["gaps"],
            )
        )

    return ReplaySummary(
        source_file=path,
        map_name=None,  # TODO: requires full header parse
        game_duration_seconds=duration_seconds,
        game_version=version,
        players=players,
        notes=[
            "Age CLICK times are read directly from the command stream (real). "
            "ARRIVAL times are estimated as click + standard research duration "
            "and ignore civ bonuses (e.g. Malay age up faster).",
            "Build order counts units when QUEUED, not when they pop — a queued "
            "villager takes ~25s to appear, and cancelled queues still count.",
            "Players controlled by the AI issue age-ups via AI orders, so their "
            "age timings may be missing.",
            "Civilizations, maps, and economy stats (idle TC, vils-by-age) are "
            "not extracted yet.",
        ],
    )


def _estimate_main_tc_idle(occupations: list[tuple]) -> dict:
    """Estimate idle time of the player's FIRST Town Center.

    `occupations` is a list of (time, object_ids, kind, value) where kind is
    "vil" (value=count, ~25s each) or "age" (value=research seconds). We pick
    the main TC as the object the first villager was trained from, then model
    its production line: any gap with nothing training/researching is idle.

    Idle is only counted between the first and last villager trained there (we
    don't penalise a TC you deliberately stopped using late-game).
    """
    empty = {
        "tc_id": None, "villagers": None, "first": None,
        "last": None, "idle_total": None, "gaps": [],
    }
    vil_events = [o for o in occupations if o[2] == "vil" and o[1]]
    if not vil_events:
        return empty

    main_tc = vil_events[0][1][0]
    # All occupations that involve the main TC, in chronological order.
    occ = sorted((o for o in occupations if main_tc in (o[1] or [])), key=lambda o: o[0])

    busy_until: Optional[float] = None
    idle_total = 0.0
    gaps: list[IdleGap] = []
    villagers = 0
    first = last = None

    for t, _objs, kind, value in occ:
        if busy_until is not None and t > busy_until:
            gap = t - busy_until
            if gap >= _MIN_IDLE_GAP_SECONDS:
                gaps.append(IdleGap(start=busy_until, seconds=gap))
                idle_total += gap
        if busy_until is None or t > busy_until:
            busy_until = t
        if kind == "vil":
            count = int(value)
            villagers += count
            if first is None:
                first = t
            last = t
            busy_until += VILLAGER_TRAIN_SECONDS * count
        else:  # age research occupies the TC for its full duration
            busy_until += float(value)

    gaps.sort(key=lambda g: g.seconds, reverse=True)
    return {
        "tc_id": main_tc, "villagers": villagers, "first": first,
        "last": last, "idle_total": idle_total, "gaps": gaps,
    }


def _build_age_timings(clicks: dict[str, float]) -> list[AgeTiming]:
    """Turn {age_name: click_seconds} into ordered AgeTiming rows."""
    timings: list[AgeTiming] = []
    for age in _AGE_ORDER:
        click = clicks.get(age)
        if click is None:
            continue
        research = AGE_RESEARCH_SECONDS[age]
        timings.append(
            AgeTiming(
                age=age,
                click_time=click,
                arrival_time=click + research,
                arrival_estimated=True,
            )
        )
    return timings


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
