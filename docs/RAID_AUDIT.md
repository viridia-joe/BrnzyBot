# Raid Audit — design

A deterministic per-raider analysis of a Warcraft Logs report. Given a WCL report
URL and a character, it produces the three-section scorecard the team already
writes by hand (see the maintainer's elemental-shaman comparison doc) — but
automatically, and consistently.

> Think "WoWAudit / wipefest, but opinionated for our team and grounded in our
> own ideal-behavior rubric." Core logic is deterministic (no LLM); an LLM, when
> enabled, can narrate the same evidence.

## The scorecard (from the example doc)

Each line is a **check** with a verdict (✅/⚠️/❌/ℹ️/❔) and a one-line summary.

### Baseline — *"are you making the most of what you have?"*
| Check | Source | Verdict logic |
|---|---|---|
| Gear iLvl | CombatantInfo gear | informational |
| Spec | CombatantInfo talents vs `SpecProfile.standard_build_note` | flag large deviations |
| Primary stat | rankings / summary | informational |
| Parse % (avg + best, per phase) | `rankings` | informational benchmark |

### Execution — *"are you playing well moment to moment?"*
| Check | Source | Verdict logic |
|---|---|---|
| Activity % | cast table active time | `< min_activity_pct` → ⚠️ |
| Rotation | cast table counts vs `core_spells` / `discouraged_spells` | discouraged spell as filler → ❌ (e.g. Earth Shock for ele) |
| Threat awareness | threat table / aggro events | count of aggro pulls |
| Utility (interrupts/dispels) | interrupts + dispels tables | informational / role-aware |
| Movement | per-fight parse percentile spread (high- vs low-movement fights) | large gap → ⚠️ "movement planning" |
| Other cast choices | cast table (off-role spells, e.g. DPS healing) | informational |

### Preparation — *"did you show up ready?"*
| Check | Source | Verdict logic |
|---|---|---|
| Consumes (food/flask/elixirs/weapon oil/potions) | CombatantInfo auras + cast events | missing required → ❌; missing optional → ⚠️ |
| Enchants | CombatantInfo gear `permanentEnchant` per slot | missing enchantable slots → ⚠️/❌ |
| Gems | CombatantInfo gear gems → quality | any below "rare" (green) → ⚠️/❌; meta present? |

## WCL data map

`core/wcl_client.py` already provides most of this:

| Need | Call | Status |
|---|---|---|
| report code / fight | `parse_report_url` (in audit) + `get_fights` | ready |
| name → sourceID | `get_master_actors` | ready |
| gear, enchants, gems, consumes-at-pull, talents | `get_combatant_info` | ready (normalize fields) |
| parse %, per-fight percentiles | `get_rankings` | ready (parse shape) |
| rotation counts, activity %, off-role casts | **new** `table(dataType: Casts)` query | TODO |
| interrupts / dispels | **new** `table(dataType: Interrupts/Dispels)` | TODO |
| potions used | **new** `events(dataType: Casts)` filtered to potion abilities | TODO |
| threat / aggro | `table(dataType: Threat)` | TODO (lower priority) |

## Code shape

```
core/audit/
  checks.py    — Verdict, CheckResult, Section, AuditReport (+ render())
  profiles.py  — SpecProfile + ConsumeRule; ELE_SHAMAN seeded; PROFILES registry
  report.py    — parse_report_url, pure check_* fns, build_audit() orchestrator
```

The `check_*` functions are **pure** (take normalized data, return a `CheckResult`)
so they're unit-testable against fixtures and can be validated against the example
doc before the WCL wiring is done. `build_audit()` is the integration point; the
remaining work is marked `# TODO(wcl)`.

### Spec profiles = the written assumptions

`SpecProfile` is where each spec's "ideal behaviors" live, so the rubric is data,
not scattered `if`s. Seeded `ELE_SHAMAN` values (validated against current guides):

- **Hit cap:** only ~**4% spell hit from gear** — Elemental Precision + Nature's
  Guidance + Totem of Wrath supply ~9–12% innate. Over the gear cap = wasted stats.
- **Rotation:** Chain Lightning on CD → Lightning Bolt filler. **Earth Shock as a
  filler is a DPS loss** (low coefficient, mana-inefficient) — it's an
  interrupt/movement tool. (Confirms the doc's Shermshaman note.)
- **Consumes:** Flask of Blinding Light (or Supreme Power) *or* Adept's Elixir +
  Elixir of Draenic Wisdom/Major Mageblood; Brilliant/Superior Wizard Oil; +spell
  damage food; Super Mana / Destruction potions.
- **Gems:** rare (blue) or better; meta = Chaotic Skyfire Diamond.

Sources: Icy Veins, Wowhead, Warcraft Tavern elemental shaman guides (TBC Classic).

## Validating assumptions against real parses

Two complementary inputs feed the rubric:
1. **Guides** → the baseline ideal (seeded above).
2. **Top-tier parses** → reality check. A future job can pull the top-N ranked
   ele parses for a boss (`rankings`/`character rankings`), aggregate their cast
   mixes and consume usage, and surface where our written assumptions diverge from
   what 95+ parsers actually do (e.g. confirm core-spell share, flag specs).

## Surfacing it

- **Command:** `/audit <warcraftlogs-url> [character]` (defaults to the report's
  matching registered character/spec). Cog stays thin; logic in `core/audit/`.
- **Output:** `AuditReport.render()` → the scorecard, chunked to 2000 chars.
- **Deterministic by default.** With `ENABLE_LLM=true`, pass the `evidence` dicts
  to a narrator for prose coaching — gated like every other LLM site.

## Implementation plan

1. **(done) Scaffold** — result model, `ELE_SHAMAN` profile, pure checks, render.
2. **(done) Preparation checks live** — `core/audit/normalize.py` maps a WCL
   `CombatantInfo` record to the normalized gear/gems/auras the checks expect;
   `report.py` wires `get_fights`/`get_master_actors`/`get_combatant_info` and
   runs enchants/gems/consumes (+ a free Baseline iLvl line). Shipped both
   single-character (`build_audit`) and **whole-roster** (`build_roster_audit`),
   surfaced via the `/audit` cog. Covered by `tests/test_audit.py` (wired into CI).
3. **Cast table query** — add `table(dataType: Casts)`; implement rotation +
   activity; add potion-event query. *(check_rotation/check_activity already exist
   and are unit-tested; they just need the cast-table feed.)*
4. **Baseline** — `get_rankings` → parse avg/best; talent → spec deviation check.
5. **Movement & utility** — per-fight percentile spread; interrupts/dispels.
6. **`/audit` cog** — *(done for the Preparation cut; extend output as 3–5 land.)*
7. **Top-parse validation** job to tune the profiles.

### Decisions made in the Preparation cut
- **Fight selection:** one at-pull snapshot per run — explicit `?fight=N` wins,
  else the longest *kill* (fallback: longest fight). Consumes/enchants/gems are
  per-pull, so one representative pull is enough.
- **Spec resolution (roster):** the cog maps each logged player → canonical spec
  via the guild's `characters` registry and passes a `resolve_spec(name, class)`
  callback into core. Unregistered players, or specs with no profile yet, are
  listed under "Skipped" rather than dropped silently.
- **Gem quality:** WCL CombatantInfo gems carry item level, not a quality string,
  so quality is inferred from TBC item-level thresholds (≥110 epic, ≥70 rare,
  else green). Flags green gems exactly as the example doc does.
- **Meta gem:** detected by a small known-id set; an unrecognised gem yields
  "unknown" (never a false "missing"), so the roster under-warns rather than
  mis-accuses. The pure `check_gems` still takes an explicit `meta_present` and
  is unit-tested on the missing-meta path.
- **Field-mapping caveat:** normalization follows the documented CombatantInfo
  schema and degrades to ❔ on missing/renamed keys — so the first live report can
  only ever require a small tweak in `normalize.py`, never a crash.

## Open questions
- ~~First shippable cut~~ → **Preparation-only, whole-roster** (done).
- How much to weight per-fight movement percentiles vs raw parse (noisy on small
  samples). *(Deferred to the Execution/Movement steps.)*
- Which specs to author next — the example is ele; **other casters next**
  (warlock / mage / shadow priest / balance druid), then melee/tanks/healers.
</content>
