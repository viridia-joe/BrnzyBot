# Black Temple - verified boss-strategy research

**Status:** research output for review - generated 2026-06-14 - raid content_phase **3**

Fourth raid in the [`PHASE_READINESS.md`](../PHASE_READINESS.md) s3 workstream
(after SSC, TK, Mount Hyjal). Anniversary **P3** content - staged ahead of release
and gated behind `content_phase` so `/strat` and `/bossguide` only surface it once
the realm reaches Phase 3.

## How this was produced + confidence model

- Nine parallel research agents (one per boss), anchored on **Wowhead TBC,
  Icy-Veins TBC, Warcraft Wiki**, fan tactics sites as corroboration only.
- **Every non-obvious mechanic required >=2 independent sources.** Exact numbers
  flagged **UNVERIFIED** and kept out of user-facing text (sources frequently
  disagree on BT damage/timer values).
- Same caveat as prior raids: direct `WebFetch` returns HTTP 403 on anchor sites;
  claims rest on cross-checked search snippets.

**Corrections / misnomers caught:**
- **Naj'entus** - "Crashing Wave" is **not** a real ability; the shield-break AoE
  is the Tidal Shield burst (informally "Tidal Burst").
- **Supremus** - it is **Hateful Strike** (highest-current-health in melee), not
  Hurtful Strike; the two phases **alternate** on a timer, not progress one-way.
- **Mother Shahraz** - "Shadowguard" is a Troll Priest racial, **not** a Shahraz
  ability; the raid shadow damage comes from her beams + Fatal Attraction.
- **Illidari Council** - Gathios' confirmed aura is **Chromatic Resistance** (+
  Devotion), not "Sanctity"; all four member names/classes verified exact.
- **Reliquary of Souls** - Aura of Suffering is an armor/defense/healing shutdown,
  not a max-HP reduction; Seethe is a **taunt-triggered** threat amp (rule: do not
  taunt in P3), not an automatic raid threat wipe.

---

## 1. High Warlord Naj'entus
- **Type:** single-target healing/gear check (BT1); no adds, no movement beyond spread.
- **Mechanics:** **Impaling Spine** (impales a random player; others click to free
  them and get a **Naj'entus Spine** item); **Tidal Shield** (boss goes immune +
  self-heals; break it by **throwing** looted spines); **Tidal Burst** (shield-break
  = big raid-wide frost - top the raid first); **Needle Spine** (raid AoE, spread);
  hard enrage. 1 tank.
- **Killers:** breaking the shield while not topped; not freeing impaled players;
  Needle Spine on a stacked raid; enrage.
