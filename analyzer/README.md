# analyzer/ — AoE2 DE replay analyzer (exploratory)

A Python project for parsing **AoE2 DE replay/save files** (`.aoe2record`) and extracting useful
stats to help you improve — especially the boring-but-game-losing stuff like idle TC time and
late Age clicks.

## Status: partially working — exploratory

We use the [`mgz`](https://pypi.org/project/mgz/) library to walk the replay's **command
stream** (the body of the file). That part is robust, so some stats are now **real**. The
**header** (civs, map) isn't fully parseable for every DE sub-version yet, so those fall back
to `unknown`. If `mgz` is missing or a file can't be read, the parser returns a clearly-flagged
**mock** summary so the CLI and tests still run.

### ✅ Working now (real data, read from the file)
- **Game version** string (e.g. `VER 9.4`).
- **Real game duration** (from SYNC operations / postgame `world_time`).
- **Per-player activity**: total actions, buildings placed (`BUILD`), units queued (`MAKE`).
- **Player names** (scraped from the header string table — slot order, may not align with
  action `player_id`s; flagged in the output notes).

### 🚧 Still TODO (needs full header parse or command-stream simulation)
- **Civilizations** per player (header parse unsupported for this DE sub-version).
- **Feudal / Castle / Imperial click and arrival times.**
- **Villager count by age** and **resource distribution over time.**
- **Town Center idle time** — the silent game-loser.
- **Farm count** and **number of Town Centers** (catch the Goth "too many TCs" trap).
- **Housed time** — how long you spent population-blocked.
- **Build order reconstruction** — a timeline of what was built/queued when.

⚠️ Don't over-trust the numbers yet. Duration and activity counts are solid; everything marked
`n/a` or `unknown` is not extracted yet.

## Usage (skeleton)

```bash
python -m aoe2_analyzer analyze path/to/replay.aoe2record
```

With a real `.aoe2record` this prints the version, real duration, and per-player activity.
With a missing/unreadable file it prints a clearly-labelled mock summary instead.

## Project layout

```
analyzer/
├── README.md
├── pyproject.toml
├── src/
│   └── aoe2_analyzer/
│       ├── __init__.py
│       ├── cli.py        <- argparse CLI: `python -m aoe2_analyzer analyze <file>`
│       ├── parser.py     <- returns a MOCK ReplaySummary (real parsing = TODO)
│       ├── models.py     <- dataclasses: PlayerSummary, AgeTiming, EconomySnapshot, ReplaySummary
│       └── report.py     <- pretty-print a ReplaySummary to the terminal
├── tests/
│   └── test_parser.py    <- validates the mock parser returns a ReplaySummary
└── samples/
    └── README.md         <- drop sample .aoe2record files here (gitignored ideally)
```

## Development

```bash
cd analyzer
pip install -e .
python -m aoe2_analyzer analyze samples/whatever.aoe2record
pytest
```

## Notes on the real parsing problem (for future me)

- `.aoe2record` files are essentially a recorded command stream + a header, not a state dump.
- Most stats (idle TC time, vils-by-age) have to be **reconstructed by simulating the command
  log**, which is the hard part.
- Consider leaning on existing community work rather than starting from zero — see `parser.py`
  TODOs for candidate libraries to investigate.
