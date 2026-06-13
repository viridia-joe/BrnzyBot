# Raid Audit Matrix — Design

A whole-raid-night consumable/prep view: players × boss-fights, the way an officer
actually reviews a clear. Modeled on the Google Sheets mockup. Builds on the
existing per-fight audit (spec detection, consume rules) but gathers across the
whole report instead of one pull.

## Decisions (from review)
- **New `/raidaudit` command** — leave `/audit` (single-fight deep view) intact.
- **Compact text tables** — one code-block table per consumable category.
- **Full optimal-consume grading** — grade each consumable against the spec's best
  choice for that fight, including **creature-type awareness** (Demonslaying on a
  non-demon is flagged as wasted).

## Output shape

```
# Raid Audit — <Zone>, <date>  ·  N raiders × M boss kills

## Gems & Enchants   (roster-wide; these don't change between pulls)
            Gems        Enchants
Brnzy       ✅          ⚠️ 7/9 (missing 2 minor)
Syllina     ✅          ✅ 9/9
Shermnshamn ❌          ❌ 1/9

## Food
            Hydross  Lurker  Leo  Morogrim  Vashj
Brnzy       ✅       ✅      ✅   ✅        ✅
Shermnshamn ❌       ❌      ❌   ✅        ✅

## Weapon Oils / Windfury        (same matrix)
## Elixirs / Flasks              (shows the actual consumable + ⚠️/❌)
## Potion Use                    (N of M possible)
```

- **Gems/Enchants**: one summary cell per player (roster-wide), not per-fight.
- **Food / Oil / Potion**: ✅/⚠️/❌ grid, abbreviated boss names as columns.
- **Elixirs/Flasks**: show the *named* consumable per cell (the mockup's most
  detailed row), with ⚠️ when present-but-suboptimal, ❌ when missing.
- Column count is bounded by Discord width. **Chunk bosses into wings / logical
  partitions of 4–6 per table** (e.g. Karazhan: the lower wing, then the upper
  wing/Curator→Prince, then Nightbane; SSC fits in one table of 6). When an
  instance has no natural wing, make a judgment call and split into comfortable
  4–6-boss tables. Each consumable category (Food/Oil/Elixir/Potion) repeats its
  table per chunk. Abbreviate boss names (Hydross, Lurker, Leo, FLK, Morogrim,
  Vashj). Never silently truncate — every kill appears in some chunk.

## Data gathering

For the report:
1. `get_fights(code)` → all **kill** fights (skip wipes for the matrix).
2. `get_master_actors(code)` → roster (name, class).
3. Per player: `get_combatant_info(code, source_id=sid)` → **one event per fight**,
   each carrying that fight's `auras` (food/flask/elixir/oil) + the stat block.
   - The by-fight query (`get_combatant_info(code, fight_id)`) returns nothing on
     some reports — the **by-source** query is the reliable path (verified live).
4. Potions: `get_casts(code, fight_id)` per kill fight, tally potion casts per
   source (reuse `_tally_casts`).
5. Spec per fight: reuse `spec_from_stats` on each fight's event so a spec-switcher
   is graded against the right spec's consumes per fight (Shermnshamn ele→resto).

Cost: ~(1 + roster + kills) WCL calls. A full SSC clear (6 kills, 25 raiders) is
heavier than `/audit`; the rate limiter + circuit breaker already protect it, and
the command defers. Acceptable for an officer-run "review the night" command.

## Optimal-consume grading

Grading philosophy differs by role — this is the heart of the feature:

- **DPS: strict.** DPS is measured on throughput, and the best throughput
  flask/elixir is unequivocally best ~99% of the time. A present-but-suboptimal
  throughput consumable on a DPS is a real, flaggable miss (⚠️).
- **Healers: graceful.** Healer needs are situational and hard to read from a
  parse — throughput vs longevity is a legitimate judgment call (e.g. an MP5
  flask over a +healing flask on a long, mana-intensive fight is often the
  *correct* choice, not a mistake). So for healers, treat any reasonable
  flask/elixir as **acceptable** (✅, or a soft note), and only ❌ a genuinely
  absent consumable. Never hard-flag a healer for picking longevity over throughput.

Each cell is graded ✅ / ⚠️ / ❌ against the spec's choice for that fight:

- **✅ optimal / acceptable** — present and best-in-slot (DPS), or any reasonable
  choice (healer).
- **⚠️ suboptimal** — DPS only: present but a weaker throughput choice than the
  spec's best. ALSO any role: a **wasted type-gated** consumable (Demonslaying on
  a non-demon).
- **❌ missing** — no consumable in that slot.

### Creature-type awareness (the Leotheras nuance)
`data/boss_types.json`: `{encounter_id|boss_name: creature_type}` from research.
- **Demon bosses** (Demonslaying is GOOD): Terestian Illhoof, Prince Malchezaar,
  Magtheridon. (Leotheras's body is **Humanoid** — only his Inner Demon adds are
  Demon, so Demonslaying on Leo is ⚠️ wasted.)
- **Undead bosses** (Consecrated Sharpening Stone is GOOD): Attumen, Moroes,
  Nightbane.
- A type-gated consumable used off-type → ⚠️ with a note ("Demonslaying does
  nothing on Leotheras — he's Humanoid").

### Spec-best consumable tables
Extend `SpecProfile.consumes` (or a parallel `best_consumes`) with a ranked list
per slot so grading can say "present but not best." Start from the spec rules
already in `profiles.py`; the research gives the caster/melee/healer best-in-slot.

## Build stages
1. **Data layer** — `gather_raid_matrix(code) -> {fights, players, per-cell auras +
   potions + per-fight spec}`. Pure, testable against a fixture.
2. **`data/boss_types.json`** + a `creature_type(fight)` helper.
3. **Grading** — `grade_consumable(spec, slot, aura_name, boss_type) -> (mark, note)`.
4. **Render** — compact text tables with width-aware boss abbreviations.
5. **`/raidaudit` cog** — defer, gather, render, chunk. Rate-limited like `/audit`.
6. **Fixture + tests** — extend the synthetic log with per-fight varied consumes
   (a raider who skips food on some fights, uses Demonslaying on a non-demon) and
   assert the matrix marks them.

## Open questions for later
- Date in the header needs the report start time (WCL gives it; format on render).
- Wipes excluded from the matrix by default — add a flag to include them?
- Very large raids (40 in a pug) may exceed Discord limits even compacted — may
  need an "officer summary" mode (only flag the players with ❌/⚠️).
