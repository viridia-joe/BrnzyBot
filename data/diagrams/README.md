# Canonical fight diagrams

One great, committed diagram per encounter — referenced at runtime, not redrawn.

## How it works
- `/bossguide` serves `data/diagrams/<boss_key>.png` if it exists (via
  `core.fight_diagrams.get_canonical`). Pure file read — **no Pillow at runtime**.
- Lookup order: **canonical PNG → legacy procedural generator → text only**.
- So the moment a `<boss_key>.png` is committed here, that boss uses it; until then
  it falls back gracefully.

## Authoring (do this once per boss, offline, with Pillow)
1. Drop the real minimap background crop in `data/diagrams/backgrounds/<zone>.png`
   (true to the actual in-game minimap — that's the "high fidelity" requirement).
2. Write `data/diagrams/<boss_key>.json` (see `gruul.json` for the shape):
   - `background`: path relative to `data/diagrams/`.
   - `title`: caption drawn top-left.
   - `markers`: list of `{role, x, y, label}` where `x`/`y` are **fractions 0..1**
     of the background (resolution-independent), placed per the **known most-popular
     strategy**.
3. Render: `python -m tools.render_diagrams <boss_key>` → writes `<boss_key>.png`.
4. Commit the resulting PNG (and the spec + background).

## Consistent role icons (used on every encounter)
| role | color | glyph |
|---|---|---|
| `boss` | purple | B |
| `tank` | blue | T |
| `healer` | green | H |
| `melee` | red | M |
| `ranged` | orange | R |
| `marker` | grey | * (stack point / note) |

Defined once in `tools/render_diagrams.py:ROLE_ICONS` so the whole bestiary looks
uniform. Keep `<boss_key>` matching the bossguide boss keys.

## Notes
- Minimap art is Blizzard IP; fine for a fan tool — keep a source/attribution note.
- `boss_key` must match `core/bossguide_data.py` keys.
