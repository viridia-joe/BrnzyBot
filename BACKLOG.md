# Backlog

## Raid Audit (`/audit <warcraftlogs-url>`)

**Priority:** High
**Effort:** High (phased — Preparation-only first cut is Medium)

Deterministic per-raider analysis of a WCL report, scored against a spec's
"ideal behaviors" rubric across **Baseline / Execution / Preparation** — the
three-section scorecard the team writes by hand today. Pulls parse %, rotation
(flagging off-spec spells like Earth Shock for ele), activity %, movement spread,
consumes, enchants, and gems straight from Warcraft Logs.

Design + WCL data map: [`docs/RAID_AUDIT.md`](docs/RAID_AUDIT.md).
Scaffold landed in `core/audit/` (result model, `ELE_SHAMAN` profile, pure
checks, render). Remaining work is marked `# TODO(wcl)` in `core/audit/report.py`
— mostly normalizing `get_combatant_info` and adding a `table(dataType: Casts)`
query. Start with the Preparation checks (enchants/gems/consumes): highest value,
no new WCL queries needed beyond CombatantInfo.

## Spec Override Flag

**Priority:** High
**Effort:** Medium

Add a `-spec` flag to `!gearcheck` that forces spec detection instead of auto-detecting from the most recent log.

Use case: player has a main spec and an off spec. `!gearcheck Jaina` returns ele shaman because that's their most recent log, but they also heal as resto. `!gearcheck Jaina -Restoration` should find the most recent log where Jaina was specced Restoration and assess that gear.

Implementation:
- Accept optional `-SpecName` flag in gearcheck.py args
- When flag present, query WCL for recent reports (limit 10-20)
- For each report, check the character's talent distribution
- Find the first report matching the requested spec
- Run the normal gearcheck against that report's gear snapshot

Considerations:
- Spec name matching should be fuzzy: "Resto", "Restoration", "resto_shaman" all work
- If no log found for that spec, say so: "No Restoration logs found in last 20 reports for Jaina"
- May need to map user-friendly names to internal spec names: "Holy" → could be holy_priest, holy_paladin — need class context

## Healer Analysis

**Priority:** Medium
**Effort:** Medium-High

Add healer-specific analysis section to `!gearcheck` (similar to tank survival analysis).

### Metrics to assess:

**Throughput:**
- +Healing EP total (from gear)
- Spell crit % (especially valuable for Holy Paladin with Illumination)
- Spell haste rating (cast time reduction on heals)

**Regen:**
- MP5 (mana per 5 seconds while casting)
- Spirit (mana regen while not casting, and while casting for priests with Meditation/Spirit of Redemption)
- Intellect (total mana pool + crit contribution)
- Estimated mana pool: (base mana + intellect * 15) — compare to thresholds
- Estimated combat regen: MP5 + spirit-based regen (spec-dependent)

**Spec-specific notes:**
- **Holy Paladin:** Crit is king due to Illumination mana return. Flash of Light spam means haste is less valuable than for other healers. Spell damage matters for threat during solo content.
- **Resto Shaman:** Chain Heal specialist. MP5 > Spirit for mana regen. Totem management matters but can't be assessed from gear.
- **Resto Druid:** HoT-based. Spirit is very valuable (Tree of Life + Intensity). Spell haste reduces GCD for HoT application.
- **Holy Priest:** Flexible healer. Spirit-based regen with Meditation. Crit for surge of light procs. Circle of Healing in later phases.

### Thresholds (approximate, Phase 1):

| Metric | Minimum | Comfortable | Well-geared |
|--------|---------|-------------|-------------|
| +Healing | 1200 | 1500 | 1800 |
| MP5 (combat) | 50 | 80 | 100+ |
| Mana Pool | 8000 | 9500 | 11000 |
| Spell Crit % | 15% | 20% | 25% |

### Implementation:
- Add `healer_thresholds.json` similar to `tank_thresholds.json`
- Add `analyze_healer()` function in gearcheck.py
- Compute regen from: MP5 + Spirit-based regen (formula varies by class/talent)
- Show pass/fail on mana pool and regen thresholds
- Note: healer throughput is much harder to assess from gear alone — there's no "effective health" equivalent

## Enchant Database

**Priority:** Low
**Effort:** Medium

The defense calculation for tanks currently uses a hardcoded enchant ID → defense rating map. This misses uncommon enchants and will break as new enchants appear in later phases.

Build a proper enchant database similar to the item database:
- Source enchant data from WowSims or Wowhead
- Store enchant_id → stats mapping in SQLite
- Use it for defense calculation and potentially for EP calculation (enchants contribute to total EP)

## Set Bonus Awareness in BiS

**Priority:** Low
**Effort:** High

Currently set bonuses are calculated for equipped gear but NOT factored into the BiS recommendation. A true BiS calculation would consider:
- Whether equipping a set piece would activate a set bonus
- Whether replacing a set piece would break an active set bonus
- The combinatorial optimization of which set pieces to keep vs replace

This is a hard combinatorial problem. Current approach (EP per slot independently + set bonus as separate line item) is good enough for Phase 1. Revisit if set bonus value becomes a dominant factor in later phases.

## Relic EP Overrides

**Priority:** Low
**Effort:** Low

Totems, Idols, and Librams currently show "proc-based, not EP-rated". These could get override EP values similar to trinkets, but the data is very spec-specific and the items are rarely the bottleneck for progression.

## gearprio.py Trinket/Gem/Set Awareness

**Priority:** Medium
**Effort:** Medium

`gearprio.py` doesn't use trinket EP overrides, gem EP, or set bonus calculations. Its upgrade recommendations for trinkets and socketed items are based on raw stats only — inconsistent with `gearcheck.py`. Port the same EP calculation logic to gearprio.
