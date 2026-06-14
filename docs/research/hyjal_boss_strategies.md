# Battle for Mount Hyjal - verified boss-strategy research

**Status:** research output for review - generated 2026-06-14 - raid content_phase **3**

Third raid in the [`PHASE_READINESS.md`](../PHASE_READINESS.md) s3 workstream,
after [SSC](ssc_boss_strategies.md) and [TK](tk_boss_strategies.md). Anniversary
**P3** content - researched and staged ahead of release, gated behind
`content_phase` so `/strat` and `/bossguide` only surface it once the realm
reaches Phase 3.

## How this was produced + confidence model

- Five parallel research agents (one per boss), anchored on **Wowhead TBC,
  Icy-Veins TBC, Warcraft Wiki**, fan tactics sites as corroboration only.
- **Every non-obvious mechanic required >=2 independent sources.** Exact numbers
  flagged **UNVERIFIED** and kept out of user-facing text.
- Same sourcing caveat as the prior raids: direct `WebFetch` returns HTTP 403 on
  anchor sites in this environment; claims rest on cross-checked search snippets.

**Hallucinations / common confusions caught:**
- **Rage Winterchill - Icebolt** is a root + burst + fast DoT you **heal through**
  (or break with a PvP trinket / immunity); it is **not** a "store damage and
  release on break" mechanic - do **not** stop DPSing the boss. "Death Chill" is
  **not a real ability** (a conflation of Death and Decay + his frost theme).
- **Kaz'rogal - Mark of Kaz'rogal does not chain/re-apply** on explosion (the
  boss marks many mana users at once; the danger is many independent bombs). And
  you do **not** pre-drain mana to zero - the real play is to keep mana **high**
  (or be mana-less).
- **Azgalor - Doom cannot be removed** by any means except death; the Lesser
  Doomguard spawns regardless. Handle with add-tanking + Soulstone / battle-rez,
  **not** dispel timing.
- **Archimonde - Finger of Death** triggers specifically when **no player is in
  melee range** (keep a melee on him and it never fires), not generic range-aggro.
  Online "Doomfire Spirit / 18,000 damage" figures are the later **Hellfire
  Citadel** version, not TBC Hyjal.

The raid is a defend-the-base format: trash waves precede each boss. Bosses 1-2
(Rage Winterchill, Anetheron) are at the **Alliance base (Jaina)**; bosses 3-4
(Kaz'rogal, Azgalor) at the **Horde base (Thrall)**; Archimonde is the finale at
the Night Elf base.

---

## 1. Rage Winterchill  ·  *Alliance base*

- **Type:** one-tank, lightly-healed tank-and-spank / soft DPS race (first boss).
- **Summary:** A reanimated lich; spread the raid wide, heal Icebolt targets fast,
  and dodge Death and Decay until he dies before the berserk. The encounter resets
  if Jaina dies.
- **Mechanics:** **Icebolt** (random-target Frost burst + root + fast DoT; heal or
  break with trinket/immunity, keep DPSing the boss); **Death and Decay** (random
  ground pool ticking percent max HP/sec; stay spread, move out); **Frost Armor**
  (melee chill, play through it); **Berserk** (hard enrage).
- **Roles:** 1 tank; 1-2 instant-cast Icebolt healers + spot healers; DPS spread
  and survive over parse.
- **Killers:** slow Icebolt heals; stacking into Death and Decay; berserk; killing Jaina.
- **Notes:** Icebolt is NOT stored-damage-release; "Death Chill" is not a real ability.
- **Sources:** wowhead.com/tbc npc=17767 · icy-veins.com/tbc-classic (Rage Winterchill) ·
  warcraft.wiki.gg/wiki/Rage_Winterchill_(tactics) · wowpedia mirror · mmo-champion.com/content/1272
- **Confidence:** high on qualitative mechanics/roles; numbers UNVERIFIED.

---

## 2. Anetheron  ·  *Alliance base*

- **Type:** two-tank patchwork with a healing-cripple cone and an Infernal add.
- **Summary:** Spread so **Carrion Swarm** (frontal shadow cone, heavy healing
  reduction) hits as few as possible; a fire off-tank isolates each **Towering
  Infernal**; keep healing-reduction debuffs on the boss to beat **Vampiric Aura**.
- **Mechanics:** Carrion Swarm (face away, spread, never stack healers); **Sleep**
  (undispellable, breaks on damage - back up slept healers); **Inferno** (Towering
  Infernal on a random player, pulses fire - off-tank holds it clear, ranged burn);
  Vampiric Aura (self-heal from melee damage - Mortal Strike/Aimed Shot/Wound
  Poison cut it); Berserk.
- **Roles:** 2 tanks (MT faced away + fire off-tank); spread healers with backup
  pairs; DPS keep MS-debuffs up, kill Infernals fast.
- **Killers:** stacked healers eating Carrion Swarm; Infernal near boss/raid; slept
  healer with no backup; ignoring healing-reduction debuffs.
- **Sources:** wowhead.com/tbc npc=17808 · icy-veins.com/tbc-classic (Anetheron) ·
  warcraft.wiki.gg/wiki/Anetheron_(tactics) · warcrafttavern.com/tbc/guides/anetheron
- **Confidence:** high on mechanics/roles (2+ sources each); numbers UNVERIFIED.

---

## 3. Kaz'rogal  ·  *Horde base*

- **Type:** tank-and-spank with a mana-attrition soft enrage.
- **Summary:** **Mark of Kaz'rogal** drains mana from many mana users; a marked
  player who hits zero mana explodes for heavy shadow AoE. Spread, keep mana high
  (or be mana-less), and race him before the Mark frequency cascades.
- **Mechanics:** Mark of Kaz'rogal (spread; topped-up/mana-less players never
  detonate; recasts faster over time = soft enrage; does **not** chain); **War
  Stomp** (PBAoE stun); **Cripple** (melee slow, needs Freedom); **Malevolent
  Cleave** (face away).
