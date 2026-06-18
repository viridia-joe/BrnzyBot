# Sunwell Plateau - verified boss-strategy research

**Status:** research output for review - generated 2026-06-14 - raid content_phase **4**

Sixth and final raid in the [`PHASE_READINESS.md`](../PHASE_READINESS.md) s3
workstream (after SSC, TK, Mount Hyjal, Black Temple, Zul'Aman). Anniversary **P4**
content - the end of The Burning Crusade - staged ahead of release and gated behind
`content_phase` so `/strat` and `/bossguide` only surface it once the realm reaches
Phase 4.

> **Phase-axis note:** Sunwell is Anniversary calendar **P4**; its gear is tagged
> item content-phase **5** in the WowSims DB. The realm-phase model (`core/phase.py`)
> sets P4's `content_phase_max` to 5 so the optimizer includes Sunwell loot, while
> this strategy content gates on **calendar phase 4**.

## How this was produced + confidence model

- Six parallel research agents (one per boss), anchored on **Wowhead TBC,
  Icy-Veins TBC, Warcraft Wiki**, fan tactics sites as corroboration only.
- **Every non-obvious mechanic required >=2 independent sources.** Exact numbers
  flagged **UNVERIFIED** and kept out of user-facing text.
- Same caveat: direct `WebFetch` returns HTTP 403 on anchor sites; claims rest on
  cross-checked search snippets. Add counts and proper nouns were double-checked
  after a prior pass (Hex Lord) miscounted adds.

**Corrections caught:**
- **Eredar Twins** - they do **NOT** share a health pool (independent bars). When
  one dies the survivor inherits one of the dead twin's abilities, so kill
  **Sacrolash first** (Alythess then only gains the weak Shadow Nova, not the lethal
  Conflagration). The debuffs are properly **Dark Touched** (shadow) / **Flame
  Touched** (fire); resistance gear is explicitly **not** the answer.
- **Felmyst** - players caught by the breath are **mind-controlled** (not "turned
  into a Vapor"); the chasing **Demonic Vapor** trail spawns **Unyielding Dead**
  skeletons; there is **no** special "two breaths at low health" - the ground/air
  cycle just repeats.
- **M'uru** - portal waves are **2 Shadowsword Berserkers + 1 Shadowsword Fury
  Mage** each (two portals); **"Shadowsword Fleshbringer" / "Sunblade" adds do not
  exist** here. The **Void Sentinel** and the ~8 **Dark Fiends** spawn from M'uru,
  not the portals. Negative Energy is single-target in P1, chains/accelerates in P2.
- **Kalecgos** - exactly **one** enemy add (Sathrovarr) plus the friendly NPC
  **Kalec** (must survive); separate health pools driven to ~1%, Crazed Rage at 10%.
- **Kil'jaeden** - P1 has **three** Hand of the Deceiver adds; **Sinister
  Reflection spawns four copies at every gate** (85/55/25%), not once.

---

## 1. Kalecgos
- **Type:** two-realm fight (Sunwell boss 1); 25-player.
- **Mechanics:** normal realm = Kalecgos; **Spectral Blast** pulls a player to the
  **Spectral Realm** to fight **Sathrovarr the Corruptor** alongside friendly
  **Kalec** (must live). Separate HP pools but both must reach ~1%; **Crazed Rage**
  at 10% forces a together-kill. **Spectral Exhaustion** (60s lockout -> 3rd tank),
  **Arcane Buffet** (cleared by a Spectral trip), **Curse of Boundless Agony**
  (decurse to pass). 3 tanks.
- **Killers:** bosses' HP drifting apart; Kalec dying (instant wipe); uncontrolled curse.
- **Sources:** icy-veins.com/tbc-classic (Kalecgos) · warcrafttavern.com/tbc/guides/kalecgos ·
  wowpedia.fandom.com/wiki/Kalecgos_(tactics) · warcraft.wiki.gg mirror

## 2. Brutallus
- **Type:** pure DPS/healing check (Sunwell boss 2); no adds, ~6-min hard enrage.
- **Mechanics:** **Meteor Slash** (frontal split + stacking fire-vulnerability ->
  two soak groups alternate, taunt-swap at ~3 stacks); **Burn** (spreading ramping
  fire DoT - run out or immunity it); **Stomp** (tank spike + armor reduction). 2 tanks.
- **Killers:** the enrage; Burn spreading; botched Meteor Slash rotation.
- **Sources:** wowhead.com/tbc (Brutallus) · icy-veins.com/tbc-classic (Brutallus) ·
  warcrafttavern.com/tbc/guides/brutallus · mmo-champion.com/content/313

## 3. Felmyst
- **Type:** ground/air dragon (Sunwell boss 3, raised from Brutallus's foe).
- **Mechanics:** ground = **Gas Nova** (priest Mass Dispel; raid in <=10 sub-groups),
  **Corrosion** (tank +100% physical taken -> swap), **Encapsulate** (run out),
  Noxious Fumes (passive); air = **Demonic Vapor** (chasing trail, spawns Unyielding
  Dead - kite, kill), **Fog of Corruption** (breath cloud, **mind-controls** caught
  players - dodge to the safe side). 2 tanks. No special low-HP behavior.
- **Killers:** missed Gas Nova dispel; Fog of Corruption catches; vapor trail; Corrosion spike.
- **Sources:** warcrafttavern.com/tbc/guides/felmyst · icy-veins.com/tbc-classic (Felmyst) ·
  wowpedia.fandom.com/wiki/Felmyst · mmo-champion.com/content/314

## 4. Eredar Twins
- **Type:** two bosses at once (Sunwell boss 4); **independent** health, ~6-min enrage.
- **Bosses:** **Lady Sacrolash** (shadow: Confounding Blow disorient -> 2-tank swap,
  Shadow Nova, Shadow Image adds); **Grand Warlock Alythess** (fire: Conflagration,
  Blaze patches, Pyrogenics - purge). **Kill Sacrolash first** (survivor inherits
  one ability). **Dark Touched** (shadow, -healing) / **Flame Touched** (fire DoT)
  cleared by taking the opposite school. Resistance gear is not the answer.
- **Killers:** enrage; Conflagration on a clump; Dark Touched stacking; missed
  Confounding Blow taunt; killing Alythess first (Sacrolash gains Conflagration).
- **Sources:** wowhead.com/tbc (Eredar Twins) · icy-veins.com/tbc-classic ·
  wowpedia.fandom.com/wiki/Eredar_Twins · warcrafttavern.com · mmo-champion.com/content/315

## 5. M'uru
- **Type:** two-phase add war then demon burn (Sunwell boss 5); the hardest fight.
- **Phases:** **P1 M'uru** - two portals spawn **2 Berserkers + 1 Fury Mage** each
  (~60s), M'uru spawns **Void Sentinels** (split into ~8 Void Spawns) and ~8 **Dark
  Fiends** (killed by offensive **Mass Dispel**), plus single-target Negative Energy;
  **P2 Entropius** - Negative Energy chains/accelerates (enrage), roaming **Black
  Hole**, Darkness under players. ~3-4 tanks, shared ~10-min enrage, no break.
- **Killers:** missed Dark Fiend dispels; loose Berserkers; Void Spawns piling up;
  Black Hole/Negative Energy in P2; slow transition into the shared enrage.
- **Sources:** warcraft.wiki.gg/wiki/M'uru_(tactics) · wowpedia mirror ·
  icy-veins.com/tbc-classic (M'uru) · warcrafttavern.com/tbc/guides/muru

## 6. Kil'jaeden
- **Type:** multi-phase finale (Sunwell boss 6); the end boss of TBC. HP gates 85/55/25%.
- **Phases:** **P1** three **Hand of the Deceiver** adds (kill one at a time, no
  cleave); **P2** KJ emerges (Soul Flay, Legion Lightning - spread, Fire Bloom -
  spread); **P3 (85%)** Shield Orbs + **Darkness of a Thousand Souls** begins; **P4
  (55%)** **Armageddon** meteors; **P5 (25%)** faster Darkness, burn. **Sinister
  Reflection** = 4 clones at each gate. **Orbs of the Blue Flight** (Kalecgos
  empowers 4: 1@85, 1@55, 2@25) -> ride one and drop **Shield of the Blue** so the
  raid survives each Darkness (limited uses). 3 tanks for the Hands.
- **Killers:** missed Shield of the Blue during Darkness; cleaving the Hands;
  Armageddon impacts; clumping for Fire Bloom/Legion Lightning; loose Reflections.
- **Sources:** icy-veins.com/tbc-classic (Kil'jaeden) · wowhead.com/tbc (Kil'jaeden) ·
  warcraft.wiki.gg/wiki/Kil'jaeden_(tactics) · warcrafttavern.com · tbc.wowhead.com/spell=45833

---

## Master UNVERIFIED list (do NOT publish as exact)

All damage values, cast/recast timers, debuff durations, HP totals, enrage timers,
Crazed Rage stack counts, the exact Kalecgos banish threshold (~1%), Void Sentinel
spawn cadence, and meteor counts. Qualitative content (mechanics, handling, roles,
phases, kill orders, add rosters/counts) is cross-confirmed and is what ships.
