# Zul'Aman - verified boss-strategy research

**Status:** research output for review - generated 2026-06-14 - raid content_phase **3**

Fifth raid in the [`PHASE_READINESS.md`](../PHASE_READINESS.md) s3 workstream
(after SSC, TK, Mount Hyjal, Black Temple). Anniversary **P3** content - a 10-player
raid, staged ahead of release and gated behind `content_phase` so `/strat` and
`/bossguide` only surface it once the realm reaches Phase 3.

> **Phase-axis note (the "ZA trap"):** Anniversary folds Zul'Aman into calendar
> **P3**, but its gear is tagged item content-phase **4** in the WowSims DB. That
> divergence is handled by the realm-phase model (`core/phase.py`): P3's
> `content_phase_max` is 4 so the optimizer includes ZA loot. This strategy content
> is keyed to **calendar phase 3** for gating.

## How this was produced + confidence model

- Six parallel research agents (one per boss), anchored on **Wowhead TBC,
  Icy-Veins TBC, Warcraft Wiki**, fan tactics sites as corroboration only.
- **Every non-obvious mechanic required >=2 independent sources.** Exact numbers
  flagged **UNVERIFIED** (10-man values differ across guides/versions).
- Same caveat: direct `WebFetch` returns HTTP 403 on anchor sites; claims rest on
  cross-checked search snippets.

**Corrections caught:**
- **Nalorakk** - the ability-to-form mapping is partly inverted: **Mangle, Brutal
  Swipe and Surge are troll-form**; the heavy stacking bleeds and Deafening Roar
  (silence) are **bear-form**. No "Earth Shock" or "Berserker Charge".
- **Jan'alai** - the **35% all-hatch** is distinct from a separate **~20% melee
  frenzy**; Fire Bombs **teleport the raid to center and wall it in**, not just rain.
- **Halazzi** - title is **Lynx Avatar**; he splits into **both** troll-form
  "Halazzi the Worshipper" **and** the Spirit of the Lynx (not just a Lynx add),
  merging when either hits ~20%; TBC Classic split points are **75/50/25%** (the
  60/30% figures are older tuning).
- **Hex Lord Malacrass** - the two starting adds are from an **8-NPC pool** (blood
  elf priest, ogre, imp, dragonhawk, wraith, undead, elemental, serpent) - **not**
  trolls and **not** the four animal-god bosses; the **Alyson Antille** priest add
  is the real heal threat (kill first). A "Sacrifice / Gift of the Doomsayer"
  self-heal is **unverified/misattributed**.

---

## 1. Nalorakk  ·  *Bear Avatar*
- **Type:** two-tank swap; alternates troll and bear form on a timer (no threat drop on shift).
- **Mechanics:** **Mangle** (troll - amplifies bleed damage on its target -> tank
  swap), **Surge** (troll - charge at the **most distant** player + damage-taken
  increase; ranged spread and rotate furthest), Brutal Swipe (troll cleave);
  **Lacerating Slash** (bear - heavy stacking bleed), **Deafening Roar** (bear -
  area silence); ~10-min enrage. Largest timed-run bonus.
- **Killers:** failed tank swap (Mangle + bleeds on one tank); Surge on a clumped/
  squishy player; Deafening Roar silencing the healer; enrage.
- **Sources:** icy-veins.com/tbc-classic (Nalorakk) · wowhead.com/tbc npc=23576 ·
  warcraft.wiki.gg/wiki/Nalorakk_(tactics) · warcrafttavern.com

## 2. Akil'zon  ·  *Eagle Avatar*
- **Type:** single-tank positioning/healer-attrition fight (no hard enrage).
- **Mechanics:** **Electrical Storm** (lifts a random player + builds a raid storm
  - **stack tightly under the lifted player**, then re-spread); **Static
  Disruption** (arcs to nearby players - **spread** at all other times); Gust of
  Wind (knock-up, heavy landing damage); Call Lightning (tank nuke); **Soaring
  Eagles** (weak adds after each storm). Stack-for-storm vs spread-otherwise is the crux.
- **Killers:** slow collapse for the storm; staying stacked after (Static Disruption
  chains); Gust landing into Static with no buffer; healer OOM.
