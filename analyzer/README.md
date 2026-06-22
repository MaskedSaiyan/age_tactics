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
- **Main Town Center idle time** (estimate): we identify the first TC (the object the
  first villager was trained from) and model its production line — training a villager
  occupies it ~25s, age-ups block it for the research time. Any gap is idle, reported as a
  total, "≈ N villagers' worth", and the longest gaps with timestamps.
- **Player names** (scraped from the header string table, slot order).

### 🚧 Roadmap (needs command-stream simulation / full header parse)
- **Civilizations** per player and **map**.
- **Resources are NOT in the replay** — food/wood/gold/stone are simulated state, not
  recorded (the postgame block has none either). A resource-over-time view would require a
  full economy simulation (villager assignments × gather rates) and would be an estimate.
- **Exact resource types** — currently inferred from drop-off proximity (see above). True
  types would need the header's object table, which isn't parsed for this DE sub-version.
- **Farm count** and **number of Town Centers** (catch the Goth "too many TCs" trap).
- **Housed time** — how long you spent population-blocked.

> Counts are recorded when a unit is **queued**, not when it pops (a villager takes ~25s to
> appear, and cancelled queues still count). AI players issue orders differently, so their
> age timings / build order may be missing.

## Usage

```bash
# FULL report, all sections (overview + build order + villager assignments).
# This is the one to run — you don't have to remember the others.
python -m aoe2_analyzer analyze path/to/replay.aoe2record

# Just the overview section (timings, pace, TC idle, activity).
python -m aoe2_analyzer analyze path/to/replay.aoe2record --summary-only

# Analyse, then interactively rename the file (Enter = use suggestion,
# n = keep, or type your own name; '.aoe2record' is added automatically).
python -m aoe2_analyzer analyze path/to/replay.aoe2record --rename

# Identify many replays at once (who-vs-who + a suggested filename to rename to).
python -m aoe2_analyzer id *.aoe2record
#   rec.aoe2record: soad vs PromiDE  [VER 9.4, 35:07]  -> soad-vs-PromiDE-35m.aoe2record
```

The `analyze` report bundles everything below. The same views are also available
as focused sub-commands (handy for piping or one player):

```bash
# Number villagers by appearance and infer each one's first resource.
python -m aoe2_analyzer assignments path/to/replay.aoe2record --player 1

# List villager-like units (builders) and their object ids.
python -m aoe2_analyzer villagers path/to/replay.aoe2record --player 1

# Follow one villager: every order it received (inferred resource + map x/y).
python -m aoe2_analyzer unit path/to/replay.aoe2record 2810
```

> Following a unit is exact (object id + target id + position). The resource
> (wood/gold/food) is **inferred** from the nearest drop-off camp at the time of
> the order — a best-effort guess: gold and stone share one camp (so they show
> as `gold/stone`), and it's weak in the early game before any camp exists
> (those show as `unknown`/`elsewhere`).

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
