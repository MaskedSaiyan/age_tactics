"""Tests for the replay parser.

Two layers:
  * a missing/garbage path must fall back to a valid MOCK ReplaySummary;
  * if a real sample .aoe2record is present, real parsing must yield sensible
    numbers (this test self-skips when no sample is available).
"""

import os

import pytest

from aoe2_analyzer.models import AgeTiming, PlayerSummary, ReplaySummary
from aoe2_analyzer.parser import parse_replay

SAMPLE = os.path.join(
    os.path.dirname(__file__), "..", "samples", "rec.aoe2record"
)


# --- Mock fallback (no real file) ----------------------------------------- #


def test_parse_replay_returns_replay_summary():
    summary = parse_replay("does/not/need/to/exist.aoe2record")
    assert isinstance(summary, ReplaySummary)


def test_missing_file_falls_back_to_mock():
    summary = parse_replay("whatever.aoe2record")
    assert summary.is_mock is True


def test_mock_summary_has_players():
    summary = parse_replay("whatever.aoe2record")
    assert len(summary.players) >= 1
    assert all(isinstance(p, PlayerSummary) for p in summary.players)


def test_mock_summary_records_source_file():
    path = "some/path/replay.aoe2record"
    summary = parse_replay(path)
    assert summary.source_file == path


def test_mock_goth_player_has_age_timings():
    summary = parse_replay("whatever.aoe2record")
    goth = next((p for p in summary.players if p.civ == "Goths"), None)
    assert goth is not None
    assert all(isinstance(t, AgeTiming) for t in goth.age_timings)
    assert goth.age("Castle") is not None


# --- Real parsing (only if a sample replay exists) ------------------------ #


@pytest.mark.skipif(
    not os.path.isfile(SAMPLE), reason="no sample .aoe2record in samples/"
)
def test_real_parse_extracts_sensible_data():
    summary = parse_replay(SAMPLE)
    assert isinstance(summary, ReplaySummary)
    assert summary.is_mock is False
    assert summary.game_version  # e.g. "VER 9.4"
    assert summary.game_duration_seconds and summary.game_duration_seconds > 0
    assert len(summary.players) >= 1
    # At least one player should have real activity counts.
    assert any(
        (p.action_count or 0) > 0 for p in summary.players
    ), "expected per-player action counts from the command stream"