- **Sources:** icy-veins.com/tbc-classic (Naj'entus) · wowhead.com/tbc npc=22887 ·
  wowpedia.fandom.com/wiki/High_Warlord_Naj'entus · warcrafttavern.com · mmo-champion.com/content/1278

## 2. Supremus
- **Type:** alternating two-phase fire construct (BT2).
- **Phases:** P1 tankable (**Hateful Strike** soak on highest-current-HP melee;
  **Molten Flame** ground trails); P2 untankable **Fixate** + **Volcanic Geyser**
  (kite him in a circle, spread). Phases alternate ~every 60s until death.
- **Roles:** 2 tanks (main + Hateful Strike soak), both idle in P2; mobile healing.
- **Killers:** standing in fire trails/geysers; kiting into the raid; Hateful Strike
  on a non-tank (a DPS/off-tank had higher current HP).
- **Sources:** icy-veins.com/tbc-classic (Supremus) · wowhead.com/tbc npc=22898 ·
  warcraft.wiki.gg/wiki/Supremus · warcrafttavern.com

## 3. Shade of Akama
- **Type:** add-control / escort (BT3, easiest T6 boss).
- **Mechanics:** Akama channels; **Ashtongue Channelers** (6) + replacement
  **Sorcerers** shackle the Shade (top kill priority - free it); **Defenders**
  (add-tank center), **Spiritbinders** (healers - interrupt/CC/kill), Rogues/
  Elementalists (CC). P2: the freed Shade reaches Akama, becomes tankable, burn it
  in ~60s before Akama dies.
- **Roles:** add-tank (center) + Shade tank (P2); 2-3 healers on add-tank, 1-2 on
  Akama; CC team on support adds.
- **Killers:** Channelers/Sorcerers too slow; Spiritbinder heals; add-tank death; Akama dies.
- **Sources:** icy-veins.com/tbc-classic (Shade of Akama) · wowhead.com/tbc npc=22841 ·
  warcraft.wiki.gg/wiki/Shade_of_Akama_(tactics) · warcrafttavern.com

## 4. Teron Gorefiend
- **Type:** tank-and-spank gated by the **Shadow of Death** ghost mini-game (BT4).
- **Mechanics:** Shadow of Death marks a random player who dies and becomes a
  **Vengeful Spirit** (ghost with a special action bar: Spirit Volley/Chains/Lance)
  - the only thing that can kill the **4 Shadowy Constructs** that spawn at the
  corpse. Marked players run to a far corner before death and clear their constructs
  (do **not** release/run off - succeed and you're resurrected). Dispel **Incinerate**;
  **Doom Blossom** adds = soft enrage. 1 tank; everyone must know the ghost game.
- **Killers:** failed/abandoned ghost phase; constructs reaching the raid; Doom Blossom pile-up.
- **Sources:** icy-veins.com/tbc-classic (Teron) · wowhead.com/tbc npc=22871 ·
  warcraft.wiki.gg/wiki/Teron_Gorefiend_(tactics) · warcrafttavern.com

## 5. Gurtogg Bloodboil
- **Type:** positioning/healing single-target on a ~90s timed loop (BT5).
- **Mechanics:** **Bloodboil** hits the **furthest** players (the 5 furthest) - the
  raid splits into two groups that rotate through furthest range so each takes one,
  then swaps out; **Fel Rage** (P2) fixates a random **non-tank**, buffing them while
  the boss ignores the tank - **every healer instantly switches** to that player;
  **Acidic Wound** (tank swap); Fel Acid Breath (face away); 10-min enrage. 2-3 tanks.
- **Killers:** Bloodboil rotation failure; Fel Rage target dies; tank-swap/Acidic Wound; enrage.
- **Sources:** icy-veins.com/tbc-classic (Gurtogg) · wowhead.com/tbc (Gurtogg) ·
  warcraft.wiki.gg/wiki/Gurtogg_Bloodboil · warcrafttavern.com · mmo-champion.com/content/1281

## 6. Reliquary of Souls
- **Type:** three sequential Essences, each its own sub-boss (BT6).
- **Phases:** **P1 Essence of Suffering** (Aura turns off healing + strips tank
  armor/defense - survive on absorbs/Healthstones; Fixate; dispel Soul Drain);
  **P2 Essence of Desire** (Aura reflects your damage + doubles healing + drains max
  mana - do **not** over-burst/overheal; interrupt Spirit Shock; Spellsteal Rune
  Shield); **P3 Essence of Anger** (growing raid shadow DoT; Soul Scream cone - face
  away; Spite; never **taunt** = Seethe; Bloodlust). Kill **Enslaved Soul** ghosts
  near the raid between phases to refill HP/mana.
- **Killers:** undispelled Soul Drain; P1 tank death (no armor); P2 reflect/OOM;
  Soul Scream/Seethe; Aura of Anger out-ramping heals.
- **Sources:** warcrafttavern.com/tbc/guides/reliquary-of-souls · wowpedia (RoS) ·
  warcraft.wiki.gg/wiki/Reliquary_of_Souls · wowhead.com/tbc npc=23418/23419/23420

## 7. Mother Shahraz
- **Type:** gear/coordination check, the shadow-resistance fight (BT7); no adds/phases.
- **Mechanics:** **Saber Lash** (heavy frontal **split** among stacked tanks - stack
  2-3; lone tank dies; targets are immune to Fatal Attraction); **Fatal Attraction**
  (teleports several players together, escalating shadow damage near each other -
  **run apart** to opposite corners, not through the raid/tanks - #1 wipe cause);
  Prismatic Shield (rotating resistance); Silencing Shriek; hard enrage. SR strongly
  recommended in original tuning.
- **Killers:** Fatal Attraction mishandled; insufficient SR/healing; unstacked tanks; enrage.
- **Sources:** icy-veins.com/tbc-classic (Mother Shahraz) · wowhead.com/tbc npc=22947 ·
  wowpedia.fandom.com/wiki/Mother_Shahraz · warcrafttavern.com · mmo-champion.com/content/1284

## 8. Illidari Council
- **Type:** 4-member council, **shared health pool**, die together (BT8); 15-min enrage.
- **Members:** **Gathios the Shatterer** (paladin - Consecration, Hammer of Justice,
  Blessing of Spell Warding/Protection); **High Nethermancer Zerevor** (mage -
  Blizzard/Flamestrike, Arcane Explosion if melee on him); **Lady Malande** (priest -
  **Circle of Healing heals the pool = priority interrupt**; Reflective Shield);
  **Veras Darkshadow** (rogue - Vanish + poison burst on random players).
- **Roles:** 4 tanks (apart); raid-aware healing; dedicated Malande interrupt rotation.
- **Killers:** missed Circle of Healing interrupts (-> enrage); ground AoE; Veras burst;
  attacking through Reflective Shield.
- **Sources:** wowhead.com/tbc npc=23426 (+22949/22950/22951) · icy-veins.com/tbc-classic ·
  warcraft.wiki.gg/wiki/Illidari_Council · warcrafttavern.com · mmo-champion.com/content/1285

## 9. Illidan Stormrage
- **Type:** 5-phase finale, opened by Akama (BT9).
- **Phases:** **P1 (100-65%)** melee - **Shear** removes most of the tank's HP unless
  mitigated (swap/cooldown), Flame Crash, Draw Soul cone; **P2 Flames of Azzinoth** -
  two Flame elementals each kited by a **fire-resistance** tank (avoid Blaze, face
  Flame Blast away; kill both to end); **P3 (65-30%)** ground + **Agonizing Flames**
  (spread); **P4 Demon Form** - a **shadow-resistance warlock** tanks him, raid stays
  >20yd (Shadow Blast), dodge **Eye Blast** lines, kill **Shadow Demons** fast (P3/P4
  alternate to 30%); **P5 (30-0%)** Maiev - lead Illidan onto **Cage Traps** to strip
  his enrage and burn.
- **Roles:** main tank (Shear, often 2 swapping) + 2 FR Flame tanks + 1 SR warlock
  (Demon Form); heavy healing; Shadow Demon kill squad; Cage Trap baiters.
- **Killers:** missed Shear mitigation; Blaze/Flame Blast; Flame reset; Eye Blast;
  clumping in Demon Form; Shadow Demons; failed Cage Traps; Agonizing Flames chains.
- **Sources:** warcraft.wiki.gg/wiki/Illidan_Stormrage_(tactics) · icy-veins.com/tbc-classic ·
  wowhead.com/tbc npc=22917 · wowpedia.fandom.com/wiki/Illidan_Stormrage_(tactics) · warcrafttavern.com

---

## Master UNVERIFIED list (do NOT publish as exact)

All damage values, cast/recast timers, debuff durations, radii, HP totals, enrage
timers, fire/shadow-resistance thresholds, and add counts across all nine bosses.
Sources frequently disagree on BT numbers (e.g. Naj'entus Impaling Spine/Needle
Spine values, Saber Lash total, Illidari Council pool HP, Illidan FR threshold) -
the qualitative content (mechanics, handling, roles, phases, kill priorities) is
the load-bearing output and is cross-confirmed; numbers are not shipped.
