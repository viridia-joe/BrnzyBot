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

**Shipped — Preparation cut (whole-roster):** `core/audit/` now wires WCL live —
`normalize.py` maps `get_combatant_info` to normalized gear/gems/auras, and
`report.py` runs enchants/gems/consumes (+ a Baseline iLvl line) for one raider
(`build_audit`) or every profiled raider in the report (`build_roster_audit`),
surfaced by the `/audit` cog. Covered by `tests/test_audit.py` (in CI), which
reproduces the Brnzy-vs-Shermshaman example.

**Remaining:** Execution (`table(dataType: Casts)` → rotation/activity — the pure
checks already exist and are tested), Baseline parse % (`get_rankings`), movement
& utility, then more spec profiles (other casters next). See the plan in the doc.

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

## Offline Dev/Test Harness (WCL fixtures)

**Priority:** High
**Effort:** Medium

We can't run the WCL-backed features (`/rotationcheck`, `/gearcheck`, auto-register)
end-to-end in the cloud dev environment: there are no `WCL_CLIENT_ID`/`WCL_CLIENT_SECRET`
there and no built `*.db`. Today the only verification possible is mocking WCL responses
by hand. A fixture-based harness fixes that and unblocks confident iteration from this box.

**Goal:** record a handful of *real* WCL responses once (from a machine that has creds —
e.g. VS Code on desktop), commit them as JSON fixtures, and run the pure logic against
them with no network.

Implementation:
- Add `scripts/capture-wcl-fixtures.py` — given creds + a report code (and a character),
  dump the raw responses we actually consume to `tests/fixtures/wcl/<name>.json`:
  `get_character_recent_reports`, `get_master_actors`, `get_fights`, `get_abilities`,
  `get_casts` (a caster with at least one downranked spell if possible), and
  `get_combatant_info` (gear with `gems` + `permanentEnchant` populated).
- Add `tests/` with tests that monkeypatch `core.rotation_handler.wcl` (and the gear
  fetch) to serve fixtures, then assert on the handler output. The mock E2E I ran by
  hand for `/rotationcheck` is the template — promote it to `tests/test_rotation.py`.
- Scrub fixtures of anything sensitive (they're just public log data, but double-check
  player names are fine to commit; offer an anonymize flag in the capture script).
- Wire `python3 -m pytest -q` (or a stdlib `unittest` runner, to avoid adding a dep)
  into `.github/workflows/ci.yml` after the byte-compile step.

Considerations:
- Keep it dependency-light: a stdlib `unittest` runner avoids adding pytest to the 1 GB box.
- Fixtures double as documentation of the exact WCL response shapes we depend on.
- Capture 2-3 specs (a downranking caster, a clean caster, a caster with empty
  sockets + missing enchant) so both the rotation and gems/enchants features are covered.

## Caster Gems & Enchants Review

**Priority:** High
**Effort:** High (phased)

Add a gems & enchants audit to `/gearcheck` for caster specs. Build it in phases —
the first is cheap and high-value; the later ones are "a lot."

**Data we already have** (confirmed): `gear_cache` captures `enchant` (permanentEnchant
id) and `gems` (list of gem ids) per equipped item; the item DB has `sockets`
(JSON list of socket colors incl. `Meta`) and `socket_bonus`; `data/gems.json` has the
best caster gem per color. **Gaps:** no gem-id→quality map (needed to flag green gems),
and no enchantable-slot / recommended-enchant reference.

### Phase 1 — flag the obvious (buildable now from existing data)
- **Empty sockets:** `len(item.sockets excluding Meta)` vs `len(equipped gems)` → "N empty sockets".
- **Missing enchants:** `enchant == 0` on an enchantable slot.
- **Cheap gems:** socketed gem of green (uncommon) quality. Needs a gem-id→quality
  source — either confirm gems are in the item DB with quality, add a small
  `data/gem_quality.json`, or fall back to the existing Wowhead lookup used for unknown items.

### Enchant severity (validated against TBC values — weight callouts by slot)
Treat a missing **major** enchant as a real grade hit (A → B); a missing **minor**
enchant as cosmetic (A → A+). The user's instinct checks out:

| Slot | Tier | Typical caster enchant (≈ value) |
|---|---|---|
| **Weapon** | Major | Major Spellpower (+40 sp) / Soulfrost (+54 shadow-frost) — the single biggest |
| **Head** | Major | Arcanum / Glyph of Power (~+22 sp, +14 spell hit) — rep-gated |
| **Legs** | Major | Spellthread (Mystic +25 sp/+15 sta, Runic +35 sp/+20 sta) |
| **Shoulder** | Major | Greater Inscription of the Orb (~+12 sp, +15 crit) — rep-gated |
| **Chest** | Minor | Exceptional Stats (+6 all) — trivial for a caster |
| **Feet** | Minor | Boar's Speed / minor stats — mostly run speed |
| **Wrist / Hands / Back** | Minor | small int/sp/threat-reduction enchants |
| **Finger** | Optional | enchanter-only (+sp each) — only flag for enchanters |
| Neck / Trinket / Wand / Relic | n/a | not enchantable — never flag |

Encode as `data/enchant_slots.json`: `{slot: {enchantable, tier, recommended}}`.

### Phase 2 — gem optimization to hit cap
Once flagging works, recommend a gem layout that reaches the spell hit cap first
(respecting socket colors + socket bonuses, like the existing `gear_optimizer` socket
logic), then…

### Phase 3 — gems by stat weights
…fills remaining sockets by spec EP weights (reuse `data/weights/*.json`). This overlaps
the existing socket-bonus math in `gear_optimizer.py` — factor that out and share it.

Considerations:
- Deterministic (no LLM); slot into the `/gearcheck` output the same way as the hit/BiS sections.
- Meta gem: don't count the Meta socket as "empty" if a meta is present; flag a missing/incorrect meta separately.
- Verify against real fixtures (see the harness item) before trusting empty-socket and
  green-gem detection — this is gear-correctness data, where wrong flags erode trust.
