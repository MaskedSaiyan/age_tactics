"""aoe2_analyzer — exploratory AoE2 DE replay parser.

NOTE: This package is a scaffold. The parser currently returns mock data;
real .aoe2record parsing is not implemented yet. See parser.py.
"""

__version__ = "0.0.1"

from .models import AgeTiming, EconomySnapshot, PlayerSummary, ReplaySummary

__all__ = [
    "AgeTiming",
    "EconomySnapshot",
    "PlayerSummary",
    "ReplaySummary",
    "__version__",
]
