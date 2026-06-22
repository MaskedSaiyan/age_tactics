# samples/

Drop AoE2 DE replay files here for testing the analyzer.

- Replays live in something like:
  `…/Games/Age of Empires 2 DE/<steamid>/savegame/` (`.aoe2record` files).
- Copy a few games here to experiment with.

## ⚠️ Reminder

The parser is **not implemented yet** — it returns mock data regardless of what you put here.
See [`../README.md`](../README.md) and `parser.py` for status.

## Tip

Consider **gitignoring** large replay files so you don't bloat the repo:

```
# .gitignore
analyzer/samples/*.aoe2record
```