- **Sources:** icy-veins.com/tbc-classic (Akil'zon) · wowhead.com/tbc npc=23574 ·
  wowpedia.fandom.com/wiki/Akil'zon_(tactics) · warcrafttavern.com

## 3. Jan'alai  ·  *Dragonhawk Avatar*
- **Type:** egg/add-control stationary fight (often hardest of the four animals).
- **Mechanics:** **Summon Hatcher** (Hatchers hatch the egg banks at an
  accelerating rate - **kill one, let one** release a controlled wave; off-tank
  gathers, raid AoEs); **35% all-hatch** (empty the banks first); **Flame Breath**
  (frontal cone); **Fire Bombs** (teleport raid to center + fire walls + detonating
  bombs); **~20% frenzy** (separate from the 35% all-hatch; tank cooldown).
- **Killers:** killing both Hatchers (full bank force-hatches at 35%); Flame Breath/
  Fire Bomb tiles; frenzy with no tank cooldown; pushing past 35% with eggs up.
- **Sources:** wowhead.com/tbc npc=23578 · icy-veins.com/tbc-classic (Jan'alai) ·
  warcraft.wiki.gg/wiki/Jan'alai_(tactics) · warcrafttavern.com

## 4. Halazzi  ·  *Lynx Avatar*
- **Type:** cyclical split fight; two stacked tanks share Saber Lash.
- **Mechanics:** **Transfigure** (splits at **75/50/25%** into troll-form **Halazzi
  the Worshipper** + the **Spirit of the Lynx**; off-tank holds the Lynx; bring
  either to ~20% to **merge** at pre-split HP); **Saber Lash** (frontal split - stack
  2 tanks); **Flame Shock** (dispel); **Corrupted Lightning Totem** (kill on sight);
  post-25% permanent **frenzy** burn. Healers delay burst-heals right after a split
  (the Lynx can pull onto them).
- **Killers:** single-tank Saber Lash spike; loose Lynx on a healer; undispelled
  Flame Shock; ignored totem; OOM in the frenzy.
- **Sources:** icy-veins.com/tbc-classic (Halazzi) · wowhead.com/tbc npc=23577 ·
  wowpedia.fandom.com/wiki/Halazzi_(tactics) · warcrafttavern.com

## 5. Hex Lord Malacrass
- **Type:** add fight + class-copy boss (no hard berserk; soft enrage).
- **Mechanics:** **two minions** from an 8-NPC pool (CC one, kill the other; **Alyson
  Antille** priest heals - kill first); **Spirit Bolts** (raid-wide shadow that
  **ramps as adds die**); **Drain Power** (stacking self-buff = soft enrage);
  **Siphon Soul** (copies a random player's class abilities - react with interrupts/
  dispels/anti-trap positioning).
- **Killers:** uncontrolled adds + Spirit Bolts at the start; the damage ramp after
  adds die; losing DPS to Drain Power; mishandled Siphon Soul.
- **Sources:** wowhead.com/tbc npc=24239 · icy-veins.com/tbc-classic (Hex Lord) ·
  wowpedia.fandom.com/wiki/Hex_Lord_Malacrass · warcrafttavern.com

## 6. Zul'jin  ·  *final boss, 5 forms*
- **Type:** stationary five-phase form-shifter; threat resets each transition (Eagle has none).
- **Phases:** **Troll (100-80%)** - Whirlwind, **Grievous Throw** (bleed clears only
  on a heal to **full**); **Bear (80%)** - **Creeping Paralysis** (dispel **before**
  it expires or it stuns), Overpower; **Eagle (60%)** - no melee/threat, **Energy
  Storm** (damages anyone casting), roaming cyclones; **Lynx (40%)** - **Claw Rage**
  (fixate burst on a non-tank - immunity/externals), **Lynx Rush** (raid bleeds);
  **Dragonhawk (20%)** - **Flame Breath** cone (face away) + **Pillars of Fire**.
- **Roles:** single tank (re-taunt each phase); heaviest healing in the raid;
  resistance totems (Nature for Bear/Lynx, Fire for Dragonhawk) + Bloodlust late.
- **Killers:** Grievous Throw not healed to full; missed Creeping Paralysis dispel;
  Claw Rage on a healer; Lynx Rush bleeds; cyclones/fire pillars; lost threat after a transition.
- **Sources:** icy-veins.com/tbc-classic (Zul'jin) · wowhead.com/tbc (Zul'jin) ·
  wowpedia.fandom.com/wiki/Zul'jin_(tactics) · warcraft.wiki.gg mirror · warcrafttavern.com

---

## Master UNVERIFIED list (do NOT publish as exact)

All damage values, cast/recast timers, debuff durations, HP totals, enrage timers,
split/threshold exact percentages where versions differ, the Hex Lord 8-add paired-
pool slot mapping, and loot item names. Qualitative content (mechanics, handling,
roles, phases, kill priorities) is cross-confirmed and is what ships; numbers do not.