- **Roles:** 1 tank (2nd backup), faced away; healers manage their own mana
  (downrank, mana-return cooldowns); casters keep mana up with potions/runes,
  druids go mana-less; non-mana classes pad the DPS check.
- **Killers:** slow DPS (escalating Marks); stacking (chain detonations); mana
  mismanagement; cleave into the raid.
- **Notes:** Mark does not chain; do NOT pre-drain to zero.
- **Sources:** wowhead.com/tbc npc=17888 · icy-veins.com/tbc-classic (Kazrogal) ·
  warcraft.wiki.gg/wiki/Kaz'rogal · wowpedia mirror · warcrafttavern.com/tbc/guides/kazrogal
- **Confidence:** high on mechanics/roles + both corrections; numbers UNVERIFIED.

---

## 4. Azgalor  ·  *Horde base*

- **Type:** add-management survival fight (last boss before Archimonde).
- **Summary:** Every cycle a random player is cursed with **Doom** (non-removable);
  they die and spawn a **Lesser Doomguard** that must be tanked and killed, so a
  Soulstone / battle-rez rotation keeps the raid whole. Spread for **Rain of Fire**
  and plan around **Howl of Azgalor** (raid silence).
- **Mechanics:** Doom (cannot be dispelled/resisted - victim runs to the add tank,
  gets rezzed); Lesser Doomguard (tank away, kill; War Stomp/Cripple if loose);
  Rain of Fire (move out, spread); Howl of Azgalor (raid silence - instants/HoTs);
  Cleave (face away); Berserk.
- **Roles:** 2-3 tanks (Azgalor faced away + Doomguard add tanks; Prot Paladin
  ideal); spread healers planning around Howl; DPS burn Doomguards then boss.
- **Killers:** loose Doomguards stomping the raid; Rain of Fire; Rain overlapping
  Howl; bleeding bodies to Doom; cleave; berserk.
- **Notes:** Doom is non-removable - add-tank + Soulstone, not dispel timing.
- **Sources:** wowhead.com/tbc (Azgalor) · icy-veins.com/tbc-classic (Azgalor) ·
  warcraft.wiki.gg/wiki/Azgalor_(tactics) · /wiki/Lesser_Doomguard · warcrafttavern.com
- **Confidence:** high on mechanics/roles + the Doom correction; numbers UNVERIFIED.

---

## 5. Archimonde  ·  *Hyjal finale*

- **Type:** single-phase, movement-heavy individual-execution fight.
- **Summary:** Tanked by one tank near center; the raid spreads in a wide ring so
  random-target abilities catch one player. **Air Burst** launches players up for
  lethal fall damage, survived only with **Tears of the Goddess** (a consumable
  every raider gets from Tyrande before the pull). Every death grants a **Soul
  Charge** (class-based raid nova), so deaths cascade. **Hand of Death** caps the timer.
- **Mechanics:** Air Burst (spread; use a Tear as you fall); Tears of the Goddess
  (mandatory for all 25; do not use too early); **Doomfire** (chasing fire trail,
  stacking fire DoT - run from it, never through the raid); Grip of the Legion
  (dispellable DoT); **Finger of Death** (instakill when no melee is on him - keep
  a melee in range); Soul Charge (deaths make it harder - minimize them); Fear
  (Tremor/Fear Ward/Berserker Rage); Hand of Death (hard timer/leash).
- **Roles:** 1 tank (Prot Warrior favored for Berserker Rage fear-immunity); spread
  healers, constant triage; DPS survival-first, melee in two camps; decursers on
  Grip; everyone uses a Tear on every Air Burst.
- **Killers:** Air Burst with no/mistimed Tear; Doomfire; Finger of Death from no
  melee; cascading Soul Charges; clumping; Hand of Death timer.
- **Notes:** Finger of Death = empty-melee trigger; ignore Hellfire-Citadel Doomfire numbers.
- **Sources:** icy-veins.com/tbc-classic (Archimonde) · warcrafttavern.com/tbc/guides/archimonde ·
  wowpedia.fandom.com/wiki/Archimonde_(tactics) · warcraft.wiki.gg mirror · mmo-champion.com/content/1276
- **Confidence:** high on mechanics/roles + Tears/Finger-of-Death framing; numbers UNVERIFIED.

---

## Master UNVERIFIED list (do NOT publish as exact)

- All damage values, cast/recast timers, debuff durations, radii, HP, wave counts,
  and berserk timers across all five bosses.
- Rage Winterchill: a periodic Frost Nova appears in some guides - UNVERIFIED for
  TBC Classic specifically.
- Kaz'rogal: exact mana-drain per second and explosion damage; Mark recast cadence.
- Archimonde: Tears of the Goddess slow-fall duration; Soul Charge nova damage.
