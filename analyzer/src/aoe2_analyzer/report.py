"""Pretty-print a ReplaySummary: age progression + build-order analysis."""

from __future__ import annotations

import os
import re
import shlex
import time

from .models import AgeTiming, BuildOrderEvent, PlayerSummary, ReplaySummary
from .resource import infer_resource

# Rough "good 1v1" click-up targets (seconds), for orientation only.
# These are ballpark benchmarks, not hard rules — they vary by map/strategy.
REFERENCE_CLICK_SECONDS = {"Feudal": 555.0, "Castle": 990.0, "Imperial": 1680.0}

# Units that are economic/utility rather than fighting army.
ECONOMIC_UNITS = {"Villager", "Fishing Ship", "Trade Cart", "Trade Cog"}


def _fmt_time(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def _fmt_delta(seconds: float) -> str:
    """Signed mm:ss, e.g. '+01:20' slower / '-00:45' faster than target."""
    sign = "+" if seconds >= 0 else "-"
    m, s = divmod(int(abs(seconds)), 60)
    return f"{sign}{m:02d}:{s:02d}"


def _na(value: object) -> str:
    return "n/a" if value is None else str(value)


# --------------------------------------------------------------------------- #
# Top-level summary
# --------------------------------------------------------------------------- #


def format_summary(
    summary: ReplaySummary, players: list[PlayerSummary] | None = None
) -> str:
    """Return the human-readable headline summary for a ReplaySummary.

    `players` restricts which players are shown (default: all).
    """
    shown = summary.players if players is None else players
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("AoE2 DE Replay Summary")
    lines.append("=" * 60)
    lines.append(f"File:     {summary.source_file}")
    lines.append(f"Version:  {summary.game_version or 'unknown'}")
    lines.append(f"Map:      {summary.map_name or 'unknown'}")
    lines.append(f"Duration: {_fmt_time(summary.game_duration_seconds)}")
    lines.append("")

    for p in shown:
        lines.extend(_format_player(p))
        lines.append("")

    if summary.notes:
        lines.append("Notes:")
        for note in summary.notes:
            lines.append(f"  - {note}")

    return "\n".join(lines).rstrip() + "\n"


def _format_player(p: PlayerSummary) -> list[str]:
    out: list[str] = []
    civ = "" if p.civ in (None, "unknown") else f" [{p.civ}]"
    flag = " 🏆" if p.winner else ""
    out.append(f"--- {p.name}{civ}{flag} ---")

    out.append("  Age progression:")
    if p.age_timings:
        for age in p.age_timings:
            arrow = "~" if age.arrival_estimated else " "
            click = f"~{_fmt_time(age.click_time)} (est)" if age.click_estimated \
                else f" {_fmt_time(age.click_time)}"
            tail = "" if age.click_estimated else f"   {_vs_target(age)}"
            out.append(
                f"    {age.age:<8} click {click}"
                f"   arrive {arrow}{_fmt_time(age.arrival_time)}"
                f"   (up-time {_fmt_time(age.transition_seconds)}){tail}"
            )
    else:
        out.append("    no age-up clicks found (AI player, or never advanced)")

    out.extend(_format_pace(p))
    out.extend(_format_age_breakdown(p))
    out.extend(_format_town_centers(p))
    out.extend(_format_tc_idle(p))

    out.append("  Activity (command stream):")
    out.append(f"    Actions issued:   {_na(p.action_count)}")
    out.append(f"    Buildings placed: {_na(p.build_count)}")
    out.append(f"    Units queued:     {_na(p.make_count)}")
    return out


def _vs_target(age: AgeTiming) -> str:
    target = REFERENCE_CLICK_SECONDS.get(age.age)
    if target is None or age.click_time is None:
        return ""
    delta = age.click_time - target
    label = "slower" if delta > 0 else "faster"
    return f"vs target {_fmt_delta(delta)} ({label})"


def _format_pace(p: PlayerSummary) -> list[str]:
    """Show the gaps between ages — the 'tiempos de avance' at a glance."""
    feudal, castle, imperial = p.age("Feudal"), p.age("Castle"), p.age("Imperial")

    def gap(a: AgeTiming | None, b: AgeTiming | None) -> str:
        if a is None or b is None or a.click_time is None or b.click_time is None:
            return "--:--"
        return _fmt_time(b.click_time - a.click_time)

    out = ["  Pace (time between age-up clicks):"]
    out.append(f"    Dark   → Feudal:   {_fmt_time(feudal.click_time) if feudal else '--:--'}")
    out.append(f"    Feudal → Castle:   {gap(feudal, castle)}")
    out.append(f"    Castle → Imperial: {gap(castle, imperial)}")
    return out


# --------------------------------------------------------------------------- #
# Build-order analysis
# --------------------------------------------------------------------------- #


def _is_military(name: str) -> bool:
    return name not in ECONOMIC_UNITS


def _counts_up_to(events: list[BuildOrderEvent], cutoff: float | None) -> tuple[int, int, int]:
    """(villagers, military units, buildings) queued/placed up to `cutoff` seconds."""
    vills = mil = bld = 0
    for e in events:
        if cutoff is not None and e.game_time > cutoff:
            break
        if e.kind == "unit":
            if e.name == "Villager":
                vills += e.count
            elif _is_military(e.name):
                mil += e.count
        elif e.kind == "building":
            bld += e.count
    return vills, mil, bld


def _format_age_breakdown(p: PlayerSummary) -> list[str]:
    """Villagers / military / buildings queued by the time of each age click."""
    if not p.build_order:
        return []
    out = ["  Production by age (cumulative, when queued):"]
    for age in p.age_timings:
        v, m, b = _counts_up_to(p.build_order, age.click_time)
        out.append(
            f"    By {age.age} ({_fmt_time(age.click_time)}): "
            f"{v} villagers, {m} military, {b} buildings"
        )
    v, m, b = _counts_up_to(p.build_order, None)
    out.append(f"    Game total:        {v} villagers, {m} military, {b} buildings")
    return out


def _format_town_centers(p: PlayerSummary) -> list[str]:
    """Every Town Center that trained villagers, its online window and own idle."""
    if not p.town_centers:
        return []
    n = len(p.town_centers)
    total_idle = sum(tc.idle_seconds for tc in p.town_centers)
    out = [f"  Town Centers: {n}" + ("  (boom)" if n >= 3 else "")
           + f"   — total idle across all TCs: {_fmt_time(total_idle)}"
           f" (≈ {total_idle / 25.0:.0f} villagers' worth)"]
    for i, tc in enumerate(p.town_centers, 1):
        tag = " (starting)" if i == 1 else ""
        out.append(
            f"    TC{i}{tag}: villagers {_fmt_time(tc.first)} → {_fmt_time(tc.last)}"
            f"   idle {_fmt_time(tc.idle_seconds)}"
        )
    return out


def _format_tc_idle(p: PlayerSummary, top_gaps: int = 5) -> list[str]:
    """Show the estimated idle time of the player's first Town Center."""
    if p.main_tc_id is None or p.total_idle_tc_seconds is None:
        return []
    multi = len(p.town_centers) > 1
    label = "First Town Center" if multi else "Main Town Center"
    out = [f"  {label} (obj {p.main_tc_id}) — idle estimate:"]
    out.append(f"    Production window:      {_fmt_time(p.main_tc_first_seconds)}"
               f" → {_fmt_time(p.main_tc_last_seconds)}")
    lost_vils = p.total_idle_tc_seconds / 25.0
    out.append(
        f"    Idle (not training):    {_fmt_time(p.total_idle_tc_seconds)}"
        f"  (≈ {lost_vils:.1f} villagers' worth)"
    )
    if p.main_tc_idle_gaps:
        out.append(f"    Longest idle gaps (top {min(top_gaps, len(p.main_tc_idle_gaps))}):")
        for gap in p.main_tc_idle_gaps[:top_gaps]:
            out.append(
                f"      at {_fmt_time(gap.start)}  idle {_fmt_time(gap.seconds)}"
            )
    if multi:
        out.append("    ⚠ Idle covers only this first TC. With batch-queueing across "
                   f"{len(p.town_centers)} TCs it reads low — judge the boom by TC count "
                   "+ villagers, not this number.")
    return out


def _cum_idle(gaps: list, cutoff: float) -> float:
    """Total main-TC idle seconds up to `cutoff` (a gap straddling it counts partly)."""
    total = 0.0
    for g in gaps:
        if g.start >= cutoff:
            continue
        total += min(g.seconds, cutoff - g.start)
    return total


def format_progression(summary: ReplaySummary, step_seconds: int = 180) -> str:
    """Cross-player timeline: cumulative villagers & military at each time mark.

    This is the 'how the game progressed' view — it shows the state of every
    player *at each moment*, so you can see who was ahead minute by minute
    instead of only the end-of-game totals (which late AI production inflates).
    """
    players = summary.players
    if not players:
        return ""
    dur = summary.game_duration_seconds or 0
    marks = list(range(step_seconds, int(dur) + 1, step_seconds))
    if not marks:
        return ""

    def col(name: str) -> str:
        return f"{name[:9]:>9s}"

    header = "  time  | " + " ".join(col(p.name) for p in players)

    def table(title: str, military: bool) -> list[str]:
        rows = [f"  {title}", header]
        for t in marks:
            cells = []
            for p in players:
                v, m, _ = _counts_up_to(p.build_order, t)
                cells.append(f"{(m if military else v):9d}")
            rows.append(f"  {_fmt_time(t)} | " + " ".join(cells))
        return rows

    def idle_table() -> list[str]:
        rows = ["  TC IDLE over time (cumulative, mm:ss not training):", header]
        for t in marks:
            cells = []
            for p in players:
                if p.main_tc_id is None:  # AI / no modelled TC — not measured, not zero
                    cells.append(f"{'—':>9s}")
                else:
                    cells.append(f"{_fmt_time(_cum_idle(p.main_tc_idle_gaps, t)):>9s}")
            rows.append(f"  {_fmt_time(t)} | " + " ".join(cells))
        return rows

    out = ["=" * 60, "PROGRESSION — cumulative by time (queued)", "=" * 60]
    out.append("Age clicks:")
    for p in players:
        if not p.age_timings:
            continue
        clicks = "  ".join(
            f"{a.age[0]} {'~' if a.click_estimated else ''}{_fmt_time(a.click_time)}"
            for a in p.age_timings if a.click_time is not None
        )
        if clicks:
            tag = "  (IA, ~estimado)" if p.is_ai else ""
            out.append(f"  {p.name[:18]:<18} {clicks}{tag}")
    out.append("")
    out.extend(table("VILLAGERS over time:", military=False))
    out.append("")
    out.extend(table("MILITARY over time:", military=True))
    out.append("")
    out.extend(idle_table())
    out.append("")
    out.append("(Vill/military are cumulative units QUEUED — not alive; they exclude")
    out.append(" the free starting 3 vills + scout, and totals inflate late as AIs")
    out.append(" keep producing. TC idle is the main TC's lost training time so far —")
    out.append(" lower is better; a climbing column is economy bleeding out.)")
    return "\n".join(out) + "\n"


def format_build_order(p: PlayerSummary) -> str:
    """Return the full numbered build-order timeline for one player."""
    lines = ["=" * 60, f"BUILD ORDER — {p.name}", "=" * 60]
    if not p.build_order:
        lines.append("(no build-order events — likely an AI player)")
        return "\n".join(lines) + "\n"

    # Idle gaps of the main TC, woven into the timeline at the moment they start
    # so you can see exactly which villager-clicks were missed (and where).
    idle = sorted(p.main_tc_idle_gaps, key=lambda g: g.start)
    gi = 0

    def flush_idle(until: float) -> None:
        nonlocal gi
        while gi < len(idle) and idle[gi].start <= until:
            g = idle[gi]
            lost = g.seconds / 25.0
            lines.append(
                f"  {_fmt_time(g.start)}  ⏳ TC idle {_fmt_time(g.seconds)}"
                f"  (≈ {lost:.1f} vill{'s' if lost >= 2 else ''} missed)"
            )
            gi += 1

    current_age = "Dark Age"
    lines.append(f"[{current_age}]")
    vill_no = 0
    for e in p.build_order:
        flush_idle(e.game_time)
        if e.kind == "age":
            current_age = e.name
            lines.append("")
            lines.append(f"[{current_age}]  (clicked {_fmt_time(e.game_time)})")
            continue
        if e.kind == "building":
            lines.append(f"  {_fmt_time(e.game_time)}  🏠 {e.name}")
            continue
        # unit
        if e.name == "Villager":
            if e.count == 1:
                vill_no += 1
                label = f"Villager #{vill_no}"
            else:
                label = f"Villager #{vill_no + 1}–#{vill_no + e.count} (x{e.count})"
                vill_no += e.count
        else:
            label = e.name if e.count == 1 else f"{e.name} x{e.count}"
        icon = "👤" if e.name == "Villager" else "⚔️ "
        lines.append(f"  {_fmt_time(e.game_time)}  {icon} {label}")

    flush_idle(float("inf"))
    return "\n".join(lines) + "\n"


def _fmt_pos(x: float | None, y: float | None) -> str:
    if x is None or y is None:
        return ""
    return f"@ ({x:.1f}, {y:.1f})"


def _player_dropoffs(summary: ReplaySummary, owner: int | None) -> list[tuple]:
    if owner is None:
        return []
    p = next((pl for pl in summary.players if pl.player_id == owner), None)
    return p.resource_dropoffs if p else []


def format_unit_log(summary: ReplaySummary, object_id: int) -> str:
    """Return the chronological command log for one unit (by object id)."""
    cmds = summary.unit_commands.get(object_id)
    owner = summary.unit_owner.get(object_id)
    dropoffs = _player_dropoffs(summary, owner)
    owner_name = None
    if owner is not None:
        owner_name = next(
            (p.name for p in summary.players if p.player_id == owner), f"player {owner}"
        )

    is_villager = object_id in summary.builder_ids
    kind = "Villager" if is_villager else "Unit"
    header = f"{kind} {object_id}"
    if owner_name:
        header += f"  (owner: {owner_name})"

    lines = ["=" * 60, header, "=" * 60]
    if not cmds:
        lines.append("(no commands recorded for this object id)")
        return "\n".join(lines) + "\n"

    for c in cmds:
        verb = c.action.lower()
        bits = [f"  {_fmt_time(c.game_time)}  {verb:<8}"]
        if c.detail:
            bits.append(f"-> {c.detail}")
        elif c.action == "ORDER":
            res = infer_resource(c.x, c.y, dropoffs, c.game_time)
            bits.append(f"-> {res}" if res else "-> gather")
        elif c.target_id not in (None, -1):
            bits.append(f"-> target {c.target_id}")
        else:
            bits.append("->")
        pos = _fmt_pos(c.x, c.y)
        if pos:
            bits.append(pos)
        lines.append(" ".join(bits))
    lines.append("")
    lines.append("(resource = inferred from nearest drop-off camp; best-effort, not exact)")
    return "\n".join(lines) + "\n"


def format_villager_list(summary: ReplaySummary, player_id: int | None = None) -> str:
    """List builder units (villagers) and how many commands each received."""
    lines = ["=" * 60, "Villager-like units (issued at least one BUILD)", "=" * 60]
    ids = sorted(summary.builder_ids)
    if player_id is not None:
        ids = [i for i in ids if summary.unit_owner.get(i) == player_id]

    if not ids:
        lines.append("(none found)")
        return "\n".join(lines) + "\n"

    # Group by owner for readability.
    by_owner: dict[int, list[int]] = {}
    for oid in ids:
        by_owner.setdefault(summary.unit_owner.get(oid, -1), []).append(oid)

    for owner, oids in by_owner.items():
        owner_name = next(
            (p.name for p in summary.players if p.player_id == owner), f"player {owner}"
        )
        lines.append(f"\n{owner_name} ({len(oids)} villagers):")
        for oid in oids:
            cmds = summary.unit_commands.get(oid, [])
            first = cmds[0].game_time if cmds else None
            lines.append(
                f"  obj {oid:<6} first seen {_fmt_time(first)}   {len(cmds)} commands"
            )
    return "\n".join(lines) + "\n"


# Buildings a villager constructs that imply what it then gathers.
_BUILD_RESOURCE = {"Farm": "food", "Mill": "food", "Lumber Camp": "wood",
                   "Mining Camp": "gold/stone"}


def _assignment(task, dropoffs: list[tuple]) -> tuple[str, str]:
    """(resource, human-readable detail) for a villager's first task command."""
    if task is None:
        return "unknown", "no task command recorded"
    where = _fmt_pos(task.x, task.y)
    when = _fmt_time(task.game_time)
    if task.action == "BUILD":
        res = _BUILD_RESOURCE.get(task.detail or "")
        if res:
            return res, f"built {task.detail} ({res}) at {when} {where}".rstrip()
        # Non-resource build (house, etc.) — fall back to position inference.
        res = infer_resource(task.x, task.y, dropoffs, task.game_time) or "unknown"
        return res, f"built {task.detail} at {when} {where}".rstrip()
    res = infer_resource(task.x, task.y, dropoffs, task.game_time) or "unknown"
    return res, f"first sent to {res} at {when} {where}".rstrip()


def format_assignments(summary: ReplaySummary, player_id: int) -> str:
    """Number villagers by real appearance order and show their first task.

    Unlike the build order (numbered by *queue* order, which omits the starting
    villagers), this lists villagers by when they first received a command —
    their true order — and infers the resource of their first gather order.
    """
    dropoffs = _player_dropoffs(summary, player_id)
    villagers = [v for v in summary.builder_ids if summary.unit_owner.get(v) == player_id]
    villagers.sort(key=lambda o: summary.unit_commands[o][0].game_time)

    owner_name = next(
        (p.name for p in summary.players if p.player_id == player_id), f"player {player_id}"
    )
    lines = ["=" * 60, f"VILLAGER ASSIGNMENTS — {owner_name}", "=" * 60]
    if not villagers:
        lines.append("(no villagers identified for this player)")
        return "\n".join(lines) + "\n"

    tally: dict[str, int] = {}
    for i, oid in enumerate(villagers, 1):
        cmds = summary.unit_commands[oid]
        first_seen = cmds[0].game_time
        # First task = earliest ORDER (gather) or BUILD (often farms -> food).
        task = next((c for c in cmds if c.action in ("ORDER", "BUILD")), None)
        res, detail = _assignment(task, dropoffs)
        tally[res] = tally.get(res, 0) + 1
        lines.append(f"  Villager #{i:<2} (obj {oid})  appeared {_fmt_time(first_seen)}  — {detail}")

    lines.append("")
    lines.append("First-task tally (inferred):")
    for res, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {res:<12} {n}")
    lines.append("")
    lines.append("(villagers = units that issued a BUILD; resource inferred from nearest")
    lines.append(" drop-off camp at order time — best-effort, weak before camps exist)")
    return "\n".join(lines) + "\n"


def _human_players(summary: ReplaySummary) -> list[PlayerSummary]:
    """Human players (deep-dived by default). Falls back to all players."""
    return [p for p in summary.players if not p.is_ai] or summary.players


def find_player(summary: ReplaySummary, query: str) -> PlayerSummary | None:
    """Resolve a player by numeric id or (case-insensitive) name substring."""
    q = query.strip()
    if q.isdigit():
        pid = int(q)
        return next((p for p in summary.players if p.player_id == pid), None)
    ql = q.lower()
    exact = [p for p in summary.players if p.name.lower() == ql]
    if exact:
        return exact[0]
    sub = [p for p in summary.players if ql in p.name.lower()]
    return sub[0] if sub else None


def format_report(
    summary: ReplaySummary, players: list[PlayerSummary] | None = None
) -> str:
    """One full, sectioned report: overview + per-player build order + assignments.

    `players` restricts the report to specific players (default: humans).
    """
    deep_dive = players if players is not None else _human_players(summary)
    parts: list[str] = []
    parts.append("#" * 60)
    parts.append("#  SECTION 1 — OVERVIEW (timings, pace, TC idle, activity)")
    parts.append("#" * 60)
    parts.append(format_summary(summary, deep_dive))

    progression = format_progression(summary)
    if progression:
        parts.append("")
        parts.append("#" * 60)
        parts.append("#  SECTION 1b — PROGRESSION (who led, minute by minute)")
        parts.append("#" * 60)
        parts.append(progression)

    for p in deep_dive:
        parts.append("")
        parts.append("#" * 60)
        parts.append(f"#  SECTION 2 — BUILD ORDER — {p.name}")
        parts.append("#" * 60)
        parts.append(format_build_order(p))

        parts.append("")
        parts.append("#" * 60)
        parts.append(f"#  SECTION 3 — VILLAGER ASSIGNMENTS — {p.name}")
        parts.append("#" * 60)
        parts.append(format_assignments(summary, p.player_id))

    return "\n".join(parts)


def matchup(names: list[str]) -> str:
    """'A vs B' from scraped player names (or 'unknown')."""
    real = [n for n in names if n]
    return " vs ".join(real) if real else "unknown"


def suggested_name(names: list[str], duration_seconds: float | None = None) -> str:
    """A filesystem-safe slug like 'soad-vs-PromiDE-35m' for renaming."""
    real = [n for n in names if n] or ["unknown"]
    slug = "-vs-".join(real)
    if duration_seconds:
        slug += f"-{int(duration_seconds // 60)}m"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", slug).strip("_")
    return slug or "unknown"


def dated_filename(
    path: str, summary: ReplaySummary, mtime: float | None = None
) -> str:
    """Date-first filename: 'YYYY-MM-DD-HHMM_soad-vs-...-56m.aoe2record'.

    The date comes from the original AoE2 filename's '@YYYY.MM.DD HHMMSS' tag,
    falling back to the file's modification time. Date-first keeps games sorted
    chronologically and avoids the collisions a matchup-only name causes.
    """
    names = [p.name for p in summary.players]
    slug = "-vs-".join(n for n in names if n) or "unknown"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", slug).strip("_")

    base = os.path.basename(path)
    m = re.search(r"@(\d{4})\.(\d{2})\.(\d{2}) (\d{2})(\d{2})", base)
    if m:
        date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}-{m.group(4)}{m.group(5)}"
    elif mtime:
        date = time.strftime("%Y-%m-%d-%H%M", time.localtime(mtime))
    else:
        date = ""

    dur = summary.game_duration_seconds
    dur_part = f"{int(dur // 60)}m" if dur else ""
    parts = [p for p in (date, slug, dur_part) if p]
    return "_".join(parts) + ".aoe2record"


