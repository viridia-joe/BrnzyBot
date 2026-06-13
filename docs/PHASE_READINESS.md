# Phase 2–5 readiness plan

Status: **proposal** (2026-06-13). Addresses the gaps from the codebase review,
redesigns the phase model to be **realm-driven** (zero guild-admin burden), and
sequences the boss-strategy research that must come first.

All factual claims about the release calendar are **sourced** (see
[Appendix: sources](#appendix-sources)) — the whole point is to not ship
hallucinated content.

---

## 0. The fact that reshapes everything

Phase progression is a **realm-wide, calendar fact** set by Blizzard — not a
per-guild choice. Every guild on a realm is on the same phase on the same day.
So the bot should **derive** the phase from `realm + today's date` and guild
admins should never touch it.

And the calendar the default realm actually runs on is **not** what the code
assumes:

- **Dreamscythe is a US Classic 20th-Anniversary PvE realm**, so it follows the
  **TBC Anniversary (2026) 4-phase** schedule.
- The code assumes the **original 5-phase** TBC (`/setup phase` allows 1–6,
  `/gearcheck` allows 1–5). Those don't match the realm.

| Anniversary phase | Released | Raids / zones | Arena | **Item content-phase ceiling** (WowSims numbering) |
|---|---|---|---|---|
| **P1** | 2026-02-19 | Karazhan, Gruul's Lair, Magtheridon | S1 | 1 |
| **P2** | 2026-05-14 | Serpentshrine Cavern, Tempest Keep (The Eye), Ogri'la, Sha'tari Skyguard | S2 | 2 |
| **P3** | Summer 2026 (TBD) | **Mount Hyjal, Black Temple, Zul'Aman** | S3 | **4** |
| **P4** | Autumn 2026 (TBD) | Sunwell Plateau, Isle of Quel'Danas | S4 | 5 |

> **The ZA trap.** WowSims tags Zul'Aman gear as original **phase 4** and Sunwell
> as **phase 5**. Anniversary folds ZA into calendar **P3**. So the optimizer's
> `phase <= ?` ceiling for Anniversary P3 must be **4** (to include ZA loot), and
> P4 must be **5**. Calendar phase and item content-phase are *different axes* and
> the plan keeps them separate.

---

## 1. Redesign: realm + date driven phase (headline change)

**Goal:** admins set `/setup realm` and nothing else; the phase auto-advances on
the announced date with no command and no redeploy.

### 1a. New data file — `data/phase_schedule.json`

A versioned calendar, easy to update as Blizzard announces dates. Separates the
**calendar** from the **item content ceiling** and from per-realm **rulesets**:

```jsonc
{
  "rulesets": {
    "anniversary": {
      "label": "TBC Classic Anniversary (2026)",
      "phases": [
        {"phase":1,"release":"2026-02-19","content_phase_max":1,"arena_season":1,
         "raids":["Karazhan","Gruul's Lair","Magtheridon's Lair"]},
        {"phase":2,"release":"2026-05-14","content_phase_max":2,"arena_season":2,
         "raids":["Serpentshrine Cavern","Tempest Keep: The Eye"]},
        {"phase":3,"release":null,"release_window":"Summer 2026","content_phase_max":4,"arena_season":3,
         "raids":["Mount Hyjal","Black Temple","Zul'Aman"]},
        {"phase":4,"release":null,"release_window":"Autumn 2026","content_phase_max":5,"arena_season":4,
         "raids":["Sunwell Plateau"]}
      ]
    }
    // "original_tbc" and "private" rulesets can be added later
  },
  "realms": { "dreamscythe": "anniversary", "_default": "anniversary" },
  "sources": ["https://www.wowhead.com/tbc/guide/..."]   // provenance, reviewed
}
```

`release: null` = announced but undated → **not yet live** (the previous phase
holds until a real date lands). Updating a date is a one-line data edit, no code.

### 1b. New module — `core/phase.py`

```python
@dataclass
class PhaseInfo:
    calendar_phase: int       # what the realm calls "the current phase"
    content_phase_max: int    # WowSims item-DB ceiling for the optimizer
    raids: list[str]
    arena_season: int
    source: str               # "auto" | "override"

def resolve_phase(realm: str, *, today: date | None = None,
                  override: int | None = None) -> PhaseInfo: ...
```

Resolution order: **override** (admin escape hatch) → realm's ruleset →
`_default` ruleset. Pick the highest phase whose `release <= today`. Never raises
— unknown realm falls back to `_default`; an all-`null` calendar yields P1. Logs
what it resolved and why.

Every current reader of "phase" goes through this: the optimizer's `phase <= ?`
ceiling becomes `content_phase_max`; gear tier markers (🔥 current vs 🥇 still-BiS)
key off `calendar_phase`; `/srprio` and `/simexport` likewise.

### 1c. `/setup phase` becomes an optional override, not the source of truth

- Default: **auto** (derived). Admins do nothing.
- `/setup phase <n>` → stores an explicit override (for private servers, PTR, or
  a realm we haven't catalogued yet). `/setup phase auto` → clears it.
- **Migration:** add a nullable `phase_override` column; treat the existing
  `current_phase` as an override **only if** an admin set it explicitly,
  otherwise ignore it in favor of auto. (Most guilds left it at the default, so
  they silently start auto-advancing.) The welcome/onboarding copy drops the
  "set your phase" step.

### 1d. Hygiene folded in here

- **Unify the bound:** validate the override against the realm ruleset's max
  (Anniversary = 4), from one constant — kills the admin(1–6, `cogs/admin.py`)
  vs gear(1–5, `cogs/gear.py`) disagreement.
- **`phase=0` import guard:** `scripts/import-items.py` defaults un-tagged items
  to `phase=0`, which `phase >= 1` silently drops. Log the phase-0 count after
  import and warn if it spikes (guards against a WowSims format change nuking the
  pool).

---

## 2. Consolidate boss content into one data-driven store

Today boss content lives in **three** places with inconsistent coverage:

| Store | Feeds | Covers |
|---|---|---|
| `data/strategy/*.json` → FTS DB | `/strat` (`strategy_context.py`) | Kara, Gruul, Mag (P1) only |
| `data/boss_strats.json` (13 entries) | `/bossguide` (`bossguide_handler.py`) | P1 (Karazhan) |
| `core/bossguide_data.py` (**hardcoded Python**) | `/bossguide` | SSC, TK (P2) |

`/strat` doesn't even cover the current phase, and SSC/TK strategy lives in
`.py` source. Adding 4 more raids across this is untenable.

**Plan:** one schema, `data/strategy/<raid>.json`, keyed raid → boss, tagged with
`content_phase`, feeding **both** `/strat` (via the FTS build) and `/bossguide`.

```jsonc
{
  "_meta": {"raid":"Serpentshrine Cavern","content_phase":2,"sources":[...]},
  "bosses": [{
    "name":"Hydross the Unstable","aliases":["Hydross"],"type":"...",
    "summary":"...", "phases":[...], "abilities":[{"name":"...","desc":"..."}],
    "roles":{"tank":"...","healer":"...","dps":"..."},   // bossguide assignments
    "killers":[...], "prep":[...], "tips":[...],
    "sources":["<url>","<url>"]                          // per-boss provenance
  }]
}
```

Steps: (1) lock the schema; (2) migrate `bossguide_data.py` SSC/TK into it and
delete the Python store; (3) reconcile `boss_strats.json` into the per-raid
files; (4) point `bossguide_handler` at the unified data; (5) `content_phase` lets
`/strat` and `/bossguide` filter to what's live on the realm. **Do this before P3**
— it's the highest-leverage structural change and the foundation the research in
§3 writes into.

---

## 3. Boss-strategy research workstream — anti-hallucination (start here)

**This methodology is already proven in this repo.** The recent
`fix(tips): deep-research accuracy pass` corrected **56 of 76** raid tips that had
factual errors (Lurker despawn, Solarian P2 was a hallucinated AoE, Hydross
NR/FR reversed, etc.). That confirms two things: the hallucination risk is real,
and the **verify-raid-tips workflow** (chunk by encounter → structured JSON of
index→corrected text → apply → validate JSON → no fancy Unicode) works. **Reuse
that exact pattern** for full per-boss strategies; don't invent a new one.

Remaining raids and their bosses (rosters to be **verified during research**, not
trusted from memory):

| Raid | Phase | Bosses (~count) |
|---|---|---|
| Serpentshrine Cavern | P2 | 6 |
| Tempest Keep: The Eye | P2 | 4 |
| Mount Hyjal | P3 | 5 |
| Black Temple | P3 | 9 |
| Zul'Aman | P3 | 6 |
| Sunwell Plateau | P4 | 6 |

≈ **36 bosses**. Note this is "phases **2–4**" on the Anniversary calendar (you
said 2–5 in original numbering — same set of raids).

**Methodology (the guardrail):**
1. **Anchor sources:** Wowhead TBC guides, Icy-Veins TBC, Warcraft Wiki. Tactics
   blogs only as corroboration, never sole source.
2. **Cross-verify:** every mechanic/ability needs **≥2 independent** sources;
   disagreements get flagged `"review": true`, not guessed.
3. **Cite inline:** each boss carries a `sources` array — provenance ships with
   the data so any claim is auditable later.
4. **Use the `deep-research` skill** per raid (fan-out search, fetch, adversarial
   verify, cited synthesis) → transcribe verified output into the §2 schema.
5. **Pilot first:** run **SSC** end-to-end (research → schema → `/strat` +
   `/bossguide` working), review the quality bar together, *then* scale the same
   template to the other five raids. SSC is the current-phase flagship.

**Sequencing:** SSC (pilot) → TK → Mount Hyjal → Black Temple → Zul'Aman →
Sunwell. P3/P4 raids can be researched and staged **ahead** of release and gated
by `content_phase` so they light up automatically on the day.

---

## 4. Source-data enrichment — ✅ shipped; retire the stopgaps

This was the keystone; **it has since shipped** (Recently Shipped:
*"Item DB source data — 4,342/4,389 items enriched; World Boss=16, Arena=718,
raids correct"*, and *"/srprio fully working after source_type filter fix"*). So
the obtainability/tier logic now rides on real `source_type`. Two follow-ups:

- **Retire the now-redundant stopgaps** I added when the *fixture* DB still had
  empty source data: the curated `data/world_boss_items.json` denylist and the
  arena-name fallback in `gear_optimizer`. With `source_type` populated they're
  duplicative (and default `include_world_boss=True` makes them no-ops anyway).
  Remove them, or keep `world_boss_items.json` only as a CI-fixture aid and gate
  it accordingly.
- **Per-phase coverage check:** when P3/P4 items land, re-run enrichment and
  confirm the new raids (Hyjal/BT/ZA/Sunwell bosses) and any new world bosses
  classify correctly — and that the ~47 currently-unenriched items aren't
  raid-relevant. Add this to the phase-boundary checklist (§6).

---

## 5. Phase-aware stat weights (fidelity — lower priority, can defer)

`data/weights/*.json` carry a single `weights`/`hit_cap` per spec. Real EP weights
drift across phases (haste/hit/spellpower revalue with budgets and set bonuses),
so late-phase advice computed on early-phase weights is *approximate but not
wrong*. Options, cheapest first:

- **Now:** document the approximation; leave weights static.
- **Later:** allow an optional `weights_by_phase` block keyed by `content_phase`,
  falling back to the base `weights`. Defer until after P3 content ships — it's a
  precision tune, not a correctness fix. (Relates to the existing backlog item
  *"Set Bonus Awareness in BiS"*, which flags T6 4pc as a late-phase concern.)

---

## 6. Audit baselines per phase (operational)

`data/baselines/` is gitignored and built on the VM via `build_baselines.py`
(WCL creds). Each new raid needs fresh percentile baselines **captured after its
bosses are being logged** or `/audit` is meaningless for them. Action: add a
phase-boundary checklist to [`DEPLOYMENT.md`](DEPLOYMENT.md) — "when phase N raids
open: re-import items, re-run enrichment (§4), re-run `build_baselines.py` for the
new encounters" — and consider a scheduled reminder.

---

## Sequencing summary

1. **§3 pilot — research SSC** (reuse the proven verify-raid-tips loop). ← start
2. **§2 — consolidate content store**, migrating SSC out of Python into the schema.
3. **§1 — realm-driven phase model** (schedule file + `core/phase.py` + override
   migration + hygiene). Ships the auto-advance + ZA-ceiling fix.
4. Scale **§3 research** to TK → MH → BT → ZA → Sunwell, staged behind
   `content_phase`.
5. **§4 stopgap retirement**, **§5 / §6** fidelity + ops as follow-ups.

Items 1–3 should land **before Anniversary P3** (summer 2026) so Hyjal/BT/ZA and
the ZA-ceiling fix are ready on release day with no admin action.

---

## Appendix: sources

- Wowhead — [TBC Anniversary phase release roadmap](https://www.wowhead.com/tbc/guide/the-burning-crusade-classic-anniversary-phase-release-roadmap),
  [2026 roadmap: final phase this year](https://www.wowhead.com/tbc/news/the-burning-crusade-anniversary-2026-roadmap-final-phase-will-release-this-year-380188)
- [Icy-Veins — TBC Classic Anniversary Overview](https://www.icy-veins.com/tbc-classic/tbc-classic-anniversary-overview)
- [Warcraft Wiki — Burning Crusade Classic Anniversary Edition](https://warcraft.wiki.gg/wiki/World_of_Warcraft:_Burning_Crusade_Classic_Anniversary_Edition)
- Realm type — [Warcraft Tavern: Dreamscythe (US) population](https://www.warcrafttavern.com/population/classic/us/dreamscythe/)

> Phase dates beyond P2 are **not yet exactly dated** by Blizzard (announced as
> Summer / Autumn 2026). `data/phase_schedule.json` carries `null` releases until
> confirmed; revisit when Blizzard posts the dates.
