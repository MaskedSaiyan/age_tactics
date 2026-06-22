# analyzer/ — AoE2 DE replay analyzer

A Python tool that parses **AoE2 DE replay files** (`.aoe2record`) and reconstructs your
**build order** and **age-up timings** so you can see exactly where to improve — when you
clicked each age and how many villagers / military / buildings you had by then.

## How it works

We use the [`mgz`](https://pypi.org/project/mgz/) library to walk the replay's **command
stream** (the body of the file) — every action each player took, interleaved with time ticks.
That stream is robust across DE versions, so the timings and build order are **real data read
straight from the file**. The header (civ, map) isn't fully parseable for every DE sub-version
yet, so those still show `unknown`.

### ✅ Extracted now (real data)
- **Game version** (e.g. `VER 9.4`) and **real game duration**.
- **Age-up timings**: when **Feudal / Castle / Imperial** were *clicked* (read from the
  RESEARCH action on each age tech). Arrival is estimated as click + standard research time.
- **Pace**: time spent in each age (Dark→Feudal, Feudal→Castle, Castle→Imperial).
- **Build order**: a chronological, numbered timeline of every unit queued
  (`MAKE` + `DE_QUEUE`) and building placed (`BUILD`), with age markers — i.e. Villager #1..N,
  the military, and buildings up to each age.
- **Production by age**: cumulative villagers / military / buildings at each age click.
- **Player names** (scraped from the header string table, slot order).

### 🚧 Roadmap (needs command-stream simulation / full header parse)
- **Civilizations** per player and **map**.
- **Resource distribution over time** and **villagers actually alive** (vs queued).
- **Town Center idle time** — the silent game-loser.
- **Farm count** and **number of Town Centers** (catch the Goth "too many TCs" trap).
- **Housed time** — how long you spent population-blocked.

> Counts are recorded when a unit is **queued**, not when it pops (a villager takes ~25s to
> appear, and cancelled queues still count). AI players issue orders differently, so their
> age timings / build order may be missing.

## Usage

```bash
# Headline summary: age timings, pace, production-by-age, activity.
python -m aoe2_analyzer analyze path/to/replay.aoe2record

# Same, plus the full numbered build-order timeline.
python -m aoe2_analyzer analyze path/to/replay.aoe2record --build-order
```

## Project layout

```
analyzer/
├── README.md
├── pyproject.toml
├── src/
│   └── aoe2_analyzer/
│       ├── cli.py        <- argparse CLI: `analyze <file> [--build-order]`
│       ├── parser.py     <- walks the command stream -> ReplaySummary
│       ├── gamedata.py   <- unit/building id -> name lookups
│       ├── models.py     <- dataclasses: AgeTiming, BuildOrderEvent, PlayerSummary, …
│       └── report.py     <- pretty-print summary + build order
├── tests/
│   └── test_parser.py    <- real-parse tests against samples/rec.aoe2record
└── samples/
    └── rec.aoe2record    <- sample replay used by the tests
```

## Development

```bash
cd analyzer
pytest                 # tests add src/ to the path automatically (see pyproject)
python -m aoe2_analyzer analyze samples/rec.aoe2record --build-order
```

Adding a new unit/building name? Put the id in `gamedata.py`. Unknown ids render as
`Unit #<id>` / `Building #<id>` so the build order stays readable without risking wrong labels.
