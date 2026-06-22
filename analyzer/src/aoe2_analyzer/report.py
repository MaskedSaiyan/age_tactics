"""Pretty-print a ReplaySummary: age progression + build-order analysis."""

from __future__ import annotations

from .models import AgeTiming, BuildOrderEvent, PlayerSummary, ReplaySummary

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


def format_summary(summary: ReplaySummary) -> str:
    """Return the human-readable headline summary for a ReplaySummary."""
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("AoE2 DE Replay Summary")
    lines.append("=" * 60)
    lines.append(f"File:     {summary.source_file}")
    lines.append(f"Version:  {summary.game_version or 'unknown'}")
    lines.append(f"Map:      {summary.map_name or 'unknown'}")
    lines.append(f"Duration: {_fmt_time(summary.game_duration_seconds)}")
    lines.append("")

    for p in summary.players:
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
            out.append(
                f"    {age.age:<8} click {_fmt_time(age.click_time)}"
                f"   arrive {arrow}{_fmt_time(age.arrival_time)}"
                f"   (up-time {_fmt_time(age.transition_seconds)})"
                f"   {_vs_target(age)}"
            )
    else:
        out.append("    no age-up clicks found (AI player, or never advanced)")

    out.extend(_format_pace(p))
    out.extend(_format_age_breakdown(p))
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


def _format_tc_idle(p: PlayerSummary, top_gaps: int = 5) -> list[str]:
    """Show the estimated idle time of the player's first Town Center."""
    if p.main_tc_id is None or p.total_idle_tc_seconds is None:
        return []
    out = [f"  Main Town Center (obj {p.main_tc_id}) — idle estimate:"]
    out.append(f"    Villagers trained here: {p.main_tc_villagers}")
    out.append(
        f"    Production window:      {_fmt_time(p.main_tc_first_seconds)}"
        f" → {_fmt_time(p.main_tc_last_seconds)}"
    )
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
    return out


def format_build_order(p: PlayerSummary) -> str:
    """Return the full numbered build-order timeline for one player."""
    lines = ["=" * 60, f"BUILD ORDER — {p.name}", "=" * 60]
    if not p.build_order:
        lines.append("(no build-order events — likely an AI player)")
        return "\n".join(lines) + "\n"

    current_age = "Dark Age"
    lines.append(f"[{current_age}]")
    vill_no = 0
    for e in p.build_order:
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

    return "\n".join(lines) + "\n"


def print_summary(summary: ReplaySummary) -> None:
    print(format_summary(summary), end="")


def print_build_orders(summary: ReplaySummary) -> None:
    """Print the full numbered build order for each human (age-clicking) player."""
    players = [p for p in summary.players if p.age_timings] or summary.players
    for p in players:
        print()
        print(format_build_order(p), end="")
