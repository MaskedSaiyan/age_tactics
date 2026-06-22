# aoe2-tactics-lab

A practical lab for getting better at **Age of Empires II: Definitive Edition**, with a heavy focus on **team games** and the **Goths**.

## What's in here

- **AoE2 DE civilization notes** — what each civ actually does, in plain language.
- **Build orders** — Fast Castle, Feudal rushes, and team-game Imperial plans with concrete checkpoints.
- **Team-game tactics** — how to play your slot (flank vs pocket), when to sling resources, and when to commit.
- **Replay analyzer experiments** — an exploratory Python project (`analyzer/`) for pulling stats out of `.aoe2record` files.

## Philosophy

This repo is about **practical checkpoints, not perfect tournament builds**.

You won't find frame-perfect, to-the-second pro build orders here. What you'll find are
build orders with *checkpoints* you can actually hit mid-game while you're also microing
fights, walling, and yelling at your pocket to sling you wood. The goal is:

> "Am I roughly on track? Yes/no. If no, what do I fix right now?"

If a build says "before clicking Castle you want ~8 farms and a deer or two", that's a
checkpoint you can glance at — not a religion.

## Layout

```
aoe2-tactics-lab/
├── README.md            <- you are here
├── civs/                <- civ notes + build orders
│   ├── goths/           <- the main focus
│   ├── huns/
│   ├── malay/
│   ├── aztecs/
│   └── mayans/
└── analyzer/            <- exploratory Python replay parser
```

## Who this is for

A player who wants to climb with **Goths in team games** and is willing to use replays to
find out why they keep losing the 40-minute fight (spoiler: usually idle TC time and a late
Imperial click).
