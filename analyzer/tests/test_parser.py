"""Tests for the replay parser.

  * a missing/garbage path must raise a clear ReplayParseError (no mock fallback);
  * with the bundled sample .aoe2record, real parsing must yield sensible numbers
    and extract age-up click times (this test self-skips if the sample is absent).
"""

import os

import pytest

from aoe2_analyzer.models import AgeTiming, ReplaySummary
from aoe2_analyzer.parser import ReplayParseError, parse_replay

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "samples", "rec.aoe2record")


# --- Failure handling (no real file) -------------------------------------- #


def test_missing_file_raises():
    with pytest.raises(ReplayParseError):
        parse_replay("does/not/exist.aoe2record")


# --- Real parsing (only if the sample replay exists) ---------------------- #


@pytest.mark.skipif(not os.path.isfile(SAMPLE), reason="no sample .aoe2record")
def test_real_parse_extracts_sensible_data():
    summary = parse_replay(SAMPLE)
    assert isinstance(summary, ReplaySummary)
    assert summary.game_version  # e.g. "VER 9.4"
    assert summary.game_duration_seconds and summary.game_duration_seconds > 0
    assert len(summary.players) >= 1
    assert any((p.action_count or 0) > 0 for p in summary.players), (
        "expected per-player action counts from the command stream"
    )


@pytest.mark.skipif(not os.path.isfile(SAMPLE), reason="no sample .aoe2record")
def test_real_parse_extracts_age_timings():
    summary = parse_replay(SAMPLE)
    # At least one player advanced an age, so some AgeTiming must be present.
    aged = [p for p in summary.players if p.age_timings]
    assert aged, "expected at least one player with age-up timings"

    for p in aged:
        for t in p.age_timings:
            assert isinstance(t, AgeTiming)
            assert t.click_time is not None and t.click_time > 0
            # arrival is estimated as click + research time, so strictly later.
            assert t.arrival_time is not None and t.arrival_time > t.click_time
            assert t.arrival_estimated is True

    # Ages, when present, must be in chronological order (Feudal before Castle…).
    for p in aged:
        clicks = [t.click_time for t in p.age_timings]
        assert clicks == sorted(clicks), "age clicks should be chronological"


@pytest.mark.skipif(not os.path.isfile(SAMPLE), reason="no sample .aoe2record")
def test_real_parse_reconstructs_build_order():
    summary = parse_replay(SAMPLE)
    aged = [p for p in summary.players if p.age_timings]
    assert aged, "expected a player with a build order"
    p = aged[0]

    assert p.build_order, "expected build-order events"
    # Events must be chronological.
    times = [e.game_time for e in p.build_order]
    assert times == sorted(times)
    # A real game queues villagers and places buildings.
    assert any(e.kind == "unit" and e.name == "Villager" for e in p.build_order)
    assert any(e.kind == "building" for e in p.build_order)
    # Age markers appear in the timeline too.
    assert any(e.kind == "age" for e in p.build_order)


@pytest.mark.skipif(not os.path.isfile(SAMPLE), reason="no sample .aoe2record")
def test_real_parse_tracks_individual_units():
    summary = parse_replay(SAMPLE)
    # Builders (villagers) are identified, and each has a command log.
    assert summary.builder_ids, "expected builder (villager) object ids"
    oid = next(iter(summary.builder_ids))
    cmds = summary.unit_commands[oid]
    assert cmds, "a builder should have at least one command"
    # Commands are chronological and a builder issued at least one BUILD.
    times = [c.game_time for c in cmds]
    assert times == sorted(times)
    assert any(c.action == "BUILD" for c in summary.unit_commands[oid])
    # Ownership is recorded and points at a real player.
    assert summary.unit_owner[oid] in {p.player_id for p in summary.players}
