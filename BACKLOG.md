# Backlog

## Recently Shipped
- `/audit` Preparation cut — enchants, gems, meta, consumes, iLvl per raider
- `/audit` Execution section — rotation anomaly check wired to cast data
- Offline fixture harness — synthetic WCL logs, item-DB fixture, CI audit
- WCL client unified — `gear_cache` uses `wcl_client` (retry/breaker/fixtures)
- Healer analysis in `/gearcheck` — throughput + regen metrics, pass/fail thresholds
- `/srprio <character> <raid>` — top-5 SR picks by EP for a named raid instance
- Gems & enchants summary in `/gearcheck` — empty sockets, missing enchants, meta check
- Spec-search in `/gearcheck` — walks recent logs to find the right spec when explicit
- Rotation profiles — 20 specs (all DPS, all classes)
- Rotation baselines pipeline — `scripts/build_baselines.py` pulls top-N Anniversary parses
- `🥇` emoji fix — Phase 1 BiS items now correctly marked vs current-phase BiS
- `/gearprio` double-subtraction fix + BiS-equivalence test harness
- `/srprio` — shipped, needs source-data to function end-to-end (see keystone item)
- Fight diagram framework — per-boss PNG lookup with authoring tool
- Dead code removed — `core/gearprio.py`, `core/compute-upgrades.py`, `core/triage.py` body
- Heartbeat mojibake fix — lore/tips/jokes UTF-8 repaired

---

## ⭐ Populate item-DB source data — KEYSTONE

**Priority:** Highest · **Effort:** Medium

All 4,513 items in the DB have empty `source_type` / `source_name`. This silently breaks:
- `/gearprio` + `/gearcheck` obtainability filters (world-boss, arena, PvP are no-ops)
- `/srprio` — filters on `source_type='Raid'`; returns nothing until this lands
- Upgrade prose — "source:" annotations are blank

**Stopgaps to retire after fix:** `data/world_boss_items.json` denylist, arena name fallback in `gear_optimizer`.

**Plan:** fix `core/enrich_item_sources.py` to emit a `World Boss` type, run against prod DB, validate known items (Talon of the Tempest → World Boss, Gladiator's → Arena, Nexus Key → Raid/TK), retire stopgaps, extend `tests/test_item_restrictions.py`.

---

## Reaction Feedback Harvesting (👍 / 👎 on bot responses)

**Priority:** Medium · **Effort:** Medium

`core/feedback.py` exists but is **unwired** — no `on_raw_reaction_add` listener anywhere. Work is connecting it, not building from scratch.

Remaining:
- Reaction listener cog mapping 👎/❌ → negative, 👍/🎯 → positive on bot's own messages
- Log response text at post-time (keyed by message_id) so the harvester has the actual answer
- `tools/feedback_cli.py` offline digest, or owner-only `/feedback review`

---

## Gear Correctness — Externally-Grounded BiS Validation

**Priority:** High · **Effort:** High (content is the long pole)

`tests/test_bis_equivalence.py` (shipped) pins gearprio/gearcheck against the optimizer's own BiS (internal consistency). Still open: compare `solve_bis` to **human-verified curated BiS lists** (`data/bis/<spec>_p<N>.json`) to catch bad weights or bad item data that internal consistency can't detect.

---

## Weapon Slot Display in `/gearprio`

**Priority:** Low · **Effort:** Low

The double-subtraction fix made weapon upgrades surface with correct EP, but the "from" item renders as `(empty)` for staves/2H because WCL slot names (`Main Hand`) don't match DB slot names (`Two-Hand`). Cosmetic only — the EP values are right. Fix: share `/srprio`'s `_canon_slot` normalizer.

---

## Raid Audit — Execution Section

**Priority:** High · **Effort:** Medium

Preparation audit is shipped. Execution phase wired (cast analysis from rotation handler). Still open: parse % from `get_rankings`, movement/uptime metrics, more spec profiles beyond casters.

---

## Enchant Database

**Priority:** Low · **Effort:** Medium

Tank defense calculation uses a hardcoded enchant ID → defense rating map. Build a proper `enchant_id → stats` SQLite table sourced from WowSims/Wowhead. Unblocks more accurate tank EP and opens enchant recommendations.

---

## Set Bonus Awareness in BiS

**Priority:** Low · **Effort:** High

BiS solver treats set pieces independently; it doesn't account for activating or breaking set bonuses. Good enough for Phase 1/2. Revisit if set bonus value becomes dominant in later phases (T6 4pc etc.).

---

## Relic EP Overrides

**Priority:** Low · **Effort:** Low

Totems, Idols, Librams show "proc-based, not EP-rated." Could get spec-specific override EP values like trinkets. Rarely the bottleneck.

---

## Fight Diagram Content

**Priority:** Medium · **Effort:** Medium (asset authoring)

Framework shipped. Remaining: author real minimap backgrounds + per-boss JSON specs, commit rendered PNGs for P1–P2. Code is done; this is content work.

---

## Scrub Em-Dashes from Boss Strat Prose

**Priority:** Low · **Effort:** Low

`data/boss_strats.json` (~58 em-dashes), `data/strategy/*.json` (karazhan ~78, gruuls ~23, magtheridon ~11). Write `tools/scrub_emdashes.py`, eyeball diffs, replace with natural punctuation. Don't touch Python module docstrings (house convention per CLAUDE.md).
