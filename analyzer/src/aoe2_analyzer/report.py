"""Pretty-print a ReplaySummary to the terminal."""

from __future__ import annotations

from .models import PlayerSummary, ReplaySummary


def _fmt_time(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def format_summary(summary: ReplaySummary) -> str:
    """Return a human-readable string for a ReplaySummary."""
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("AoE2 DE Replay Summary")
    lines.append("=" * 60)
    if summary.is_mock:
        lines.append("⚠️  MOCK DATA — real parsing was unavailable.")
        lines.append("")
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


def _na(value: object) -> str:
    """Render None as 'n/a' so unknown != zero."""
    return "n/a" if value is None else str(value)


def _format_player(p: PlayerSummary) -> list[str]:
    out: list[str] = []
    flag = " 🏆" if p.winner else ""
    team = f"team {p.team}" if p.team is not None else "team ?"
    out.append(f"--- {p.name} [{p.civ}] ({team}){flag} ---")

    for age in p.age_timings:
        out.append(
            f"  {age.age:<9} click {_fmt_time(age.click_time)}"
            f"  arrive {_fmt_time(age.arrival_time)}"
            f"  (up-time {_fmt_time(age.transition_seconds)})"
        )

    # Real activity stats (from the command stream).
    out.append(f"  Actions issued:    {_na(p.action_count)}")
    out.append(f"  Buildings placed:  {_na(p.build_count)}")
    out.append(f"  Units queued:      {_na(p.make_count)}")

    # Reconstructed eco stats (still TODO for real replays -> usually n/a).
    out.append(f"  Final villagers:   {_na(p.final_villagers)}")
    out.append(f"  Peak Town Centers: {_na(p.peak_town_centers)}")
    out.append(f"  Idle TC time:      {_fmt_time(p.total_idle_tc_seconds)}")
    out.append(f"  Housed time:       {_fmt_time(p.total_housed_seconds)}")
    return out


def print_summary(summary: ReplaySummary) -> None:
    print(format_summary(summary), end="")
