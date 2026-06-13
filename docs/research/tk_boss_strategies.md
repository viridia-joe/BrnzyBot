# Tempest Keep: The Eye - verified boss-strategy research

**Status:** research output for review - generated 2026-06-13 - raid content_phase **2**

Second raid in the [`PHASE_READINESS.md`](../PHASE_READINESS.md) §3 research
workstream, after the [SSC pilot](ssc_boss_strategies.md). Same bar: sourced,
cross-verified content replacing the hand-authored/AI strat blobs that were
relocated (un-verified) into `data/strategy/tempest_keep.json`. On sign-off this
content is wired into `/strat` (flip `_meta.strat_index` to true) and `/bossguide`.

## How this was produced + confidence model

- Four parallel research agents (one per boss), anchored on **Wowhead TBC,
  Icy-Veins TBC, Warcraft Wiki**, with fan tactics sites as corroboration only.
- **Every non-obvious mechanic required >=2 independent sources.** Disagreements
  and unconfirmed numbers are flagged **UNVERIFIED**, not guessed.
- **Sourcing caveat (same as the SSC pilot):** direct `WebFetch` returned **HTTP 403
  on every anchor site** in this environment. All claims rest on **search-result
  snippets cross-checked across sources**, not full-page reads.
  - **High confidence:** mechanic existence, handling, roles, kill orders, phase
    structure, add composition, and the load-bearing proper nouns (advisor names,
    the seven weapon names).
  - **Low confidence:** exact numbers (damage, timers, HP, radii). Flagged and kept
    out of user-facing text - raiders need "keep a melee on him," not "~2000 fire."

**The methodology caught real hallucinations (the point):** Al'ar's old data was
badly wrong - it had P1 as 100-to-25% (it is a full bar, then a Rebirth and a
second full bar) and claimed *only ranged* can hit him in P1 (the **opposite** is
true - melee must stay on him or Flame Buffet wipes the raid); Flame Buffet was
mislabeled a tank-swap stack (the real swap is Melt Armor in P2). Kael'thas's old
weapon list named **Thori'dal** (a *Sunwell* legendary, not in this fight) and
"Lady Vashj's Venom Bolt." Solarian's "Wrath of the Astromancer = run-to-wall bomb"
was a retail-style framing ("not a bomb fight" in TBC), portals open at random
spots (not fixed N/SW/SE), and Blinding Light was missing entirely. All corrected
below.

---

## 1. Al'ar  ·  *most-corrected*

- **Aliases:** Al'ar, Phoenix God, the Phoenix. **Type:** two-stage fire fight -
  melee-tanked platform rotation (P1) into a free-roaming ground phase (P2).
- **Summary:** Al'ar must always have a melee body (a tank) on him or Flame Buffet
  punishes the whole raid - he has no ranged threat table (Ragnaros-style). In P1
  he hops between four elevated platforms in sequence (clockwise); the raid kills
  Ember adds (they explode on death and drain his HP) and jumps down to the floor
  whenever he flies to center for Flame Quills. At 0% he detonates and **Rebirths
  at full health** in the room center to begin P2, a ground fight with armor-shred
  tank swaps (Melt Armor), Dive Bombs that spawn embers, fire patches, and Charges.
  The raid effectively kills him twice.
- **Mechanics:**
  - **Flame Buffet** - cast only when no one is in melee range; escalating raid-wide
    fire damage. The core rule: always keep a tank on him. (Not a tank-swap trigger.)
  - **Flame Quills (P1)** - he flies to center and fires quills outward; everyone,
    tanks included, jumps down off the platforms to the floor.
  - **Ember of Al'ar** - phoenix adds (on platform shifts in P1, from Dive Bombs in
    P2); on death cast **Ember Blast** (fire explosion), so killed away from raid;
    each ember killed drains a chunk of Al'ar's HP.
  - **Rebirth** - at 0% in P1 he detonates and revives full-HP in the center; heavy
    fire + knockback nearby. Spread off center during the swap.
  - **Melt Armor (P2)** - armor-shred debuff on the current tank; off-tank taunts
    immediately. This is the real tank swap.
  - **Dive Bomb (P2)** - targets the ground under a random player, crashes for heavy
    fire, spawns two embers; move off the marker. (Old guides call this "Meteor" -
    same ability, not a separate mechanic.)
  - **Flame Patch (P2)** - fire under random players; move out. **Charge (P2)** -
    after a Dive Bomb he charges a random player; ranged/healers hug walls so the
    knockback goes into a wall. **Berserk** - hard enrage if the fight runs long.