def rename_command(path: str, summary: ReplaySummary, mtime: float | None = None) -> str:
    """A ready-to-paste 'mv <path> <dir>/<dated name>' line for quick renaming."""
    target = os.path.join(os.path.dirname(path), dated_filename(path, summary, mtime))
    return f"mv {shlex.quote(path)} {shlex.quote(target)}"


def format_identity(path: str, summary: ReplaySummary) -> str:
    """One line per replay: 'file: A vs B  [VER 9.4, 35:07]  -> suggested.aoe2record'."""
    base = os.path.basename(path)
    names = [p.name for p in summary.players]
    version = summary.game_version or "?"
    dur = _fmt_time(summary.game_duration_seconds)
    return (
        f"{base}: {matchup(names)}  [{version}, {dur}]"
        f"  -> {suggested_name(names, summary.game_duration_seconds)}.aoe2record"
    )


def print_report(
    summary: ReplaySummary, players: list[PlayerSummary] | None = None
) -> None:
    print(format_report(summary, players), end="")


def print_summary(summary: ReplaySummary) -> None:
    print(format_summary(summary), end="")


# --------------------------------------------------------------------------- #
# Cross-game comparison
# --------------------------------------------------------------------------- #

# Metric order for compare tables: (label, function -> formatted str).
def player_metric_rows(p: PlayerSummary) -> list[tuple[str, str]]:
    """Key headline metrics for one player, as (label, value) rows."""
    feudal, castle, imp = p.age("Feudal"), p.age("Castle"), p.age("Imperial")

    def click(a) -> str:
        return _fmt_time(a.click_time) if a else "--:--"

    def gap(a, b) -> str:
        if a and b and a.click_time is not None and b.click_time is not None:
            return _fmt_time(b.click_time - a.click_time)
        return "--:--"

    vf = _counts_up_to(p.build_order, feudal.click_time if feudal else None)
    vc = _counts_up_to(p.build_order, castle.click_time if castle else None)
    total = _counts_up_to(p.build_order, None)
    idle = _fmt_time(p.total_idle_tc_seconds) if p.total_idle_tc_seconds is not None else "--:--"

    return [
        ("Feudal click", click(feudal)),
        ("Castle click", click(castle)),
        ("Imperial click", click(imp)),
        ("Feudal→Castle", gap(feudal, castle)),
        ("Vills by Feudal", str(vf[0])),
        ("Vills by Castle", str(vc[0])),
        ("Total villagers", str(total[0])),
        ("Total military", str(total[1])),
        ("Main TC idle", idle),
    ]


def format_compare(games: list[tuple[str, PlayerSummary]]) -> str:
    """Side-by-side table of key metrics across games for one player.

    `games` is a list of (game_label, PlayerSummary).
    """
    if not games:
        return "(no games to compare)\n"

    rows = [player_metric_rows(p) for _, p in games]
    labels = [lbl for lbl, _ in rows[0]]

    # Column widths: metric label column + one column per game.
    label_w = max(len(l) for l in labels)
    headers = [f"G{i+1}" for i in range(len(games))]
    col_w = max(6, *(len(h) for h in headers))

    out = ["Legend:"]
    for i, (lbl, _) in enumerate(games):
        out.append(f"  G{i+1} = {lbl}")
    out.append("")

    out.append(f"{'metric':<{label_w}}  " + "  ".join(f"{h:>{col_w}}" for h in headers))
    out.append(f"{'-' * label_w}  " + "  ".join("-" * col_w for _ in headers))
    for r, label in enumerate(labels):
        values = [rows[g][r][1] for g in range(len(games))]
        out.append(f"{label:<{label_w}}  " + "  ".join(f"{v:>{col_w}}" for v in values))
    return "\n".join(out) + "\n"
