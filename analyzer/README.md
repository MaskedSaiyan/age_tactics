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
- **Progression timeline**: every player's cumulative villagers and military at
  fixed time marks (every 3 min) side by side — see *who led at each moment*,
  not just the end-game totals (which late AI production inflates).
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
# FULL report, all sections (overview + progression + build order + assignments).
# This is the one to run — you don't have to remember the others.
python -m aoe2_analyzer analyze path/to/replay.aoe2record

# Local web app: dropdowns to filter by PLAYER and pick ANY replay, then view
# its interactive report. Stdlib http.server, no install. Ctrl-C to stop.
# The player filter lists only regular players (recurring handles) — random AI
# personalities are excluded automatically.
python -m aoe2_analyzer serve --open            # serves ./samples on :8000
python -m aoe2_analyzer serve --min-games 3     # count rarer opponents as regulars

# Interactive HTML report (charts, age timeline, head-to-head, key events).
# Self-contained single file — works offline, double-click to open, shareable.
python -m aoe2_analyzer report                      # newest in ./samples
python -m aoe2_analyzer report game.aoe2record --open   # write + open in browser

# Drop a new replay into ./samples and just run it — no path needed.
# `analyze` (and `progression`) auto-pick the NEWEST .aoe2record:
python -m aoe2_analyzer analyze              # newest in ./samples
python -m aoe2_analyzer analyze some/folder  # newest in that folder

# Progression only: who led on villagers / military, minute by minute.
# (End-of-game totals mislead — AIs keep producing after they've won.)
python -m aoe2_analyzer progression                 # newest in ./samples
python -m aoe2_analyzer progression game.aoe2record --step 120

# Just the overview section (timings, pace, TC idle, activity).
python -m aoe2_analyzer analyze path/to/replay.aoe2record --summary-only

# Analyse only YOUR player (by name substring or id), and save it to a file.
python -m aoe2_analyzer analyze game.aoe2record --player soad --out soad-game.txt

# Compare one player's key metrics across several games (why some go better).
python -m aoe2_analyzer compare game1.aoe2record game2.aoe2record --player soad

# Head-to-head: compare two players within ONE game (you vs your rival).
python -m aoe2_analyzer versus game.aoe2record soad shura

# Analyse, then interactively rename the file (Enter = use suggestion,
# n = keep, or type your own name; '.aoe2record' is added automatically).
python -m aoe2_analyzer analyze path/to/replay.aoe2record --rename

# Fast scan of a save FOLDER (header only) — who's in each game, newest first.
# Great for finding a recent game without analysing every file.
python -m aoe2_analyzer scan ~/Games/.../SaveGame/

# Identify replays (full parse) and print a copy-paste mv line per file...
python -m aoe2_analyzer id ~/Games/.../SaveGame/
#   # rec.aoe2record: soad vs PromiDE  [VER 9.4, 35:07]  -> soad-vs-PromiDE-35m.aoe2record
#   mv 'rec.aoe2record' soad-vs-PromiDE-35m.aoe2record

# ...or rename them all in place (collision-safe: adds -2/-3 on clashes).
python -m aoe2_analyzer id ~/Games/.../SaveGame/ --rename
```

`scan` and `id` accept folders, globs, or individual files. `scan` is header-only
(fast, may list lobby/AI names); `id` does a full parse for clean, accurate names.

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