- **Roles:** **Tanks** - P1: a tank always in melee on his current platform,
  rotating platform to platform; a ground tank gathers embers and drags them clear.
  P2: main tank on Al'ar, off-tank taunts every Melt Armor and grabs the two Dive
  Bomb embers. **Healers** - heavy raid healing throughout; tanks topped through
  Melt Armor. **DPS** - melee MUST hit him on the platforms and follow him; all DPS
  burn embers (they drain his HP) and dodge ember explosions; jump down on Quills.
- **Killers:** no melee on him -> Flame Buffet spam (the #1 killer); not jumping
  down on Flame Quills; standing in Ember Blast; missed Melt Armor swap; eating Dive
  Bomb/Charge while clumped or off-wall; enrage.
- **Corrections (caught):** P1 is **not** 100-to-25% (full bar -> Rebirth -> second
  full bar; no 25% threshold); **not** ranged-only in P1 (melee mandatory); Flame
  Buffet is the no-melee punishment, **not** a tank-swap stack (swap is Melt Armor,
  P2); platform rotation reads **clockwise**, not counterclockwise; "Meteor" = Dive
  Bomb (one mechanic); "embers self-resurrect into a Phoenix" is **UNVERIFIED**.
- **Sources:** icy-veins.com/tbc-classic/al-ar-guide-strategy-abilities-loot ·
  warcrafttavern.com/tbc/guides/alar/ · warcraft.wiki.gg/wiki/Al'ar ·
  wowpedia.fandom.com/wiki/Al'ar · wowwiki-archive.fandom.com/wiki/Al'ar · wowhead.com/tbc npc=19514
- **Confidence:** high on mechanics/phases/roles and all six corrections (4+ sources
  each); UNVERIFIED: all exact numbers, precise compass order, the ember-rez detail.

---

## 2. Void Reaver

- **Aliases:** Void Reaver, "Loot Reaver." **Type:** gear/DPS-check tank-and-spank.
- **Summary:** Widely the easiest boss in The Eye - a pure gear check, not a
  coordination test. Tanked center while the raid spreads around it. Three
  mechanics only: Knock Away (knocks the tank back and reduces threat), Arcane Orb
  (a ground-targeted projectile at a random non-melee player), and Pounding (a
  repeating AoE around the boss). A forgiving hard enrage closes it out.
- **Mechanics:**
  - **Knock Away** - knocks the current tank back and **reduces** their threat (does
    not fully wipe it). Boss is **not tauntable**, so the next-highest-threat tank
    must already be in melee. Cannot be cast during Pounding. ~20-30s cd UNVERIFIED.
  - **Arcane Orb** - slow projectile at a random raider **not** in melee range; lands
    on the ground where they stood (no tracking) and on impact deals heavy arcane
    damage + silences everyone in radius. Spread; move off the spot. Radius/dmg UNVERIFIED.
  - **Pounding** - repeating AoE centered on the boss, mostly hitting melee; largely
    healed through, though melee can step out during the channel. Numbers UNVERIFIED.
  - **Enrage** - hard enrage ~10 min (UNVERIFIED timer); real but forgiving.
- **Roles:** **Tanks** - 3 (safe baseline; 2 works geared) rotate naturally via Knock
  Away, holding by raw threat in melee since untauntable; Misdirection on the lead
  tank helps. **Healers** - heal Pounding, top Orb victims, watch caster silences.
  **DPS** - burn for enrage; ranged spread wide and move off orb markers; melee stack
  and watch Pounding (melee aren't orb-targeted).
- **Killers:** clumping for Arcane Orb (multi-death + mass silence); tanks not
  ready after Knock Away; enrage; a healer silenced at a bad moment.
- **Corrections (caught):** old "Knock Away wipes threat" -> it **reduces** threat;
  "Pounding nothing to dodge" -> melee can step out; everything else (untauntable,
  Orb = random non-melee + ground-targeted + silence, 3-tank default, Loot Reaver) verified.
- **Sources:** wowhead.com/tbc npc=19516 · icy-veins.com/tbc-classic (Void Reaver) ·
  warcrafttavern.com/tbc/guides/void-reaver · warcraft.wiki.gg/wiki/Void_Reaver ·
  wowpedia.fandom.com/wiki/Void_Reaver · mmo-champion.com/content/213
- **Confidence:** high on mechanics/roles/untauntability/Orb targeting; all numbers UNVERIFIED.

---

## 3. High Astromancer Solarian

- **Aliases:** Solarian. **Type:** caster tank-and-spank + recurring split phase +
  void-form burn.
- **Summary:** The raid nukes Solarian in her main phase while healing random-target
  arcane damage and managing Wrath of the Astromancer (a spreading arcane debuff).
  On a timer she vanishes to center, opens three portals that flood the room with
  Solarium Agents, then returns flanked by two Solarium Priests that must be
  interrupted or they heal her. At 20% she transforms into a voidwalker, drops the
  add cycle, and gains a melee-range fear with heavy shadow damage. Execution check.
- **Mechanics:**
  - **Wrath of the Astromancer** - single-target arcane debuff; on expiry it knocks
    the target and nearby players up and **bounces to the nearest player**. Afflicted
    moves away from the raid (or to arcane-resist soakers). Does **not** teleport;
    **not** a fixed-radius "run to the wall" bomb. Numbers UNVERIFIED.
  - **Blinding Light** - periodic raid-wide arcane pulse in the main phase (was
    omitted from old data). **Arcane Missiles** - channeled arcane on a random player.
  - **Solarium Portals** - on the split, three portals open at **random** locations
    and spawn Solarium Agents (~5 each, UNVERIFIED); off-tank gathers, raid AoEs.
  - **Solarium Priests** - two appear **with Solarian** when she returns (~15s after
    the split, not 30), casting Greater Heal (interruptable) + Arcane Torrent.
  - **P2 void form (20%)** - Void Bolt (shadow, tank) + Psychic Scream (melee fear).
- **Roles:** **Tanks** - MT on Solarian (Prot Paladin handy for adds), off-tank on
  Agents; optional 1-2 arcane-resist soaker tanks for Wrath. **Healers** - Wrath/
  Missiles targets, raid through Blinding Light, tank through Void Bolt (heavy in P2).
  **DPS/interrupts** - burn boss, AoE Agents on split, **mandatory** priest-interrupt
  rotation; melee mind the P2 fear.
- **Killers:** Wrath mishandled (stays in raid / bounces through a clump); priests
  not interrupted (out-heal your DPS); Agents overwhelming; uncontrolled P2 fears;
  healers OOM on sustained arcane.
- **Corrections (caught):** Wrath is a bounce/spread debuff, **not** a teleport/
  run-to-wall bomb; portals are **random**, not N/SW/SE; the two priests arrive
  **with the boss**, not from portals; return is ~15s, not ~30s; **Blinding Light
  added**. Split is timer-based (~50s) - confirmed. P2 voidwalker/fear - confirmed.
- **Sources:** wowhead.com/tbc npc=18805 · icy-veins.com/tbc-classic (Solarian) ·
  warcraft.wiki.gg/wiki/High_Astromancer_Solarian · wowpedia.fandom.com/wiki/High_Astromancer_Solarian ·
  warcrafttavern.com/tbc/guides/high-astromancer-solarian · r/classicwow "not a bomb fight" PSA
- **Confidence:** high on mechanics/phases/add+priest cycle/P2 transition; numbers UNVERIFIED.

---

## 4. Kael'thas Sunstrider  ·  *TK end boss, 5 phases*

- **Aliases:** Kael'thas, Kael, KT, Prince Kael'thas. **Type:** 5-phase council +
  weapons + solo endurance fight.
- **Summary:** P1 is a sequential gauntlet of his four advisors, one at a time. P2
  spawns seven animated legendary weapons the raid kills and then equips for the
  rest of the fight. P3 resurrects all four advisors at once. P4 is Kael himself
  with Phoenixes, Pyroblast and Mind Control; P5 is Gravity Lapse, repeating until
  he dies. One of TBC's most coordination-heavy fights.
- **Phases:**
  - **P1 Advisors (one at a time, exact order):** Thaladred the Darkener -> Lord
    Sanguinar -> Grand Astromancer Capernian -> Master Engineer Telonicus.
  - **P2 Seven Weapons (exact names):** Cosmic Infuser (mace - heals the other
    weapons, pull aside and kill; a healer can equip after), Phaseshift Bulwark
    (shield - tank; on-use absorb + brief CC immunity), Devastation (axe - hard
    melee, pull aside), Staff of Disintegration (staff - caster), Netherstrand
    Longbow (bow - hunter), Warp Slicer (sword - melee), Infinity Blade (sword -
    melee; attacking a mind-controlled player with it instantly breaks the MC).
  - **P3 Advisor rez:** all four rez at full HP while Kael is up; **Bloodlust here**.
    Split ranged (Thaladred then Capernian) and melee (Sanguinar then Telonicus).
  - **P4 Kael engages:** Phoenix (kite; on death leaves a Phoenix Egg that must die
    fast or it respawns), Pyroblast (interrupt, often after a Shock Barrier shield),
    Flame Strike (move out), Fireball, Mind Control.
  - **P5 Gravity Lapse (~50%):** raid floats and takes ongoing arcane damage; spread
    to max distance (Nether Beam chains to nearby players); never touch Nether Vapor
    clouds. Repeats on a cycle until death.
- **Mechanics (per advisor):** Thaladred Gaze/Fixate (kite him, near one-shots
  squishies); Sanguinar Bellowing Roar (AoE fear - Fear Ward/Tremor); Capernian
  Arcane Explosion if anyone is in melee (keep melee OFF; range-tank her, a warlock
  works) + Conflagration; Telonicus ground bombs + a periodic stun (watch feet).
- **Roles:** **Tanks** - one per advisor in P1 (Capernian range-held by a caster);
  P2 pull Cosmic Infuser + Devastation aside and take the shield; P4 tank Kael while
  a tank/hunter kites Phoenixes. **Healers** - spread for bombs/fear/arcane; heavy
  raid damage P4-P5; a healer can take the Infuser after P2. **DPS** - follow the P1
  order; equip assigned weapons fast (caster Staff, hunter Longbow, melee Warp
  Slicer; Infinity Blade breaks MC); Pyroblast interrupt rotation in P4; spread and
  dodge Nether Vapor in P5.
- **Killers:** un-kited Thaladred Gaze; Sanguinar fear into other advisors/weapons;
  melee in Capernian's Arcane Explosion; Phoenix Egg not killed fast; missed
  Pyroblast interrupt; un-broken Mind Control (esp. an MC'd healer); Nether Vapor /
  clumping during Gravity Lapse.
- **Corrections (caught):** old weapon list had **Thori'dal** (a Sunwell legendary,
  NOT this fight) and "Lady Vashj's Venom Bolt" - dropped; verified seven are Cosmic
  Infuser, Phaseshift Bulwark, Devastation, Staff of Disintegration, Netherstrand
  Longbow, Warp Slicer, Infinity Blade. Weapons are real equippable items, not just
  an aura (mixed active/passive). P3 = all four up at once (split ranged/melee), not
  a strict single-target reorder. Advisor names + P1 order verified correct.
- **Sources:** warcraft.wiki.gg/wiki/Kael'thas_Sunstrider_(tactics) ·
  wowpedia.fandom.com/wiki/Kael'thas_Sunstrider · icy-veins.com/tbc-classic (Kael'thas) ·
  wowwiki-archive.fandom.com · warcrafttavern.com (TBC Kael'thas) · mmo-champion.com/content/693
- **Confidence:** high on advisor names + P1 order and the seven weapon names
  (load-bearing, 2+ sources each); medium on weapon-to-class mapping; numbers UNVERIFIED.

---

## Master UNVERIFIED list (do NOT publish as exact)

- **Al'ar:** platform timer (~30s), Flame Buffet (~2k/+10%/stack), Flame Quills
  (~8k/s), ember HP-drain %, Melt Armor (~80%/60s), boss HP, exact compass order,
  "embers self-resurrect."
- **Void Reaver:** Knock Away cd (~20-30s) and threat-reduction %, Arcane Orb
  radius/damage, Pounding radius/damage/interval, enrage timer (~10 min).
- **Solarian:** split timer (~50s), return delay (~15s), Agents per portal (~5),
  Blinding Light interval (~20s), all damage values, "Mark of Solarian" resist stack.
- **Kael'thas:** advisor HP (~half normal), weapon loot window (~60s), Phoenix Egg
  HP, Pyroblast cast/cd, Gravity Lapse damage. P4/P5 are forward transitions, not
  an alternating loop (P5 Gravity Lapse repeats within itself).
